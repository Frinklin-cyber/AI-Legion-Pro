from fastapi import APIRouter, Depends, HTTPException, Form, Query
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.deps import get_db, get_current_tenant
from src.db.models import Merchant, ShopUser, BusinessData, UsageLog

router = APIRouter(prefix="/api/dashboard", tags=["商家后台"])

import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
STORE_CONFIG_PATH = os.path.join(DATA_DIR, "store_configs.json")

def _load_store_configs():
    """加载 store_configs.json"""
    if os.path.exists(STORE_CONFIG_PATH):
        with open(STORE_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save_store_configs(configs):
    """保存 store_configs.json"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STORE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(configs, f, ensure_ascii=False, indent=2)

def _sync_to_store_configs(tenant_id: str, data: dict):
    """同步商家配置到 store_configs.json，供指挥中心使用"""
    configs = _load_store_configs()
    configs[tenant_id] = data
    _save_store_configs(configs)
    
    # 同时更新 web_dashboard 作为向后兼容的默认配置
    configs["web_dashboard"] = data
    _save_store_configs(configs)

def _build_store_config(merchant: Merchant, store_info: dict) -> dict:
    """从商家数据构建指挥中心所需的配置格式"""
    si = store_info or {}
    return {
        "type": si.get("type", "custom"),
        "type_name": si.get("type_name", "自定义店铺"),
        "name": si.get("store_name", merchant.name),
        "products": si.get("products", ""),
        "address": si.get("address", merchant.region or ""),
        "hours": si.get("hours", "10:00-22:00"),
        "phone": si.get("phone", merchant.phone or ""),
        "location_feature": si.get("location_feature", ""),
        "faq_knowledge": si.get("faq_knowledge", ""),
        "latitude": si.get("latitude", 0) or si.get("lat", 0) or 0,
        "longitude": si.get("longitude", 0) or si.get("lng", 0) or 0,
        "search_radius": si.get("search_radius", 2000),
        "kpi_values": {},
    }


# ==================== 数据看板 ====================

@router.get("/stats")
async def dashboard_stats(
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """数据看板：本月使用次数、剩余次数、最近记录"""
    from datetime import datetime, timedelta

    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 本月使用次数
    r1 = await db.execute(
        select(func.count(UsageLog.id)).where(
            UsageLog.tenant_id == tenant_id,
            UsageLog.created_at >= month_start,
        )
    )
    monthly_count = r1.scalar() or 0

    # 总员工数
    r2 = await db.execute(
        select(func.count(ShopUser.id)).where(
            ShopUser.tenant_id == tenant_id,
            ShopUser.is_active == True,
        )
    )
    employee_count = r2.scalar() or 0

    # 最近 5 条使用记录
    r3 = await db.execute(
        select(UsageLog)
        .where(UsageLog.tenant_id == tenant_id)
        .order_by(UsageLog.created_at.desc())
        .limit(5)
    )
    recent_logs = [
        {
            "id": log.id,
            "user_name": log.user_name,
            "action": log.action,
            "feature": log.feature,
            "created_at": log.created_at.isoformat() if log.created_at else "",
        }
        for log in r3.scalars().all()
    ]

    return {
        "status": "success",
        "data": {
            "monthly_usage": monthly_count,
            "employee_count": employee_count,
            "recent_logs": recent_logs,
        },
    }


# ==================== 商家信息管理 ====================

@router.get("/profile")
async def get_profile(
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """获取商家信息（完整版，包含指挥中心所需的所有字段）"""
    r = await db.execute(select(Merchant).where(Merchant.tenant_id == tenant_id))
    merchant = r.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")

    # 取业务数据中的 store_info
    r2 = await db.execute(
        select(BusinessData).where(
            BusinessData.tenant_id == tenant_id,
            BusinessData.data_type == "store_info",
        )
    )
    store_info = r2.scalar_one_or_none()
    store_content = {}
    if store_info:
        try:
            store_content = json.loads(store_info.content)
        except Exception:
            store_content = {}

    # 构建指挥中心配置
    store_config = _build_store_config(merchant, store_content)

    return {
        "status": "success",
        "data": {
            "name": merchant.name,
            "account": merchant.account,
            "phone": merchant.phone,
            "region": merchant.region,
            "is_active": merchant.is_active,
            "created_at": merchant.created_at.isoformat() if merchant.created_at else "",
            "store_info": store_content,
            "store_config": store_config,  # 指挥中心可直接使用的配置
        },
    }


@router.put("/profile")
async def update_profile(
    name: str = Form("", description="商家名称"),
    phone: str = Form("", description="电话"),
    region: str = Form("", description="地区"),
    store_type: str = Form("", description="店铺类型ID"),
    type_name: str = Form("", description="店铺类型名称"),
    store_name: str = Form("", description="店铺名称"),
    products: str = Form("", description="主营产品"),
    address: str = Form("", description="店铺地址"),
    hours: str = Form("", description="营业时间"),
    location_feature: str = Form("", description="店铺特色"),
    faq_knowledge: str = Form("", description="FAQ知识"),
    lat: str = Form("", description="纬度"),
    lng: str = Form("", description="经度"),
    search_radius: str = Form("", description="搜索半径"),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """更新商家信息（完整版，同时同步到指挥中心配置）"""
    r = await db.execute(select(Merchant).where(Merchant.tenant_id == tenant_id))
    merchant = r.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")

    if name:
        merchant.name = name
    if phone:
        merchant.phone = phone
    if region:
        merchant.region = region

    # 更新 store_info（包含所有字段）
    r2 = await db.execute(
        select(BusinessData).where(
            BusinessData.tenant_id == tenant_id,
            BusinessData.data_type == "store_info",
        )
    )
    store_info = r2.scalar_one_or_none()
    if store_info:
        content = json.loads(store_info.content or "{}")
    else:
        content = {}
        store_info = BusinessData(tenant_id=tenant_id, data_type="store_info")
        db.add(store_info)

    # 更新所有字段
    if store_type:
        content["type"] = store_type
    if type_name:
        content["type_name"] = type_name
    if store_name:
        content["store_name"] = store_name
    if products:
        content["products"] = products
    if address:
        content["address"] = address
    if hours:
        content["hours"] = hours
    if location_feature:
        content["location_feature"] = location_feature
    if faq_knowledge:
        content["faq_knowledge"] = faq_knowledge
    if lat:
        content["latitude"] = lat
        content["lat"] = lat
    if lng:
        content["longitude"] = lng
        content["lng"] = lng
    if search_radius:
        content["search_radius"] = int(search_radius) if str(search_radius).isdigit() else 2000
    if phone:
        content["phone"] = phone

    store_info.content = json.dumps(content, ensure_ascii=False)
    await db.flush()

    # 同步到 store_configs.json（供指挥中心使用）
    store_config = _build_store_config(merchant, content)
    _sync_to_store_configs(tenant_id, store_config)

    # 记录使用日志
    db.add(UsageLog(
        tenant_id=tenant_id,
        user_name=merchant.name,
        action="更新了商家信息（含店铺配置）",
        feature="信息管理",
    ))

    await db.commit()

    return {
        "status": "success",
        "message": "更新成功",
        "data": store_config,
    }


# ==================== 员工管理 ====================

@router.get("/employees")
async def list_employees(
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """获取员工列表"""
    r = await db.execute(
        select(ShopUser)
        .where(ShopUser.tenant_id == tenant_id)
        .order_by(ShopUser.created_at.desc())
    )
    employees = [
        {
            "id": u.id,
            "name": u.name,
            "phone": u.phone,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else "",
        }
        for u in r.scalars().all()
    ]
    return {"status": "success", "data": employees}


@router.post("/employees")
async def add_employee(
    name: str = Form(..., description="员工姓名"),
    phone: str = Form("", description="手机号"),
    role: str = Form("operator", description="角色"),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """添加员工"""
    user = ShopUser(
        tenant_id=tenant_id,
        name=name,
        phone=phone,
        role=role,
    )
    db.add(user)
    await db.flush()

    # 记录日志
    db.add(UsageLog(
        tenant_id=tenant_id,
        user_name=name,
        action=f"添加了员工「{name}」",
        feature="员工管理",
    ))

    return {
        "status": "success",
        "message": "添加成功",
        "data": {"id": user.id, "name": user.name, "role": user.role},
    }


@router.delete("/employees/{employee_id}")
async def delete_employee(
    employee_id: int,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """删除员工"""
    r = await db.execute(
        select(ShopUser).where(
            ShopUser.id == employee_id,
            ShopUser.tenant_id == tenant_id,
        )
    )
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="员工不存在")

    await db.delete(user)
    db.add(UsageLog(
        tenant_id=tenant_id,
        user_name="管理员",
        action=f"删除了员工「{user.name}」",
        feature="员工管理",
    ))
    return {"status": "success", "message": f"已删除员工「{user.name}」"}


# ==================== 使用记录 ====================

@router.get("/usage-logs")
async def list_usage_logs(
    page: int = 1,
    page_size: int = 20,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """获取使用记录（分页）"""
    offset = (page - 1) * page_size
    r = await db.execute(
        select(UsageLog)
        .where(UsageLog.tenant_id == tenant_id)
        .order_by(UsageLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    logs = [
        {
            "id": log.id,
            "user_name": log.user_name,
            "action": log.action,
            "feature": log.feature,
            "created_at": log.created_at.isoformat() if log.created_at else "",
        }
        for log in r.scalars().all()
    ]

    # 总数
    r2 = await db.execute(
        select(func.count(UsageLog.id)).where(UsageLog.tenant_id == tenant_id)
    )
    total = r2.scalar() or 0

    return {
        "status": "success",
        "data": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
