"""地址清洗工具 - AI军团 v3.1

对用户输入的原始地址进行清洗和标准化，为 POI 搜索提供干净输入。
核心流程：去口语化 → 提取括号Hint → 识别行政区划 → 提取地标/店名
"""

from __future__ import annotations

import re
from typing import Any


# ── 口语化/噪音模式 ──────────────────────────────────────────

_NOISE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 年份 + 开业
    (re.compile(r"\d{4}\s*年\s*新?\s*开\s*的?"), ""),
    # "地址在/位于 XXX旁/附近/边上/楼下/隔壁/对面/里面"
    (re.compile(r"(地址在|位于|在)\s*(SOHO|万达|银泰|万象城|龙湖|来福士|恒隆|大悦城|K11|IFS|SKP)\s*(旁|附近|边上|楼下|隔壁|对面|里面)?", re.IGNORECASE),
     r"\2"),
    # "不用导航就能看到"等废话
    (re.compile(r"不用导航.{0,10}就能.{0,5}看到[，,。.]?"), ""),
    # "就在XXX隔壁" → "XXX隔壁"
    (re.compile(r"就在\s*(.{2,20}?)\s*(隔壁|旁边|对面|楼下|边上)"), r"\1\2"),
    # "具体地址是"、"详细地址是" 等前缀
    (re.compile(r"(具体|详细|准确|精确)?地址[是为：:]\s*"), ""),
    # "大概在" "大约在"
    (re.compile(r"(大概在|大约在|应该在)\s*"), ""),
    # 多余标点：多个连续逗号→一个
    (re.compile(r"[，,]{2,}"), "，"),
    # 括号内"原某某店" → 提取为hint
    (re.compile(r"[（(]\s*原\s*(.{2,15}?店?)\s*[)）]"), r"，原\1"),
]


# ── 中国行政区划关键词（省/市/区/县/旗） ─────────────────────

_ADMIN_REGEX = re.compile(
    r"(?P<province>(?:北京|上海|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|广西|海南|"
    r"四川|贵州|云南|西藏|陕西|甘肃|青海|宁夏|新疆|内蒙古|香港|澳门|台湾)(?:省|市|自治区|特别行政区)?)"
    r"(?P<city>(?:.{1,8}?(?:市|州|地区|盟|自治州)))?"
    r"(?P<district>(?:.{1,10}?(?:区|县|市|旗|镇)))?"
    r"(?P<suffix>.+)?",
)

# 商圈关键词（地标提取）。
_LANDMARK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(万达广场|银泰城|万象城|来福士|恒隆广场|龙湖天街|大悦城|IFS|K11|SKP|"
               r"印象城|吾悦广场|宝龙广场|世茂广场|新天地|太古里|壹方城|"
               r"光环|荟聚|永旺|盒马|宜家|迪卡侬|优衣库|海底捞|星巴克)", re.IGNORECASE),
]

# 店名提取（引导名词）
_SHOP_NAME_PREFIXES: list[re.Pattern[str]] = [
    re.compile(r"(?:店名|商户名|商家名|名称)[：:]\s*(?P<name>.{2,30}?)(?:[，,\s]|$)"),
    re.compile(r"(?P<calling>.{2,30}?[店厅馆院坊吧房])(?:[，,.]|$)"),
]


_SEMICOLON_CLEAN = re.compile(r"(\S)\s{2,}(\S)")


