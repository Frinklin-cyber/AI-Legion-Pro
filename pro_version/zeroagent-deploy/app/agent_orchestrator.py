"""
agent_orchestrator.py
多 Agent 编排 —— 在知识大脑之上扩展"业务流程自动化"能力。

流程：
  路由 Agent（规则 + LLM 兜底）
    → 分发专项 Agent（prompt 模板 + 可选知识库检索增强）
      → 质检 Agent（quality_gate 规则检查）
        → 未通过时重试纠正（最多 1 次）
          → 审计写入 data/audit_log.jsonl（全程可回溯）
            → 可选 webhook 通知 → 聚合返回

设计：复用 ZD tool_router 思路，每个 Agent 是一个注册在 agent_registry 中的"工具"。
"""

import json
import re
import time

from . import agent_registry, audit, quality_gate
from .ollama_client import OllamaUnavailableError

# 规则路由关键词表（route agent 的第一层：快、稳、不烧 token）
ROUTE_RULES = [
    ("contract_review", ["合同", "条款", "违约", "法务", "签署", "协议书", "协议"]),
    ("daily_report", ["日报", "周报", "总结", "汇报", "报表", "工作记录", "计划"]),
    ("customer_service", ["客户", "客服", "售后", "投诉", "退款", "咨询", "回复客户"]),
]

RETRY_LIMIT = 1  # 质检不通过的最大重试次数


