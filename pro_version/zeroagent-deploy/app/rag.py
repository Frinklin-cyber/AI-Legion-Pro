"""
rag.py
RAG 编排（人格驱动版）：
- index_file：提取 → 切分 → 向量化 → 增量入库
- generate_answer：问题向量化 → top-k 检索 → 将"人格 system prompt + 用户问题 + 参考文档"
  交给本地模型生成回答。不再做状态判定 / 关键词匹配 / 兜底模板——
  检索到什么就给什么，模型依据人格自主决定如何回应（引用 / 说明不确定 / 坦诚无资料并给方向）。
- retrieve：仅检索（供 Agent 编排器复用知识库）
"""

from pathlib import Path

from .chunker import chunk_pages
from .extractor import extract_document
from .vector_store import VectorStore
from .ollama_client import OllamaClient
from .persona import ZEROagentPersona


class RAGEngine:
    def __init__(self, ollama: OllamaClient, store: VectorStore,
                 chunk_size: int = 500, chunk_overlap: int = 50, top_k: int = 5):
        self.ollama = ollama
        self.store = store
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k

    # ─────────────────────────────────────────
    # 文档入库
    # ─────────────────────────────────────────
    def index_file(self, file_path) -> dict:
        """提取 → 切分 → 向量化 → 增量入库。返回 {source_file, chunks_indexed}。"""
        path = Path(file_path)
        pages = extract_document(path)
        chunks = chunk_pages(pages, path.name, self.chunk_size, self.chunk_overlap)
        if not chunks:
            raise ValueError(f"文档 {path.name} 切分后为空")

        texts = [c.text for c in chunks]
        embeddings = self.ollama.embed_texts(texts)

        # 增量更新：同一文件先删旧 chunk，再插入新 chunk
        self.store.delete_source(path.name)
        n = self.store.add_chunks(chunks, embeddings)

        return {"source_file": path.name, "chunks_indexed": n}

    # ─────────────────────────────────────────
    # 检索（不生成，供 Agent 编排器复用知识库）
    # ─────────────────────────────────────────
    def retrieve(self, question: str, top_k: int = None) -> list:
        """仅检索，返回 [{text, source_file, page_number, chunk_index, score}]"""
        q_emb = self.ollama.embed_texts([question])[0]
        return self.store.query(q_emb, top_k=top_k or self.top_k)

    # ─────────────────────────────────────────
    # 问答（人格驱动）
    # ─────────────────────────────────────────
    def ask(self, question: str) -> dict:
        """兼容别名：等价于 generate_answer。"""
        return self.generate_answer(question)

    def generate_answer(self, question: str) -> dict:
        """
        人格驱动问答。返回 {status, message, answer, references}。

        流程：检索 top-k → 组装带编号的参考文档 → 以 Persona 的 system prompt 为 messages[0]，
        用户消息 = 问题 + 参考文档（无资料时只放问题）→ 交给模型自主决定如何回答。
        模型依据人格会：引用来源 / 说明不确定程度 / 坦诚无资料并给方向，不再由代码判定。
        """
        question = question.strip()
        if not question:
            return {
                "status": "ok",
                "message": "请问你想了解什么？",
                "answer": "请问你想了解什么？",
                "references": [],
            }

        hits = self.retrieve(question, top_k=self.top_k)

        # 组装带编号的参考文档上下文
        context_parts = []
        for i, h in enumerate(hits, start=1):
            page = f"第 {h['page_number']} 页" if h["page_number"] else "无分页"
            context_parts.append(f"[{i}] 来源:{h['source_file']} {page}\n{h['text']}")
        context = "\n\n".join(context_parts)

        user_content = question
        if context:
            user_content = f"{question}\n\n参考文档：\n{context}"

        messages = [
            {"role": "system", "content": ZEROagentPersona.system_prompt()},
            {"role": "user", "content": user_content},
        ]
        answer = self.ollama.chat(messages, temperature=0.3).strip()

        references = [
            {
                "source_file": h["source_file"],
                "page_number": h["page_number"],
                "text": h["text"],
                "score": h["score"],
            }
            for h in hits
        ]
        return {
            "status": "ok",
            "message": answer,
            "answer": answer,
            "references": references,
        }