def clean_address(raw: str) -> dict[str, Any]:
    """清洗用户输入的原始地址。

    返回:
    {
        "cleaned": 清洗后的纯净地址,
        "hints":   从括号/原店名提取的搜索提示词,
        "admin_region": 识别到的行政区划（省+市+区）,
        "landmark": 识别到的地标名称,
        "shop_name": 识别到的店名,
        "raw": 原始输入,   # 保留原始输入用于调试
    }
    """
    result: dict[str, Any] = {
        "cleaned": raw.strip(),
        "hints": [],
        "admin_region": "",
        "landmark": "",
        "shop_name": "",
        "raw": raw.strip(),
    }

    text = raw.strip()
    if not text:
        return result

    # ── 步骤1：提取括号内内容作为搜索Hint ──────────────────
    bracket_hints: list[str] = re.findall(r"[（(]\s*([^)）]{2,30}?)\s*[)）]", text)
    result["hints"] = [h.strip() for h in bracket_hints if len(h.strip()) >= 2]
    # 去掉括号内容但不丢失信息（保留关键名词）
    text = re.sub(r"[（(][^)）]*[)）]", " ", text)

    # ── 步骤2：去除口语化噪音 ──────────────────────────────
    for pattern, replacement in _NOISE_PATTERNS:
        text = pattern.sub(replacement, text)

    # ── 步骤3：提取行政区划 ───────────────────────────────
    admin_match = _ADMIN_REGEX.search(text)
    if admin_match:
        parts: list[str] = []
        province = admin_match.group("province") or ""
        city = admin_match.group("city") or ""
        district = admin_match.group("district") or ""
        if province:
            parts.append(province)
        if city and city != province:
            parts.append(city)
        if district:
            parts.append(district)
        result["admin_region"] = "".join(parts)

        # 行政区划去重：如果后半段又出现了相同区划，去掉重复
        if district and result["cleaned"].count(district) > 1:
            text = text.replace(district, district, 1)  # 仅保留第一次出现

    # ── 步骤4：提取地标 ──────────────────────────────────
    for pattern in _LANDMARK_PATTERNS:
        m = pattern.search(text)
        if m:
            result["landmark"] = m.group(1)
            break

    # ── 步骤5：提取店名 ──────────────────────────────────
    for pattern in _SHOP_NAME_PREFIXES:
        m = pattern.search(text)
        if m:
            name = m.groupdict().get("name") or m.groupdict().get("calling")
            if name:
                result["shop_name"] = name.strip()
                break

    # ── 步骤6：最终清理 ──────────────────────────────────
    cleaned = text.strip()
    # 清理多余空白
    cleaned = _SEMICOLON_CLEAN.sub(r"\1 \2", cleaned)
    # 清理只剩下标点/空白的情况
    cleaned = cleaned.strip("，,。. 　\t\n\r-—")
    # 去除重复的行政区划（如"宾川县宾川县XX路"）
    if result["admin_region"]:
        # 如果address以行政区开头但后面又出现
        pattern_dedup = re.compile(re.escape(result["admin_region"]) + r"\s*")
        # 统计出现次数
        count = len(pattern_dedup.findall(cleaned))
        if count > 1:
            # 去掉后面重复的
            first_pos = cleaned.find(result["admin_region"])
            cleaned = cleaned[:first_pos + len(result["admin_region"])] + cleaned[first_pos + len(result["admin_region"]):].replace(
                result["admin_region"], "", 1
            )

    result["cleaned"] = cleaned.strip("，,。. 　\t\n\r-—") or raw.strip()
    return result


def extract_search_keywords(cleaned_result: dict[str, Any]) -> str:
    """从清洗结果中提取最优 POI 搜索关键词。

    策略：店名 > 地标 + 店类型 > 清洗后地址
    """
    parts: list[str] = []

    if cleaned_result.get("shop_name"):
        parts.append(cleaned_result["shop_name"])

    if cleaned_result.get("landmark"):
        parts.append(cleaned_result["landmark"])

    if cleaned_result.get("admin_region"):
        # 用最小的区划级别作限定
        parts.append(cleaned_result["admin_region"])

    if not parts:
        return cleaned_result.get("cleaned", "")

    return " ".join(parts)


def extract_city_param(cleaned_result: dict[str, Any]) -> str:
    """从清洗结果中提取用于 API 的城市限定参数。

    优先级：district > city > province > 空
    对于高德 POI 搜索，city 参数支持 adcode 和城市名。
    """
    admin = cleaned_result.get("admin_region", "")
    if not admin:
        return ""

    # 匹配 "任意前缀 + 行政区划后缀"，提取完整区划单元
    # 例如 "云南省大理白族自治州宾川县" → ["云南省", "大理白族自治州", "宾川县"]
    parts = re.findall(
        r"[^省市自治区州县区旗]+(?:省|市|自治区|自治州|州|地区|县|区|旗)",
        admin,
    )
    if parts:
        return parts[-1]  # 最细粒度的区划
    return admin