class AgentOrchestrator:
    def __init__(self, ollama, rag_engine=None, retry_limit: int = RETRY_LIMIT):
        self.ollama = ollama
        self.rag = rag_engine
        self.retry_limit = retry_limit

    # ─────────────────────────────────────────
    # 1. 路由 Agent
    # ─────────────────────────────────────────
    def route(self, task: str, agent_hint: str = None) -> dict:
        """路由：agent_hint 优先 → 规则匹配 → LLM 兜底。返回 {agent, method, reasoning}"""
        # 用户显式指定
        if agent_hint and agent_registry.get_agent(agent_hint):
            return {"agent": agent_hint, "method": "explicit",
                    "reasoning": f"用户指定 Agent: {agent_hint}", "confidence": 1.0}

        # 规则匹配（位置加权：关键词在任务中出现越靠前、命中越多，得分越高）
        best, best_score, best_kw = None, 0.0, []
        for name, keywords in ROUTE_RULES:
            hits = [k for k in keywords if k in task]
            if hits:
                score = sum(1.0 / (task.find(k) + 1) for k in hits)
                if score > best_score:
                    best, best_score, best_kw = name, score, hits
        if best and best_score > 0:
            return {"agent": best, "method": "rule",
                    "reasoning": f"规则匹配关键词 {best_kw} → {best}",
                    "confidence": min(0.9, 0.5 + best_score)}

        # LLM 兜底
        return self._llm_route(task)

    def _llm_route(self, task: str) -> dict:
        agents = agent_registry.list_agents()
        desc = "\n".join(f"- {a['name']}: {a['description']}" for a in agents)
        prompt = (
            f"你是任务路由器。根据用户任务选择最合适的专项 Agent。\n"
            f"可用 Agent：\n{desc}\n\n"
            f"用户任务：{task}\n\n"
            f"只返回 JSON：{{\"agent\": \"Agent名称\", \"reasoning\": \"一句话理由\"}}"
        )
        try:
            raw = self.ollama.generate(prompt, system="你是企业 Agent 路由器，输出严格 JSON。", temperature=0.1)
            parsed = quality_gate.parse_output_json(raw)
            if parsed and agent_registry.get_agent(str(parsed.get("agent", ""))):
                return {"agent": parsed["agent"], "method": "llm",
                        "reasoning": parsed.get("reasoning", "LLM 路由"), "confidence": 0.8}
        except OllamaUnavailableError:
            pass
        return {"agent": None, "method": "none", "reasoning": "无法路由，无匹配 Agent", "confidence": 0.0}

    # ─────────────────────────────────────────
    # 2. 执行专项 Agent
    # ─────────────────────────────────────────
    def _resolve_params(self, spec: dict, task: str, params: dict) -> dict:
        """把 task 自动填入 Agent 的必填参数（未显式传 params 时）"""
        if params:
            return params
        props = (spec.get("parameters") or {}).get("properties", {})
        required = (spec.get("parameters") or {}).get("required", [])
        if required:
            first = required[0]
            if first in props:
                return {first: task}
        return {"task": task}

    def _build_prompt(self, spec: dict, resolved: dict, knowledge: str = "") -> str:
        system_prompt = spec["system_prompt"]
        if spec.get("use_kb") and "{knowledge}" in system_prompt:
            system_prompt = system_prompt.replace(
                "{knowledge}", knowledge or "（知识库为空，暂无参考资料）")

        input_block = "\n".join(f"{k}: {v}" for k, v in resolved.items())
        # 未在 system_prompt 中使用 {knowledge} 占位符时，把知识附加在用户输入之后
        if spec.get("use_kb") and "{knowledge}" not in spec["system_prompt"] and knowledge:
            input_block += "\n\n【知识库检索结果】\n" + knowledge
        return system_prompt, input_block

    def _retrieve_knowledge(self, resolved: dict) -> str:
        """供 use_kb Agent 检索知识库（为空时返回空字符串）"""
        if not self.rag:
            return ""
        kb_q = resolved.get("kb_question") or resolved.get("customer_question") or ""
        # 剥离口语前缀（客户问：/请问/咨询：），提升检索命中率
        kb_q = re.sub(r"^(客户问[:：]?\s*|请问[:：]?\s*|咨询[:：]?\s*|问题[:：]?\s*)+", "", kb_q)
        if not kb_q:
            return ""
        try:
            hits = self.rag.retrieve(kb_q, top_k=4)
        except OllamaUnavailableError:
            return ""
        if not hits:
            return ""
        parts = []
        for h in hits:
            page = f"第 {h['page_number']} 页" if h["page_number"] else "无分页"
            parts.append(f"[{h['source_file']} {page}] {h['text']}")
        return "\n\n".join(parts)

    def _run_agent(self, spec: dict, resolved: dict, task_id: str,
                   knowledge: str = "", extra_instruction: str = "") -> str:
        system_prompt, input_block = self._build_prompt(spec, resolved, knowledge)
        if extra_instruction:
            input_block += f"\n\n【修正要求】\n{extra_instruction}"
        return self.ollama.generate(
            prompt=input_block,
            system=system_prompt,
            temperature=0.1,
        )

    # ─────────────────────────────────────────
    # 3. 总入口
    # ─────────────────────────────────────────
    def run(self, task: str, agent: str = None, params: dict = None,
            webhook_channel: str = None) -> dict:
        task_id = audit.new_task_id()
        started = time.time()
        task = (task or "").strip()
        if not task:
            raise ValueError("任务内容不能为空")

        audit.log_agent_event(task_id, "-", "route", "OK", "任务受理", {"task": task[:100]})

        # 路由
        routing = self.route(task, agent_hint=agent)
        audit.log_agent_event(task_id, routing["agent"] or "-", "route",
                              "OK" if routing["agent"] else "FAIL",
                              f"{routing['method']} 路由 → {routing['agent']}",
                              {"reasoning": routing["reasoning"]})

        agent_name = routing["agent"]
        if not agent_name:
            return {
                "task_id": task_id, "ok": False,
                "error": "无法确定合适的专项 Agent，请明确任务类型或指定 agent 参数。",
                "routing": routing, "elapsed_ms": int((time.time() - started) * 1000),
            }

        spec = agent_registry.get_agent(agent_name)
        resolved = self._resolve_params(spec, task, params or {})

        # 可选知识库增强
        knowledge = self._retrieve_knowledge(resolved) if spec.get("use_kb") else ""

        # 执行 + 质检 + 重试
        raw_output = ""
        quality = None
        attempts = 0
        for attempt in range(self.retry_limit + 1):
            attempts = attempt + 1
            extra = ""
            if quality and not quality["passed"]:
                failed = [c["detail"] for c in quality["checks"] if not c["passed"]]
                extra = "上轮输出未通过质检，问题如下：\n- " + "\n- ".join(failed) + \
                        "\n请严格修正后重新输出完整 JSON，不要再犯同样错误。"
            raw_output = self._run_agent(spec, resolved, task_id, knowledge, extra)
            input_text = json.dumps(resolved, ensure_ascii=False)
            quality = quality_gate.quality_check(
                raw_output,
                output_schema=spec.get("output_schema"),
                input_text=input_text,
            )
            audit.log_agent_event(task_id, agent_name,
                                  "quality" if attempt else "execute",
                                  "OK" if quality["passed"] else ("RETRY" if attempt < self.retry_limit else "FAIL"),
                                  f"尝试{attempts}: 质检得分 {quality['score']}",
                                  {"checks": quality["checks"]})
            if quality["passed"]:
                break

        # 输出（解析后的 JSON 或原文）
        parsed = quality["parsed"]
        result = parsed if parsed is not None else raw_output

        # webhook 通知
        notify = None
        if webhook_channel:
            from .webhook_sender import send_webhook
            summary = f"[ZEROagent] Agent「{spec.get('title', agent_name)}」执行完成\n任务: {task[:80]}\n质检: {'通过' if quality['passed'] else '未通过'} (得分 {quality['score']})"
            notify = send_webhook(webhook_channel, summary)
            audit.log_agent_event(task_id, agent_name, "notify",
                                  "OK" if notify["sent"] else "WARN", str(notify))

        audit.log_agent_event(task_id, agent_name, "done",
                              "OK" if quality["passed"] else "FAIL",
                              f"完成，共 {attempts} 次尝试",
                              {"elapsed_ms": int((time.time() - started) * 1000)})

        return {
            "task_id": task_id,
            "ok": quality["passed"],
            "agent": agent_name,
            "agent_title": spec.get("title", agent_name),
            "result": result,
            "quality": {k: v for k, v in quality.items() if k != "parsed"},
            "routing": routing,
            "attempts": attempts,
            "notify": notify,
            "elapsed_ms": int((time.time() - started) * 1000),
        }
