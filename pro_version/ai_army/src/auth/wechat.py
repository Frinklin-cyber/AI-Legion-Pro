"""微信小程序登录认证

流程:
1. 小程序端调用 wx.login() 获取临时 code
2. 小程序将 code 发送到本接口 /api/auth/wx-login
3. 本服务使用 code 向微信服务器换取 openid + session_key
4. 生成 JWT Token，将 openid 编码到 Token 中返回给小程序
5. 小程序后续请求在 Authorization: Bearer <token> 中携带此 JWT

参考文档:
- https://developers.weixin.qq.com/miniprogram/dev/api/open-api/login/wx.login.html
- https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/login.html
"""

import time
import hashlib
import jwt as pyjwt
from typing import Optional
from dataclasses import dataclass
from loguru import logger
import httpx

from config.env import WEAPP_APPID, WEAPP_SECRET, JWT_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_HOURS


@dataclass
class WechatSession:
    """微信 code2session 返回结果"""
    openid: str
    session_key: str
    unionid: Optional[str] = None
    errcode: int = 0
    errmsg: str = ""


def call_code2session(code: str) -> WechatSession:
    """调用微信官方接口，用 code 换取 openid 和 session_key

    GET https://api.weixin.qq.com/sns/jscode2session
    """
    if not WEAPP_APPID or not WEAPP_SECRET:
        raise RuntimeError(
            "微信小程序 AppID 或 AppSecret 未配置。"
            "请在 .env 中设置 WEAPP_APPID 和 WEAPP_SECRET。"
        )

    url = "https://api.weixin.qq.com/sns/jscode2session"
    params = {
        "appid": WEAPP_APPID,
        "secret": WEAPP_SECRET,
        "js_code": code,
        "grant_type": "authorization_code",
    }

    logger.info(f"【微信登录】请求 code2session, appid={WEAPP_APPID[:4]}****")

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, params=params)
            data = resp.json()
    except httpx.HTTPError as e:
        logger.error(f"【微信登录】网络请求失败: {e}")
        raise RuntimeError(f"微信接口请求失败: {e}")

    errcode = data.get("errcode", 0)
    if errcode != 0:
        errmsg = data.get("errmsg", "未知错误")
        logger.error(f"【微信登录】code2session 失败: errcode={errcode}, errmsg={errmsg}")
        raise RuntimeError(f"微信登录失败: {errmsg} (code={errcode})")

    session = WechatSession(
        openid=data.get("openid", ""),
        session_key=data.get("session_key", ""),
        unionid=data.get("unionid"),
        errcode=errcode,
        errmsg="ok",
    )

    logger.info(f"【微信登录】成功获取 openid={session.openid[:8]}****, unionid={'存在' if session.unionid else '无'}")
    return session


def generate_jwt(openid: str, unionid: Optional[str] = None) -> str:
    """生成 JWT Token

    payload:
        - sub: openid (Subject)
        - uid: unionid (可选，跨应用统一ID)
        - iat: 签发时间
        - exp: 过期时间
    """
    now = int(time.time())
    payload = {
        "sub": openid,
        "uid": unionid or "",
        "iat": now,
        "exp": now + JWT_EXPIRE_HOURS * 3600,
        "iss": "ai-army-command",
    }
    token = pyjwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def verify_token(token: str) -> Optional[dict]:
    """验证 JWT Token，返回 payload 或 None"""
    try:
        payload = pyjwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
        return payload
    except pyjwt.ExpiredSignatureError:
        logger.warning("【JWT】Token 已过期")
        return None
    except pyjwt.InvalidTokenError as e:
        logger.warning(f"【JWT】Token 无效: {e}")
        return None


def wechat_login(code: str) -> dict:
    """完整微信登录流程 (供 API 端点调用)

    返回:
        {
            "status": "success",
            "token": "eyJ...",
            "openid": "oXXXX",
            "expires_in": 86400
        }
    """
    # 1. 调用微信 code2session
    session = call_code2session(code)

    # 2. 生成 JWT
    token = generate_jwt(session.openid, session.unionid)

    # 3. 返回结果（不要返回 session_key 给前端！安全性）
    return {
        "status": "success",
        "token": token,
        "openid": session.openid,
        "unionid": session.unionid,
        "expires_in": JWT_EXPIRE_HOURS * 3600,
        "token_type": "Bearer",
    }


def get_openid_from_token(token: str) -> Optional[str]:
    """从 JWT 中提取 openid（供后续 API 鉴权使用）"""
    payload = verify_token(token)
    if payload is None:
        return None
    return payload.get("sub")


# ==================== JWT 鉴权依赖 ====================

from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer(auto_error=False)


async def jwt_optional(request: Request) -> Optional[str]:
    """可选的 JWT 鉴权：提取 openid，不强制要求登录"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    return get_openid_from_token(token)


async def jwt_required(request: Request) -> str:
    """强制 JWT 鉴权：必须返回有效 openid，否则 401"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录，请先使用微信授权登录")

    token = auth[7:]
    openid = get_openid_from_token(token)
    if openid is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新授权")

    return openid
