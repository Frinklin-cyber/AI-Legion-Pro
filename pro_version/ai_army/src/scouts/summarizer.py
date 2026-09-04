"""侦察兵 - AI摘要生成器

调用DeepSeek将爬取的新闻生成200字结构化每日简报。
"""

from typing import Any

from loguru import logger

from src.core import BaseSoldier

BRIEFING_SYSTEM_PROMPT = """你是一名顶尖的商业情报分析官，负责为企业决策者生成每日情报简报。

## 输出格式要求
请严格按照以下Markdown结构输出：

# 📰 AI军团每日情报简报
**日期：** {date}

## 🔥 今日重点关注（Top 3）
1. **【标题】** - 一句话说明为什么重要
2. ...
3. ...

## 📊 行业动态速览
- 按主题归类，每类1-2条要点

## 💡 战略启示（对我方业务的启示）
- 基于今日情报，提炼1-3条可行动的洞察

## ⚠️ 风险预警
- 对可能影响业务的风险进行标注

---
*本简报由AI军团侦察兵自动生成*
"""


class IntelligenceSummarizer(BaseSoldier):
    """情报摘要生成器 - 侦察兵核心AI"""

    name = "侦察兵-摘要官"
    role = "scout_summarizer"
    temperature = 0.5
    max_tokens = 1500

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """将新闻列表生成为每日简报

        Args:
            task: {
                "items": list[dict],  # 新闻列表
                "date": str,         # 简报日期（可选，默认今天）
                "focus_keywords": list[str],  # 关注关键词（可选）
                "industry_context": str,  # 行业上下文描述（可选，用于精准聚焦）
            }

        Returns:
            {"briefing": "markdown字符串", "tokens_used": int}
        """
        items = task.get("items", [])
        if not items:
            return {"briefing": "# 今日无新情报\n暂无需要汇报的行业动态。", "tokens_used": 0}

        date_str = task.get("date", __import__("datetime").date.today().isoformat())
        focus = task.get("focus_keywords", ["AI", "企业服务", "数字化转型", "SaaS"])
        industry_context = task.get("industry_context", "")

        # 构建新闻文本
        news_text = "\n\n".join(
            f"### [{i+1}] {item['title']}\n"
            f"- 来源: {item.get('source', '未知')}\n"
            f"- 链接: {item.get('link', '无')}\n"
            f"- 摘要: {item.get('summary', '无')}"
            for i, item in enumerate(items[:30])  # 最多30条
        )

        # 构建用户消息
        if industry_context:
            user_message = f"""请基于以下今日情报，生成每日简报。

**行业上下文：** {industry_context}

**重点筛选与解读：** 请优先筛选与该行业相关的情报，从行业经营视角解读。
- 竞品动态、营销策略、供应链变化等与实体经营相关的情报优先
- 与行业无关的通用科技新闻可放在次要位置

**重点关注领域：** {', '.join(focus)}

**今日原始情报（共{len(items)}条，展示{min(len(items), 30)}条）：**

{news_text}

请按照系统指令中的格式要求，生成结构化的每日情报简报。语言精炼，每部分不超过200字。"""
        else:
            user_message = f"""请基于以下今日情报，生成每日简报。

**重点关注领域：** {', '.join(focus)}

**今日原始情报（共{len(items)}条，展示{min(len(items), 30)}条）：**

{news_text}

请按照系统指令中的格式要求，生成结构化的每日情报简报。语言精炼，每部分不超过200字。"""

        system_prompt = BRIEFING_SYSTEM_PROMPT.format(date=date_str)

        logger.info(f"[摘要官] 开始处理 {len(items)} 条情报...")
        if industry_context:
            logger.info(f"[摘要官] 行业聚焦模式: {industry_context[:80]}...")
        briefing, tokens = self.chat(system_prompt, user_message)
        logger.info(f"[摘要官] 简报生成完成，消耗 {tokens} tokens")

        return {
            "briefing": briefing,
            "tokens_used": tokens,
            "item_count": len(items),
        }


# ====== 使用示例 ======
if __name__ == "__main__":
    from src.scouts.crawler import crawl_all

    # 1. 爬取新闻
    print("=" * 60)
    print("📡 侦察兵出动 - 正在收集情报...")
    print("=" * 60)
    news_items = crawl_all()

    # 2. AI生成简报
    print("\n📝 摘要官就位 - 正在生成简报...\n")
    summarizer = IntelligenceSummarizer()
    result = summarizer.execute({
        "items": news_items,
        "focus_keywords": ["AI大模型", "企业服务", "SaaS出海"],
    })

    print(result["briefing"])
    print(f"\n📊 Token消耗: {result['tokens_used']}")
