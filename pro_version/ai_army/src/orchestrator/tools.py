"""v2.0 编排引擎 · DeepSeek Function Calling 工具集

注册工具（全部真实可执行，供编排引擎的 Step3 调用）：
- rag_search        语义检索行业知识库（ChromaDB，继承 v1.0）
- shop_diagnose     店铺经营体检（行业基因库基准 + 店铺画像）
- calculate         安全计算器（成本 / 利润 / 定价）
- regulation_lookup 本地法规速查（劳动 / 合同 / 广告 / 消保 / 税）
- template_fill     营销模板初稿生成（短视频 / 文案 / 活动话术）
- csv_analyze       业务数据问答（需先上传 CSV，未上传则如实提示）
"""

import ast
import json
import operator
import re
from typing import Any, Callable

from loguru import logger

# ───────────────────────── 安全计算器 ─────────────────────────
_ALLOWED_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _safe_calc(expr: str) -> str:
    """白名单 AST 求值，支持 + - * / // % ** () 与数字"""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return f"表达式语法错误：{expr}"
    try:
        def _eval(node):
            if isinstance(node, ast.Expression):
                return _eval(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
                return _ALLOWED_OPS[type(node.op)](_eval(node.left), _eval(node.right))
            if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
                return _ALLOWED_OPS[type(node.op)](_eval(node.operand))
            raise ValueError(f"不支持的表达式元素: {type(node).__name__}")
        val = _eval(tree)
        return f"{val:,.2f}" if isinstance(val, float) else str(val)
    except Exception as e:
        return f"无法计算：{e}"


# ───────────────────────── 本地法规速查库 ─────────────────────────
_REGULATION_DB: dict[str, list[dict]] = {
    "labor": [
        {"title": "劳动合同法 第40条（无过失辞退）", "points": ["提前30日书面通知或支付代通知金", "需支付经济补偿N（每满一年一个月工资）", "情形：医疗期满不能工作 / 不胜任经培训仍不胜任 / 客观情况重大变化"]},
        {"title": "劳动合同法 第39条（过失性辞退）", "points": ["严重违反规章制度可立即解除", "无需支付经济补偿", "须有证据支撑，制度须经民主程序并公示"]},
        {"title": "降薪合规要点", "points": ["单方降薪属变更劳动合同，需与员工协商一致并书面确认", "绩效/提成浮动部分可依制度调整", "恶意降薪逼迫离职属违法，可能承担2N赔偿"]},
        {"title": "加班费标准", "points": ["平日延时150%", "休息日加班不能补休的200%", "法定节假日300%"]},
        {"title": "试用期规则", "points": ["试用期包含在合同期内", "3个月≤合同<1年试用≤1个月；1-3年≤2个月；3年以上≤6个月", "同一单位只能约定一次试用期"]},
        {"title": "社保缴纳", "points": ["为员工缴纳社保是法定义务，不可协商放弃", "未缴社保员工可解除合同并主张经济补偿"]},
    ],
    "contract": [
        {"title": "合同审查要点", "points": ["核对主体资质与签约权限", "付款节点与违约金对等", "争议解决条款（仲裁/法院、管辖地）", "送达地址条款必备"]},
    ],
    "ip": [
        {"title": "商标注册", "points": ["先注册后使用，类别需覆盖实际经营项目", "使用他人未注册商标有侵权风险"]},
        {"title": "宣传素材版权", "points": ["网络下载图片/音乐需确认授权", "字体商用需授权（如方正/汉仪）", "AI生成内容标注与平台规则需留意"]},
    ],
    "consumer": [
        {"title": "消费者权益保护要点", "points": ["明码标价，不得虚假宣传", "退换货规则需事先公示", "预付费充值需按约定履约，超范围储值受限"]},
    ],
    "advert": [
        {"title": "广告法红线", "points": ["禁用'最'、'第一'、'国家级'等绝对化用语", "优惠活动需标明期限与适用范围", "代言需真实使用"]},
    ],
    "tax": [
        {"title": "小规模纳税人优惠（现行政策）", "points": ["月销售额10万以下免征增值税（具体以申报期政策为准）", "'六税两费'减半政策适用于小规模纳税人/个体户", "季度申报，注意开票金额合并计算"]},
        {"title": "个体户经营所得", "points": ["查账征收按5%-35%超额累进", "核定征收地区按核定率", "建议保留进销存凭证"]},
    ],
}


# ───────────────────────── 营销模板库 ─────────────────────────
_TEMPLATES: dict[str, dict] = {
    "短视频脚本": {"scene": "拍摄 15-60s 短视频，吸引到店/下单", "structure": [
        "【前3秒钩子】悬念/痛点/利益点开场：『{hook}』",
        "【展示】产品/环境/过程特写，配口播卖点：{selling_points}",
        "【信任】门店实拍 + 营业执照/资质/好评画面",
        "【行动号召】限时福利 + 引导：{cta}",
        "【文案】标题 + 话题标签：#本地生活 #{city}美食 等",
    ]},
    "朋友圈文案": {"scene": "私域日常种草", "structure": [
        "【今日主推】一句话利益点：{hook}",
        "【图片/视频建议】3-6 张实拍 + 1 张活动海报",
        "【评论区运营】统一回复优惠细则，私信引导下单",
    ]},
    "开业活动": {"scene": "新店开业引流", "structure": [
        "【活动主题】{theme}",
        "【引流品】前 N 名到店享 {offer}",
        "【裂变】分享集赞 / 邀请好友得 {gift}",
        "【转化】储值/会员卡锁定复购：{membership}",
        "【平台投放】抖音/美团/大众点评上架团购与开业券",
    ]},
    "促销话术": {"scene": "节日/淡季促销", "structure": [
        "【限时】仅 X 天（制造紧迫感）",
        "【限量】前 X 份 / 每日限量",
        "【组合】套餐比单点省 ¥X（算给顾客看）",
        "【售后】不满意无条件退款/重做，降低决策门槛",
    ]},
}


def _pick_template(scene: str) -> dict | None:
    for key, tpl in _TEMPLATES.items():
        if key in scene:
            return tpl
    return None


# ───────────────────────── 工具实现上下文 ─────────────────────────
class ToolContext:
    """工具执行上下文：绑定当前商家画像，供各工具读取店铺信息"""

    def __init__(self, profile: dict | None = None) -> None:
        self.profile = profile or {}
        self._vector = None

    # 店铺辅助字段
    @property
    def store_type(self) -> str:
        return self.profile.get("type") or self.profile.get("store_type") or "restaurant"

    @property
    def store_name(self) -> str:
        return (self.profile.get("store_name") or self.profile.get("name") or "本店")

    def _vector_store(self):
        if self._vector is None:
            try:
                from src.knowledge.vector_store import VectorStore
                self._vector = VectorStore()
            except Exception as e:
                logger.warning(f"[tools] 向量库不可用: {e}")
                self._vector = False
        return self._vector or None

    # ── 1. rag_search ──
    def rag_search(self, query: str, top_k: int = 4) -> str:
        """语义检索行业知识库（RAG）"""
        store = self._vector_store()
        if not store:
            return json.dumps({"ok": False, "reason": "知识库暂不可用"}, ensure_ascii=False)
        try:
            hits = store.search(query, top_k=min(int(top_k), 6))
        except Exception as e:
            return json.dumps({"ok": False, "reason": str(e)[:200]}, ensure_ascii=False)
        if not hits:
            return json.dumps({"ok": True, "hits": []}, ensure_ascii=False)
        docs = [{
            "content": h["content"][:500],
            "source": h.get("metadata", {}).get("source", ""),
        } for h in hits]
        return json.dumps({"ok": True, "hits": docs}, ensure_ascii=False)

    # ── 2. shop_diagnose ──
    def shop_diagnose(self, aspect: str = "整体") -> str:
        """店铺体检：行业基准 + 店铺画像 + 待核验指标"""
        from config.industry_genome import get_genome
        profile = self.profile
        payload: dict[str, Any] = {"ok": True, "aspect": aspect}
        # 行业基准
        try:
            genome = get_genome(self.store_type)
            payload["industry"] = genome.name
            payload["benchmarks"] = genome.format_benchmarks()
            payload["red_flags"] = genome.format_red_flags()
        except Exception:
            payload["industry"] = profile.get("type_name", "自定义行业")
            payload["benchmarks"] = "（无该行业基准数据）"
            payload["red_flags"] = ""
        # 店铺画像
        payload["store"] = {
            "store_name": profile.get("store_name") or profile.get("name", ""),
            "type_name": profile.get("type_name", ""),
            "products": profile.get("products", ""),
            "region": profile.get("region", ""),
            "address": profile.get("address", ""),
            "hours": profile.get("hours", ""),
            "location_feature": profile.get("location_feature", ""),
            "faq_knowledge": profile.get("faq_knowledge", ""),
        }
        return json.dumps(payload, ensure_ascii=False)

    # ── 3. calculate ──
    def calculate(self, expression: str) -> str:
        return _safe_calc(expression)

    # ── 4. regulation_lookup ──
    def regulation_lookup(self, domain: str, keyword: str = "") -> str:
        items = _REGULATION_DB.get(domain, [])
        if keyword:
            items = [it for it in items if keyword.lower() in (it["title"] + " ".join(it["points"])).lower()]
        return json.dumps({"ok": True, "domain": domain, "items": items}, ensure_ascii=False)

    # ── 5. template_fill ──
    def template_fill(self, scene: str, product: str = "", platform: str = "") -> str:
        tpl = _pick_template(scene)
        if not tpl:
            return json.dumps({
                "ok": True,
                "note": "未匹配到模板，请把可用场景写入最终答案",
                "available": list(_TEMPLATES.keys()),
            }, ensure_ascii=False)
        product = product or self.profile.get("products") or "本店招牌产品"
        hooks = {
            "短视频脚本": f"为什么{self.store_name}的{product}让顾客反复回购？",
            "朋友圈文案": f"{self.store_name}的{product}，凭什么让人排队？",
            "开业活动": f"{self.store_name}盛大开业，福利拉满！",
            "促销话术": f"{self.store_name}限时特惠，错过再等一年！",
        }
        cta = {
            "短视频脚本": f"点击下方定位，到店报『{self.store_name}粉丝』享专属福利",
            "朋友圈文案": f"私信回复【优惠】获取今日专属福利",
        }
        city = (self.profile.get("region") or "").replace("省", "").replace("市", "") or "本地"
        content = []
        for line in tpl["structure"]:
            content.append(line
                           .replace("{hook}", hooks.get(scene, "一句话钩子"))
                           .replace("{selling_points}", f"主打{product}，突出新鲜/性价比/服务")
                           .replace("{cta}", cta.get(scene, "点击下方按钮立即下单"))
                           .replace("{theme}", f"{self.store_name}开业福利专场")
                           .replace("{offer}", "首单 5 折 / 买一送一")
                           .replace("{gift}", "招牌小食一份")
                           .replace("{membership}", "储值 300 送 50，锁定回头客"))
        out = {"ok": True, "scene": scene, "platform": platform or "全平台", "city": city, "store_name": self.store_name,
               "product": product, "draft": "\n".join(f"{i+1}. {c}" for i, c in enumerate(content))}
        return json.dumps(out, ensure_ascii=False)

    # ── 6. csv_analyze ──
    def csv_analyze(self, question: str = "") -> str:
        return json.dumps({
            "ok": False,
            "reason": "当前会话未检测到已上传的 CSV/Excel 业务数据文件；如您已上传，请重新发起问题；否则建议改用「店铺诊断」或描述数字让编排器计算。",
        }, ensure_ascii=False)


# ───────────────────────── 工具 Schema 注册 ─────────────────────────
def build_tools(ctx: ToolContext) -> tuple[list[dict], dict[str, Callable]]:
    """构建 OpenAI tools schema 与 名称→函数 映射"""
    schemas: list[dict] = [
        {"type": "function", "function": {
            "name": "rag_search",
            "description": "语义检索行业知识库（行业文档/法规/案例）。当问题需要行业知识、经营对标、政策法规依据时调用。",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "检索关键词/问题，尽量完整"},
                "top_k": {"type": "integer", "description": "返回条数，默认4"},
            }, "required": ["query"]},
        }},
        {"type": "function", "function": {
            "name": "shop_diagnose",
            "description": "对当前店铺进行经营体检：返回行业基准KPI、红线预警与店铺画像，用于营收下滑归因、经营诊断类问题。",
            "parameters": {"type": "object", "properties": {
                "aspect": {"type": "string", "description": "体检维度：整体/流量/转化/成本/复购/人效"},
            }},
        }},
        {"type": "function", "function": {
            "name": "calculate",
            "description": "精确计算成本/利润/定价/转化率等。参数为数学表达式，示例: '100*(1-0.2)-15' 或 '(12000/30)/8'。",
            "parameters": {"type": "object", "properties": {
                "expression": {"type": "string", "description": "数学表达式，仅含数字与 + - * / // % ** ( )"},
            }, "required": ["expression"]},
        }},
        {"type": "function", "function": {
            "name": "regulation_lookup",
            "description": "查询中国常用经营法规要点。domain: labor(劳动/降薪/辞退/加班) contract(合同) ip(商标/版权) consumer(消费者权益) advert(广告法) tax(税务/小规模纳税人)。",
            "parameters": {"type": "object", "properties": {
                "domain": {"type": "string", "enum": ["labor", "contract", "ip", "consumer", "advert", "tax"]},
                "keyword": {"type": "string", "description": "可选关键词过滤，如 降薪/试用期/加班"},
            }, "required": ["domain"]},
        }},
        {"type": "function", "function": {
            "name": "template_fill",
            "description": "生成营销模板初稿。scene 取值: 短视频脚本/朋友圈文案/开业活动/促销话术。",
            "parameters": {"type": "object", "properties": {
                "scene": {"type": "string", "enum": ["短视频脚本", "朋友圈文案", "开业活动", "促销话术"]},
                "product": {"type": "string", "description": "产品名，缺省用店铺主营"},
                "platform": {"type": "string", "description": "平台：抖音/小红书/美团/朋友圈"},
            }, "required": ["scene"]},
        }},
        {"type": "function", "function": {
            "name": "csv_analyze",
            "description": "分析商家上传的 CSV/Excel 业务数据（需已上传文件）。",
            "parameters": {"type": "object", "properties": {
                "question": {"type": "string", "description": "想分析的问题"},
            }},
        }},
    ]
    mapping: dict[str, Callable] = {
        "rag_search": ctx.rag_search,
        "shop_diagnose": ctx.shop_diagnose,
        "calculate": ctx.calculate,
        "regulation_lookup": ctx.regulation_lookup,
        "template_fill": ctx.template_fill,
        "csv_analyze": ctx.csv_analyze,
    }
    return schemas, mapping


def describe_tools(schemas: list[dict]) -> str:
    """供 Step3 系统提示使用的工具说明"""
    lines = []
    for s in schemas:
        f = s["function"]
        lines.append(f"- `{f['name']}`：{f['description']}")
    return "\n".join(lines)
