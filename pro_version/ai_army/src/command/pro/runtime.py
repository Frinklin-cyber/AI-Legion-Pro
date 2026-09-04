"""Pro 版运行时状态（内存）

存放正在执行的执行单（execution）与步骤状态，供前端轮询。
注意：仅内存存储；plans / approvals / schedules 持久化在 SQLite。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TaskStep:
    """编排引擎中的单个任务步骤"""
    id: str
    department: str
    action: str
    depends_on: list[str] = field(default_factory=list)
    input: dict[str, Any] = field(default_factory=dict)
    cost: int = 0
    needs_approval: bool = False
    schedule: str | None = None

    # 执行状态
    status: str = "waiting"   # waiting/running/quality_checking/quality_retry/done/needs_approval/failed
    output: str = ""
    error: str = ""
    retry_count: int = 0
    approval_id: str = ""
    feedback: str = ""
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "department": self.department,
            "action": self.action,
            "depends_on": self.depends_on,
            "input": self.input,
            "cost": self.cost,
            "needs_approval": self.needs_approval,
            "schedule": self.schedule,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "retry_count": self.retry_count,
            "approval_id": self.approval_id,
            "feedback": self.feedback,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_task(cls, t: dict[str, Any]) -> "TaskStep":
        return cls(
            id=str(t.get("id", "")),
            department=str(t.get("department", "")),
            action=str(t.get("action", "")),
            depends_on=list(t.get("depends_on", []) or []),
            input=t.get("input") or {},
            cost=int(t.get("cost", 0) or 0),
            needs_approval=bool(t.get("needs_approval", False)),
            schedule=t.get("schedule"),
        )


@dataclass
class Execution:
    """一次执行单（进程内状态）"""
    exec_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    plan_id: str = ""
    store_id: str = ""
    goal: str = ""
    status: str = "running"   # running/done/failed
    estimated_cost: int = 0
    actual_cost: int = 0
    steps: dict[str, TaskStep] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: str = ""

    @property
    def step_list(self) -> list[TaskStep]:
        return list(self.steps.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "exec_id": self.exec_id,
            "plan_id": self.plan_id,
            "store_id": self.store_id,
            "goal": self.goal,
            "status": self.status,
            "estimated_cost": self.estimated_cost,
            "actual_cost": self.actual_cost,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "steps": [s.to_dict() for s in self.step_list],
        }


# 内存执行单存储
EXECUTIONS: dict[str, Execution] = {}

# 运行中的 asyncio 任务句柄（防 GC）
RUNNING_TASKS: set[Any] = set()


def new_execution(plan_id: str, store_id: str, goal: str,
                  tasks: list[dict[str, Any]]) -> Execution:
    """创建并注册一个执行单"""
    exec_obj = Execution(plan_id=plan_id, store_id=store_id, goal=goal)
    for t in tasks:
        step = TaskStep.from_task(t)
        exec_obj.steps[step.id] = step
        exec_obj.estimated_cost += step.cost
    EXECUTIONS[exec_obj.exec_id] = exec_obj
    return exec_obj


def get_execution(exec_id: str) -> Execution | None:
    return EXECUTIONS.get(exec_id)
