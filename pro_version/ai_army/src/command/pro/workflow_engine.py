"""任务编排引擎（Pro 版 Layer 2）

职责：解析任务树 → 按依赖分层 → 并行执行 → 质检重试 → 扣费结算 → 存结果。

每个 task 的执行流程：
1. 检查依赖是否全部完成，未完成则等待下一轮
2. 从 results 取出前置任务输出，注入当前 task.input
3. 调用 billing.deduct 预扣（余额不足则该任务失败，不影响其他）
4. 普通任务 → executor.execute 直接执行；审批型任务 → 产出草稿待老板确认
5. 调 quality_agent.review 质检，不通过自动重试（最多 2 次，注入修改意见）
6. 质检最终不通过 / 执行失败 → 退还该任务预扣积分，任务标记 failed
7. 成功 → 输出存入 results，actual_cost 累加
8. needs_approval → 写入 approval_gate 返回 approval_id，等待老板审批后再发布
9. 全部结束后结算：实际消耗 = 成功任务 cost 之和（失败任务已即时退款）
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from src.db import async_session
from src.command.pro.billing import billing, InsufficientBalanceError
from src.command.pro.executor import executor
from src.command.pro.quality_agent import quality_agent, build_industry_context
from src.command.pro.approval_gate import approval_gate
from src.command.pro.runtime import Execution, TaskStep, new_execution, get_execution, RUNNING_TASKS

MAX_QUALITY_RETRIES = 2  # 质检最多重试 2 次


class WorkflowEngine:
    """编排引擎（全 async）"""

    async def start(self, plan: dict[str, Any], plan_id: str, store_id: str) -> Execution:
        """启动一次执行（立即返回执行单，后台跑任务树）"""
        goal = plan.get("goal", "")
        tasks = plan.get("tasks", [])
        exec_obj = new_execution(plan_id, store_id, goal, tasks)

        task = asyncio.create_task(self._run(exec_obj))
        RUNNING_TASKS.add(task)
        task.add_done_callback(RUNNING_TASKS.discard)
        logger.info(f"[编排] 执行单 {exec_obj.exec_id} 已启动（{len(tasks)} 个任务）")
        return exec_obj

    async def _run(self, exec_obj: Execution) -> None:
        """按依赖分层调度，直到全部结束"""
        try:
            while exec_obj.status == "running":
                # 选出一批依赖已完成的 waiting 任务
                ready = [s for s in exec_obj.step_list
                         if s.status == "waiting" and self._deps_done(exec_obj, s)]
                if not ready:
                    unfinished = [s for s in exec_obj.step_list if s.status in ("waiting", "running")]
                    if unfinished:
                        # 存在循环依赖 / 前置失败 / 被阻塞
                        blocked = [s.id for s in unfinished]
                        logger.warning(f"[编排] 任务被阻塞: {blocked}")
                        exec_obj.error = f"任务依赖无法满足，被阻塞: {blocked}"
                        exec_obj.status = "failed"
                    break
                # 1. 串行预扣（避免并发读改写竞态），余额不足的任务直接失败
                prepaid: list[TaskStep] = []
                for s in ready:
                    try:
                        await billing.deduct(exec_obj.store_id, s.cost, exec_obj.plan_id)
                        prepaid.append(s)
                    except InsufficientBalanceError as e:
                        s.status = "failed"
                        s.error = str(e)
                        logger.error(f"[编排] 任务 {s.id} 中止: {e}")
                # 2. 并行执行已预扣任务
                await asyncio.gather(*(self._process_step(exec_obj, s) for s in prepaid))

            # 结算（失败任务已即时退款，此处仅统计实耗）
            await self._settle(exec_obj)
        except Exception as e:
            logger.error(f"[编排] 执行单 {exec_obj.exec_id} 异常: {e}")
            exec_obj.status = "failed"
            exec_obj.error = str(e)

    def _deps_done(self, exec_obj: Execution, step: TaskStep) -> bool:
        return all(dep in exec_obj.results for dep in step.depends_on)

    async def _process_step(self, exec_obj: Execution, step: TaskStep) -> None:
        """处理单个任务：执行 → 质检 → 重试 → 审批/落库（预扣已在 _run 串行完成）"""
        step.status = "running"
        step.started_at = _now()

        # 1. 注入前置任务输出
        input_data = dict(step.input)
        for dep in step.depends_on:
            if dep in exec_obj.results:
                input_data[f"__dep_{dep}"] = exec_obj.results[dep]

        # 2. 执行（审批型任务产出草稿，普通任务直接执行）
        output_text = ""
        if step.needs_approval:
            output_text = self._build_draft(exec_obj, step, input_data)
            if not output_text:
                step.status = "failed"
                step.error = "审批型任务无可用内容（请确认前置任务已生成）"
                await self._refund(exec_obj, step)
                return
        else:
            payload: dict[str, Any] = {
                **input_data, "action": step.action, "store_id": exec_obj.store_id,
            }
            result = await executor.execute(payload)
            if result["status"] != "success":
                step.status = "failed"
                step.error = str(result["result"])
                await self._refund(exec_obj, step)
                logger.error(f"[编排] 任务 {step.id} 执行失败: {step.error}")
                return
            output_text = self._stringify_output(result["result"])

        # 4. 质检（自动重试，最多 2 次）
        industry_ctx = build_industry_context(input_data.get("store_type", "custom"))
        passed = await self._quality_review(output_text, step, industry_ctx, input_data)
        if not passed:
            step.status = "failed"
            step.output = output_text
            await self._refund(exec_obj, step)
            return

        # 5. 结果入库
        step.output = output_text
        exec_obj.results[step.id] = output_text
        exec_obj.actual_cost += step.cost

        # 6. 审批型任务 → 人工审批网关（payload 携带执行所需完整参数）
        if step.needs_approval:
            # 定时发布类任务：补充 cron / schedule_id / goal，审批通过后可立即注册
            cron = step.schedule or input_data.get("cron", "") or input_data.get("schedule", "")
            approval_payload: dict[str, Any] = {
                **input_data,
                "action": step.action,
                "content": output_text,
                "store_id": exec_obj.store_id,
                "schedule_id": f"plan_{exec_obj.plan_id}_task_{step.id}",
                "cron": cron,
                "goal": exec_obj.goal,
            }
            approval_id = await approval_gate.create(
                store_id=exec_obj.store_id,
                plan_id=exec_obj.plan_id,
                task_id=step.id,
                action=step.action,
                payload=approval_payload,
            )
            step.approval_id = approval_id
            step.status = "needs_approval"
            step.finished_at = _now()
            logger.info(f"[编排] 任务 {step.id} 待老板审批 #{approval_id}")
            return

        step.status = "done"
        step.finished_at = _now()
        logger.info(f"[编排] 任务 {step.id} 完成 ✅")

    async def _quality_review(self, output: str, step: TaskStep,
                              industry_ctx: str, input_data: dict[str, Any]) -> bool:
        """质检 + 自动重试（最多 2 次）。通过返回 True。"""
        step.status = "quality_checking"
        review = await quality_agent.review(output, {
            "action": step.action,
            "department": step.department,
            "input": input_data,
        }, industry_ctx)

        while not review.get("approved") and step.retry_count < MAX_QUALITY_RETRIES:
            step.retry_count += 1
            step.status = "quality_retry"
            step.feedback = review.get("feedback", "")
            logger.info(f"[编排] 任务 {step.id} 质检未通过，第 {step.retry_count} 次重试")

            # 重新执行（注入修改意见）
            payload: dict[str, Any] = {
                **input_data,
                "action": step.action,
                "store_id": input_data.get("store_id", ""),
                "_quality_feedback": review.get("feedback", ""),
                "must_fix": review.get("must_fix", []),
            }
            if step.needs_approval:
                output = self._build_draft_with_feedback(step, input_data, review)
            else:
                result = await executor.execute(payload)
                output = self._stringify_output(result["result"]) if result["status"] == "success" else ""
            step.output = output

            review = await quality_agent.review(output, {
                "action": step.action,
                "department": step.department,
                "input": input_data,
            }, industry_ctx)

        step.feedback = review.get("feedback", "")
        if not review.get("approved"):
            step.error = f"质检重试 {step.retry_count} 次后仍未通过：{review.get('feedback', '')}"
            logger.warning(f"[编排] 任务 {step.id} 质检最终未通过")
            return False
        step.status = "quality_passed"
        return True

    async def _refund(self, exec_obj: Execution, step: TaskStep) -> None:
        """任务失败，退还未消耗的预扣积分"""
        try:
            await billing.refund(exec_obj.store_id, step.cost, exec_obj.plan_id)
        except Exception as e:
            logger.error(f"[编排] 任务 {step.id} 退款失败: {e}")

    # ── 草稿构建（审批型任务）─────────────────────────
    def _build_draft(self, exec_obj: Execution, step: TaskStep, input_data: dict[str, Any]) -> str:
        """审批型任务：从 input / 依赖输出中收集待发布内容"""
        parts: list[str] = []
        content = input_data.get("content") or input_data.get("draft")
        if content:
            parts.append(str(content))
        for dep in step.depends_on:
            if dep in exec_obj.results:
                parts.append(f"[来源: {dep}]\n{str(exec_obj.results[dep])}")
        return "\n\n".join(parts)

    def _build_draft_with_feedback(self, step: TaskStep, input_data: dict[str, Any],
                                   review: dict[str, Any]) -> str:
        draft = str(input_data.get("content") or step.output or "")
        fix = review.get("must_fix", [])
        if fix:
            draft += "\n\n【按质检意见修订】\n" + "\n".join(f"- {m}" for m in fix)
        return draft

    def _stringify_output(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            # 取最可能的人类可读字段
            for key in ("content", "briefing", "report", "diagnosis", "answer"):
                if result.get(key):
                    return str(result[key])
            return json.dumps(result, ensure_ascii=False, indent=2)
        return str(result)

    # ── 结算 ─────────────────────────────────────────
    async def _settle(self, exec_obj: Execution) -> None:
        done = [s for s in exec_obj.step_list if s.status in ("done", "needs_approval")]
        failed = [s for s in exec_obj.step_list if s.status == "failed"]
        if failed:
            exec_obj.status = "failed"
            exec_obj.error = f"有 {len(failed)} 个任务失败: {[s.id for s in failed]}"
        else:
            exec_obj.status = "done"
        exec_obj.finished_at = _now()
        exec_obj.actual_cost = sum(s.cost for s in done)
        logger.info(
            f"[编排] 结算完成: 预估 {exec_obj.estimated_cost}，实耗 {exec_obj.actual_cost}，"
            f"失败 {len(failed)} 个任务"
        )

        # 回写计划状态（running → done/failed）
        try:
            from src.db.models import Plan
            async with async_session() as session:
                plan = await session.get(Plan, exec_obj.plan_id)
                if plan is not None:
                    plan.status = exec_obj.status
                    plan.estimated_cost = exec_obj.actual_cost
                    await session.commit()
        except Exception as e:
            logger.warning(f"[编排] 计划状态回写失败: {e}")

    # ── 对外查询 ─────────────────────────────────────
    async def get_status(self, exec_id: str) -> dict[str, Any] | None:
        exec_obj = get_execution(exec_id)
        return exec_obj.to_dict() if exec_obj else None


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat()


# 全局单例
workflow_engine = WorkflowEngine()
