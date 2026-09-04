"""特种部队 - 内容创作引擎

支持场景：
- 公众号/知乎长文
- 短视频脚本
- 朋友圈/社交媒体文案
- 客户提案/方案
- 批量内容生成
"""

from typing import Any
from datetime import datetime

from loguru import logger

from src.core import BaseSoldier
from config.prompts.content_prompts import (
    LONG_ARTICLE_PROMPT,
    SHORT_VIDEO_PROMPT,
    SOCIAL_POST_PROMPT,
    PROPOSAL_PROMPT,
    BATCH_CONTENT_TEMPLATES,
)


class ContentCreator(BaseSoldier):
    """内容创作者 - 特种部队主力"""

    name = "特种兵-内容创作官"
    role = "special_forces_content"
    temperature = 0.8  # 内容创作需要更高创造性
    max_tokens = 3000

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """执行内容创作任务

        Args:
            task: {
                "type": str,              # article/video/social/proposal
                "topic": str,             # 主题
                "audience": str,          # 目标受众
                "key_message": str,       # 核心信息
                "platform": str,          # 平台
                "extra": dict,            # 额外参数
            }

        Returns:
            {"content": str, "type": str, "tokens_used": int}
        """
        content_type = task.get("type", "article")
        topic = task.get("topic", "企业AI改革")
        audience = task.get("audience", "中小企业主和管理者")
        key_message = task.get("key_message", "AI改革不是选项，是生存必需")
        platform = task.get("platform", "公众号")
        extra = task.get("extra", {})

        # 选择Prompt模板
        prompt_map = {
            "article": (LONG_ARTICLE_PROMPT, {"topic": topic, "audience": audience, "key_message": key_message}),
            "video": (SHORT_VIDEO_PROMPT, {"topic": topic, "platform": platform, "goal": extra.get("goal", "涨粉")}),
            "social": (SOCIAL_POST_PROMPT, {"topic": topic, "data_points": extra.get("data_points", ""), "engagement_goal": extra.get("engagement_goal", "评论互动")}),
            "proposal": (PROPOSAL_PROMPT, {"industry": extra.get("industry", "传统制造业"), "pain_points": extra.get("pain_points", "效率低下"), "goals": extra.get("goals", "降本增效"), "budget": extra.get("budget", "待定")}),
        }

        system_prompt, format_kwargs = prompt_map.get(content_type, prompt_map["article"])
        user_message = system_prompt.format(**format_kwargs) if "{" in system_prompt else system_prompt

        logger.info(f"[内容创作官] 类型: {content_type} | 主题: {topic[:30]}...")
        content, tokens = self.chat(system_prompt, user_message)
        logger.info(f"[内容创作官] 创作完成，{len(content)}字, {tokens} tokens")

        return {
            "content": content,
            "type": content_type,
            "topic": topic,
            "tokens_used": tokens,
            "generated_at": datetime.now().isoformat(),
        }

    def create_article(self, topic: str, audience: str = "中小企业管理者",
                       key_message: str = "企业AI改革正当时") -> str:
        """快捷方法：生成长文"""
        result = self.execute({
            "type": "article",
            "topic": topic,
            "audience": audience,
            "key_message": key_message,
        })
        return result["content"]

    def create_video_script(self, topic: str, platform: str = "抖音",
                            goal: str = "涨粉") -> str:
        """快捷方法：生成短视频脚本"""
        result = self.execute({
            "type": "video",
            "topic": topic,
            "platform": platform,
            "extra": {"goal": goal},
        })
        return result["content"]

    def create_social_post(self, topic: str, data_points: str = "",
                           engagement_goal: str = "评论互动") -> str:
        """快捷方法：生成朋友圈文案"""
        result = self.execute({
            "type": "social",
            "topic": topic,
            "extra": {"data_points": data_points, "engagement_goal": engagement_goal},
        })
        return result["content"]

    def create_proposal(self, industry: str, pain_points: str,
                        goals: str = "降本增效", budget: str = "待定") -> str:
        """快捷方法：生成客户提案"""
        result = self.execute({
            "type": "proposal",
            "topic": f"为{industry}企业提供AI改革方案",
            "extra": {"industry": industry, "pain_points": pain_points, "goals": goals, "budget": budget},
        })
        return result["content"]


class BatchGenerator(BaseSoldier):
    """批量内容生成器 - 按模板批量产出"""

    name = "特种兵-批量生成官"
    role = "special_forces_batch"
    temperature = 0.75
    max_tokens = 2000

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """批量生成内容

        Args:
            task: {
                "template": str,     # weekly_posts / product_launch / thought_leadership
                "topic": str,        # 核心主题
                "count": int,        # 生成数量（覆盖模板默认值）
            }

        Returns:
            {"items": list[dict], "total_tokens": int}
        """
        template_name = task.get("template", "weekly_posts")
        topic = task.get("topic", "企业AI改革")
        count = task.get("count", 0)

        template = BATCH_CONTENT_TEMPLATES.get(template_name)
        if not template:
            raise ValueError(f"未知模板: {template_name}，可用: {list(BATCH_CONTENT_TEMPLATES.keys())}")

        # 获取生成主题列表
        if "themes" in template:
            themes = template["themes"]
            if count:
                themes = themes[:count]
        elif "items" in template:
            themes = template["items"]
            if count:
                themes = themes[:count]
        else:
            themes = [f"{topic} - 第{i}天" for i in range(1, (count or 5) + 1)]

        items: list[dict[str, Any]] = []
        total_tokens = 0

        for i, theme in enumerate(themes):
            logger.info(f"[批量生成] 进度 {i+1}/{len(themes)}: {theme}")

            system_prompt = SOCIAL_POST_PROMPT  # 默认用社交媒体模板
            user_message = f"主题：{theme}\n上下文：{topic}\n\n请生成内容。"

            try:
                content, tokens = self.chat(system_prompt, user_message)
                items.append({
                    "index": i + 1,
                    "theme": theme,
                    "content": content,
                    "tokens": tokens,
                })
                total_tokens += tokens
            except Exception as e:
                logger.error(f"[批量生成] 第{i+1}条失败: {e}")
                items.append({
                    "index": i + 1,
                    "theme": theme,
                    "content": f"[生成失败: {e}]",
                    "tokens": 0,
                })

        logger.info(f"[批量生成] 完成！共{len(items)}条，消耗{total_tokens} tokens")

        return {
            "items": items,
            "total_tokens": total_tokens,
            "success_count": sum(1 for item in items if "[生成失败" not in item["content"]),
            "template": template_name,
        }


# ====== 使用示例 ======
if __name__ == "__main__":
    creator = ContentCreator()

    print("=" * 60)
    print("🎨 特种部队内容创作引擎")
    print("=" * 60)

    # 示例：生成一条朋友圈
    print("\n--- 朋友圈文案示例 ---\n")
    post = creator.create_social_post(
        topic="帮一家餐饮连锁完成AI点餐系统，错误率从12%降到0.3%",
        data_points="错误率 -97.5% | 客户满意度 +40% | 员工培训时间 -80%",
    )
    print(post)

    # 示例：批量生成
    print("\n\n--- 批量生成测试 ---\n")
    batch = BatchGenerator()
    result = batch.execute({
        "template": "weekly_posts",
        "topic": "中小企业如何用AI实现降本增效",
        "count": 3,  # 只生成3条做演示
    })

    for item in result["items"]:
        print(f"\n{item['theme']}:")
        print(f"  {item['content'][:150]}...")
