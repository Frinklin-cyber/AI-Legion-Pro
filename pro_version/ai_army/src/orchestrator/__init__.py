"""AI军团 v2.0 进阶版 · 多过程 AI 编排引擎

LangGraph 风格 StateGraph 的轻量落地实现（节点 + 条件路由 + 事件回调）。
用户任何经营问题进来，自动编排为一条多步骤 AI 工作流：

    Step1 意图识别与领域路由
    Step2 上下文画像补全
    Step3 工具调用 + 深度推理（DeepSeek Function Calling 循环）
    Step4 多方案生成 + 优劣对比
    Step5 执行指引输出

对外统一入口：src.orchestrator.engine.OrchestrationEngine
"""
from src.orchestrator.engine import OrchestrationEngine

__all__ = ["OrchestrationEngine"]
