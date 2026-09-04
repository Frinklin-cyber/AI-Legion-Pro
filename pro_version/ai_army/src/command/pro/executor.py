"""执行手脚（Pro 版发布层）

接收通过审批 / 无需审批的 task_result，根据 action 分发到现有模块函数。
现有五大模块一行不改，只 import 调用。

动作分发表（ACTIONS）：
    发企微    → scouts.push.push_to_wecom      （企业微信机器人推送）
    爬取情报  → scouts.crawler.crawl_all       （抓取行业资讯）
    生成文案  → special_forces.ContentCreator  （内容创作流水线）
    数据分析  → staff.DataAnalyst              （数据问答分析）
    分析报告  → staff.reporter.save_report     （生成 HTML/MD 报告）
    店铺诊断  → staff.AttributionAnalyzer      （归因诊断）
    定时发布  → logistics.TaskScheduler        （Celery 风格 cron 任务）
    存报告    → knowledge 向量库                （存入店铺知识库/记忆）
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from loguru import logger

from src.command.pro.memory import store_memory
from src.command.pro.billing import price_for_action


# ── 同步处理函数（在线程池中执行，不阻塞事件循环）─────────────

def _handle_generate_copy(payload: dict[str, Any]) -> dict[str, Any]:
    """生成文案 / 朋友圈 / 脚本"""
    from src.special_forces.content_gen import ContentCreator
    creator = ContentCreator()
    task: dict[str, Any] = {
        "type": payload.get("content_type", "article"),
        "topic": payload.get("topic", payload.get("content", "")),
        "target_audience": payload.get("audience", "通用"),
        "style": payload.get("style", "衡水风格"),
        "platform": payload.get("platform", ""),
    }
    result = creator.execute(task)
    return {"content": result.get("content", ""), "tokens_used": result.get("tokens_used", 0)}


def _handle_crawl_intel(payload: dict[str, Any]) -> dict[str, Any]:
    """爬取竞品情报 + 生成结构化简报"""
    from src.scouts.crawler import crawl_all
    from src.scouts.summarizer import IntelligenceSummarizer

    items = crawl_all()
    if not items:
        return {"items": [], "briefing": "今日无新情报", "item_count": 0}
    summarizer = IntelligenceSummarizer()
    result = summarizer.execute({
        "items": items,
        "focus_keywords": payload.get("focus_keywords", []),
        "industry_context": payload.get("industry_context", ""),
    })
    return {
        "items": items,
        "briefing": result.get("briefing", ""),
        "item_count": result.get("item_count", len(items)),
    }


def _handle_data_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    """数据分析 / 问答"""
    from src.staff.data_agent import DataAnalyst
    analyst = DataAnalyst()
    task: dict[str, Any] = {
        "question": payload.get("question", payload.get("goal", "分析当前经营状况")),
        "filepath": payload.get("filepath", ""),
        "analysis_type": payload.get("analysis_type", "auto"),
    }
    result = analyst.execute(task)
    return {
        "report": result.get("report", ""),
        "analysis_type": result.get("analysis_type", "auto"),
        "tokens_used": result.get("tokens_used", 0),
    }


def _handle_store_diagnosis(payload: dict[str, Any]) -> dict[str, Any]:
    """店铺诊断（归因分析）"""
    from src.staff.attribution_analyzer import AttributionAnalyzer
    analyzer = AttributionAnalyzer()
    diagnosis = analyzer.build_diagnosis(
        store_type=payload.get("store_type", "custom"),
        kpi_snapshots=payload.get("kpi_snapshots", []),
        red_flags=payload.get("red_flags", []),
        trend_data=payload.get("trend_data", ""),
        region_context=payload.get("region_context", ""),
    )
    text = (
        f"【观察】{diagnosis.observation}\n"
        f"【归因】{diagnosis.attribution}\n"
        f"【建议】{diagnosis.recommendation}\n"
        f"【预期收益】{diagnosis.expected_impact}"
    )
    return {"diagnosis": text, "detail": diagnosis.dict() if hasattr(diagnosis, "dict") else {}}


def _handle_generate_report(payload: dict[str, Any]) -> dict[str, Any]:
    """生成 HTML / Markdown 分析报告"""
    from src.staff.reporter import save_report
    analysis_text = payload.get("report", payload.get("content", ""))
    title = payload.get("title", "AI 军团运营分析报告")
    results = save_report(analysis_text=analysis_text, output_dir="./data/reports",
                          fmt=payload.get("format", "md"), title=title)
    return {"files": results, "title": title}


def _handle_wecom_push(payload: dict[str, Any]) -> dict[str, Any]:
    """企业微信推送"""
    from src.scouts.push import push_to_wecom
    content = payload.get("content", "")
    msg_type = payload.get("msg_type", "markdown")
    ok = push_to_wecom(content, msg_type)
    detail = "推送成功" if ok else "推送失败（未配置 Webhook 或企微返回错误）"
    return {"pushed": bool(ok), "detail": detail}


def _handle_schedule_post(payload: dict[str, Any]) -> dict[str, Any]:
    """定时发布（注册到任务调度器）"""
    from src.command.pro.scheduler_pro import register_schedule_job
    schedule_id = payload.get("schedule_id", "")
    cron = payload.get("cron", "")
    goal = payload.get("goal", payload.get("content", ""))
    store_id = payload.get("store_id", "")
    if schedule_id and cron and goal:
        ok = register_schedule_job(schedule_id, cron, goal, store_id)
        return {"pushed": bool(ok), "detail": "定时任务已注册" if ok else "调度器未绑定，仅落库"}
    return {"pushed": False, "detail": "缺少 schedule_id / cron / goal 参数"}


def _handle_save_report(payload: dict[str, Any]) -> dict[str, Any]:
    """存报告 → 写入店铺长期记忆"""
    content = payload.get("content", payload.get("report", ""))
    store_id = payload.get("store_id", "")
    if content and store_id:
        store_memory.save(store_id, "final", content, {"action": payload.get("action", "")})
    return {"saved": bool(content), "store_id": store_id}


# ── 动作分发表 ──────────────────────────────────────────────
# key 为 AI 店长可能输出的 action 名（含别名），统一路由到具体处理函数

ACTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    # 企业微信推送
    "发企微": _handle_wecom_push,
    "企微推送": _handle_wecom_push,
    "推送": _handle_wecom_push,
    # 内容创作
    "生成文案": _handle_generate_copy,
    "写引流文案": _handle_generate_copy,
    "写文案": _handle_generate_copy,
    "发朋友圈": _handle_generate_copy,
    "朋友圈文案": _handle_generate_copy,
    "生成短视频脚本": _handle_generate_copy,
    "短视频脚本": _handle_generate_copy,
    "生成图文": _handle_generate_copy,
    # 情报
    "爬取情报": _handle_crawl_intel,
    "竞品情报": _handle_crawl_intel,
    "情报爬取": _handle_crawl_intel,
    "市场情报": _handle_crawl_intel,
    # 数据分析
    "数据分析": _handle_data_analysis,
    "数据问答": _handle_data_analysis,
    # 分析报告
    "分析报告": _handle_generate_report,
    "生成报告": _handle_generate_report,
    "运营报告": _handle_generate_report,
    # 店铺诊断
    "店铺诊断": _handle_store_diagnosis,
    "经营诊断": _handle_store_diagnosis,
    "诊断分析": _handle_store_diagnosis,
    # 定时发布
    "定时发布": _handle_schedule_post,
    "安排发布": _handle_schedule_post,
    "预约发布": _handle_schedule_post,
    # 存报告 / 记忆
    "存报告": _handle_save_report,
    "保存报告": _handle_save_report,
    "存入记忆": _handle_save_report,
}


class Executor:
    """执行手脚（全 async）"""

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """按 payload 中的 action 分发执行

        Args:
            payload: {"action": str, ...任务参数}

        Returns:
            {"status": "success"|"unknown_action"|"failed", "result": {...}}
        """
        action = str(payload.get("action", ""))
        handler = ACTIONS.get(action)
        if handler is None:
            return {"status": "unknown_action", "result": {"error": f"未知动作: {action}"}}

        logger.info(f"[执行手] 分发动作: {action}")
        try:
            # 同步模块在线程池执行，避免阻塞事件循环
            result = await asyncio.to_thread(handler, payload)
            return {"status": "success", "action": action, "result": result}
        except Exception as e:
            logger.error(f"[执行手] {action} 执行失败: {e}")
            return {"status": "failed", "action": action, "result": {"error": str(e)}}

    @staticmethod
    def resolve_department(department: str) -> str:
        """部门别名归一化"""
        mapping = {
            "侦察兵": "scouts",
            "参谋部": "staff",
            "创作部": "special_forces",
            "特种部队": "special_forces",
            "后勤兵": "logistics",
            "知识库": "knowledge",
        }
        return mapping.get(department, department)


# 全局单例
executor = Executor()
