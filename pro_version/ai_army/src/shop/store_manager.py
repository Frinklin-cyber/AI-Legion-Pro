"""店长助理 (StoreManager) v2.1 - 行业基因组驱动 + 本地化增强

管理店铺全局运营：配置管理、经营分析、日报生成、营销策划。
从 Python 硬编码迁移到 YAML 行业基因组配置。
v2.1: 集成区域上下文增强器，生成本地化内容。
"""

import json
import re
from typing import Any
from loguru import logger

from src.core import BaseSoldier
from config.industry_genome import get_genome, IndustryGenome
from config.store_templates import get_store_type
from src.shop.store_prompts import STORE_ANALYSIS_PROMPT, STORE_DAILY_REPORT_PROMPT, STORE_MARKETING_PROMPT
from src.shop.region_enricher import enrich_region_sync, _extract_region_name


def _extract_city_from_address(address: str) -> str:
    """从地址中提取城市/县级地名，如'宾川县金牛镇...' -> '宾川', '北京市朝阳区...' -> '北京'"""
    if not address:
        return ""
    # 1. 先匹配 X省X市 或 X自治区X市 → 提取市名
    m = re.search(r"(?:省|自治区)(.{2,6}市)", address)
    if m:
        return m.group(1)[:-1]
    # 2. 匹配 X市 开头 → 提取市名（直辖市/地级市）
    m = re.match(r"^(.{2,6}市)", address)
    if m:
        return m.group(1)[:-1]
    # 3. 匹配 X县 / X区 开头 → 提取县/区名
    m = re.match(r"^(.{2,6}(?:县|区))", address)
    if m:
        return m.group(1)[:-1]
    return address[:4].strip()


