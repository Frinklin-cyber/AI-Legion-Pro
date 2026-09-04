"""
agent_registry.py
Agent 注册表 —— 复用 Zero Daemon tool_router 的设计思路：
每个 Agent 就是一个"工具"，有 name / description / parameters（OpenAI function-calling 风格 schema）。
配置以 JSON 文件存放在 agents/ 目录，启动时自动加载，支持动态注册。
"""

import json
import threading
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"

# name -> AgentSpec dict（模块级注册表，同 tool_router.func_map）
_registry: dict = {}
_lock = threading.Lock()


def register_agent(spec: dict):
    """注册一个 Agent。幂等：同名覆盖。spec 必须含 name/description/system_prompt。"""
    name = spec.get("name")
    if not name:
        raise ValueError("Agent 配置缺少 name 字段")
    if "system_prompt" not in spec:
        raise ValueError(f"Agent {name} 配置缺少 system_prompt 字段")
    with _lock:
        _registry[name] = spec
    return name


def register_from_file(path) -> str:
    """从 JSON 文件加载并注册一个 Agent"""
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    return register_agent(spec)


def load_agents_from_dir(directory: Path = AGENTS_DIR) -> list:
    """加载目录下所有 *.json Agent 配置，返回注册的 name 列表"""
    directory = Path(directory)
    if not directory.exists():
        return []
    loaded = []
    for f in sorted(directory.glob("*.json")):
        try:
            loaded.append(register_from_file(f))
        except Exception as e:
            print(f"[WARN] Agent 配置加载失败 {f.name}: {e}")
    return loaded


def get_agent(name: str) -> dict:
    """按名称取 Agent 定义；不存在返回 None"""
    return _registry.get(name)


def list_agents() -> list:
    """返回全部已注册 Agent 的 schema 摘要（供路由 Agent 与 /agents API 使用）"""
    out = []
    for name, spec in sorted(_registry.items()):
        out.append({
            "name": name,
            "title": spec.get("title", name),
            "description": spec.get("description", ""),
            "use_kb": bool(spec.get("use_kb", False)),
            "parameters": spec.get("parameters", {"type": "object", "properties": {}}),
            "output_schema": spec.get("output_schema", {}),
        })
    return out


def agent_count() -> int:
    return len(_registry)
