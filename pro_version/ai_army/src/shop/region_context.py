"""区域上下文数据结构 - RegionContext

定义本地化内容生成所需的统一数据结构。
四个维度：经济特征、用户画像、竞争环境、本地热点
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EconomyContext:
    """地区经济特征"""
    gdp_level: str = ""                     # 经济水平描述（如"中等（约550亿元）"）
    per_capita_income: str = ""             # 人均收入（如"约42000元/年"）
    major_industries: list[str] = field(default_factory=list)   # 主要产业
    consumption_level: str = ""             # 消费水平特征（如"平价消费为主"）
    business_districts: list[str] = field(default_factory=list)  # 核心商圈


@dataclass
class PopulationContext:
    """地区用户画像"""
    total_population: str = ""              # 区域人口规模
    avg_age: str = ""                       # 平均年龄
    typical_consumer: str = ""              # 典型消费者描述
    consumer_concerns: list[str] = field(default_factory=list)   # 消费者关注点
    speak_style: str = ""                   # 本地说话风格/方言特征


@dataclass
class CompetitionContext:
    """地区竞争环境"""
    total_competitors: int = 0              # 同行大致数量
    top_competitors: list[dict] = field(default_factory=list)    # 主要竞品
    market_saturation: str = ""             # 市场饱和度
    differentiation_opportunity: str = ""   # 差异化机会


@dataclass
class HotContext:
    """地区热点话题"""
    recent_hot_topics: list[str] = field(default_factory=list)   # 近期热点
    local_slang: list[str] = field(default_factory=list)         # 本地流行语


@dataclass
class RegionContext:
    """完整的区域上下文数据包"""
    region_name: str = ""                   # 地区名称（如"昆明市呈贡区"）
    adcode: str = ""                        # 行政区划代码
    location: dict[str, float] = field(default_factory=lambda: {"lat": 0.0, "lng": 0.0})
    economy_context: EconomyContext = field(default_factory=EconomyContext)
    population_context: PopulationContext = field(default_factory=PopulationContext)
    competition_context: CompetitionContext = field(default_factory=CompetitionContext)
    hot_context: HotContext = field(default_factory=HotContext)
    generated_at: str = ""                  # 生成时间戳

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于 JSON 序列化和缓存"""
        return {
            "region_name": self.region_name,
            "adcode": self.adcode,
            "location": self.location,
            "economy_context": {
                "gdp_level": self.economy_context.gdp_level,
                "per_capita_income": self.economy_context.per_capita_income,
                "major_industries": self.economy_context.major_industries,
                "consumption_level": self.economy_context.consumption_level,
                "business_districts": self.economy_context.business_districts,
            },
            "population_context": {
                "total_population": self.population_context.total_population,
                "avg_age": self.population_context.avg_age,
                "typical_consumer": self.population_context.typical_consumer,
                "consumer_concerns": self.population_context.consumer_concerns,
                "speak_style": self.population_context.speak_style,
            },
            "competition_context": {
                "total_competitors": self.competition_context.total_competitors,
                "top_competitors": self.competition_context.top_competitors,
                "market_saturation": self.competition_context.market_saturation,
                "differentiation_opportunity": self.competition_context.differentiation_opportunity,
            },
            "hot_context": {
                "recent_hot_topics": self.hot_context.recent_hot_topics,
                "local_slang": self.hot_context.local_slang,
            },
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegionContext:
        """从字典还原"""
        eco = data.get("economy_context", {})
        pop = data.get("population_context", {})
        comp = data.get("competition_context", {})
        hot = data.get("hot_context", {})
        loc = data.get("location", {})

        return cls(
            region_name=data.get("region_name", ""),
            adcode=data.get("adcode", ""),
            location={"lat": float(loc.get("lat", 0)), "lng": float(loc.get("lng", 0))},
            economy_context=EconomyContext(
                gdp_level=eco.get("gdp_level", ""),
                per_capita_income=eco.get("per_capita_income", ""),
                major_industries=eco.get("major_industries", []),
                consumption_level=eco.get("consumption_level", ""),
                business_districts=eco.get("business_districts", []),
            ),
            population_context=PopulationContext(
                total_population=pop.get("total_population", ""),
                avg_age=pop.get("avg_age", ""),
                typical_consumer=pop.get("typical_consumer", ""),
                consumer_concerns=pop.get("consumer_concerns", []),
                speak_style=pop.get("speak_style", ""),
            ),
            competition_context=CompetitionContext(
                total_competitors=int(comp.get("total_competitors", 0)),
                top_competitors=comp.get("top_competitors", []),
                market_saturation=comp.get("market_saturation", ""),
                differentiation_opportunity=comp.get("differentiation_opportunity", ""),
            ),
            hot_context=HotContext(
                recent_hot_topics=hot.get("recent_hot_topics", []),
                local_slang=hot.get("local_slang", []),
            ),
            generated_at=data.get("generated_at", ""),
        )

    def to_prompt_string(self) -> str:
        """转换为可注入 Prompt 的文本格式"""
        parts = []

        # 地区基本信息
        parts.append(f"地区名称：{self.region_name}")

        # 经济特征
        eco = self.economy_context
        eco_lines = []
        if eco.gdp_level:
            eco_lines.append(f"  经济水平：{eco.gdp_level}")
        if eco.per_capita_income:
            eco_lines.append(f"  人均收入：{eco.per_capita_income}")
        if eco.major_industries:
            eco_lines.append(f"  主要产业：{'、'.join(eco.major_industries)}")
        if eco.consumption_level:
            eco_lines.append(f"  消费特征：{eco.consumption_level}")
        if eco.business_districts:
            eco_lines.append(f"  核心商圈：{'、'.join(eco.business_districts)}")
        if eco_lines:
            parts.append("经济特征：\n" + "\n".join(eco_lines))

        # 用户画像
        pop = self.population_context
        pop_lines = []
        if pop.total_population:
            pop_lines.append(f"  区域人口：{pop.total_population}")
        if pop.avg_age:
            pop_lines.append(f"  平均年龄：{pop.avg_age}")
        if pop.typical_consumer:
            pop_lines.append(f"  典型消费者：{pop.typical_consumer}")
        if pop.consumer_concerns:
            pop_lines.append(f"  消费者关注点：{'、'.join(pop.consumer_concerns)}")
        if pop.speak_style:
            pop_lines.append(f"  说话风格：{pop.speak_style}")
        if pop_lines:
            parts.append("用户画像：\n" + "\n".join(pop_lines))

        # 竞争环境
        comp = self.competition_context
        comp_lines = []
        if comp.total_competitors > 0:
            comp_lines.append(f"  周边同行数量：约{comp.total_competitors}家")
        if comp.top_competitors:
            names = [c.get("name", "") for c in comp.top_competitors[:5]]
            comp_lines.append(f"  主要竞品：{'、'.join(names)}")
        if comp.market_saturation:
            comp_lines.append(f"  市场饱和程度：{comp.market_saturation}")
        if comp.differentiation_opportunity:
            comp_lines.append(f"  差异化机会：{comp.differentiation_opportunity}")
        if comp_lines:
            parts.append("竞争环境：\n" + "\n".join(comp_lines))

        # 本地热点
        hot = self.hot_context
        hot_lines = []
        if hot.recent_hot_topics:
            hot_lines.append(f"  近期热点：{'、'.join(hot.recent_hot_topics[:5])}")
        if hot.local_slang:
            hot_lines.append(f"  本地流行语：{'、'.join(hot.local_slang)}")
        if hot_lines:
            parts.append("本地流行语与热点：\n" + "\n".join(hot_lines))

        return "\n\n".join(parts)

    @property
    def is_empty(self) -> bool:
        """是否为空上下文"""
        return not self.region_name
