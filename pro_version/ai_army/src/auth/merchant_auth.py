"""商家认证模块 - bcrypt 密码 + JWT"""
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from config.env import JWT_SECRET_KEY, JWT_ALGORITHM


# 商家 JWT 有效期：7 天
MERCHANT_JWT_EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
    """bcrypt 哈希密码"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_token(tenant_id: str, account: str, name: str = "") -> str:
    """生成商家 JWT（别名）"""
    return generate_merchant_token(tenant_id, account, name)


def verify_token(token: str) -> dict | None:
    """验证商家 JWT（别名）"""
    return verify_merchant_token(token)


def generate_merchant_token(tenant_id: str, account: str, name: str) -> str:
    """生成商家 JWT（包含 tenant_id）"""
    now = datetime.now(timezone.utc)
    payload = {
        "tenant_id": tenant_id,
        "account": account,
        "name": name,
        "type": "merchant",  # 区分商家 token 和微信小程序 token
        "iat": now,
        "exp": now + timedelta(days=MERCHANT_JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_merchant_token(token: str) -> dict | None:
    """验证商家 JWT，成功返回 payload，失败返回 None"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "merchant":
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
