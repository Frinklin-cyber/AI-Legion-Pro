"""v2.0 进阶版 API 路由

- POST /api/v2/chat     编排问答（商家 JWT 鉴权）：意图识别→画像→工具推理→方案对比→执行指引
- GET  /api/v2/status   军团动态状态（战士数 / 知识库 / 调度任务 / 今日执行）
"""

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.deps import get_db, get_tenant_optional
from src.db.models import Merchant, BusinessData
from src.orchestrator.engine import OrchestrationEngine

router = APIRouter(prefix="/api/v2", tags=["v2 进阶编排"])


class ChatRequest(BaseModel):
    message: str
    history: list[dict] | None = None  # [{"role": "user"|"assistant", "content": "..."}]


# 五兵种展示配置
_SOLDIER_VIEWS = [
    {"key": "scout",    "icon": "📡", "name": "侦察兵",   "role": "情报监控", "desc": "竞品 / 商圈 / 关键词监控"},
    {"key": "staff",    "icon": "📊", "name": "参谋部",   "role": "数据分析", "desc": "经营分析 / 归因诊断 / 报告"},
    {"key": "special",  "icon": "✍️", "name": "特种部队", "role": "内容创作", "desc": "短视频 / 文案 / 图文批量产出"},
    {"key": "logistics","icon": "⚙️", "name": "后勤兵",   "role": "任务调度", "desc": "定时任务 / 周期执行"},
    {"key": "command",  "icon": "🎖️", "name": "指挥中枢", "role": "编排引擎", "desc": "RAG + 工具调用 + 全领域问答"},
]


def _soldier_status(role: str) -> dict:
    """返回兵种实时状态（尽力而为，失败给默认值）"""
    base = {"state": "待命", "busy": False, "detail": "-"}
    try:
        import main as _m  # 运行时导入，此时模块已加载完成
        dispatcher = getattr(_m, "dispatcher", None)
        if dispatcher is not None:
            soldiers = getattr(dispatcher, "soldiers", {}) or {}
            if soldiers:
                # 尝试匹配 role
                for key, soldier in soldiers.items():
                    if role in str(key) or role in str(getattr(soldier, "role", "")):
                        return {"state": "待命", "busy": False,
                                "detail": getattr(soldier, "name", key)}
    except Exception:
        pass
    return base


async def _load_profile(tenant_id: str, db: AsyncSession) -> dict:
    """加载商家画像（用于编排上下文补全）"""
    r = await db.execute(select(Merchant).where(Merchant.tenant_id == tenant_id))
    merchant = r.scalar_one_or_none()
    if not merchant:
        return {}
    content: dict = {}
    r2 = await db.execute(
        select(BusinessData).where(
            BusinessData.tenant_id == tenant_id,
            BusinessData.data_type == "store_info",
        )
    )
    si = r2.scalar_one_or_none()
    if si:
        try:
            content = json.loads(si.content or "{}")
        except Exception:
            content = {}
    return {
        "name": merchant.name or "",
        "store_name": content.get("store_name") or merchant.name or "",
        "type": content.get("type", ""),
        "type_name": content.get("type_name", ""),
        "products": content.get("products", ""),
        "region": merchant.region or content.get("region", ""),
        "address": content.get("address", ""),
        "hours": content.get("hours", ""),
        "phone": merchant.phone or content.get("phone", ""),
        "location_feature": content.get("location_feature", ""),
        "faq_knowledge": content.get("faq_knowledge", ""),
    }


@router.post("/chat")
async def v2_chat(
    req: ChatRequest,
    tenant_id: str = Depends(get_tenant_optional),
    db: AsyncSession = Depends(get_db),
):
    """编排问答：跑完整 Step1→5 工作流，返回事件流 + 方案 + 最终执行指引"""
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="消息不能为空")

    profile = await _load_profile(tenant_id, db)
    engine = OrchestrationEngine()
    try:
        result = await asyncio.to_thread(engine.run, message, profile, req.history)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"编排执行失败: {e}")

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error", "编排失败"))
    return result


@router.get("/status")
async def v2_status(
    tenant_id: str = Depends(get_tenant_optional),
    db: AsyncSession = Depends(get_db),
):
    """军团动态状态：供主界面动态数据 / 军团阵列使用"""
    soldiers = []
    for s in _SOLDIER_VIEWS:
        st = _soldier_status(s["key"])
        soldiers.append({**s, **st})

    # 知识库 / 调度任务（尽力而为）
    kb_docs = 0
    schedule_tasks = 0
    try:
        from src.knowledge.vector_store import VectorStore
        kb_docs = VectorStore().get_status().get("total_documents", 0)
    except Exception:
        kb_docs = 0
    try:
        import main as _m
        scheduler = getattr(_m, "scheduler", None)
        if scheduler is not None:
            schedule_tasks = len(getattr(scheduler, "_tasks", {}) or getattr(scheduler, "tasks", {}) or [])
    except Exception:
        schedule_tasks = 0

    return {
        "status": "success",
        "data": {
            "server_time": datetime.now().isoformat(timespec="seconds"),
            "soldier_count": len(soldiers),
            "soldiers": soldiers,
            "kb_docs": kb_docs,
            "schedule_tasks": schedule_tasks,
        },
    }
