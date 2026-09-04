"""
vector_store.py
ChromaDB 持久化向量库（./data/vectordb/）。
- 支持增量更新：同一文件重新上传时先删除旧 chunk 再插入（不重建全量索引）
- 余弦相似度检索
"""

import chromadb


class VectorStore:
    def __init__(self, path):
        path = str(path)
        import os
        os.makedirs(path, exist_ok=True)
        self._client = chromadb.PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"},
        )

    @staticmethod
    def _doc_id(source_file: str, index: int) -> str:
        return f"{source_file}::{index}"

    def delete_source(self, source_file: str):
        """增量更新：删除该文件的旧 chunk（文件不存在时静默跳过）"""
        try:
            self._collection.delete(where={"source_file": source_file})
        except Exception:
            pass

    def delete_by_source(self, source_file: str) -> int:
        """
        按元数据 source_file 删除该文档的全部向量（ChromaDB 元数据过滤删除）。
        返回实际删除的 chunk 数量；文档不存在时返回 0。
        """
        try:
            data = self._collection.get(
                where={"source_file": source_file}, include=["metadatas"]
            )
        except Exception:
            data = self._collection.get(where={"source_file": source_file})
        ids = list(data.get("ids") or [])
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def add_chunks(self, chunks, embeddings) -> int:
        """批量写入 chunk；返回写入数量。chunks 与 embeddings 等长。"""
        if not chunks:
            return 0
        ids = [self._doc_id(c.source_file, c.index) for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [
            {
                "source_file": c.source_file,
                "page_number": c.page_number,
                "chunk_index": c.index,
            }
            for c in chunks
        ]
        self._collection.upsert(
            ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
        )
        return len(chunks)

    def query(self, embedding, top_k: int = 5) -> list:
        """相似度检索，返回 [{text, source_file, page_number, chunk_index, score}]"""
        if self._collection.count() == 0:
            return []
        res = self._collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        results = []
        for doc, meta, dist in zip(docs, metas, dists):
            results.append({
                "text": doc,
                "source_file": meta.get("source_file", "unknown"),
                "page_number": meta.get("page_number", 0),
                "chunk_index": meta.get("chunk_index", 0),
                # 余弦距离 → 相似度
                "score": round(1.0 - dist, 4) if dist is not None else None,
            })
        return results

    def list_documents(self) -> list:
        """列出已索引文档及 chunk 数"""
        data = self._collection.get(include=["metadatas"])
        counts = {}
        for meta in data.get("metadatas") or []:
            sf = meta.get("source_file", "unknown")
            counts[sf] = counts.get(sf, 0) + 1
        return [{"source_file": sf, "chunk_count": n} for sf, n in sorted(counts.items())]

    def count(self) -> int:
        return self._collection.count()
