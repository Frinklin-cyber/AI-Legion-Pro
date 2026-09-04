"""人工审批网关（Pro 版 Layer 3 后半段）

高风险动作（发企微 / 定时发布 / 扣积分）需老板确认后才能发布。
存储：有 Redis 用之，无则 SQLite（表 approvals）。

接口：
- create(store_id, plan_id, task_id, action, payload) -> approval_id
- decide(approval_id, decision) -> 通过则返回 payload 待 executor 执行
- check(approval_id) -> 审批状态
- list_pending(store_id) -> 待办列表
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select, update

from src.db import async_session
from src.db.models import Approval

# 高风险动作：需要人工审批
HIGH_RISK_ACTIONS: set[str] = {"发企微", "定时发布", "发布朋友圈"}


class ApprovalGate:
    """人工审批网关（全 async）"""

    async def create(self, store_id: str, plan_id: str, task_id: str,
                     action: str, payload: dict[str, Any]) -> str:
        """创建一条待审批记录，返回 approval_id"""
        approval_id = uuid.uuid4().hex[:12]
        async with async_session() as session:
            session.add(Approval(
                id=approval_id,
                store_id=store_id,
                plan_id=plan_id,
                task_id=task_id,
                action=action,
                payload=json.dumps(payload, ensure_ascii=False),
                status="pending",
            ))
            await session.commit()
        logger.info(f"[审批] 新增待审批 #{approval_id} {action} (店铺 {store_id})")
        return approval_id

    async def decide(self, approval_id: str, decision: bool) -> dict[str, Any]:
        """老板审批：decision=True 通过，False 拒绝

        Returns:
            {"status": "approved"|"rejected"|"not_found", "action": str, "payload": dict}
        """
        async with async_session() as session:
            row = await session.get(Approval, approval_id)
            if row is None:
                return {"status": "not_found", "action": "", "payload": {}}

            new_status = "approved" if decision else "rejected"
            row.status = new_status
            await session.commit()

            payload: dict[str, Any] = {}
            try:
                payload = json.loads(row.payload or "{}")
            except json.JSONDecodeError:
                payload = {}

            logger.info(f"[审批] #{approval_id} → {new_status}")
            return {"status": new_status, "action": row.action, "payload": payload,
                    "store_id": row.store_id}

    async def check(self, approval_id: str) -> dict[str, Any]:
        """查询审批状态"""
        async with async_session() as session:
            row = await session.get(Approval, approval_id)
            if row is None:
                return {"status": "not_found"}
            return {
                "id": row.id,
                "store_id": row.store_id,
                "plan_id": row.plan_id,
                "task_id": row.task_id,
                "action": row.action,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else "",
            }

    async def list_pending(self, store_id: str) -> list[dict[str, Any]]:
        """列出某店铺全部待审批项"""
        async with async_session() as session:
            result = await session.execute(
                select(Approval)
                .where(Approval.store_id == store_id, Approval.status == "pending")
                .order_by(Approval.created_at.desc())
            )
            rows = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "plan_id": r.plan_id,
                    "task_id": r.task_id,
                    "action": r.action,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ]


# 全局单例
approval_gate = ApprovalGate()
