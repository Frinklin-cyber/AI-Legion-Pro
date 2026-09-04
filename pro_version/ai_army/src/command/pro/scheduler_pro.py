"""周期任务调度（Pro 版）

复用现有后勤兵 TaskScheduler（APScheduler），不引入新调度框架。
老板设置周期任务（如"每周一生成下周朋友圈计划"）→ 按 cron 触发 →
自动生成计划并执行 → 产出推送给老板确认。
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select, update

from src.db import async_session
from src.db.models import Schedule

# 全局调度器（由 main.py 的 init_scheduler 创建后注入）
_global_scheduler: Any = None

# 已注册的任务名集合（避免重复注册）
_REGISTERED: set[str] = set()


def bind_scheduler(scheduler: Any) -> None:
    """绑定现有调度器（main.py 启动时调用）"""
    global _global_scheduler
    _global_scheduler = scheduler


def get_scheduler() -> Any:
    return _global_scheduler


# ── 注册 ────────────────────────────────────────────────

def register_schedule_job(schedule_id: str, cron: str, goal: str,
                          store_id: str, template_id: str = "") -> bool:
    """注册一个周期任务到 TaskScheduler（幂等）"""
    if _global_scheduler is None:
        logger.warning("[周期任务] 调度器未绑定，任务将仅落库（服务重启后需重新注册）")
        return False

    job_name = f"pro_schedule_{schedule_id}"
    if job_name in _REGISTERED:
        return True

    from src.logistics.task_scheduler import ScheduledTask

    def _trigger() -> None:
        # APScheduler 后台线程执行，无事件循环 → asyncio.run
        asyncio.run(_run_schedule_async(schedule_id, store_id, goal, template_id))

    try:
        _global_scheduler.add_task(ScheduledTask(
            name=job_name,
            func=_trigger,
            trigger_type="cron",
            trigger_config={"cron": cron},
            description=f"Pro 周期任务: {goal[:30]}",
        ))
        _REGISTERED.add(job_name)
        logger.info(f"[周期任务] 已注册 #{schedule_id} cron={cron}")
        return True
    except Exception as e:
        logger.error(f"[周期任务] 注册失败 #{schedule_id}: {e}")
        return False


def unregister_schedule_job(schedule_id: str) -> None:
    """移除周期任务"""
    job_name = f"pro_schedule_{schedule_id}"
    if _global_scheduler is None:
        return
    try:
        _global_scheduler._scheduler.remove_job(job_name)
    except Exception:
        pass
    _REGISTERED.discard(job_name)


async def _restore_async() -> int:
    """从 DB 恢复所有启用的周期任务（服务重启后自动重新注册）"""
    from src.db.models import Schedule as ScheduleModel
    count = 0
    try:
        async with async_session() as session:
            result = await session.execute(
                select(ScheduleModel).where(ScheduleModel.enabled.is_(True))
            )
            rows = result.scalars().all()
        for r in rows:
            if register_schedule_job(r.id, r.cron, r.goal, r.store_id, r.template_id or ""):
                count += 1
        logger.info(f"[周期任务] 启动恢复完成，共注册 {count} 个任务")
    except Exception as e:
        logger.warning(f"[周期任务] 启动恢复失败: {e}")
    return count


def restore_schedules() -> None:
    """同步入口：后台线程恢复（init_scheduler 在事件循环内调用）"""
    import threading
    t = threading.Thread(target=lambda: asyncio.run(_restore_async()), daemon=True,
                         name="pro-schedule-restore")
    t.start()


# ── 触发执行 ────────────────────────────────────────────

async def _run_schedule_async(schedule_id: str, store_id: str, goal: str,
                              template_id: str = "") -> None:
    """周期任务触发：生成计划 → 执行 → 推送老板确认"""
    from src.command.pro.orchestrator import orchestrator
    from src.command.pro.workflow_engine import workflow_engine
    from src.command.pro.approval_gate import approval_gate
    from src.scouts.push import push_to_wecom

    try:
        # 1. AI 店长生成任务树
        plan = await orchestrator.build_plan(store_id, goal, template_id or None)
        plan_id = uuid.uuid4().hex[:12]
        await _save_plan(plan_id, store_id, goal, plan, status="running")

        # 2. 执行（自动跑完所有非审批型任务）
        exec_obj = await workflow_engine.start(plan, plan_id, store_id)
        # 等待执行完成
        for _ in range(120):
            if exec_obj.status != "running":
                break
            await asyncio.sleep(1)

        # 3. 汇总产物推送老板确认
        outputs = [s.output for s in exec_obj.step_list if s.output]
        summary = f"📋 周期任务执行完成（{exec_obj.status}）\n目标：{goal}\n"
        if outputs:
            summary += "\n\n".join(outputs[:3])[:1500]
        if exec_obj.status == "failed":
            summary += f"\n⚠️ 部分任务失败：{exec_obj.error or '未知'}"

        try:
            push_to_wecom(summary)
        except Exception as e:
            logger.warning(f"[周期任务] 推送失败: {e}")
    except Exception as e:
        logger.error(f"[周期任务] 执行异常 #{schedule_id}: {e}")


async def _save_plan(plan_id: str, store_id: str, goal: str,
                     plan: dict[str, Any], status: str = "draft") -> None:
    from src.db.models import Plan
    async with async_session() as session:
        session.add(Plan(
            id=plan_id,
            store_id=store_id,
            goal=goal,
            plan_json=json.dumps(plan, ensure_ascii=False),
            estimated_cost=plan.get("estimated_cost", 0),
            status=status,
        ))
        await session.commit()


# ── DB 操作 ─────────────────────────────────────────────

async def list_schedules(store_id: str) -> list[dict[str, Any]]:
    """店铺周期任务列表"""
    async with async_session() as session:
        result = await session.execute(
            select(Schedule).where(Schedule.store_id == store_id).order_by(Schedule.created_at.desc())
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "goal": r.goal,
                "cron": r.cron,
                "template_id": r.template_id,
                "enabled": r.enabled,
                "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ]


async def set_schedule_enabled(schedule_id: str, enabled: bool) -> bool:
    """启用 / 停用周期任务"""
    async with async_session() as session:
        row = await session.get(Schedule, schedule_id)
        if row is None:
            return False
        row.enabled = enabled
        await session.commit()
        if enabled:
            register_schedule_job(row.id, row.cron, row.goal, row.store_id, row.template_id or "")
        else:
            unregister_schedule_job(row.id)
        return True
