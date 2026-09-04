"""AI战士基类

所有AI战士统一继承此基类，重写 execute() 方法。
提供统一的日志、重试、Token计费等基础设施。
"""

import time
import json
from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger
from openai import OpenAI

from config.env import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL


@dataclass
class TaskRecord:
    """任务执行记录"""
    task_id: str
    soldier_name: str
    input: str
    output: str = ""
    status: str = "pending"  # pending | running | success | failed
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    tokens_used: int = 0
    retry_count: int = 0
    error_msg: str = ""

    @property
    def duration(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    def to_log(self) -> str:
        return json.dumps({
            "task_id": self.task_id,
            "soldier": self.soldier_name,
            "status": self.status,
            "duration": f"{self.duration:.2f}s",
            "tokens": self.tokens_used,
            "retries": self.retry_count,
        }, ensure_ascii=False)


class BaseSoldier(ABC):
    """AI战士基类

    所有子类需：
    1. 设置 name 和 role 属性
    2. 实现 execute(task: dict) -> dict 方法

    使用示例:
        class MyScout(BaseSoldier):
            name = "侦察兵-01"
            role = "scout"

            def execute(self, task: dict) -> dict:
                # 自定义逻辑
                return {"status": "success", "result": "..."}
    """

    name: str = "未命名战士"
    role: str = "unknown"
    max_retries: int = 3
    temperature: float = 0.7
    max_tokens: int = 2048

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        logger.info(f"🤖 {self.name} 已就位 ({self.role})")

    @abstractmethod
    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """执行任务（子类必须实现）"""
        ...

    def chat(self, system_prompt: str, user_message: str, 
             temperature: float | None = None,
             max_tokens: int | None = None) -> tuple[str, int]:
        """调用DeepSeek Chat API，返回 (回复内容, token消耗)"""
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=DEEPSEEK_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=temperature or self.temperature,
                    max_tokens=max_tokens or self.max_tokens,
                )
                content = response.choices[0].message.content or ""
                tokens = response.usage.total_tokens if response.usage else 0
                logger.debug(f"[{self.name}] API调用成功, tokens={tokens}")
                return content, tokens

            except Exception as e:
                logger.warning(f"[{self.name}] API调用失败 (尝试{attempt}/{self.max_retries}): {e}")
                if attempt == self.max_retries:
                    raise RuntimeError(f"[{self.name}] API调用全部{self.max_retries}次重试失败") from e
                time.sleep(2 ** attempt)  # 指数退避

        raise RuntimeError("Unreachable")

    def run(self, task: dict[str, Any]) -> TaskRecord:
        """运行任务并返回记录（公共入口）"""
        import uuid
        record = TaskRecord(
            task_id=str(uuid.uuid4())[:8],
            soldier_name=self.name,
            input=str(task),
        )
        record.status = "running"
        record.start_time = datetime.now()

        try:
            result = self.execute(task)
            record.output = str(result)
            record.status = "success"
            record.tokens_used = result.get("tokens_used", 0)
        except Exception as e:
            record.status = "failed"
            record.error_msg = str(e)
            logger.error(f"[{self.name}] 任务失败: {e}")
        finally:
            record.end_time = datetime.now()
            logger.info(f"[{self.name}] {record.to_log()}")

        return record

    def __repr__(self) -> str:
        return f"<Soldier: {self.name} ({self.role})>"
