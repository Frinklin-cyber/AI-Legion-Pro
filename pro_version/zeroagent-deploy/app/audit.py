"""
audit.py
全链路审计：
- data/audit.log      通用事件（上传/问答/系统），JSON 行
- data/audit_log.jsonl Agent 编排审计（路由/执行/质检/重试/webhook），JSON 行
企业要求：所有 Agent 操作可回溯。线程安全。
"""

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .config import AUDIT_FILE, DATA_DIR

_lock = threading.Lock()
AGENT_AUDIT_FILE = DATA_DIR / "audit_log.jsonl"


def _write(path: Path, entry: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log(action: str, detail: str, client_ip: str = None, status: str = "OK"):
    """写一条通用审计日志。action: system/upload/ask；status: OK/WARN/ERROR。"""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "status": status,
        "detail": detail,
        "client_ip": client_ip or "-",
    }
    try:
        _write(AUDIT_FILE, entry)
    except OSError:
        pass


def log_agent_event(task_id: str, agent: str, stage: str, status: str,
                    detail: str, extra: dict = None) -> None:
    """
    写一条 Agent 编排审计到 data/audit_log.jsonl。
    stage: route / execute / quality / retry / notify / done
    status: OK / WARN / ERROR / RETRY / FAIL
    """
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "audit_id": task_id,
        "agent": agent,
        "stage": stage,
        "status": status,
        "detail": detail,
        **(extra or {}),
    }
    try:
        _write(AGENT_AUDIT_FILE, entry)
    except OSError:
        pass


def new_task_id() -> str:
    """生成一次 Agent 任务的审计 ID（形如 agent_20260821_130000_ab12）"""
    return f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
