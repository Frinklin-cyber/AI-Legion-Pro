"""智能客服 (CustomerService) v4.1

自动回答顾客常见问题，支持产品咨询、价格询问、营业时间等。
基于店铺知识库 + RAG检索增强回答。
v4.0: 支持多用户隔离。
v4.1: 集成区域上下文，生成本地化客服话术。
"""

from typing import Any
from loguru import logger

from src.core import BaseSoldier
from src.shop.store_prompts import CUSTOMER_FAQ_PROMPT, STAFF_TRAINING_QA_PROMPT
from config.store_templates import get_store_type, get_faq_templates
from src.shop.region_enricher import enrich_region_sync, _extract_region_name


class CustomerService(BaseSoldier):
    """智能客服 - 自动回答顾客和店员咨询"""

    name = "智能客服"
    role = "shop_customer_service"
    temperature = 0.7
    max_tokens = 1024

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

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """执行客服咨询

        task types:
        - chat: 顾客咨询问答
        - staff_qa: 店员知识问答
        - batch: 批量FAQ生成
        
        支持 v4.0 多用户隔离，通过 task 中的 user_id 区分用户。
        """
        task_type = task.get("type", "chat")
        user_id = task.get("user_id", "")

        if task_type == "chat":
            return self._handle_chat(task, user_id)
        elif task_type == "staff_qa":
            return self._handle_staff_qa(task, user_id)
        elif task_type == "batch":
            return self._handle_batch(task, user_id)
        else:
            return {"status": "error", "message": f"未知任务类型: {task_type}"}

    def _get_config(self, user_id: str = "") -> dict:
        """获取店铺配置，优先使用用户隔离配置"""
        if user_id and user_id in self._user_configs:
            return self._user_configs[user_id]
        # 回退：优先 web_dashboard，再取第一个配置
        if "web_dashboard" in self._user_configs:
            return self._user_configs["web_dashboard"]
        if self._user_configs:
            # 回退到第一个可用的配置（兼容旧接口）
            first = next(iter(self._user_configs.values()))
            if isinstance(first, dict):
                return first
        return {}

    def _get_region_context(self, cfg: dict) -> str:
        """获取区域上下文"""
        import re
        address = cfg.get("address", "")
        m = re.match(r"^(.{2,6}(?:市|县|区))", address) if address else None
        region_name = m.group(1) if m else ""
        if not region_name:
            return "（暂无本地化数据）"
        try:
            ctx = enrich_region_sync(
                region_name=region_name,
                store_type=cfg.get("type", ""),
                products=cfg.get("products", ""),
                use_cache=True,
            )
            if ctx and not ctx.is_empty:
                return ctx.to_prompt_string()
        except Exception:
            pass
        return "（暂无本地化数据）"

    def _handle_chat(self, task: dict, user_id: str = "") -> dict:
        """处理顾客咨询"""
        question = task.get("question", "").strip()
        if not question:
            return {"status": "error", "message": "请提供顾客问题"}

        cfg = self._get_config(user_id)
        store_type = cfg.get("type", "custom")
        tpl = get_store_type(store_type)
        type_name = tpl["name"] if tpl else store_type
        region_context = self._get_region_context(cfg)

        user_msg = CUSTOMER_FAQ_PROMPT.format(
            store_name=cfg.get("name", "未命名店铺"),
            store_type=type_name,
            products=cfg.get("products", "各类产品/服务"),
            address=cfg.get("address", "请咨询门店"),
            hours=cfg.get("hours", "10:00-22:00"),
            phone=cfg.get("phone", "请咨询门店"),
            faq_knowledge=cfg.get("faq_knowledge", "") or "（暂无自定义FAQ知识）",
            customer_question=question,
            region_context=region_context,
        )

        content, tokens = self.chat(
            system_prompt="你是一位友好专业的实体店客服，擅长解答顾客关于产品、价格、服务的各种问题。",
            user_message=user_msg,
        )

        return {
            "status": "success",
            "answer": content,
            "tokens_used": tokens,
        }

    def _handle_staff_qa(self, task: dict, user_id: str = "") -> dict:
        """处理店员知识问答"""
        question = task.get("question", "").strip()
        if not question:
            return {"status": "error", "message": "请提供店员问题"}

        cfg = self._get_config(user_id)
        # 尝试从知识库检索
        knowledge = cfg.get("faq_knowledge", "") or "暂无知识库内容"
        try:
            from src.knowledge.vector_store import VectorStore
            store = VectorStore()
            results = store.search(question, top_k=3)
            if results:
                knowledge = "\n\n".join([
                    f"📎 {r.get('source', '知识库')}: {r.get('text', '')[:500]}"
                    for r in results
                ])
        except Exception:
            pass

        user_msg = STAFF_TRAINING_QA_PROMPT.format(
            knowledge_context=knowledge,
            question=question,
        )

        content, tokens = self.chat(
            system_prompt="你是一位实体店铺资深培训师，回答店员工作问题要做到：直接、具体、可操作。",
            user_message=user_msg,
        )

        return {
            "status": "success",
            "answer": content,
            "tokens_used": tokens,
        }

    def _handle_batch(self, task: dict, user_id: str = "") -> dict:
        """批量生成FAQ"""
        cfg = self._get_config(user_id)
        store_type = cfg.get("type", "custom")
        templates = get_faq_templates(store_type)

        answers = []
        total_tokens = 0

        for q in templates:
            result = self._handle_chat({"question": q}, user_id)
            if result["status"] == "success":
                answers.append({"question": q, "answer": result["answer"]})
                total_tokens += result.get("tokens_used", 0)

        return {
            "status": "success",
            "faqs": answers,
            "count": len(answers),
            "tokens_used": total_tokens,
        }
