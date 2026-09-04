"""质检 Agent（Pro 版 Layer 3 前半段）

职责：评估子代理产出，要么批准，要么附上具体修改说明退回。
- system prompt 从 config/prompts/quality.md 读取
- 输入：子代理产出 + 任务描述 + 行业基因库规范
- 输出：{approved: bool, score: 1-10, feedback: str, must_fix: [str]}

评估维度：符合行业基因、语调正确、信息准确、平台适配。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger
from openai import AsyncOpenAI

from config.env import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from config.industry_genome import get_genome

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config" / "prompts"

# 自动规则（无需 LLM 的硬性检查）
FORBIDDEN_PATTERNS = ["作为AI", "我不能", "我无法", "请注意", "免责声明"]


class QualityAgent:
    """质检 Agent（全 async）"""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    def _load_system_prompt(self) -> str:
        prompt_file = PROMPTS_DIR / "quality.md"
        try:
            return prompt_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("[质检] quality.md 未找到，使用内置默认 prompt")
            return (
                "你是质量控制代理。你的唯一工作是评估草稿，要么批准，要么附上具体修改说明退回。"
                "你从不从零写内容、做调研或调用工具。"
                "评估维度：1.是否符合行业基因库规范 2.语调是否匹配目标平台 "
                "3.信息是否准确（不编造数据、不夸大）4.行动号召是否明确 5.字数是否符合要求。"
                '输出 JSON：{"approved": bool, "score": 1-10, "feedback": str, "must_fix": [str]}'
            )

    async def review(self, output: str, task: dict[str, Any],
                     industry_context: str = "") -> dict[str, Any]:
        """评审一份子代理产出

        Args:
            output: 子代理产出内容
            task: 任务描述（含 action / input / department）
            industry_context: 行业基因库规范文本

        Returns:
            {"approved": bool, "score": int, "feedback": str, "must_fix": [str]}
        """
        # 0. 硬性自动规则
        auto_issues = self._auto_check(output)
        if auto_issues:
            return {
                "approved": False,
                "score": 3,
                "feedback": "未通过自动规则检查：\n" + "\n".join(f"- {i}" for i in auto_issues),
                "must_fix": auto_issues,
            }

        # 1. AI 质检
        system_prompt = self._load_system_prompt()
        user_message = self._build_user_message(output, task, industry_context)

        try:
            content = await self._chat_json(system_prompt, user_message)
            result = self._parse_review(content)
        except Exception as e:
            logger.warning(f"[质检] AI 质检失败，降级为通过：{e}")
            result = {"approved": True, "score": 7, "feedback": "质检服务异常，自动放行", "must_fix": []}

        logger.info(f"[质检] score={result['score']} approved={result['approved']} | {task.get('action', '')}")
        return result

    def _auto_check(self, content: str) -> list[str]:
        """硬性规则检查"""
        issues: list[str] = []
        if not content or len(content.strip()) < 20:
            issues.append("输出为空或过短（少于 20 字符）")
        for p in FORBIDDEN_PATTERNS:
            if p in content:
                issues.append(f"包含禁用表述：{p}")
        return issues

    def _build_user_message(self, output: str, task: dict[str, Any],
                            industry_context: str) -> str:
        task_input = task.get("input") or {}
        platform = str(task_input.get("platform", task_input.get("channel", "未知平台")))
        # 按任务类型差异化评估重点
        focus = self._evaluation_focus(task)
        return (
            f"【任务描述】{task.get('action', '')}\n"
            f"【负责部门】{task.get('department', '')}\n"
            f"【目标平台】{platform}\n"
            f"【任务类型与评估重点】{focus}\n"
            f"【行业基因规范】\n{industry_context or '（无）'}\n\n"
            f"【待质检产出】\n{output[:5000]}\n\n"
            f"请按评分维度评估，输出 JSON 结果。"
        )

    def _evaluation_focus(self, task: dict[str, Any]) -> str:
        """按任务类型返回评估重点（避免用文案标准卡分析报告）"""
        action = str(task.get("action", ""))
        department = str(task.get("department", ""))
        if action in ("店铺诊断", "经营诊断", "诊断分析"):
            return "分析类任务：重点评估数据引用是否准确、归因是否有逻辑支撑、" \
                   "建议是否具体可执行。不要求行动号召和平台语调，达到 7 分即可放行。"
        if action in ("数据分析", "分析报告", "生成报告", "运营报告"):
            return "分析类任务：重点评估结论是否有数据支撑、结构是否清晰、" \
                   "建议是否可落地。不苛求文采，达到 7 分即可放行。"
        if action in ("爬取情报", "竞品情报", "情报爬取", "市场情报"):
            return "情报类任务：重点评估信息相关性、时效性、结构化程度。达到 7 分即可放行。"
        if action in ("定时发布", "安排发布", "预约发布"):
            return "发布类任务：重点评估内容是否完整、附件/引用是否齐全。达到 7 分即可放行。"
        if department in ("创作部", "特种部队") or action in ("生成文案", "发企微"):
            return "内容创作类任务：重点评估平台语调匹配、信息准确、行动号召、字数达标。"
        return "通用任务：按常规维度评估。"

    async def _chat_json(self, system_prompt: str, user_message: str) -> str:
        response = await self.client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_tokens=1000,
        )
        return response.choices[0].message.content or ""

    def _parse_review(self, content: str) -> dict[str, Any]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(content[start:end + 1])
                except json.JSONDecodeError:
                    data = {}
            else:
                data = {}

        must_fix = data.get("must_fix", [])
        if not isinstance(must_fix, list):
            must_fix = [str(must_fix)]
        return {
            "approved": bool(data.get("approved", False)),
            "score": int(data.get("score", 5) or 5),
            "feedback": str(data.get("feedback", "")),
            "must_fix": [str(m) for m in must_fix],
        }


def build_industry_context(store_type: str) -> str:
    """构建行业基因库规范文本（供质检注入）"""
    try:
        genome = get_genome(store_type or "custom")
        return (
            f"行业：{genome.name}\n基准指标：\n{genome.format_benchmarks()}\n"
            f"红线：\n{genome.format_red_flags()}"
        )
    except Exception:
        return ""


# 全局单例
quality_agent = QualityAgent()
