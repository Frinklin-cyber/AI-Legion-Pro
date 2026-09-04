"""编排引擎对外统一入口（OrchestrationEngine）"""

from loguru import logger


class OrchestrationEngine:
    """多过程 AI 编排引擎。

    用法：
        engine = OrchestrationEngine()
        result = engine.run("这个月营收降了20%，帮我分析原因", profile={...})
        # result: {"status", "intent", "domain_name", "plans", "final", "events"}
    """

    def run(self, message: str, profile: dict | None = None,
            history: list[dict] | None = None) -> dict:
        try:
            from src.orchestrator.graph import run_graph
            return run_graph(message, profile, history)
        except Exception as e:
            logger.exception("[orchestrator] 编排执行异常")
            return {
                "status": "error",
                "error": str(e)[:300],
                "final": "⚠️ 本次编排执行出现异常，请稍后重试，或换一种问法。",
                "events": [],
                "plans": [],
            }
