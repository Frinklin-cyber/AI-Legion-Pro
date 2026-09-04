"""
pull_models.py
确保本地 Ollama 已拉取所需的 embedding 模型与 LLM 模型。
用法: python scripts/pull_models.py [embed_model] [llm_model]
"""

import sys
from pathlib import Path

import requests

# 确保从任意目录运行都能导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import OLLAMA_HOST, EMBED_MODEL, LLM_MODEL


def pull(model: str) -> bool:
    print(f"正在拉取模型: {model} ...")
    try:
        with requests.post(f"{OLLAMA_HOST}/api/pull", json={"name": model}, stream=True, timeout=600) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    print("  " + line.decode("utf-8"))
        return True
    except requests.RequestException as e:
        print(f"[FAIL] 拉取 {model} 失败: {e}")
        return False


if __name__ == "__main__":
    embed = sys.argv[1] if len(sys.argv) > 1 else EMBED_MODEL
    llm = sys.argv[2] if len(sys.argv) > 2 else LLM_MODEL
    ok = True
    if not pull(embed):
        ok = False
    if not pull(llm):
        ok = False
    print("[OK] 全部模型就绪" if ok else "[FAIL] 部分模型拉取失败，请检查网络/Ollama 服务")
    sys.exit(0 if ok else 1)
