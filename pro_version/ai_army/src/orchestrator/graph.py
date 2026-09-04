"""编排状态图（LangGraph StateGraph 的轻量落地实现）

节点：intent → profile → think_tools(条件边) → plans → finalize → END
所有节点读写共享的 state，通过 events 实时上报进度。
"""

import json
from typing import Any, Callable

from loguru import logger

from src.orchestrator.state import STEP_BY_KEY, make_event
from src.orchestrator.domains import describe_domains, DOMAIN_PROMPTS, \
    PLANS_SYSTEM_PROMPT, FINALIZE_SYSTEM_PROMPT, TOOL_SYSTEM_PROMPT
from src.orchestrator.llm import LLMClient
from src.orchestrator.tools import ToolContext, build_tools, describe_tools

Emit = Callable[[dict], None]


def _profile_plain(profile: dict | None) -> str:
    """把店铺画像格式化为可读文本"""
    p = profile or {}
    lines = []
    lines.append(f"- 店铺名称：{p.get('store_name') or p.get('name') or '（未登记）'}")
    lines.append(f"- 行业类型：{p.get('type_name') or p.get('type') or '自定义行业'}")
    lines.append(f"- 所在地区：{p.get('region') or '（未登记）'}")
    if p.get("products"):
        lines.append(f"- 主营产品：{p['products']}")
    if p.get("hours"):
        lines.append(f"- 营业时间：{p['hours']}")
    if p.get("address"):
        lines.append(f"- 门店地址：{p['address']}")
    if p.get("location_feature"):
        lines.append(f"- 店铺特色：{p['location_feature']}")
    return "\n".join(lines)


def _plans_to_markdown(plans: list[dict]) -> str:
    parts = []
    for i, pl in enumerate(plans, 1):
        parts.append(
            f"### 方案{i}：{pl.get('name','')}\n"
            f"- 预估成本：{pl.get('cost','-')}\n"
            f"- 主要风险：{pl.get('risk','-')}\n"
            f"- 适用场景：{pl.get('scene','-')}\n"
            f"{pl.get('content','')}"
        )
    return "\n\n".join(parts)


# ══════════════════════════ Step 节点实现 ══════════════════════════

def step_intent(llm: LLMClient, message: str, history: list[dict] | None, state: dict, emit: Emit) -> None:
    """Step1 意图识别与领域路由"""
    step = STEP_BY_KEY["intent"]
    emit(make_event("step_start", step=step["id"], key=step["key"], label=step["label"], desc=step["desc"]))

    sys_prompt = (
        "你是「AI军团 v2.0 编排引擎」的意图识别模块。用户是中小微企业主/个体户老板，可能提出任何经营相关问题。\n"
        "判断该问题属于哪个领域。\n\n可选领域：\n" + describe_domains() + "\n\n"
        "严格输出 JSON：{\"domain\":\"领域id\", \"summary\":\"一句话复述用户诉求\", \"confidence\":0到1, \"needs_shop_context\":是否必须结合店铺资料}"
    )
    try:
        parsed = llm.chat_json(sys_prompt, message, fallback={
            "domain": "daily", "summary": message, "confidence": 0.5,
            "needs_shop_context": False,
        })
    except Exception as e:
        logger.warning(f"[orchestrator] intent 解析失败: {e}")
        parsed = {"domain": "daily", "summary": message, "confidence": 0.4,
                  "needs_shop_context": False}

    domain = parsed.get("domain", "daily")
    if domain not in DOMAIN_PROMPTS:
        domain = "daily"
    parsed["domain"] = domain
    parsed["domain_name"] = {
        "legal": "法律合规", "tax": "财税筹划", "marketing": "营销获客",
        "operations": "运营管理", "finance": "融资贷款", "daily": "日常经营",
        "diagnose": "店铺诊断",
    }.get(domain, domain)

    state["intent"] = parsed
    state["domain"] = domain
    emit(make_event("step_end", step=step["id"], key=step["key"], label=step["label"],
                    data={"domain": parsed["domain_name"], "summary": parsed.get("summary", "")}))


def step_profile(state: dict, emit: Emit) -> None:
    """Step2 上下文画像补全（店铺 / 行业 / 地区）"""
    step = STEP_BY_KEY["profile"]
    emit(make_event("step_start", step=step["id"], key=step["key"], label=step["label"], desc=step["desc"]))

    profile = state.get("profile") or {}
    plain = _profile_plain(profile)
    filled = bool(profile.get("store_name") or profile.get("name"))
    notes = []
    if state.get("intent", {}).get("needs_shop_context") and not filled:
        notes.append("（注：商家画像未登记完整，将按通用经验回答并给出信息补齐建议）")
    state["profile_text"] = plain
    state["profile_notes"] = "".join(notes)
    emit(make_event("step_end", step=step["id"], key=step["key"], label=step["label"],
                    data={"store": plain[:300], "filled": filled}))


