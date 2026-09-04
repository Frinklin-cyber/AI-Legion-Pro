"""平台管理员后台 API - 商家列表、详情、统计、封禁管理"""
import hashlib
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.deps import get_db
from src.db.models import Merchant, ShopUser, BusinessData, UsageLog

router = APIRouter(prefix="/api/admin", tags=["平台管理"])

# 简单管理员认证（admin / admin123）
ADMIN_USER = "admin"
ADMIN_PASS_HASH = hashlib.sha256("admin123".encode()).hexdigest()


def verify_admin(admin_user: str = "", admin_pass: str = ""):
    if admin_user != ADMIN_USER:
        raise HTTPException(status_code=403, detail="管理员账号错误")
    if hashlib.sha256(admin_pass.encode()).hexdigest() != ADMIN_PASS_HASH:
        raise HTTPException(status_code=403, detail="管理员密码错误")


# ==================== 系统统计 ====================

@router.get("/stats")
async def admin_stats(
    admin_user: str = Query(""),
    admin_pass: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """系统统计：总商家数、总调用次数、活跃商家数"""
    verify_admin(admin_user, admin_pass)

    # 总商家数
    r1 = await db.execute(select(func.count(Merchant.id)))
    total_merchants = r1.scalar() or 0

    # 总调用次数
    r2 = await db.execute(select(func.count(UsageLog.id)))
    total_usage = r2.scalar() or 0

    # 近7天活跃商家数
    seven_days_ago = datetime.now() - timedelta(days=7)
    r3 = await db.execute(
        select(func.count(func.distinct(UsageLog.tenant_id))).where(
            UsageLog.created_at >= seven_days_ago
        )
    )
    active_merchants = r3.scalar() or 0

    # 启用/禁用统计
    r4 = await db.execute(select(func.count(Merchant.id)).where(Merchant.is_active == True))
    enabled_count = r4.scalar() or 0

    return {
        "status": "success",
        "data": {
            "total_merchants": total_merchants,
            "enabled_merchants": enabled_count,
            "disabled_merchants": total_merchants - enabled_count,
            "total_usage": total_usage,
            "active_merchants_7d": active_merchants,
        },
    }


# ==================== 商家列表 ====================

@router.get("/merchants")
async def list_merchants(
    admin_user: str = Query(""),
    admin_pass: str = Query(""),
    search: str = Query("", description="搜索商家名称或账号"),
    page: int = Query(1),
    page_size: int = Query(20),
    db: AsyncSession = Depends(get_db),
):
    """商家列表（支持搜索、分页）"""
    verify_admin(admin_user, admin_pass)

    query = select(Merchant)
    count_query = select(func.count(Merchant.id))

    if search:
        query = query.where(
            (Merchant.name.contains(search)) | (Merchant.account.contains(search))
        )
        count_query = count_query.where(
            (Merchant.name.contains(search)) | (Merchant.account.contains(search))
        )

    # 总数
    r = await db.execute(count_query)
    total = r.scalar() or 0

    # 分页
    offset = (page - 1) * page_size
    r2 = await db.execute(
        query.order_by(Merchant.created_at.desc()).offset(offset).limit(page_size)
    )
    merchants = [
        {
            "id": m.id,
            "tenant_id": m.tenant_id,
            "name": m.name,
            "account": m.account,
            "phone": m.phone,
            "region": m.region,
            "is_active": m.is_active,
            "created_at": m.created_at.isoformat() if m.created_at else "",
        }
        for m in r2.scalars().all()
    ]

    return {
        "status": "success",
        "data": merchants,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ==================== 商家详情 ====================

@router.get("/merchants/{tenant_id}")
async def merchant_detail(
    tenant_id: str,
    admin_user: str = Query(""),
    admin_pass: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """商家详情：基本信息 + 员工列表 + 使用统计"""
    verify_admin(admin_user, admin_pass)

    # 商家信息
    r = await db.execute(select(Merchant).where(Merchant.tenant_id == tenant_id))
    merchant = r.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")

    # 员工列表
    r2 = await db.execute(
        select(ShopUser).where(ShopUser.tenant_id == tenant_id)
    )
    employees = [
        {"id": u.id, "name": u.name, "phone": u.phone, "role": u.role, "is_active": u.is_active}
        for u in r2.scalars().all()
    ]

    # 总使用次数
    r3 = await db.execute(
        select(func.count(UsageLog.id)).where(UsageLog.tenant_id == tenant_id)
    )
    usage_count = r3.scalar() or 0

    # 近5条使用记录
    r4 = await db.execute(
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
        for log in r4.scalars().all()
    ]

    return {
        "status": "success",
        "data": {
            "merchant": {
                "id": merchant.id,
                "tenant_id": merchant.tenant_id,
                "name": merchant.name,
                "account": merchant.account,
                "phone": merchant.phone,
                "region": merchant.region,
                "is_active": merchant.is_active,
                "created_at": merchant.created_at.isoformat() if merchant.created_at else "",
            },
            "employees": employees,
            "usage_count": usage_count,
            "recent_logs": recent_logs,
        },
    }


# ==================== 启用/禁用商家 ====================

@router.put("/merchants/{tenant_id}/toggle")
async def toggle_merchant(
    tenant_id: str,
    admin_user: str = Query(""),
    admin_pass: str = Query(""),
    action: str = Query("", description="enable 或 disable"),
    db: AsyncSession = Depends(get_db),
):
    """启用/禁用商家"""
    verify_admin(admin_user, admin_pass)

    r = await db.execute(select(Merchant).where(Merchant.tenant_id == tenant_id))
    merchant = r.scalar_one_or_none()
    if not merchant:
        raise HTTPException(status_code=404, detail="商家不存在")

    if action == "disable":
        merchant.is_active = False
        msg = f"已禁用商家「{merchant.name}」"
    elif action == "enable":
        merchant.is_active = True
        msg = f"已启用商家「{merchant.name}」"
    else:
        raise HTTPException(status_code=400, detail="action 必须为 enable 或 disable")

    await db.flush()
    return {"status": "success", "message": msg}
