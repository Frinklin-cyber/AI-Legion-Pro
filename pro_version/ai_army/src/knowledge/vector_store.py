"""知识库中枢 - 向量存储引擎

基于ChromaDB实现：
- 文档向量化存储
- 语义检索
- 知识库状态查询
"""

from pathlib import Path
from typing import Any

import chromadb
from loguru import logger

from config.env import CHROMA_PERSIST_DIR


class VectorStore:
    """向量数据库封装

    使用示例：
        store = VectorStore()
        store.add_texts(["文档1内容", "文档2内容"], metadata=[{...}, {...}])
        results = store.search("查询文本", top_k=5)
    """

    def __init__(self, collection_name: str = "ai_army_knowledge") -> None:
        persist_dir = Path(CHROMA_PERSIST_DIR)
        persist_dir.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(persist_dir),
        )

        # 获取或创建collection
        try:
            self.collection = self.client.get_collection(collection_name)
            logger.info(f"[向量库] 已加载collection: {collection_name}")
        except Exception:
            self.collection = self.client.create_collection(
                name=collection_name,
                metadata={"description": "AI军团知识库"},
            )
            logger.info(f"[向量库] 已创建collection: {collection_name}")

        self.collection_name = collection_name

    def add_texts(self, texts: list[str], metadata: list[dict[str, Any]] | None = None,
                  ids: list[str] | None = None) -> None:
        """添加文本到向量库

        Args:
            texts: 文本列表
            metadata: 每条文本的元数据
            ids: 文档ID列表（可选，自动生成）
        """
        if metadata is None:
            metadata = [{}] * len(texts)

        if ids is None:
            import uuid
            ids = [str(uuid.uuid4())[:12] for _ in texts]

        self.collection.add(
            documents=texts,
            metadatas=metadata,
            ids=ids,
        )
        logger.info(f"[向量库] 已添加 {len(texts)} 条文档")

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """语义搜索

        Args:
            query: 查询文本
            top_k: 返回结果数

        Returns:
            [{"content": str, "metadata": dict, "distance": float}, ...]
        """
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k,
        )

        items: list[dict[str, Any]] = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                items.append({
                    "content": doc,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0.0,
                    "id": results["ids"][0][i] if results["ids"] else "",
                })

        logger.debug(f"[向量库] 搜索 '{query[:30]}...' → {len(items)} 条结果")
        return items

    def delete_by_ids(self, ids: list[str]) -> None:
        """按ID删除文档"""
        self.collection.delete(ids=ids)
        logger.info(f"[向量库] 已删除 {len(ids)} 条文档")

    def get_status(self) -> dict[str, Any]:
        """获取知识库状态"""
        count = self.collection.count()
        return {
            "collection": self.collection_name,
            "total_documents": count,
            "persist_dir": CHROMA_PERSIST_DIR,
        }

    def clear(self) -> None:
        """清空知识库"""
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.create_collection(
            name=self.collection_name,
            metadata={"description": "AI军团知识库"},
        )
        logger.info(f"[向量库] 已清空: {self.collection_name}")

    def load_from_files(self, directory: str) -> int:
        """从文件夹批量加载文本文件到知识库

        Args:
            directory: 包含.txt/.md文件的目录

        Returns:
            加载的文件数
        """
        path = Path(directory)
        if not path.exists():
            logger.warning(f"[向量库] 目录不存在: {directory}")
            return 0

        count = 0
        for ext in ["*.txt", "*.md", "*.py"]:
            for filepath in path.rglob(ext):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()

                    if len(content.strip()) < 10:  # 跳过空文件
                        continue

                    self.add_texts(
                        texts=[content],
                        metadata=[{
                            "source": str(filepath),
                            "filename": filepath.name,
                            "type": filepath.suffix,
                        }],
                    )
                    count += 1
                except Exception as e:
                    logger.warning(f"[向量库] 加载失败 {filepath}: {e}")

        logger.info(f"[向量库] 从 {directory} 加载了 {count} 个文件")
        return count


# ====== 使用示例 ======
if __name__ == "__main__":
    store = VectorStore("test_collection")

    # 添加文档
    store.add_texts(
        texts=[
            "企业AI改革的核心是让AI成为业务的加速器而非替代品。",
            "DeepSeek是目前性价比最高的中文大模型，API价格仅为GPT-4的1/50。",
            "自动化不是一蹴而就的，需要先做MVP验证，再逐步扩展。",
        ],
        metadata=[
            {"topic": "AI改革", "author": "指挥官"},
            {"topic": "工具推荐", "author": "侦察兵"},
            {"topic": "方法论", "author": "参谋部"},
        ],
    )

    # 搜索
    results = store.search("用什么大模型性价比最高？")
    print("搜索结果：")
    for r in results:
        print(f"  [{r['metadata'].get('topic')}] {r['content'][:60]}... (距离: {r['distance']:.3f})")

    # 状态
    print(f"\n知识库状态: {store.get_status()}")
