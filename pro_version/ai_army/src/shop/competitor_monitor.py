"""本地情报 (LocalIntel) v4.0

监控周边竞品动态：新店入驻、价格变化、促销活动、差评预警。
支持手动输入情报 + AI分析生成竞品报告。
v4.0: 支持多用户隔离。
"""

from typing import Any
from loguru import logger

from src.core import BaseSoldier
from src.shop.store_prompts import COMPETITOR_INTEL_PROMPT, NEARBY_COMPETITOR_SEARCH_PROMPT, MANUAL_COMPETITOR_ANALYSIS_PROMPT
from config.store_templates import get_store_type, get_competitor_focus, get_search_radius


class LocalIntel(BaseSoldier):
    """本地情报官 - 监控周边竞品、分析商圈动态"""

    name = "本地情报官"
    role = "shop_local_intel"
    temperature = 0.5
    max_tokens = 2500

    def __init__(self) -> None:
        super().__init__()
        self._user_configs: dict[str, dict] = {}  # v4.0: user_id -> config
        self._load_all_configs()

    def _config_path(self) -> str:
        """v4.0: 多用户配置文件路径"""
        import os
        return os.path.join(os.path.dirname(__file__), "..", "..", "data", "store_configs.json")

    def _load_all_configs(self):
        """v4.0: 加载所有用户配置"""
        import os
        import json
        config_path = self._config_path()
        old_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "store_config.json")
        # 迁移旧格式
        if os.path.exists(old_path) and not os.path.exists(config_path):
            try:
                with open(old_path, "r", encoding="utf-8") as f:
                    old_config = json.load(f)
                if old_config:
                    self._user_configs = {"_migrated": old_config}
                    os.makedirs(os.path.dirname(config_path), exist_ok=True)
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

    def get_config_for_user(self, user_id: str) -> dict:
        """v4.0: 获取指定用户的店铺配置"""
        if user_id and user_id in self._user_configs:
            return self._user_configs[user_id]
        return {}

    def set_config_for_user(self, config: dict, user_id: str):
        """v4.0: 设置指定用户的店铺配置"""
        if not user_id:
            return
        if user_id not in self._user_configs:
            self._user_configs[user_id] = {}
        self._user_configs[user_id].update(config)
        # 持久化
        import os
        import json
        config_path = self._config_path()
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self._user_configs, f, ensure_ascii=False, indent=2)

    def _get_config(self, user_id: str = "") -> dict:
        """获取店铺配置，优先使用用户隔离配置"""
        if user_id and user_id in self._user_configs:
            return self._user_configs[user_id]
        # 回退：优先 web_dashboard，再取第一个配置
        if "web_dashboard" in self._user_configs:
            return self._user_configs["web_dashboard"]
        if self._user_configs:
            first = next(iter(self._user_configs.values()))
            if isinstance(first, dict):
                return first
        return {}

    def _get_store_type_id(self, task: dict, user_id: str = "") -> str:
        """获取行业类型ID：优先 task > 用户配置 > custom"""
        return task.get("store_type") or self._get_config(user_id).get("type", "custom")

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """执行竞品分析

        task types:
        - analyze: 分析竞品情报
        - watchlist: 获取竞品监控清单
        - report: 生成竞品分析报告
        - search_nearby: 基于地理位置搜索周边竞品（自动POI + AI分析）
        - search_nearby_manual: 基于用户手动输入的周边商家列表做AI分析
        
        支持 v4.0 多用户隔离，通过 task 中的 user_id 区分用户。
        """
        task_type = task.get("type", "analyze")
        user_id = task.get("user_id", "")

        if task_type == "analyze":
            return self._handle_analyze(task, user_id)
        elif task_type == "watchlist":
            return self._handle_watchlist(task, user_id)
        elif task_type == "report":
            return self._handle_report(task, user_id)
        elif task_type == "search_nearby":
            return self._handle_search_nearby(task, user_id)
        elif task_type == "search_nearby_manual":
            return self._handle_search_nearby_manual(task, user_id)
        else:
            return {"status": "error", "message": f"未知任务类型: {task_type}"}

    def _handle_analyze(self, task: dict, user_id: str = "") -> dict:
        """分析竞品情报"""
        cfg = self._get_config(user_id)
        store_type = cfg.get("type", "custom")
        tpl = get_store_type(store_type)

        focus_list = get_competitor_focus(store_type)
        focus_text = "\n".join([f"{i+1}. {f}" for i, f in enumerate(focus_list)])

        competitor_data = task.get("data", task.get("question", ""))
        if isinstance(competitor_data, dict):
            import json
            competitor_data = json.dumps(competitor_data, ensure_ascii=False, indent=2)
        competitor_data = str(competitor_data)

        user_msg = COMPETITOR_INTEL_PROMPT.format(
            store_name=cfg.get("name", "未命名店铺"),
            store_type=tpl["name"] if tpl else store_type,
            location=cfg.get("address", "未知位置"),
            competitor_data=competitor_data or "暂无竞品数据，请基于日常观察做竞品分析建议",
            focus_dimensions=focus_text,
        )

        content, tokens = self.chat(
            system_prompt=(
                "你是一名商业情报分析专家，擅长从竞品信息中发现威胁和机会。"
                "你必须严格基于用户提供的数据做分析，不得编造虚构信息。"
            ),
            user_message=user_msg,
        )

        return {
            "status": "success",
            "analysis": content,
            "tokens_used": tokens,
        }

    def _handle_watchlist(self, task: dict, user_id: str = "") -> dict:
        """获取竞品监控清单"""
        cfg = self._get_config(user_id)
        store_type = cfg.get("type", "custom")
        tpl = get_store_type(store_type)
        focus = get_competitor_focus(store_type)

        return {
            "status": "success",
            "store_type": tpl["name"] if tpl else store_type,
            "store_name": cfg.get("name", "未命名店铺"),
            "monitoring_items": focus,
            "suggested_frequency": "每日检查线上评分，每周实地观察1-2次，每月全面竞品分析1次",
        }

    def _handle_search_nearby(self, task: dict, user_id: str = "") -> dict:
        """基于地理位置搜索周边竞品

        先通过高德地图周边搜索 API 获取真实 POI 数据，
        再交给 AI 进行竞品分析（不再让 AI 凭空捏造竞品）。

        支持 task 中传入 store_type 和 products 来指定行业，
        如果不传则使用已保存的店铺配置。
        """
        cfg = self._get_config(user_id)
        # 行业类型：优先使用 task 传入的，其次使用已保存的配置
        store_type_id = task.get("store_type") or cfg.get("type", "custom")
        tpl = get_store_type(store_type_id)
        store_type_name = tpl["name"] if tpl else store_type_id

        # 产品/服务描述：优先使用 task 传入的，其次使用已保存的配置
        products = task.get("products") or cfg.get("products") or "各类产品/服务"

        # 子分类：从 task 传入或从模板子分类中取第一个
        subcategory = task.get("subcategory", "")
        if not subcategory and tpl:
            subcats = tpl.get("subcategories", [])
            subcategory = subcats[0] if subcats else ""

        # 店铺名称：支持 task 传入临时覆盖，避免旧名称误导 AI
        store_name = task.get("store_name") or cfg.get("name", "未命名店铺")
        # 如果 store_name 明显与当前搜索类型不匹配（如含"槟榔"但搜"农业"），
        # 使用 products 作为描述性名称，避免 AI 误判
        if products and products not in store_name:
            # 不强制改名，但在 prompt 中明确说明业务类型
            pass

        # 获取坐标和半径
        latitude = task.get("latitude", cfg.get("latitude", 0))
        longitude = task.get("longitude", cfg.get("longitude", 0))
        radius = task.get("radius", cfg.get("search_radius", get_search_radius(store_type_id)))

        if not latitude or not longitude:
            return {
                "status": "error",
                "message": "缺少位置坐标，请先在店铺信息中设置定位（纬度/经度）",
            }

        # ============================================================
        # 步骤A：调用高德地图周边搜索 API，获取真实 POI 数据
        # ============================================================
        from src.shop.geo import search_nearby_competitors_sync, _format_poi_for_analysis

        # 确定 POI 搜索关键词：优先用用户输入的具体产品，其次用细分品类
        poi_keywords = products if products and products != "各类产品/服务" else ""
        if not poi_keywords and subcategory:
            poi_keywords = subcategory

        try:
            real_pois = search_nearby_competitors_sync(
                lat=latitude,
                lng=longitude,
                radius=radius,
                store_type=store_type_id,
                keywords=poi_keywords,
                max_results=20,
            )
        except Exception as e:
            logger.warning(f"[竞品搜索] POI API 调用失败: {e}")
            real_pois = []

        poi_data_text = _format_poi_for_analysis(real_pois, latitude, longitude)
        poi_count = len(real_pois)

        # ============================================================
        # 步骤B：无数据 → 直接返回，不调用 LLM（防止 AI 编造）
        # ============================================================
        if poi_count == 0:
            return {
                "status": "no_data",
                "analysis": "",
                "message": (
                    f"在以「{cfg.get('name', '店铺')}」为中心、半径{radius}米的范围内，"
                    f"高德地图未返回任何商家POI数据。\n\n"
                    f"**可能原因：**\n"
                    f"1. 您所在的区域（如县城、乡镇）数字地图覆盖不全\n"
                    f"2. 店铺坐标可能不够精确，请检查经纬度\n"
                    f"3. 周边确实商家密度极低\n\n"
                    f"**建议：**\n"
                    f"请实地观察店铺周边，记录您看到的真实商家，然后通过「手动输入竞品」功能提交。"
                    f"这样AI可以基于您实地观察的真实数据做分析，而不是凭空猜测。\n\n"
                    f"**手动输入格式：**\n"
                    f"每行一个商家，格式：`商家名称，类型，大约距离，人均消费，简单描述`\n"
                    f"例：\n"
                    f"  蜜雪冰城，奶茶饮品，100米，8元，学生多、出杯快\n"
                    f"  兰州拉面，快餐面馆，80米，15元，午市爆满\n"
                    f"  零食很忙，零食零售，200米，25元，新开业、装修亮眼"
                ),
                "tokens_used": 0,
                "search_params": {
                    "latitude": latitude,
                    "longitude": longitude,
                    "radius": radius,
                },
                "industry": {
                    "type": store_type_name,
                    "type_id": store_type_id,
                    "subcategory": subcategory,
                },
                "poi_count": 0,
            }

        # ============================================================
        # 步骤C：有数据 → 将真实 POI 数据 + 行业上下文交给 AI 分析
        # ============================================================

        # 获取竞品关注维度
        focus_list = get_competitor_focus(store_type_id)
        focus_text = "\n".join([f"  {i+1}. {f}" for i, f in enumerate(focus_list)])

        # 构建行业上下文描述，帮助AI更准确地理解该行业
        industry_context = self._build_industry_context(
            store_type_name, subcategory, products, tpl
        )

        user_msg = NEARBY_COMPETITOR_SEARCH_PROMPT.format(
            store_name=store_name,
            store_type=store_type_name,
            products=products,
            address=cfg.get("address", "未知地址"),
            latitude=latitude,
            longitude=longitude,
            radius=radius,
            focus_dimensions=focus_text,
            subcategory=subcategory or products,
            industry_context=industry_context,
            poi_data=poi_data_text,
            poi_count=poi_count,
        )

        content, tokens = self.chat(
            system_prompt=(
                "你是一名商业竞争分析专家。"
                "你必须严格基于提供的真实POI数据做分析，不得编造任何虚构商家。"
                "如果地址中包含地标名称（如'电影院''商场'），这只代表位置参照物，"
                "不能假设该地标仍在运营或由此推断客群特征。"
                "每个判断必须有POI数据支撑。"
                "重要：不要根据店铺名称推断业务类型，当前分析以 'products' 和 'store_type' 为准。"
            ),
            user_message=user_msg,
        )

        return {
            "status": "success",
            "analysis": content,
            "tokens_used": tokens,
            "search_params": {
                "latitude": latitude,
                "longitude": longitude,
                "radius": radius,
            },
            "industry": {
                "type": store_type_name,
                "type_id": store_type_id,
                "subcategory": subcategory,
            },
            "poi_count": poi_count,
        }

    def _build_industry_context(
        self, store_type_name: str, subcategory: str, products: str, tpl: dict | None
    ) -> str:
        """构建行业上下文描述，帮助AI精准定位分析方向"""
        if tpl is None:
            return f"这是一个{store_type_name}行业的店铺，主营{products}。请根据该行业的通用商业逻辑进行分析。"

        # 提取KPI指标名作为行业关键词
        kpi_keys = list(tpl.get("kpi_fields", {}).keys())[:5]
        kpi_text = "、".join(kpi_keys) if kpi_keys else ""

        # 提取营销场景作为行业特征
        scenarios = tpl.get("marketing_scenarios", [])
        scenario_keywords = "、".join([s["name"] for s in scenarios[:3]]) if scenarios else ""

        parts = [f"这是一个{store_type_name}行业的店铺"]
        if subcategory:
            parts.append(f"细分品类为「{subcategory}」")
        if products:
            parts.append(f"主营{products}")
        if kpi_text:
            parts.append(f"该行业的核心经营指标包括：{kpi_text}")
        if scenario_keywords:
            parts.append(f"典型的经营场景有：{scenario_keywords}")

        return "；".join(parts) + "。请基于此行业背景进行竞品分析。"

    def _handle_report(self, task: dict, user_id: str = "") -> dict:
        """生成竞品分析报告"""
        result = self._handle_analyze(task, user_id)
        return result

    def _handle_search_nearby_manual(self, task: dict, user_id: str = "") -> dict:
        """基于用户手动输入的周边商家列表做 AI 竞品分析

        task 中需要包含:
            - competitors: str，用户输入的商家列表（自由文本）
            - store_type, products, subcategory（可选，覆盖店铺配置）
        """
        cfg = self._get_config(user_id)
        store_type_id = task.get("store_type") or cfg.get("type", "custom")
        tpl = get_store_type(store_type_id)
        store_type_name = tpl["name"] if tpl else store_type_id

        products = task.get("products") or cfg.get("products") or "各类产品/服务"
        subcategory = task.get("subcategory", "")
        if not subcategory and tpl:
            subcats = tpl.get("subcategories", [])
            subcategory = subcats[0] if subcats else ""

        # 店铺名称支持 task 覆盖
        store_name = task.get("store_name") or cfg.get("name", "未命名店铺")

        competitor_text = task.get("competitors", "").strip()
        if not competitor_text:
            return {
                "status": "error",
                "message": (
                    "请提供您实地观察到的周边商家信息。\n\n"
                    "格式参考（每行一个商家）：\n"
                    "  蜜雪冰城，奶茶饮品，100米，8元，学生多、出杯快\n"
                    "  兰州拉面，快餐面馆，80米，15元，午市爆满\n"
                    "  零食很忙，零食零售，200米，25元，新开业、装修亮眼"
                ),
            }

        # 格式化用户输入为结构化表格
        competitor_lines = competitor_text.split("\n")
        formatted = [
            f"以下为店主实地观察录入的周边 {len(competitor_lines)} 家商家：\n",
            "| # | 商家名称 | 类型 | 距我店 | 人均 | 店主备注 |",
            "|---|---|---|---|---|---|",
        ]
        for i, line in enumerate(competitor_lines, 1):
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("，")]
            name = parts[0] if len(parts) > 0 else "-"
            ptype = parts[1] if len(parts) > 1 else "-"
            dist = parts[2] if len(parts) > 2 else "-"
            price = parts[3] if len(parts) > 3 else "-"
            note = parts[4] if len(parts) > 4 else "-"
            formatted.append(f"| {i} | {name} | {ptype} | {dist} | {price} | {note} |")

        competitor_list = "\n".join(formatted)

        # 获取竞品关注维度
        focus_list = get_competitor_focus(store_type_id)
        focus_text = "\n".join([f"  {i+1}. {f}" for i, f in enumerate(focus_list)])

        # 构建行业上下文
        industry_context = self._build_industry_context(
            store_type_name, subcategory, products, tpl
        )

        user_msg = MANUAL_COMPETITOR_ANALYSIS_PROMPT.format(
            store_name=store_name,
            store_type=store_type_name,
            products=products,
            address=cfg.get("address", "未知地址"),
            focus_dimensions=focus_text,
            subcategory=subcategory or products,
            industry_context=industry_context,
            competitor_list=competitor_list,
        )

        content, tokens = self.chat(
            system_prompt=(
                "你是一名商业竞争分析专家。"
                "你必须严格基于店主提供的实地观察数据做分析，不得编造任何不存在的商家。"
                "如果数据不足，如实说明局限性。"
                "重要：不要根据店铺名称推断业务类型，当前分析以 'products' 和 'store_type' 为准。"
            ),
            user_message=user_msg,
        )

        return {
            "status": "success",
            "analysis": content,
            "tokens_used": tokens,
            "data_source": "manual_input",
            "competitor_count": len(competitor_lines),
        }