def step_think_tools(llm: LLMClient, message: str, history: list[dict] | None, state: dict, emit: Emit) -> None:
    """Step3 工具调用 + 深度推理（DeepSeek Function Calling 循环）"""
    step = STEP_BY_KEY["tools"]
    emit(make_event("step_start", step=step["id"], key=step["key"], label=step["label"], desc=step["desc"]))

    ctx = state["tool_ctx"]
    schemas, mapping = build_tools(ctx)
    sys_prompt = TOOL_SYSTEM_PROMPT.format(tool_descriptions=describe_tools(schemas))
    user_msg = (
        f"用户问题：{message}\n\n"
        f"【店铺画像】\n{state.get('profile_text', '')}\n"
        f"【领域判断】{state.get('domain_name','')} · {state.get('intent',{}).get('summary','')}"
    )

    tool_events: list[dict] = []

    def on_tool(tc: dict, result: Any) -> None:
        args_str = json.dumps(tc.get("arguments", {}), ensure_ascii=False)[:220]
        # 事件仅放结果预览，避免超长
        preview = ""
        try:
            preview = json.dumps(result, ensure_ascii=False)[:300]
        except Exception:
            preview = str(result)[:300]
        emit(make_event("tool_call", tool=tc["name"], args=args_str, result=preview))
        tool_events.append({"tool": tc["name"], "arguments": tc.get("arguments", {})})

    try:
        reasoning = llm.run_with_tools(
            sys_prompt, user_msg, schemas, mapping,
            on_tool=on_tool, history=history,
        )
    except Exception as e:
        logger.warning(f"[orchestrator] 工具推理失败，降级为直接推理: {e}")
        reasoning = llm.chat(
            "你是经营问题深度推理引擎。请给出围绕问题的关键推理与事实摘要，3-6句。",
            user_msg,
        )

    state["tool_events"] = tool_events
    state["reasoning"] = reasoning
    emit(make_event("step_end", step=step["id"], key=step["key"], label=step["label"],
                    data={"tools_called": len(tool_events), "tools": [t["tool"] for t in tool_events],
                          "reasoning": reasoning[:300]}))


def step_plans(llm: LLMClient, message: str, state: dict, emit: Emit) -> None:
    """Step4 多方案生成 + 优劣对比"""
    step = STEP_BY_KEY["plans"]
    emit(make_event("step_start", step=step["id"], key=step["key"], label=step["label"], desc=step["desc"]))

    domain = state.get("domain", "daily")
    conf = DOMAIN_PROMPTS.get(domain, DOMAIN_PROMPTS["daily"])
    sys_prompt = PLANS_SYSTEM_PROMPT.format(expert=conf["expert"], style=conf["style"])

    reasoning = state.get("reasoning", "")
    user_msg = (
        f"用户问题：{message}\n\n"
        f"【店铺画像】\n{state.get('profile_text', '')}\n"
        f"【工具推理摘要】\n{reasoning if reasoning else '（无需工具，直接经验推理）'}"
    )
    try:
        parsed = llm.chat_json(sys_prompt, user_msg, temperature=0.5, fallback={
            "summary": message, "plans": []
        })
    except Exception as e:
        logger.warning(f"[orchestrator] plans 失败: {e}")
        parsed = {"summary": message, "plans": []}

    plans = parsed.get("plans") or []
    if not plans:  # 容错：至少给一版结构化建议
        plans = [{
            "name": "综合建议", "cost": "视执行而定", "risk": "需结合实际情况调整",
            "scene": "通用场景", "content": reasoning or "建议结合店铺实际情况分步执行。",
        }]
    for pl in plans:
        for k in ("name", "cost", "risk", "scene", "content"):
            pl.setdefault(k, "")
    state["plans"] = plans
    state["plans_summary"] = parsed.get("summary", "")
    emit(make_event("step_end", step=step["id"], key=step["key"], label=step["label"],
                    data={"plan_count": len(plans),
                          "plan_names": [p.get("name", "") for p in plans]}))


def step_finalize(llm: LLMClient, message: str, state: dict, emit: Emit) -> None:
    """Step5 执行指引输出（行动清单 + 模板话术）"""
    step = STEP_BY_KEY["finalize"]
    emit(make_event("step_start", step=step["id"], key=step["key"], label=step["label"], desc=step["desc"]))

    domain = state.get("domain", "daily")
    conf = DOMAIN_PROMPTS.get(domain, DOMAIN_PROMPTS["daily"])
    sys_prompt = FINALIZE_SYSTEM_PROMPT.format(expert=conf["expert"], style=conf["style"])

    user_msg = (
        f"用户问题：{message}\n\n"
        f"【店铺画像】\n{state.get('profile_text', '')}\n"
        f"【工具推理摘要】\n{state.get('reasoning', '')}\n"
        f"【候选方案】\n{_plans_to_markdown(state.get('plans', []))}\n\n"
        "请输出最终执行指引（Markdown）：结论先行 → 行动清单 → 可直接复制的模板/话术。"
    )
    try:
        final = llm.chat(sys_prompt, user_msg, temperature=0.5, max_tokens=2800)
    except Exception as e:
        logger.error(f"[orchestrator] finalize 失败: {e}")
        final = "⚠️ 生成最终指引失败，请稍后重试。"

    state["final"] = final
    emit(make_event("step_end", step=step["id"], key=step["key"], label=step["label"],
                    data={"len": len(final)}))
    emit(make_event("final", content=final, plans=state.get("plans", [])))


# ══════════════════════════ 图执行器 ══════════════════════════

def run_graph(message: str, profile: dict | None, history: list[dict] | None) -> dict:
    """编排一次完整推理，返回 state + events"""
    events: list[dict] = []
    emit: Emit = events.append

    state: dict[str, Any] = {"profile": profile or {}}
    ctx = ToolContext(profile)
    state["tool_ctx"] = ctx
    llm = LLMClient()

    # Step1
    step_intent(llm, message, history, state, emit)
    # Step2
    step_profile(state, emit)
    # Step3（条件边：若 domain 明显无需工具也可由模型自行决定）
    step_think_tools(llm, message, history, state, emit)
    # Step4
    step_plans(llm, message, state, emit)
    # Step5
    step_finalize(llm, message, state, emit)

    return {
        "status": "success",
        "intent": {k: v for k, v in state["intent"].items() if k != "domain_name"},
        "domain_name": state.get("domain_name", "日常经营"),
        "profile_text": state.get("profile_text", ""),
        "plans": state.get("plans", []),
        "final": state.get("final", ""),
        "events": events,
    }
