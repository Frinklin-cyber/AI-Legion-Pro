"""行业基因库加载器

从 config/industry_genome/*.yaml 加载所有行业的基因组配置。
严禁在任何 Python 代码中硬编码行业名称或指标。
"""
from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any
from functools import lru_cache

from loguru import logger

GENOME_DIR = Path(__file__).parent


class IndustryGenome:
    """单个行业的基因对象，提供类型安全的访问接口"""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def id(self) -> str:
        return self._data["id"]

    @property
    def name(self) -> str:
        return self._data["name"]

    @property
    def icon(self) -> str:
        return self._data.get("icon", "🏠")

    @property
    def description(self) -> str:
        return self._data.get("description", "")

    @property
    def subcategories(self) -> list[str]:
        return self._data.get("subcategories", [])

    @property
    def default_search_radius(self) -> int:
        return self._data.get("default_search_radius", 2000)

    # ── POI 类型码（用于高德/腾讯精准商家搜索）──
    @property
    def amap_poi_type(self) -> str:
        return self._data.get("amap_poi_type", "")

    @property
    def tencent_poi_type(self) -> str:
        return self._data.get("tencent_poi_type", "")

    # ── KPI ──────────────────────────────────────────
    @property
    def kpi_formulas(self) -> dict[str, dict[str, Any]]:
        return self._data.get("kpi_formulas", {})

    @property
    def critical_kpis(self) -> list[str]:
        """返回 importance=critical 的 KPI 名称列表"""
        return [k for k, v in self.kpi_formulas.items() if v.get("importance") == "critical"]

    @property
    def high_kpis(self) -> list[str]:
        return [k for k, v in self.kpi_formulas.items() if v.get("importance") in ("critical", "high")]

    # ── 基准 ──────────────────────────────────────────
    @property
    def benchmarks(self) -> dict[str, dict[str, float]]:
        return self._data.get("benchmarks", {})

    def get_benchmark(self, metric: str, level: str = "average") -> float | None:
        """获取指标指定等级的基准值

        Args:
            metric: 指标名
            level: excellent/good/average/poor 或 economy/mid/premium
        """
        b = self.benchmarks.get(metric, {})
        return b.get(level)

    def benchmark_comparison(self, metric: str, actual: float) -> str:
        """返回实际值与行业基准的比较描述"""
        b = self.benchmarks.get(metric, {})
        if not b:
            return "暂无行业基准数据"

        avg = b.get("average") or b.get("mid")
        if avg is None:
            return "暂无行业基准数据"

        ratio = actual / avg
        if ratio >= 1.2:
            return f"高于行业均值 {avg}（{actual}/{avg}，领先{(ratio-1)*100:.0f}%）"
        elif ratio >= 0.9:
            return f"接近行业均值 {avg}（{actual}/{avg}）"
        else:
            return f"低于行业均值 {avg}（{actual}/{avg}，落后{(1-ratio)*100:.0f}%）"

    # ── 红线 ──────────────────────────────────────────
    @property
    def red_flags(self) -> list[dict[str, Any]]:
        return self._data.get("red_flags", [])

    def check_red_flags(self, metrics: dict[str, float]) -> list[dict[str, Any]]:
        """检查提供的指标值是否触发红线"""
        triggered: list[dict[str, Any]] = []
        for flag in self.red_flags:
            name = flag["metric"]
            if name not in metrics:
                continue
            actual = metrics[name]
            threshold_str = flag["threshold"]
            # 解析阈值表达式
            try:
                if threshold_str.startswith(">"):
                    limit = float(threshold_str[1:].strip())
                    if actual > limit:
                        triggered.append({**flag, "actual": actual, "triggered": True})
                elif threshold_str.startswith("<"):
                    limit = float(threshold_str[1:].strip())
                    if actual < limit:
                        triggered.append({**flag, "actual": actual, "triggered": True})
                elif "降幅" in threshold_str:
                    # "较上月降幅 > 15%" 这类相对变化需要外部传入变化率
                    pass
            except (ValueError, IndexError):
                continue
        return triggered

    # ── Prompt 模板 ───────────────────────────────────
    @property
    def prompt_templates(self) -> dict[str, str]:
        return self._data.get("prompt_templates", {})

    def get_analysis_prompt(self, **kwargs: str) -> str:
        template = self.prompt_templates.get("analysis", "")
        if not template:
            template = "请对该{store_type}的经营数据进行分析诊断。"
        return template.format(
            store_type=self.name,
            benchmarks_context=self.format_benchmarks(),
            red_flags_context=self.format_red_flags(),
            **kwargs,
        )

    def get_attribution_prompt(self, **kwargs: str) -> str:
        template = self.prompt_templates.get("attribution", "")
        if not template:
            template = "请对{store_type}的经营数据进行因果归因分析。"
        return template.format(
            store_type=self.name,
            benchmarks_context=self.format_benchmarks(),
            **kwargs,
        )

    # ── 格式化工具 ─────────────────────────────────────
    def format_benchmarks(self) -> str:
        """将行业基准格式化为可注入Prompt的文本"""
        lines: list[str] = ["| 指标 | 优秀 | 良好 | 均值 | 警戒 |", "|---|---|---|---|---|"]
        for metric, levels in self.benchmarks.items():
            exc = levels.get("excellent", levels.get("economy", "-"))
            good = levels.get("good", levels.get("mid", "-"))
            avg = levels.get("average", "-")
            poor = levels.get("poor", "-")
            lines.append(f"| {metric} | {exc} | {good} | {avg} | {poor} |")
        return "\n".join(lines)

    def format_red_flags(self) -> str:
        lines: list[str] = []
        for flag in self.red_flags:
            sev = {"critical": "🔴🔴", "high": "🔴", "medium": "🟡"}.get(flag.get("severity", ""), "⚪")
            lines.append(f"- {sev} **{flag['metric']}**: {flag.get('threshold', '')} → {flag.get('description', '')}")
        return "\n".join(lines) if lines else "暂无行业红线定义"

    # ── 通用属性 ───────────────────────────────────────
    @property
    def competitor_focus(self) -> list[str]:
        return self._data.get("competitor_focus", [])

    @property
    def marketing_scenarios(self) -> list[dict[str, str]]:
        return self._data.get("marketing_scenarios", [])

    @property
    def faq_templates(self) -> list[str]:
        return self._data.get("faq_templates", [])

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


