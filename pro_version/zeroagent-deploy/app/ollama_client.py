"""
ollama_client.py
本地 Ollama 客户端（数据不出域）。
- embedding：/api/embed（自动回退旧版 /api/embeddings）
- 生成：/api/generate（非对话单次生成）
- 对话：/api/chat（Persona 驱动，支持 system/user messages）
Ollama 不可用时抛出 OllamaUnavailableError，由 API 层转为友好 503。
"""

import requests

from .config import OLLAMA_HOST, EMBED_MODEL, LLM_MODEL, TEMPERATURE, REQUEST_TIMEOUT


class OllamaUnavailableError(Exception):
    """Ollama 服务未运行 / 模型缺失 / 网络不可达"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class OllamaClient:
    def __init__(
        self,
        host: str = OLLAMA_HOST,
        embed_model: str = EMBED_MODEL,
        llm_model: str = LLM_MODEL,
        temperature: float = TEMPERATURE,
        timeout: int = REQUEST_TIMEOUT,
    ):
        self.host = host.rstrip("/")
        self.embed_model = embed_model
        self.llm_model = llm_model
        self.temperature = temperature
        self.timeout = timeout

    # ─────────────────────────────────────────
    # 可用性
    # ─────────────────────────────────────────
    def is_available(self) -> bool:
        """Ollama 服务是否在运行"""
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def has_model(self, model: str) -> bool:
        """指定模型是否已拉取（忽略 :latest 后缀）"""
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            want = model.split(":")[0]
            names = [t.get("name", "") for t in resp.json().get("models", [])]
            return any(n.split(":")[0] == want for n in names)
        except (requests.RequestException, ValueError):
            return False

    def check_ready(self) -> str:
        """
        返回就绪状态描述：
        - ""                    一切正常
        - "embed"               embedding 模型缺失
        - "llm"                 LLM 模型缺失
        - "unavailable"         Ollama 服务未运行
        """
        if not self.is_available():
            return "unavailable"
        if not self.has_model(self.embed_model):
            return "embed"
        if not self.has_model(self.llm_model):
            return "llm"
        return ""

    # ─────────────────────────────────────────
    # Embedding
    # ─────────────────────────────────────────
    def embed_texts(self, texts) -> list:
        """
        批量向量化。新版 Ollama 走 /api/embed；旧版回退 /api/embeddings。
        返回与输入等长的二维 float 列表。
        """
        if isinstance(texts, str):
            texts = [texts]
        texts = [t for t in texts]
        if not texts:
            return []

        # 新版 API
        try:
            resp = requests.post(
                f"{self.host}/api/embed",
                json={"model": self.embed_model, "input": texts},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()["embeddings"]
        except requests.exceptions.ConnectionError:
            raise OllamaUnavailableError(
                f"无法连接本地模型服务 ({self.host})，请确认已启动: ollama serve"
            )
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 404:
                # 旧版 Ollama，逐条调用 /api/embeddings
                return self._embed_legacy(texts)
            raise OllamaUnavailableError(f"向量化失败 (HTTP {resp.status_code}): {e}")
        except (KeyError, ValueError) as e:
            raise OllamaUnavailableError(f"向量化返回格式异常: {e}")

    def _embed_legacy(self, texts) -> list:
        embeddings = []
        for t in texts:
            try:
                resp = requests.post(
                    f"{self.host}/api/embeddings",
                    json={"model": self.embed_model, "prompt": t},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                embeddings.append(resp.json()["embedding"])
            except requests.exceptions.ConnectionError:
                raise OllamaUnavailableError(
                    f"无法连接本地模型服务 ({self.host})，请确认已启动: ollama serve"
                )
        return embeddings

    # ─────────────────────────────────────────
    # 生成（RAG 回答）
    # ─────────────────────────────────────────
    def generate(self, prompt: str, system: str = None, temperature: float = None) -> str:
        """单次生成，不走对话历史。temperature 默认 0.1（RAG 要求低随机性）。"""
        payload = {
            "model": self.llm_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature if temperature is not None else self.temperature,
                "num_ctx": 8192,
            },
        }
        if system:
            payload["system"] = system
        try:
            resp = requests.post(f"{self.host}/api/generate", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("response", "")
        except requests.exceptions.ConnectionError:
            raise OllamaUnavailableError(
                f"无法连接本地模型服务 ({self.host})，请确认已启动: ollama serve"
            )
        except requests.exceptions.HTTPError as e:
            raise OllamaUnavailableError(f"模型生成失败 (HTTP {resp.status_code}): {e}")

    # ─────────────────────────────────────────
    # 对话（Persona 驱动，/api/chat）
    # ─────────────────────────────────────────
    def chat(self, messages: list, temperature: float = None) -> str:
        """
        对话式生成。messages 形如 [{"role": "system", "content": ...},
                                   {"role": "user", "content": ...}]。
        返回模型回复文本。
        """
        payload = {
            "model": self.llm_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature if temperature is not None else self.temperature,
                "num_ctx": 8192,
            },
        }
        try:
            resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")
        except requests.exceptions.ConnectionError:
            raise OllamaUnavailableError(
                f"无法连接本地模型服务 ({self.host})，请确认已启动: ollama serve"
            )
        except requests.exceptions.HTTPError as e:
            raise OllamaUnavailableError(f"模型对话失败 (HTTP {resp.status_code}): {e}")
