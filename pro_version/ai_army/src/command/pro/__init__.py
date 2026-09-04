"""AI 军团 Pro 版 —— AI 店长（主代理 + 编排引擎）

在现有五大模块（侦察兵/参谋部/创作部/后勤兵/知识库）之上增量叠加：
Layer 1：AI 店长（orchestrator）       —— 一句话目标 → JSON 任务树
Layer 2：任务编排引擎（workflow_engine） —— 依赖调度 / 并行执行 / 重试
Layer 3：质检 + 人工审批网关             —— quality_agent + approval_gate

现有模块一行不改，仅通过 import 调用其现有函数。
"""