class GenomeLoader:
    """行业基因库全局加载器（单例模式）"""

    _instance: GenomeLoader | None = None
    _genomes: dict[str, IndustryGenome] = {}
    _loaded: bool = False

    def __new__(cls) -> GenomeLoader:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _load_all(self) -> None:
        """从 YAML 文件目录加载所有行业基因组"""
        if self._loaded:
            return

        yaml_files = sorted(GENOME_DIR.glob("*.yaml"))
        if not yaml_files:
            logger.warning(f"[GenomeLoader] 未找到任何基因组 YAML 文件: {GENOME_DIR}")
            self._loaded = True
            return

        for fp in yaml_files:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if not data or "id" not in data:
                    logger.warning(f"[GenomeLoader] 跳过无效基因组文件: {fp}")
                    continue
                genome = IndustryGenome(data)
                self._genomes[genome.id] = genome
                logger.debug(f"[GenomeLoader] 已加载: {genome.id} ({genome.name})")
            except Exception as e:
                logger.error(f"[GenomeLoader] 加载失败 {fp}: {e}")

        self._loaded = True
        logger.info(f"[GenomeLoader] 共加载 {len(self._genomes)} 个行业基因组")

    @property
    def genomes(self) -> dict[str, IndustryGenome]:
        self._load_all()
        return self._genomes

    def get(self, store_type: str) -> IndustryGenome:
        """获取指定行业的基因组，不存在时返回 custom"""
        self._load_all()
        return self._genomes.get(store_type, self._genomes.get("custom"))

    def list_all(self) -> list[dict[str, Any]]:
        """列出所有可用行业（供前端使用）"""
        self._load_all()
        return [
            {
                "id": g.id,
                "name": g.name,
                "icon": g.icon,
                "description": g.description,
                "subcategories": g.subcategories,
                "default_search_radius": g.default_search_radius,
            }
            for g in self._genomes.values()
        ]

    def has(self, store_type: str) -> bool:
        self._load_all()
        return store_type in self._genomes

    def count(self) -> int:
        self._load_all()
        return len(self._genomes)


# ── 便捷全局函数 ──────────────────────────────────────────


@lru_cache(maxsize=1)
def get_loader() -> GenomeLoader:
    return GenomeLoader()


