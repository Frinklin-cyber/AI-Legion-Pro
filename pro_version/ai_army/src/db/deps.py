"""FastAPI 依赖注入：数据库会话 + 租户上下文"""
from typing import AsyncGenerator
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from src.db import async_session
from src.auth.merchant_auth import verify_merchant_token


security = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话依赖"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_tenant(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """从 JWT 解析当前租户 ID，失败则返回 401"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="请先登录")
    payload = verify_merchant_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return payload["tenant_id"]


async def get_tenant_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """可选租户解析，不强制登录"""
    if credentials is None:
        return ""
    payload = verify_merchant_token(credentials.credentials)
    return payload.get("tenant_id", "") if payload else ""
