"""Pro 版（AI 店长）API 路由

在 main.py 中通过 app.include_router(pro_router) 挂载，前缀 /api/pro。

接口清单（对应《技术需求文档》5.1）：
    POST /api/pro/goal                 目标 → 任务树（draft 计划）
    PUT  /api/pro/plan/{plan_id}       修改任务树 → 重算预估积分
    POST /api/pro/execute/{plan_id}    确认后开始执行
    GET  /api/pro/execution/{exec_id}/status  执行进度轮询
    POST /api/pro/approve              人工审批（通过则发布）
    POST /api/pro/recharge             积分充值
    GET  /api/pro/balance/{store_id}   查询余额
    POST /api/pro/schedule             创建周期任务
    GET  /api/pro/schedules/{store_id} 周期任务列表
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from src.command.pro.orchestrator import orchestrator, TEMPLATES
from src.command.pro.workflow_engine import workflow_engine
from src.command.pro.approval_gate import approval_gate
from src.command.pro.executor import executor
from src.command.pro.billing import billing
from src.command.pro.scheduler_pro import (
    register_schedule_job, list_schedules, set_schedule_enabled,
)
from src.db import async_session
from src.db.models import Plan, Schedule

pro_router = APIRouter(prefix="/api/pro", tags=["AI店长Pro版"])


# ── 请求模型 ────────────────────────────────────────────

class GoalRequest(BaseModel):
    store_id: str = Field(..., description="店铺 ID")
    goal: str = Field("", description="老板下达的目标（可与 template_id 二选一）")
    template_id: str | None = Field(None, description="快捷模板 ID")


class PlanUpdateRequest(BaseModel):
    store_id: str = Field(..., description="店铺 ID")
    plan: dict[str, Any] = Field(..., description="修改后的任务树 {goal, tasks}")


class ApproveRequest(BaseModel):
    approval_id: str = Field(..., description="审批 ID")
    decision: bool = Field(..., description="True 通过 / False 拒绝")


class RechargeRequest(BaseModel):
    store_id: str = Field(..., description="店铺 ID")
    amount: int = Field(..., gt=0, description="充值积分（1 元 = 1 积分）")


class ScheduleRequest(BaseModel):
    store_id: str = Field(..., description="店铺 ID")
    goal: str = Field(..., description="周期任务目标，如「每周一生成下周朋友圈计划」")
    cron: str = Field(..., description="cron 表达式，如 0 8 * * 1")
    template_id: str | None = Field(None, description="快捷模板 ID")


class ScheduleToggleRequest(BaseModel):
    enabled: bool = Field(..., description="启用 / 停用")


# ── 辅助函数 ────────────────────────────────────────────

async def _load_plan(plan_id: str) -> Plan | None:
    async with async_session() as session:
        return await session.get(Plan, plan_id)


async def _save_plan(plan: Plan) -> None:
    async with async_session() as session:
        await session.merge(plan)
        await session.commit()


async def _recalc_cost(plan_dict: dict[str, Any]) -> int:
    """重算任务树预估积分"""
    return sum(int(t.get("cost", 0) or 0) for t in plan_dict.get("tasks", []))


# ── 1. 下达指令：目标 → 任务树 ──────────────────────────

@pro_router.post("/goal")
async def create_plan(req: GoalRequest):
    """AI 店长生成任务树（draft 计划），暂不执行"""
    if not req.goal and not req.template_id:
        raise HTTPException(status_code=400, detail="goal 和 template_id 至少填一个")
    try:
        plan = await orchestrator.build_plan(req.store_id, req.goal, req.template_id)
    except Exception as e:
        logger.error(f"[Pro] 生成任务树失败: {e}")
        raise HTTPException(status_code=500, detail=f"AI 店长生成计划失败: {e}")

    plan_id = uuid.uuid4().hex[:12]
    await _save_plan(Plan(
        id=plan_id,
        store_id=req.store_id,
        goal=plan.get("goal", req.goal),
        template_id=req.template_id or "",
        plan_json=json.dumps(plan, ensure_ascii=False),
        estimated_cost=plan.get("estimated_cost", 0),
        status="draft",
    ))
    return {
        "plan_id": plan_id,
        "goal": plan.get("goal"),
        "estimated_cost": plan.get("estimated_cost", 0),
        "plan": plan,
    }


# ── 2. 执行前计划确认：修改任务树 ───────────────────────

@pro_router.put("/plan/{plan_id}")
async def update_plan(plan_id: str, req: PlanUpdateRequest):
    """老板增 / 删 / 改步骤、调整顺序后保存，重算预估积分"""
    plan = await _load_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    if plan.status not in ("draft", "confirmed"):
        raise HTTPException(status_code=400, detail="计划已开始执行，无法修改")

    plan.plan_json = json.dumps(req.plan, ensure_ascii=False)
    plan.estimated_cost = await _recalc_cost(req.plan)
    plan.goal = req.plan.get("goal", plan.goal)
    plan.status = "confirmed"
    await _save_plan(plan)

    return {
        "plan_id": plan_id,
        "estimated_cost": plan.estimated_cost,
        "plan": req.plan,
        "message": "计划已确认，可点击开始执行",
    }


# ── 3. 开始执行 ─────────────────────────────────────────

@pro_router.post("/execute/{plan_id}")
async def execute_plan(plan_id: str):
    """启动 workflow_engine，返回 exec_id 供轮询"""
    plan = await _load_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")

    plan_dict: dict[str, Any] = json.loads(plan.plan_json)
    if not plan_dict.get("tasks"):
        raise HTTPException(status_code=400, detail="任务树为空")

    # 状态流转：draft/confirmed → running
    plan.status = "running"
    await _save_plan(plan)

    exec_obj = await workflow_engine.start(plan_dict, plan_id, plan.store_id)
    return {
        "exec_id": exec_obj.exec_id,
        "plan_id": plan_id,
        "status": "running",
        "estimated_cost": exec_obj.estimated_cost,
    }


# ── 4. 执行进度轮询 ─────────────────────────────────────

@pro_router.get("/execution/{exec_id}/status")
async def execution_status(exec_id: str):
    """各步骤状态：等待中 / 执行中 / 质检中 / 质检重试 / 已完成 / 待审批 / 失败"""
    status = await workflow_engine.get_status(exec_id)
    if status is None:
        raise HTTPException(status_code=404, detail="执行单不存在")
    return status


# ── 5. 人工审批发布 ─────────────────────────────────────

@pro_router.post("/approve")
async def approve(req: ApproveRequest):
    """老板确认发布：审批通过后由执行手脚自动推送"""
    result = await approval_gate.decide(req.approval_id, req.decision)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="审批单不存在")

    if result["status"] == "approved":
        payload = result.get("payload") or {}
        payload["action"] = payload.get("action") or result.get("action", "")
        payload["store_id"] = payload.get("store_id") or result.get("store_id", "")
        executed = await executor.execute(payload)
        return {
            "status": "approved",
            "approval_id": req.approval_id,
            "executed": executed,
            "message": "已批准并发布",
        }
    return {"status": "rejected", "approval_id": req.approval_id, "message": "已拒绝，未发布"}


# ── 6. 积分充值 ─────────────────────────────────────────

@pro_router.post("/recharge")
async def recharge(req: RechargeRequest):
    """充值积分（1 元 = 1 积分）"""
    balance = await billing.recharge(req.store_id, req.amount)
    return {"store_id": req.store_id, "recharged": req.amount, "balance": balance}


# ── 7. 查询余额 ─────────────────────────────────────────

@pro_router.get("/balance/{store_id}")
async def balance(store_id: str):
    """查询店铺积分余额"""
    bal = await billing.get_balance(store_id)
    return {"store_id": store_id, "balance": bal}


# ── 8. 创建周期任务 ─────────────────────────────────────

@pro_router.post("/schedule")
async def create_schedule(req: ScheduleRequest):
    """老板设置周期任务，后勤兵按 cron 触发"""
    schedule_id = uuid.uuid4().hex[:12]
    async with async_session() as session:
        session.add(Schedule(
            id=schedule_id,
            store_id=req.store_id,
            goal=req.goal,
            cron=req.cron,
            template_id=req.template_id or "",
            enabled=True,
        ))
        await session.commit()

    ok = register_schedule_job(schedule_id, req.cron, req.goal, req.store_id, req.template_id or "")
    return {
        "schedule_id": schedule_id,
        "store_id": req.store_id,
        "cron": req.cron,
        "registered": ok,
        "message": "周期任务已创建" if ok else "周期任务已保存（调度器未绑定，重启后生效）",
    }


# ── 9. 周期任务列表 ─────────────────────────────────────

@pro_router.get("/schedules/{store_id}")
async def schedules(store_id: str):
    """店铺周期任务列表"""
    items = await list_schedules(store_id)
    return {"store_id": store_id, "schedules": items}


# ── 辅助：周期任务启停（增量）──────────────────────────

@pro_router.post("/schedule/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: str, req: ScheduleToggleRequest):
    """启用 / 停用周期任务"""
    ok = await set_schedule_enabled(schedule_id, req.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="周期任务不存在")
    return {"schedule_id": schedule_id, "enabled": req.enabled}


# ── 辅助：快捷模板列表（增量，供前端按钮）──────────────

@pro_router.get("/templates")
async def list_templates():
    """快捷模板按钮列表"""
    return {
        "templates": [
            {"id": k, "name": v[:20], "goal": v}
            for k, v in TEMPLATES.items()
        ]
    }


# ── 辅助：积分流水（增量）───────────────────────────────

@pro_router.get("/transactions/{store_id}")
async def transactions(store_id: str, limit: int = 20):
    """积分流水"""
    items = await billing.list_transactions(store_id, limit=min(limit, 100))
    return {"store_id": store_id, "transactions": items}
