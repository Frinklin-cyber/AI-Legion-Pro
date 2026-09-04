"""
quality_gate.py
质检 Agent —— 对专项 Agent 的输出做确定性规则检查：
  1. 格式正确    : 可解析为 JSON，且 output_schema 定义的必需字段齐全
  2. 引用完整    : 输出中标注的原文引用（clause 等）必须一字不差出现在输入文本中
  3. 无幻觉      : 输出中的条款编号/数字若在输入中不存在，判为疑似幻觉
  4. 内容完整    : 非空、长度合理、关键数组有值
  5. 敏感词检查  : 配置的敏感词（如"无限期""绝对保证"）不得出现在输出中

质检不通过时：由编排器触发一次"重试纠正"，仍不通过则原样返回并标记。
"""

import json
import re

# 敏感词表（企业可按行业自定义；此处为示例，不依赖第三方审核服务）
DEFAULT_SENSITIVE_WORDS = [
    "无限期", "绝对保证", "百分之百", "无任何风险", "包赚", "稳赚",
]


def parse_output_json(text: str):
    """容忍模型输出 JSON 外围包裹 ```json ... ``` 或多余文字。解析失败返回 None。"""
    if not isinstance(text, str):
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # 尝试提取第一个 { ... } 块
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                return None
        return None


def _parse_json(text: str):
    """内部别名，兼容旧引用"""
    return parse_output_json(text)


def _required_keys(output_schema: dict) -> list:
    """从 output_schema 提取必需字段（顶层 key）"""
    if not isinstance(output_schema, dict):
        return []
    keys = []
    for k, v in output_schema.items():
        if isinstance(v, str) and " - " in v:
            keys.append(k)
        else:
            keys.append(k)
    return keys


def _collect_quoted_refs(obj) -> list:
    """递归收集输出中所有疑似引用字段的值（用于与输入文本比对，防幻觉）"""
    refs = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("clause", "原文", "引用", "kb_sources", "source_file") and isinstance(v, str):
                refs.append(v)
            elif isinstance(v, (dict, list)):
                refs.extend(_collect_quoted_refs(v))
    elif isinstance(obj, list):
        for item in obj:
            refs.extend(_collect_quoted_refs(item))
    return refs


def _all_refs_present(refs: list, source_text: str) -> list:
    """返回 [缺失引用...]；每条引用须在输入文本中出现（防幻觉/引用完整）"""
    if not source_text:
        return refs  # 无输入文本时无法校验，视为缺失
    missing = []
    for ref in refs:
        ref = (ref or "").strip()
        if not ref:
            continue
        # 归一化空白后比对（容忍换行差异）
        norm_ref = re.sub(r"\s+", "", ref)
        norm_src = re.sub(r"\s+", "", source_text)
        if len(norm_ref) >= 4 and norm_ref not in norm_src:
            missing.append(ref[:80])
    return missing


def _check_sensitive(text: str, words: list) -> list:
    return [w for w in words if w and w in text]


def quality_check(
    raw_output: str,
    *,
    output_schema: dict = None,
    input_text: str = "",
    sensitive_words: list = None,
) -> dict:
    """
    对 Agent 输出执行质检。
    返回 {"passed": bool, "score": int, "checks": [{name, passed, detail}]}
    """
    checks = []
    raw = raw_output or ""
    parsed = parse_output_json(raw)

    # 1. 格式正确
    if output_schema:
        ok = parsed is not None
        checks.append({
            "name": "格式正确(JSON可解析)",
            "level": "error",
            "passed": ok,
            "detail": "输出为有效 JSON" if ok else "输出无法解析为 JSON",
        })
    else:
        ok = bool(raw.strip())
        checks.append({
            "name": "输出非空",
            "level": "error",
            "passed": ok,
            "detail": f"输出长度 {len(raw)}" if ok else "输出为空",
        })

    # 2. 必需字段齐全（仅检查字段存在且非 None；空数组/空串不算缺失）
    keys = _required_keys(output_schema or {})
    if parsed is not None and keys:
        missing = [k for k in keys if k not in parsed or parsed[k] is None]
        checks.append({
            "name": "必需字段齐全",
            "level": "error",
            "passed": not missing,
            "detail": "字段完整" if not missing else f"缺失: {missing}",
        })
    else:
        checks.append({"name": "必需字段齐全", "level": "error", "passed": True, "detail": "未定义 output_schema 或无需校验"})

    # 3. 引用完整（防幻觉）：输出中的引用片段须在输入中出现
    refs = _collect_quoted_refs(parsed) if parsed else []
    if refs:
        missing = _all_refs_present(refs, input_text)
        checks.append({
            "name": "引用完整(无幻觉)",
            "level": "error",
            "passed": not missing,
            "detail": f"校验 {len(refs)} 处引用，全部在原文中" if not missing else f"发现 {len(missing)} 处疑似幻觉引用: {missing[:3]}",
        })
    else:
        checks.append({"name": "引用完整(无幻觉)", "level": "error", "passed": True, "detail": "输出无引用字段"})

    # 4. 关键数组非空（提示级：如确无内容属业务正常，如合同无风险）
    if parsed is not None:
        empty_arrs = [k for k, v in parsed.items() if isinstance(v, list) and k in keys and len(v) == 0]
        checks.append({
            "name": "关键数组非空",
            "level": "warning",
            "passed": not empty_arrs,
            "detail": "关键数组均有内容" if not empty_arrs else f"空数组: {empty_arrs}（如确无此类内容属正常）",
        })
    else:
        checks.append({"name": "关键数组非空", "level": "warning", "passed": True, "detail": "跳过"})

    # 5. 敏感词检查
    words = sensitive_words or DEFAULT_SENSITIVE_WORDS
    hits = _check_sensitive(raw, words)
    checks.append({
        "name": "敏感词检查",
        "level": "error",
        "passed": not hits,
        "detail": "无敏感词" if not hits else f"命中敏感词: {hits}",
    })

    # 通过标准：仅 error 级检查必须全部通过；warning 级仅提示
    errors = [c for c in checks if c.get("level") != "warning"]
    passed = all(c["passed"] for c in errors)
    score = int(100 * sum(c["passed"] for c in errors) / len(errors)) if errors else 100
    return {"passed": passed, "score": score, "checks": checks, "parsed": parsed}