class StoreManager(BaseSoldier):
    """店长助理 - 统筹店铺经营管理的AI战士"""

    name = "店长助理"
    role = "shop_store_manager"
    temperature = 0.5
    max_tokens = 3000

    def __init__(self) -> None:
        super().__init__()
        self.store_config: dict = {}
        self._user_configs: dict[str, dict] = {}  # v4.0: user_id -> config
        self._load_config()
        self._current_user_id: str = ""

    def _config_path(self) -> str:
        """v4.0: 多用户配置文件路径"""
        import os
        return os.path.join(os.path.dirname(__file__), "..", "..", "data", "store_configs.json")

    def _load_config(self):
        """v4.0: 从文件加载所有用户配置"""
        import os
        config_path = self._config_path()
        # 兼容旧版单用户文件
        old_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "store_config.json")
        if os.path.exists(old_path) and not os.path.exists(config_path):
            try:
                with open(old_path, "r", encoding="utf-8") as f:
                    old_config = json.load(f)
                if old_config:
                    self._user_configs = {"_migrated": old_config}
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(self._user_configs, f, ensure_ascii=False, indent=2)
            except Exception:
                self._user_configs = {}
        elif os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    self._user_configs = json.load(f)
            except Exception:
                self._user_configs = {}
        else:
            self._user_configs = {}

    def _save_config(self):
        """v4.0: 保存所有用户配置"""
        import os
        config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
        os.makedirs(config_dir, exist_ok=True)
        with open(self._config_path(), "w", encoding="utf-8") as f:
            json.dump(self._user_configs, f, ensure_ascii=False, indent=2)

    def get_config(self, user_id: str = "") -> dict:
        """v4.0: 获取指定用户的店铺配置"""
        if user_id and user_id in self._user_configs:
            return self._user_configs[user_id]
        return {}

    def set_config(self, config: dict, user_id: str = "") -> dict:
        """v4.0: 设置指定用户的店铺配置"""
        uid = user_id or "_default"
        if uid not in self._user_configs:
            self._user_configs[uid] = {}
        self._user_configs[uid].update(config)
        # 兼容旧引用
        self.store_config = self._user_configs[uid]
        self._current_user_id = uid
        # 如果设置了类型，补充类型相关默认配置
        if "type" in config:
            tpl = get_store_type(config["type"])
            if tpl and "kpi_values" not in self._user_configs[uid]:
                self._user_configs[uid]["kpi_values"] = {}
                for k, v in tpl.get("kpi_fields", {}).items():
                    self._user_configs[uid]["kpi_values"][k] = 0
        self._save_config()
        return self._user_configs[uid]

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """执行店长任务

        task types:
        - config: 获取/设置店铺配置
        - analyze: 经营数据分析
        - daily_report: 生成每日日报
        - marketing: 生成营销内容
        
        支持 v4.0 多用户隔离，通过 task 中的 user_id 区分用户。
        """
        task_type = task.get("type", "analyze")
        user_id = task.get("user_id", self._current_user_id)

        if task_type == "config":
            return self._handle_config(task, user_id)
        elif task_type == "analyze":
            return self._handle_analyze(task, user_id)
        elif task_type == "daily_report":
            return self._handle_daily_report(task, user_id)
        elif task_type == "marketing":
            return self._handle_marketing(task, user_id)
        else:
            return {"status": "error", "message": f"未知任务类型: {task_type}"}

    def _get_user_config(self, user_id: str = "") -> dict:
        """获取店铺配置，优先使用用户隔离配置，回退到旧版"""
        if user_id and user_id in self._user_configs:
            return self._user_configs[user_id]
        if self.store_config:
            return self.store_config
        return {}

    def _handle_config(self, task: dict, user_id: str = "") -> dict:
        if "update" in task:
            self.set_config(task["update"], user_id)
        return {
            "status": "success",
            "config": self.get_config(user_id),
        }

    def _handle_analyze(self, task: dict, user_id: str = "") -> dict:
        cfg = self._get_user_config(user_id)
        store_type = cfg.get("type", "custom")
        genome = get_genome(store_type)

        kpi_text = "\n".join([
            f"  - {name}（单位：{info['unit']}，公式：{info['formula']}）"
            for name, info in genome.kpi_formulas.items()
        ])

        # 注入行业基准
        benchmarks_text = genome.format_benchmarks()
        red_flags_text = genome.format_red_flags()

        data_section = task.get("data", task.get("question", "请基于当前店铺情况做通用分析"))
        if isinstance(data_section, dict):
            data_section = json.dumps(data_section, ensure_ascii=False, indent=2)

        region_context = self._get_region_context(cfg)

        user_msg = STORE_ANALYSIS_PROMPT.format(
            store_name=cfg.get("name", "未命名店铺"),
            store_type=genome.name,
            kpi_definitions=kpi_text,
            data_section=data_section,
            region_context=region_context,
        )

        # 追加行业基准上下文
        user_msg += f"""

## 行业基准数据（{genome.name}）
{benchmarks_text}

## 行业红线预警
{red_flags_text}

## 硬性要求
1. 所有指标必须与行业基准对比，格式：「您的XX为{值}，{高于/低于}行业均值{基准值}」
2. 建议必须可量化（如「预计提升客单价15-20元」）
3. 归因必须到具体的时段/品类/人员层面
"""

        content, tokens = self.chat(
            system_prompt="你是一名实体店铺经营分析专家，擅长从数据中发现问题和机会。所有分析必须包含行业基准对比。",
            user_message=user_msg,
        )

        return {
            "status": "success",
            "analysis": content,
            "tokens_used": tokens,
        }

    def _handle_daily_report(self, task: dict, user_id: str = "") -> dict:
        from datetime import date
        today = date.today().isoformat()
        cfg = self._get_user_config(user_id)
        genome = get_genome(cfg.get("type", "custom"))

        data_section = task.get("data", "")

        region_context = self._get_region_context(cfg)

        user_msg = STORE_DAILY_REPORT_PROMPT.format(
            store_name=cfg.get("name", "未命名店铺"),
            date=task.get("date", today),
            weather=task.get("weather", "未知"),
            data_section=data_section,
            region_context=region_context,
        )

        content, tokens = self.chat(
            system_prompt="你是一名实体店铺店长，每天撰写经营日报。",
            user_message=user_msg,
        )

        return {
            "status": "success",
            "report": content,
            "tokens_used": tokens,
        }

    def _get_region_context(self, cfg: dict, products: str = "") -> str:
        """获取区域上下文文本，用于注入 Prompt。
        
        尝试从地址提取区域名，调用高德 API 获取本地化数据包。
        失败时返回空字符串，不阻塞主流程。
        """
        address = cfg.get("address", "")
        city = _extract_city_from_address(address)
        region_name = _extract_region_name(address, city)
        
        if not region_name:
            return "（暂无本地化数据，请补充店铺地址后获取更精准的本地化文案）"
        
        try:
            ctx = enrich_region_sync(
                region_name=region_name,
                store_type=cfg.get("type", ""),
                products=products or cfg.get("products", ""),
                use_cache=True,
            )
            if ctx and not ctx.is_empty:
                return ctx.to_prompt_string()
        except Exception as e:
            logger.warning(f"[StoreManager] 区域上下文获取失败: {e}")
        
        return "（暂无本地化数据，请补充店铺地址后获取更精准的本地化文案）"

    def _handle_marketing(self, task: dict, user_id: str = "") -> dict:
        cfg = self._get_user_config(user_id)
        store_type = cfg.get("type", "custom")
        genome = get_genome(store_type)
        scenario = task.get("scenario", "产品推荐")
        topic = task.get("topic", "")
        audience = task.get("audience", "周边顾客")
        channel = task.get("channel", "朋友圈")

        format_map = {
            "朋友圈": "150-300字，1个emoji，结尾互动提问",
            "公众号": "800-1500字，有开头钩子、3个小标题、结尾行动引导",
            "短视频脚本": "60秒结构：5s钩子+15s痛点+30s解决方案+10s行动号召",
            "海报文案": "标题10字内+副标题15字+3个卖点（每个8字）+二维码引导",
            "小红书": "口语化种草文，300-500字，带话题标签，多用\"我\"视角",
            "大众点评": "突出环境/服务/性价比，200-400字，带具体场景描写",
        }
        format_req = format_map.get(channel, "300-500字营销文案")

        products = ", ".join(genome.subcategories[:5] if genome.subcategories else [cfg.get("products", "各类产品")])
        address = cfg.get("address", "")
        city = _extract_city_from_address(address)
        region_context = self._get_region_context(cfg, products)

        user_msg = STORE_MARKETING_PROMPT.format(
            store_name=cfg.get("name", "未命名店铺"),
            store_type=genome.name,
            products=products,
            address=address,
            city=city,
            location_feature=cfg.get("location_feature", ""),
            region_context=region_context,
            scenario=scenario,
            topic=topic or f"为{cfg.get('name', '本店')}撰写{scenario}营销内容",
            audience=audience,
            channel=channel,
            format_requirements=format_req,
        )

        content, tokens = self.chat(
            system_prompt="你是一名实体店铺营销策划专家，擅长创作高转化的营销文案。你必须严格使用用户提供的真实店铺信息，绝不编造虚构数据。",
            user_message=user_msg,
        )

        return {
            "status": "success",
            "content": content,
            "scenario": scenario,
            "channel": channel,
            "tokens_used": tokens,
        }
