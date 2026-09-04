"""商家认证路由 - 注册 / 登录 / JWT 验证"""
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import async_session
from src.db.models import Merchant
from src.auth.merchant_auth import hash_password, verify_password, create_token, verify_token

router = APIRouter(prefix="/auth", tags=["auth"])


async def get_db():
    async with async_session() as session:
        yield session


@router.post("/register")
async def register(
    name: str = Form(...),
    account: str = Form(...),
    password: str = Form(...),
    phone: str = Form(""),
    region: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """商家注册"""
    if len(password) < 6:
        return JSONResponse(
            {"status": "error", "message": "密码至少6位"}, status_code=400
        )

    # 检查账号是否已存在
    r = await db.execute(select(func.count(Merchant.id)).where(Merchant.account == account))
    if r.scalar() > 0:
        return JSONResponse(
            {"status": "error", "message": "账号已存在"}, status_code=400
        )

    merchant = Merchant(
        name=name,
        account=account,
        password_hash=hash_password(password),
        phone=phone,
        region=region,
    )
    db.add(merchant)
    await db.commit()
    await db.refresh(merchant)

    token = create_token(merchant.tenant_id, account)
    return JSONResponse(
        {
            "status": "success",
            "message": "注册成功",
            "data": {
                "token": token,
                "tenant_id": merchant.tenant_id,
                "name": merchant.name,
                "account": merchant.account,
            },
        }
    )


@router.post("/login")
async def login(
    account: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """商家登录"""
    r = await db.execute(select(Merchant).where(Merchant.account == account))
    merchant = r.scalar_one_or_none()

    if not merchant:
        return JSONResponse(
            {"status": "error", "message": "账号不存在"}, status_code=400
        )
    if not merchant.is_active:
        return JSONResponse(
            {"status": "error", "message": "账号已被禁用"}, status_code=403
        )
    if not verify_password(password, merchant.password_hash):
        return JSONResponse(
            {"status": "error", "message": "密码错误"}, status_code=400
        )

    token = create_token(merchant.tenant_id, account)
    return JSONResponse(
        {
            "status": "success",
            "message": "登录成功",
            "data": {
                "token": token,
                "tenant_id": merchant.tenant_id,
                "name": merchant.name,
                "account": merchant.account,
            },
        }
    )


@router.get("/me")
async def get_me(request: Request):
    """获取当前商家信息（需 JWT）"""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse(
            {"status": "error", "message": "未登录"}, status_code=401
        )

    payload = verify_token(auth.split(" ", 1)[1])
    if not payload:
        return JSONResponse(
            {"status": "error", "message": "登录已过期"}, status_code=401
        )

    async with async_session() as db:
        r = await db.execute(select(Merchant).where(Merchant.tenant_id == payload["tenant_id"]))
        merchant = r.scalar_one_or_none()
        if not merchant:
            return JSONResponse(
                {"status": "error", "message": "商家不存在"}, status_code=404
            )

    return JSONResponse(
        {
            "status": "success",
            "data": {
                "tenant_id": merchant.tenant_id,
                "name": merchant.name,
                "account": merchant.account,
                "phone": merchant.phone,
                "region": merchant.region,
            },
        }
    )
