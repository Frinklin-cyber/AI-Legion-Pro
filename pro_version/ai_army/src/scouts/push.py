"""侦察兵 - 消息推送器

支持推送到：
- 企业微信机器人（Webhook）
- 飞书机器人（Webhook）
- 本地Markdown文件
"""

from typing import Any
from datetime import datetime

import requests
import httpx
from loguru import logger

from config.env import WECOM_WEBHOOK_URL, FEISHU_WEBHOOK_URL


def push_to_wecom(content: str, msg_type: str = "markdown") -> bool:
    """推送到企业微信群机器人

    Args:
        content: 消息内容（支持markdown格式）
        msg_type: 消息类型（text/markdown）

    Returns:
        是否推送成功
    """
    if not WECOM_WEBHOOK_URL:
        logger.warning("[推送] 未配置企业微信Webhook，跳过推送")
        return False

    payload: dict[str, Any] = {
        "msgtype": msg_type,
        msg_type: {"content": content},
    }

    try:
        resp = requests.post(WECOM_WEBHOOK_URL, json=payload, timeout=10)
        result = resp.json()
        if result.get("errcode") == 0:
            logger.info("[推送] ✅ 企业微信推送成功")
            return True
        else:
            logger.error(f"[推送] ❌ 企业微信推送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"[推送] ❌ 企业微信推送异常: {e}")
        return False


def push_to_feishu(content: str) -> bool:
    """推送到飞书机器人

    Args:
        content: 消息内容（支持Markdown）

    Returns:
        是否推送成功
    """
    if not FEISHU_WEBHOOK_URL:
        logger.warning("[推送] 未配置飞书Webhook，跳过推送")
        return False

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "📰 每日情报简报"},
            },
            "elements": [
                {"tag": "markdown", "content": content},
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}"}
                    ],
                },
            ],
        },
    }

    try:
        resp = requests.post(FEISHU_WEBHOOK_URL, json=payload, timeout=10)
        result = resp.json()
        if result.get("code") == 0:
            logger.info("[推送] ✅ 飞书推送成功")
            return True
        else:
            logger.error(f"[推送] ❌ 飞书推送失败: {result}")
            return False
    except Exception as e:
        logger.error(f"[推送] ❌ 飞书推送异常: {e}")
        return False


def save_briefing_to_file(briefing: str, output_dir: str = "./data/briefings") -> str:
    """保存简报到本地Markdown文件

    Args:
        briefing: 简报内容
        output_dir: 输出目录

    Returns:
        文件路径
    """
    import os
    os.makedirs(output_dir, exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{output_dir}/briefing_{date_str}.md"
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(briefing)
    
    logger.info(f"[推送] ✅ 简报已保存: {filename}")
    return filename


def push_briefing(briefing: str, channels: list[str] | None = None) -> dict[str, bool]:
    """多渠道推送简报

    Args:
        briefing: 简报Markdown内容
        channels: 推送渠道列表，支持 ["wecom", "feishu", "file"]
                  为None时尝试所有配置了的渠道

    Returns:
        {"wecom": True/False, "feishu": True/False, "file": True/False}
    """
    if channels is None:
        channels = ["wecom", "feishu", "file"]

    results: dict[str, bool] = {}

    if "wecom" in channels:
        # 企微markdown消息限制4096字节，截断处理
        truncated = briefing[:3800] + ("\n\n...(内容过长已截断)" if len(briefing) > 3800 else "")
        results["wecom"] = push_to_wecom(truncated)

    if "feishu" in channels:
        results["feishu"] = push_to_feishu(briefing[:4000])

    if "file" in channels:
        save_briefing_to_file(briefing)
        results["file"] = True

    return results


# ====== 日常简报推送（定时任务入口） ======
async def daily_briefing_task() -> None:
    """每日简报定时任务 - 供Celery Beat / APScheduler调用"""
    from src.scouts.crawler import crawl_all
    from src.scouts.summarizer import IntelligenceSummarizer

    logger.info("=" * 50)
    logger.info("📡 每日情报简报任务启动")
    logger.info("=" * 50)

    # 1. 爬取
    items = crawl_all()
    if not items:
        logger.warning("今日无新情报")
        push_to_wecom("📭 今日无新增行业动态。")
        return

    # 2. 摘要
    summarizer = IntelligenceSummarizer()
    result = summarizer.execute({"items": items})

    # 3. 推送
    push_results = push_briefing(result["briefing"])
    logger.info(f"推送结果: {push_results}")


if __name__ == "__main__":
    # 测试推送
    test_msg = "## 测试消息\n这是一条来自AI军团的测试推送。\n\n> 一切正常！"
    
    print("测试企业微信推送...")
    push_to_wecom(test_msg)
    
    print("测试飞书推送...")
    push_to_feishu(test_msg)
    
    print("保存本地文件...")
    save_briefing_to_file(test_msg)
