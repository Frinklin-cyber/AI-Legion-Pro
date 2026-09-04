"""
AI军团 - 用户管理 & 数据隔离层

- 用户注册/查询 (users.json)
- 管理员识别
- 用户级数据隔离
"""
import json
import hashlib
import time
from pathlib import Path
from typing import Optional
from loguru import logger

DATA_DIR = Path(__file__).parent.parent / "data"
USERS_PATH = DATA_DIR / "users.json"
ADMIN_PATH = DATA_DIR / "admin_users.json"


# ──── 用户管理 ────

def _load_json(path: Path) -> dict | list:
    if not path.exists():
        return {} if path.suffix == '.json' else []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning(f"JSON 加载失败: {path}", exc_info=True)
        return {}


def _save_json(path: Path, data):
    """原子写入：先写临时文件再替换，防止写入中断导致数据损坏"""
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def get_or_create_user(openid: str, nickname: str = "", avatar: str = "") -> dict:
    """获取或创建用户。每次登录都会更新 last_login。"""
    users = _load_json(USERS_PATH)
    if not isinstance(users, dict):
        users = {}

    if openid in users:
        users[openid]["last_login"] = _now()
        if nickname:
            users[openid]["nickname"] = nickname
        if avatar:
            users[openid]["avatar"] = avatar
        _save_json(USERS_PATH, users)
        logger.info(f"用户登录: {nickname or users[openid].get('nickname', openid[:8])}")
        return users[openid]

    # 新用户
    user = {
        "openid": openid,
        "nickname": nickname or f"商家{openid[-6:]}",
        "avatar": avatar,
        "store_type": "",
        "store_name": "",
        "created_at": _now(),
        "last_login": _now(),
        "record_count": 0,
    }
    users[openid] = user
    _save_json(USERS_PATH, users)
    logger.info(f"新用户注册: {nickname or f'商家{openid[-6:]}'} ({openid[:8]}...)")
    return user


def get_user(openid: str) -> Optional[dict]:
    """获取用户信息"""
    users = _load_json(USERS_PATH)
    if not isinstance(users, dict):
        return None
    return users.get(openid)


def update_user_profile(openid: str, **kwargs):
    """更新用户资料（store_type, store_name 等）"""
    users = _load_json(USERS_PATH)
    if not isinstance(users, dict):
        users = {}
    if openid not in users:
        users[openid] = {"openid": openid, "created_at": _now()}
    for k, v in kwargs.items():
        if v is not None:
            users[openid][k] = v
    users[openid]["last_login"] = _now()
    _save_json(USERS_PATH, users)


def increment_user_record_count(openid: str):
    """用户录入数据时增加计数"""
    users = _load_json(USERS_PATH)
    if isinstance(users, dict) and openid in users:
        users[openid]["record_count"] = users[openid].get("record_count", 0) + 1
        _save_json(USERS_PATH, users)


def get_all_users() -> list[dict]:
    """获取所有用户列表（管理员用）"""
    users = _load_json(USERS_PATH)
    if not isinstance(users, dict):
        return []
    return sorted(users.values(), key=lambda u: u.get("last_login", ""), reverse=True)


# ──── 管理员 ────

def _load_admin_list() -> list[str]:
    """加载管理员 openid 列表"""
    data = _load_json(ADMIN_PATH)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("openids", [])
    # 创建默认文件
    _save_json(ADMIN_PATH, {"openids": [], "note": "将管理员微信openid填入openids数组"})
    return []


def is_admin(openid: str) -> bool:
    """判断用户是否为管理员"""
    if not openid:
        return False
    admins = _load_admin_list()
    return openid in admins


def add_admin(openid: str) -> bool:
    """添加管理员"""
    admins = _load_admin_list()
    if openid not in admins:
        admins.append(openid)
        _save_json(ADMIN_PATH, {"openids": admins})
        return True
    return False


# ──── 通用工具 ────

def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
