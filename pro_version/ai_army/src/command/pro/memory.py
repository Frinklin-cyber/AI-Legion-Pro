"""店铺长期记忆模块（Pro 版 / AI 店长）

基于现有 ChromaDB（knowledge 模块的 VectorStore），按 store_id 分 collection 持久化：
- 历史诊断报告
- 过往生成文案
- 老板改稿记录 / 最终确认版本

每次编排前注入最近 N 条上下文，让 AI 店长"记得这家店"。
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from src.knowledge.vector_store import VectorStore


def _collection_name(store_id: str) -> str:
    """店铺专属 collection 名（前缀避免与全局知识库冲突）"""
    return f"store_memory_{store_id}"


class StoreMemory:
    """店铺长期记忆（ChromaDB 按 store_id 隔离）"""

    def __init__(self, store_id: str = "") -> None:
        self.store_id = store_id
        self._store: VectorStore | None = None

    # ── 底层访问（懒加载 VectorStore）──────────────
    def _get_store(self) -> VectorStore:
        if self._store is None or self._store.collection_name != _collection_name(self.store_id):
            self._store = VectorStore(collection_name=_collection_name(self.store_id))
        return self._store

    # ── 写入 ──────────────────────────────────────
    def save(self, store_id: str, doc_type: str, content: str,
             metadata: dict[str, Any] | None = None) -> None:
        """保存一条店铺记忆

        Args:
            store_id: 店铺 ID
            doc_type: 文档类型（diagnosis/content/revised/final）
            content:  文本内容
            metadata: 附加元数据（如 goal / created_at）
        """
        self.store_id = store_id
        meta = dict(metadata or {})
        meta["store_id"] = store_id
        meta["doc_type"] = doc_type
        self._get_store().add_texts(
            texts=[content],
            metadata=[meta],
        )
        logger.info(f"[记忆] 店铺 {store_id} 已保存 {doc_type} 记忆")

    # ── 检索 ──────────────────────────────────────
    def retrieve(self, store_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """检索店铺历史记忆，供编排器注入上下文"""
        self.store_id = store_id
        try:
            results = self._get_store().search(query, top_k)
            return [
                {
                    "content": r["content"],
                    "doc_type": r["metadata"].get("doc_type", ""),
                    "created_at": r["metadata"].get("created_at", ""),
                    "distance": r["distance"],
                }
                for r in results
            ]
        except Exception as e:
            logger.warning(f"[记忆] 检索失败（可能无历史）：{e}")
            return []

    def build_context(self, store_id: str, goal: str, top_k: int = 5) -> str:
        """构建注入 AI 店长 prompt 的店铺历史上下文文本"""
        memories = self.retrieve(store_id, goal, top_k)
        if not memories:
            return "（该店铺暂无历史记忆）"
        parts = [f"[历史记忆 {i + 1} | {m['doc_type']}]\n{m['content']}" for i, m in enumerate(memories)]
        return "\n---\n".join(parts)

    # ── 状态 ──────────────────────────────────────
    def status(self, store_id: str) -> dict[str, Any]:
        """记忆库状态"""
        self.store_id = store_id
        try:
            status = self._get_store().get_status()
            return {
                "store_id": store_id,
                "total_memories": status.get("total_documents", 0),
            }
        except Exception as e:
            logger.warning(f"[记忆] 状态查询失败：{e}")
            return {"store_id": store_id, "total_memories": 0, "error": str(e)}


# 全局单例
store_memory = StoreMemory()
