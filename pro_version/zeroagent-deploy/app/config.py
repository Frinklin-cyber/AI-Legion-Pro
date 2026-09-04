"""
config.py
ZEROagent 企业知识大脑 PoC 配置
全部可通过环境变量覆盖（企业部署时无需改代码）。
设计原则：数据不出域 —— 默认仅连接本地 Ollama，不调用任何公网 API。
"""

import os
from pathlib import Path

# ─────────────────────────────────────────────
# 目录
# ─────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("ZD_DATA_DIR", str(BASE_DIR / "data")))
VECTOR_DB_PATH = DATA_DIR / "vectordb"
UPLOAD_DIR = DATA_DIR / "uploads"
AUDIT_FILE = DATA_DIR / "audit.log"
# 负面反馈（"回答不准"）收集目录：data/feedback/feedback.jsonl（JSONL 格式）
FEEDBACK_FILE = DATA_DIR / "feedback" / "feedback.jsonl"
STATIC_DIR = BASE_DIR / "app" / "static"

# ─────────────────────────────────────────────
# Ollama（本地模型，数据不出域）
# ─────────────────────────────────────────────
# 容器内部署时由 docker-compose 注入 http://ollama:11434
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")  # 或 bge-m3（注意切换后需清空向量库）
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")            # 或 qwen2.5-coder:7b

# ─────────────────────────────────────────────
# 切分与检索
# ─────────────────────────────────────────────
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
TOP_K = int(os.getenv("TOP_K", "5"))
# 弱相关阈值：top-k 中所有命中的相似度均低于该值时，判定为"弱相关/无关"，进入智能助手模式

# ─────────────────────────────────────────────
# 生成参数
# ─────────────────────────────────────────────
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.1"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "180"))

# ─────────────────────────────────────────────
# 上传限制
# ─────────────────────────────────────────────
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".md", ".txt"}
