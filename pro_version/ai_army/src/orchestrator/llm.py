"""DeepSeek LLM 客户端封装（v2.0 编排引擎专用）

支持：
- 普通文本对话 chat()（deepseek-chat）
- 结构化 JSON 输出 chat_json()（response_format=json_object + 容错解析）
- Function Calling 工具调用循环 run_with_tools()（官方推荐写法：
  messages.append(response.choices[0].message) 整体追加，自动保留 reasoning_content）
"""

import json
import re
from typing import Any, Callable

from loguru import logger
from openai import OpenAI

from config.env import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

# 快速生成 / 工具调用模型（deepseek-chat / V3）
MODEL_CHAT = "deepseek-chat"
# 复杂推理模型（deepseek-reasoner / R1；不支持 function calling，仅用于纯推理场景）
MODEL_REASON = "deepseek-reasoner"


def _extract_json(text: str) -> dict[str, Any]:
    """从 LLM 输出中稳健提取 JSON（剥掉 markdown 代码块、取首个 {..} 或 [..]）"""
    if not text:
        raise ValueError("空响应")
    t = text.strip()
    # 去掉 ```json ... ``` 包裹
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", t)
    if fence:
        t = fence.group(1).strip()
    # 尝试整体解析
    try:
        return json.loads(t)
    except Exception:
        pass
    # 提取第一个 JSON 对象
    obj = re.search(r"\{.*\}", t, re.DOTALL)
    if obj:
        try:
            return json.loads(obj.group(0))
        except Exception:
            pass
    # 提取第一个 JSON 数组
    arr = re.search(r"\[.*\]", t, re.DOTALL)
    if arr:
        try:
            val = json.loads(arr.group(0))
            return {"items": val}
        except Exception:
            pass
    raise ValueError(f"无法从响应中解析 JSON: {t[:200]}")


class LLMClient:
    """线程安全的 DeepSeek 客户端（每次调用新建 client，避免并发共享问题）"""

    def __init__(self) -> None:
        self.api_key = DEEPSEEK_API_KEY
        self.base_url = DEEPSEEK_BASE_URL
        self.model = DEEPSEEK_MODEL

    def _client(self) -> OpenAI:
        return OpenAI(api_key=self.api_key, base_url=self.base_url)

    # ── 普通文本 ──────────────────────────────────────────
    def chat(self, system: str, user: str, *, model: str | None = None,
             temperature: float = 0.7, max_tokens: int = 2600,
             history: list[dict] | None = None) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history[-8:])
        messages.append({"role": "user", "content": user})

        resp = self._client().chat.completions.create(
            model=model or self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = (resp.choices[0].message.content or "").strip()
        logger.debug(f"[orchestrator.llm] chat OK, len={len(content)}, model={model or self.model}")
        return content

    # ── 结构化 JSON ───────────────────────────────────────
    def chat_json(self, system: str, user: str, *, model: str | None = None,
                  temperature: float = 0.3, history: list[dict] | None = None,
                  fallback: dict | None = None) -> dict[str, Any]:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history[-8:])
        messages.append({"role": "user", "content": user})

        try:
            resp = self._client().chat.completions.create(
                model=model or self.model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            raw = (resp.choices[0].message.content or "").strip()
            return _extract_json(raw)
        except Exception as e:
            logger.warning(f"[orchestrator.llm] chat_json 失败: {e}")
            if fallback is not None:
                return fallback
            raise

    # ── Function Calling 工具循环 ─────────────────────────
    def run_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict],
        tool_map: dict[str, Callable],
        on_tool: Callable[[dict, Any], None] | None = None,
        *,
        max_iter: int = 6,
        history: list[dict] | None = None,
    ) -> str:
        """执行 DeepSeek 工具调用循环。

        官方推荐写法：把每次返回的 message 整体 messages.append(msg)，
        自动保留 reasoning_content，避免 400 报错。
        on_tool(tool_call_dict, result) 用于实时上报工具执行事件。
        返回最终（无 tool_calls 时）模型回答文本。
        """
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history[-6:])
        messages.append({"role": "user", "content": user})

        final_text = ""
        for _ in range(max_iter):
            resp = self._client().chat.completions.create(
                model=self.model,  # deepseek-chat 支持 function calling
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.4,
                max_tokens=2400,
            )
            msg = resp.choices[0].message
            messages.append(msg)  # 整体追加（含 reasoning_content / tool_calls）

            if not getattr(msg, "tool_calls", None):
                final_text = (msg.content or "").strip()
                break

            for tc in msg.tool_calls:
                fn = tc.function
                try:
                    args = json.loads(fn.arguments or "{}")
                except Exception:
                    args = {"raw": fn.arguments}
                result = None
                try:
                    handler = tool_map.get(fn.name)
                    result = handler(**args) if handler else {"error": f"未知工具: {fn.name}"}
                except Exception as e:
                    logger.warning(f"[orchestrator] 工具 {fn.name} 执行失败: {e}")
                    result = {"error": str(e)[:300]}
                if on_tool:
                    on_tool({"name": fn.name, "arguments": args}, result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False)[:4000],
                })
        else:
            final_text = (final_text or "已达最大推理轮次，请基于已有信息作答。").strip()
        return final_text
