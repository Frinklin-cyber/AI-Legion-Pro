"""AI 店长主代理（Pro 版 Layer 1）

职责：接收老板目标 → 输出 JSON 任务树。
- 使用 DeepSeek（openai 兼容，AsyncOpenAI）
- system prompt 从 config/prompts/orchestrator.md 读取
- 调用前先从 store_memory 检索该 store_id 最近 N 条历史记录注入上下文
- 输出必须为合法 JSON（ORCHESTRATOR_OUTPUT_SCHEMA）
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from loguru import logger
from openai import AsyncOpenAI

from config.env import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from src.command.pro.billing import price_for_action
from src.command.pro.memory import store_memory

# 任务树输出 Schema（供前端渲染 / 编排引擎解析）
ORCHESTRATOR_OUTPUT_SCHEMA: dict[str, Any] = {
    "goal": str,
    "tasks": [
        {
            "id": "task_1",
            "department": "侦察兵|参谋部|创作部|后勤兵|知识库",
            "action": "str，如：竞品情报/店铺诊断/写引流文案",
            "depends_on": ["前置 task_id 列表"],
            "input": "dict，该任务的输入参数",
            "cost": "int，预估积分消耗",
            "needs_approval": "bool，对外发布/花钱 = true",
            "schedule": "str|None，cron 表达式，周期任务用",
        }
    ],
}

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config" / "prompts"

# 快捷模板（可选）：模板按钮 → 预填目标
TEMPLATES: dict[str, str] = {
    "weekend_drain": "策划本周末的引流活动，先诊断店铺现状，再生成一套朋友圈+抖音文案，最后安排定时发布",
    "weekly_plan": "制定下周的运营计划：包含竞品情报收集、店铺数据分析、一周朋友圈内容排期",
    "new_product": "为我的新品做推广方案：先做竞品情报，再写公众号长文和短视频脚本",
    "store_diagnosis": "对店铺做一次全面经营诊断，输出诊断报告和改善建议",
}


class Orchestrator:
    """AI 店长：目标 → 任务树"""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    def _load_system_prompt(self) -> str:
        """读取 orchestrator.md system prompt"""
        prompt_file = PROMPTS_DIR / "orchestrator.md"
        try:
            return prompt_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("[店长] orchestrator.md 未找到，使用内置默认 prompt")
            return (
                "你是一个 AI 店长，管理一支虚拟商业军团。"
                "当商家给你一个目标时：拆解为有序子任务，每个子任务指定负责部门，"
                "确定依赖关系，预估积分消耗，标记需要人工审批的任务，周期任务给出 cron。"
                "严格输出 JSON，不输出任何解释性文字。"
            )

    async def build_plan(self, store_id: str, goal: str,
                         template_id: str | None = None) -> dict[str, Any]:
        """生成任务树

        Returns:
            {"goal": str, "tasks": [...], "estimated_cost": int}
        """
        # 1. 快捷模板 → 目标
        final_goal = goal or TEMPLATES.get(template_id or "", goal)

        # 2. 注入店铺历史记忆
        memory_ctx = store_memory.build_context(store_id, final_goal, top_k=5)

        system_prompt = self._load_system_prompt()
        user_message = self._build_user_message(store_id, final_goal, memory_ctx)

        content = await self._chat_json(system_prompt, user_message)
        plan = self._parse_task_tree(content, final_goal)

        # 3. 兜底计算预估积分（确保 cost 有值）
        estimated = self._estimate_cost(plan)
        plan["estimated_cost"] = estimated
        return plan

    def _build_user_message(self, store_id: str, goal: str, memory_ctx: str) -> str:
        return (
            f"【店铺 ID】{store_id}\n"
            f"【老板目标】{goal}\n"
            f"【店铺历史记忆】\n{memory_ctx}\n\n"
            f"请根据上述信息输出 JSON 任务树。"
        )

    async def _chat_json(self, system_prompt: str, user_message: str) -> str:
        """调用 DeepSeek 返回文本"""
        response = await self.client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=3000,
        )
        return response.choices[0].message.content or ""

    def _parse_task_tree(self, content: str, fallback_goal: str) -> dict[str, Any]:
        """从 LLM 输出中提取合法 JSON 任务树（容错解析）"""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # 尝试截取 {} 包裹的最外层 JSON
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(content[start:end + 1])
                except json.JSONDecodeError:
                    data = {}
            else:
                data = {}

        goal = data.get("goal") or fallback_goal
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("AI 店长未生成有效任务树，请重试")

        # 规范化每个任务
        normalized: list[dict[str, Any]] = []
        for i, t in enumerate(tasks, 1):
            if not isinstance(t, dict):
                continue
            dept = str(t.get("department", "参谋部"))
            action = str(t.get("action", "通用任务"))
            normalized.append({
                "id": str(t.get("id", f"task_{i}")),
                "department": dept,
                "action": action,
                "depends_on": list(t.get("depends_on", []) or []),
                "input": t.get("input") or {},
                "cost": int(t.get("cost", 0) or price_for_action(action)),
                "needs_approval": bool(t.get("needs_approval", False)),
                "schedule": t.get("schedule"),
            })
        return {"goal": goal, "tasks": normalized}

    def _estimate_cost(self, plan: dict[str, Any]) -> int:
        """兜底预估积分"""
        return sum(int(t.get("cost", 0) or 0) for t in plan.get("tasks", []))

    def parse_schedule(self, plan: dict[str, Any]) -> str | None:
        """从任务树中提取 cron 表达式（周期任务用）"""
        for t in plan.get("tasks", []):
            if t.get("schedule"):
                return str(t["schedule"])
        return None


# 全局单例
orchestrator = Orchestrator()