def get_genome(store_type: str) -> IndustryGenome:
    """获取指定行业基因组"""
    return get_loader().get(store_type)


def list_genomes() -> list[dict[str, Any]]:
    """列出所有行业"""
    return get_loader().list_all()


# ── POI 类型 → 行业推断 ───────────────────────────────────

_POI_TYPE_TO_GENOME: dict[str, list[str]] = {
    "restaurant": ["美食", "餐厅", "餐饮", "中餐", "火锅", "烧烤", "小吃", "快餐", "咖啡", "茶饮",
                   "奶茶", "烘焙", "面包", "甜品", "糖水", "日韩", "日料", "韩餐", "西餐", "牛排",
                   "自助", "轻食", "沙拉", "早餐", "卤味", "熟食", "外卖", "食堂", "团餐", "面馆",
                   "粉店", "米线", "麻辣烫", "冒菜", "串串", "烤鱼", "酸菜鱼", "饮品"],
    "retail": ["超市", "便利店", "零售", "商店", "商超", "母婴", "服饰", "服装", "鞋", "化妆品",
               "美妆", "数码", "手机", "家电", "烟酒", "茶叶", "眼镜", "文具", "宠物用品", "便利店",
               "杂货", "批发", "零售"],
    "hotel": ["酒店", "宾馆", "旅馆", "民宿", "客栈", "住宿", "旅店", "公寓"],
    "entertainment": ["KTV", "影院", "电影院", "网吧", "网咖", "酒吧", "棋牌", "台球", "足浴",
                      "按摩", "SPA", "游乐园", "剧本杀", "密室", "电玩", "ktv", "ktv"],
    "healthcare": ["医院", "诊所", "药店", "药房", "口腔", "牙科", "体检", "医美", "整形",
                   "中医", "宠物医院", "宠物诊所", "社区医疗"],
    "education": ["培训", "教育", "学校", "早教", "驾校", "托管", "自习室", "补习班", "辅导班",
                  "兴趣班", "幼儿园", "机构"],
    "fitness": ["健身", "瑜伽", "游泳馆", "游泳", "运动", "球馆", "羽毛球", "篮球", "舞蹈",
                "拳击", "跆拳道", "健身房"],
    "florist": ["鲜花", "花店", "礼品", "婚庆", "花卉", "绿植"],
    "service": ["美发", "理发", "美容", "美甲", "干洗", "家政", "维修", "快递", "银行", "照相",
                "图文", "打印", "开锁", "搬家", "保洁", "宠物服务", "洗衣"],
    "real_estate": ["房产", "地产", "中介", "售楼", "二手房", "租房", "置业"],
    "auto": ["汽车", "洗车", "汽修", "维修", "加油站", "4S", "保养", "轮胎", "汽车美容"],
}

# 百度地图常返回英文 type（如 cater、hotel、life_service），直接映射
_ENGLISH_TYPE_TO_GENOME: dict[str, str] = {
    "cater": "restaurant",
    "food": "restaurant",
    "restaurant": "restaurant",
    "hotel": "hotel",
    "life": "service",
    "service": "service",
    "shopping": "retail",
    "retail": "retail",
    "entertainment": "entertainment",
    "education": "education",
    "school": "education",
    "medical": "healthcare",
    "health": "healthcare",
    "car": "auto",
    "auto": "auto",
    "estate": "real_estate",
    "sport": "fitness",
    "gym": "fitness",
    "flower": "florist",
    "travel": "hotel",
}


def infer_genome_from_poi_type(poi_type: str | None) -> str | None:
    """根据 POI 类型文本推断行业 genome id。

    Args:
        poi_type: 地图 POI 类型字段，如 "美食;中餐厅;火锅店" 或 "酒店;星级酒店;三星级酒店"。

    Returns:
        匹配到的行业 id，未匹配到返回 None。
    """
    if not poi_type:
        return None

    text = poi_type.lower()

    # 优先命中百度英文 type（如 cater / hotel / life_service）
    for en_type, genome_id in _ENGLISH_TYPE_TO_GENOME.items():
        if en_type in text:
            return genome_id

    scores: dict[str, int] = {}
    for genome_id, keywords in _POI_TYPE_TO_GENOME.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score:
            scores[genome_id] = score

    if not scores:
        return None
    return max(scores, key=lambda k: scores[k])
