"""知识库中枢 - RAG检索增强生成引擎 v2.0

将向量检索结果注入AI对话，并在检索前加载行业基因基准数据。
硬性要求：所有AI输出必须包含对比数据（如"您的翻台率 2.1，低于周边均值 2.8"）。
"""

from typing import Any

from loguru import logger

from src.core import BaseSoldier
from src.knowledge.vector_store import VectorStore
from config.industry_genome import get_genome, IndustryGenome

RAG_SYSTEM_PROMPT = """你是一个基于知识库的专业回答助手。请根据提供的参考文档回答用户问题。

## 规则
1. **优先使用知识库**：回答应基于[参考文档]中的内容
2. **标注来源**：使用知识库中的信息时，注明来源
3. **诚实边界**：如果知识库内容不足以回答，请明确说"知识库中暂无相关信息"
4. **补充专业知识**：在知识库基础上可以补充你的专业知识，但要区分明确

{industry_context}

## 当前知识库内容
{context}

---
现在请回答用户的问题。"""


RAG_INDUSTRY_PROMPT = """## 行业专业参照（{industry_name}）
以下为该行业的基准数据，回答经营相关问题时必须引用对比：

{benchmarks}

## 行业红线预警
{red_flags}

## 专业要求
- 所有涉及经营指标的回答必须包含 "您的XX为{实际值}，{对比关系}行业{等级}{基准值}"
- 建议必须可量化，不能泛泛而谈
- 引用具体行业数据增强说服力"""


class RAGEngine(BaseSoldier):
    """RAG增强生成引擎 v2.0 - 行业基因组增强版

    在执行检索前，先加载对应行业的基准数据，
    确保所有AI输出包含对比数据。

    使用示例：
        engine = RAGEngine()
        engine.set_industry("restaurant")  # 加载餐饮行业基准
        answer = engine.ask("如何提升翻台率？")
    """

    name = "知识库-检索增强官"
    role = "knowledge_rag"
    temperature = 0.5
    max_tokens = 2000

    def __init__(self) -> None:
        super().__init__()
        self.vector_store = VectorStore()
        self._default_top_k = 5
        self._genome: IndustryGenome | None = None
        self._industry_context: str = ""

    def set_industry(self, store_type: str) -> IndustryGenome:
        """设置行业上下文，加载对应基因组"""
        self._genome = get_genome(store_type)
        self._industry_context = RAG_INDUSTRY_PROMPT.format(
            industry_name=self._genome.name,
            benchmarks=self._genome.format_benchmarks(),
            red_flags=self._genome.format_red_flags(),
        )
        logger.info(f"[RAG] 已加载行业上下文: {self._genome.name}")
        return self._genome

    def load_knowledge(self, directory: str) -> int:
        """从文件夹加载知识"""
        return self.vector_store.load_from_files(directory)

    def add_knowledge(self, text: str, metadata: dict[str, Any] | None = None) -> None:
        """添加一条知识"""
        self.vector_store.add_texts([text], [metadata or {}])

    def search_knowledge(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """纯检索（不用AI）"""
        return self.vector_store.search(query, top_k)

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """RAG问答

        Args:
            task: {
                "question": str,          # 用户问题
                "top_k": int,             # 检索数量（可选，默认5）
                "store_type": str,        # 行业类型（可选，自动加载基因组）
                "industry_context": str,  # 额外行业上下文（可选）
            }

        Returns:
            {"answer": str, "sources": list, "tokens_used": int, "context_count": int}
        """
        question = task.get("question", "")
        top_k = task.get("top_k", self._default_top_k)
        store_type = task.get("store_type", "")

        if not question:
            return {"answer": "请提供一个问题", "sources": [], "tokens_used": 0}

        # 0. 自动加载行业基因组（如果提供了store_type）
        if store_type and (self._genome is None or self._genome.id != store_type):
            self.set_industry(store_type)

        # 1. 检索相关知识
        results = self.vector_store.search(question, top_k)

        # 2. 构建知识库上下文
        if results:
            context_parts: list[str] = []
            for i, r in enumerate(results, 1):
                source = r["metadata"].get("source", r["metadata"].get("filename", "未知来源"))
                context_parts.append(f"[文档{i} | 来源: {source}]\n{r['content']}\n")
            context = "\n---\n".join(context_parts)
        else:
            context = "（知识库中暂无相关文档）"

        # 3. 行业基因组上下文注入
        industry_ctx = self._industry_context or ""
        extra_ctx = task.get("industry_context", "")
        if extra_ctx and not industry_ctx:
            industry_ctx = extra_ctx

        # 4. AI生成回答
        system_prompt = RAG_SYSTEM_PROMPT.format(
            context=context,
            industry_context=industry_ctx,
        )

        logger.info(f"[RAG] 检索到 {len(results)} 条相关文档, 行业: {self._genome.name if self._genome else '无'}, 问题: {question[:50]}...")
        answer, tokens = self.chat(system_prompt, question)

        return {
            "answer": answer,
            "sources": [
                {"id": r["id"], "source": r["metadata"].get("source", ""), "distance": r["distance"]}
                for r in results
            ],
            "tokens_used": tokens,
            "context_count": len(results),
        }

    def ask(self, question: str, top_k: int = 5, store_type: str = "") -> str:
        """快捷方法：直接提问获取回答"""
        result = self.execute({"question": question, "top_k": top_k, "store_type": store_type})
        return result["answer"]

    def get_status(self) -> dict[str, Any]:
        """获取知识库状态"""
        status = self.vector_store.get_status()
        if self._genome:
            status["industry"] = self._genome.name
            status["industry_id"] = self._genome.id
        return status


# ====== 使用示例 ======
if __name__ == "__main__":
    engine = RAGEngine()

    # 添加示例知识
    engine.add_knowledge(
        "企业AI改革三步法：第一步诊断（找出效率瓶颈），第二步试点（选一个环节做MVP），第三步推广（全公司复制）。",
        {"source": "内部方法论", "version": "1.0"},
    )
    engine.add_knowledge(
        "DeepSeek API定价：输入1元/百万tokens，输出2元/百万tokens。相比OpenAI GPT-4节省约95%成本。",
        {"source": "DeepSeek官网", "date": "2024"},
    )

    # 提问
    print("=" * 60)
    print("🧠 RAG引擎测试")
    print("=" * 60)

    questions = [
        "企业AI改革应该怎么开始？",
        "DeepSeek的API价格是多少？",
        "用RAG有什么好处？",  # 知识库外的提问
    ]

    for q in questions:
        print(f"\n❓ {q}")
        answer = engine.ask(q)
        print(f"🤖 {answer[:200]}...")
