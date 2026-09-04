"""AI军团 - 环境配置管理

所有配置从环境变量读取，不硬编码任何敏感信息。
支持 .env 文件加载。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv(Path(__file__).parent.parent / ".env")

_SENTINEL = object()


def _env(key: str, default: object = _SENTINEL) -> str:
    """读取环境变量，缺失时抛出明确错误"""
    val = os.getenv(key)
    if val is not None:
        return val
    if default is not _SENTINEL:
        return str(default)
    if key.endswith("_API_KEY"):
        raise ValueError(f"❌ 缺少关键环境变量: {key}，请检查 .env 文件")
    return ""


# ========== DeepSeek API ==========
DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = _env("DEEPSEEK_MODEL", "deepseek-chat")

# ========== 企业微信 ==========
WECOM_WEBHOOK_URL = _env("WECOM_WEBHOOK_URL")
FEISHU_WEBHOOK_URL = _env("FEISHU_WEBHOOK_URL")

# ========== Redis ==========
REDIS_URL = _env("REDIS_URL", "redis://localhost:6379/0")

# ========== ChromaDB ==========
CHROMA_PERSIST_DIR = _env("CHROMA_PERSIST_DIR", "./data/chroma_db")

# ========== 邮件 ==========
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")

# ========== 爬虫 ==========
CRAWL_DELAY = int(_env("CRAWL_DELAY", "2"))
CRAWL_MAX_RETRIES = int(_env("CRAWL_MAX_RETRIES", "3"))
USER_AGENT = _env("USER_AGENT", "Mozilla/5.0 (compatible; AI-Army/1.0)")

# ========== 数据库 ==========
# 开发环境默认使用 SQLite，生产环境改为 PostgreSQL:
#   postgresql+asyncpg://user:pass@localhost:5432/ai_army
DATABASE_URL = _env("DATABASE_URL", "sqlite+aiosqlite:///./data/ai_army.db")

# ========== 日志 ==========
LOG_LEVEL = _env("LOG_LEVEL", "INFO")
LOG_DIR = _env("LOG_DIR", "./logs")

# ========== 即梦/Doubao 文生图 API (火山引擎 Ark) ==========
ARK_API_KEY = _env("ARK_API_KEY")  # 火山引擎 Ark API Key
ARK_BASE_URL = _env("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
ARK_IMAGE_MODEL = _env("ARK_IMAGE_MODEL", "doubao-seedream-5-0-pro-260628")

# ========== Dashboard ==========
DASHBOARD_HOST = _env("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(_env("DASHBOARD_PORT", "8000"))
ARM_COMMAND_API_KEY = _env("ARM_COMMAND_API_KEY", "")  # API鉴权密钥，为空则跳过鉴权
ARM_AUTH_ENABLED = bool(ARM_COMMAND_API_KEY)  # 是否开启鉴权

# ========== 微信小程序 ==========
WEAPP_APPID = _env("WEAPP_APPID", "")         # 小程序 AppID
WEAPP_SECRET = _env("WEAPP_SECRET", "")       # 小程序 AppSecret
JWT_SECRET_KEY = _env("JWT_SECRET_KEY", "ai-army-jwt-secret-change-in-production")
JWT_ALGORITHM = _env("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS = int(_env("JWT_EXPIRE_HOURS", "72"))

# ========== 地理编码备用API（可选，用于兜底）==========
AMAP_API_KEY = _env("AMAP_API_KEY", "")      # 高德地图Web服务API Key（主）
TENCENT_KEY = _env("TENCENT_KEY", "")         # 腾讯地图WebService Key（备）
BAIDU_MAP_AK = _env("BAIDU_MAP_AK", "")       # 百度地图AK（POI搜索/地理编码）

# ========== 项目路径 ==========
PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR_PATH = PROJECT_ROOT / LOG_DIR

# 确保必要目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR_PATH.mkdir(parents=True, exist_ok=True)
