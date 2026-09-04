"""指挥中心 - 任务调度分发器

负责任务的分发、执行和状态追踪。
支持多AI战士并行执行任务。
"""

from typing import Any
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

from loguru import logger

from src.core import BaseSoldier, TaskRecord


class TaskStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


@dataclass
class Mission:
    """作战任务"""
    mission_id: str
    title: str
    description: str
    assigned_soldier: str
    task_data: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 1  # 1-5, 5最高
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    result: dict[str, Any] | None = None
    record: TaskRecord | None = None


class CommandDispatcher:
    """指挥中心任务调度器

    使用示例：
        dispatcher = CommandDispatcher()

        # 注册战士
        dispatcher.register_soldier(my_scout)
        dispatcher.register_soldier(my_analyst)

        # 分发任务
        mission = dispatcher.dispatch("scout", {"url": "..."})

        # 查看状态
        status = dispatcher.get_all_status()
    """

    def __init__(self) -> None:
        self._soldiers: dict[str, BaseSoldier] = {}
        self._missions: dict[str, Mission] = {}
        logger.info("[指挥中心] 司令部已启动，等待战士报到...")

    def register_soldier(self, soldier: BaseSoldier) -> None:
        """注册一名AI战士"""
        key = soldier.role
        self._soldiers[key] = soldier
        logger.info(f"[指挥中心] ✅ {soldier.name} 报到完毕 ({soldier.role})")

    def unregister_soldier(self, role: str) -> None:
        """移除一名AI战士"""
        if role in self._soldiers:
            name = self._soldiers[role].name
            del self._soldiers[role]
            logger.info(f"[指挥中心] ❌ {name} 已退役 ({role})")

    def list_soldiers(self) -> list[dict[str, Any]]:
        """列出所有已注册战士"""
        return [
            {
                "name": s.name,
                "role": s.role,
                "temperature": s.temperature,
                "max_tokens": s.max_tokens,
            }
            for s in self._soldiers.values()
        ]

    def dispatch(self, soldier_role: str, task_data: dict[str, Any],
                 title: str = "", priority: int = 1) -> Mission | None:
        """分发任务给指定战士

        Args:
            soldier_role: 战士角色名
            task_data: 任务数据
            title: 任务标题
            priority: 优先级1-5

        Returns:
            Mission对象，战士不存在返回None
        """
        if soldier_role not in self._soldiers:
            logger.error(f"[指挥中心] 战士未报到: {soldier_role}, 可用: {list(self._soldiers.keys())}")
            return None

        import uuid
        mission = Mission(
            mission_id=str(uuid.uuid4())[:8],
            title=title or task_data.get("type", "未命名任务"),
            description=str(task_data),
            assigned_soldier=soldier_role,
            task_data=task_data,
            priority=priority,
        )

        soldier = self._soldiers[soldier_role]

        try:
            logger.info(f"[指挥中心] 🚀 派遣 {soldier.name} 执行: {mission.title}")
            mission.status = TaskStatus.RUNNING
            mission.updated_at = datetime.now()

            record = soldier.run(task_data)
            mission.record = record
            mission.updated_at = datetime.now()

            if record.status == "success":
                mission.status = TaskStatus.SUCCESS
                logger.info(f"[指挥中心] ✅ 任务完成: {mission.title} ({record.duration:.1f}s)")
            else:
                mission.status = TaskStatus.FAILED
                logger.error(f"[指挥中心] ❌ 任务失败: {mission.title} - {record.error_msg}")

        except Exception as e:
            mission.status = TaskStatus.FAILED
            mission.updated_at = datetime.now()
            logger.error(f"[指挥中心] 💥 任务异常: {mission.title} - {e}")

        self._missions[mission.mission_id] = mission
        return mission

    def dispatch_parallel(self, tasks: list[dict[str, Any]]) -> list[Mission | None]:
        """并行分发多个任务

        Args:
            tasks: [
                {"role": "scout_summarizer", "data": {...}, "title": "..."},
                {"role": "staff_analyst", "data": {...}, "title": "..."},
            ]

        Returns:
            任务结果列表
        """
        from concurrent.futures import ThreadPoolExecutor

        def _run(task: dict) -> Mission | None:
            return self.dispatch(
                soldier_role=task["role"],
                task_data=task.get("data", {}),
                title=task.get("title", ""),
                priority=task.get("priority", 1),
            )

        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            results = list(executor.map(_run, tasks))

        return results

    def get_mission(self, mission_id: str) -> Mission | None:
        """根据ID获取任务"""
        return self._missions.get(mission_id)

    def get_all_status(self) -> dict[str, Any]:
        """获取指挥中心全局状态"""
        missions_status: dict[str, int] = {s.value: 0 for s in TaskStatus}
        for m in self._missions.values():
            missions_status[m.status.value] += 1

        return {
            "soldiers_count": len(self._soldiers),
            "missions_total": len(self._missions),
            "missions_by_status": missions_status,
            "soldiers": self.list_soldiers(),
            "recent_missions": [
                {
                    "id": m.mission_id,
                    "title": m.title,
                    "soldier": m.assigned_soldier,
                    "status": m.status.value,
                    "duration": m.record.duration if m.record else 0,
                    "created_at": m.created_at.isoformat(),
                }
                for m in list(self._missions.values())[-10:]  # 最近10个
            ],
        }

    def get_missions_needing_review(self) -> list[Mission]:
        """获取需人工审核的任务"""
        return [m for m in self._missions.values() if m.status == TaskStatus.NEEDS_REVIEW]


# ====== 使用示例 ======
if __name__ == "__main__":
    from src.scouts.summarizer import IntelligenceSummarizer

    dispatcher = CommandDispatcher()

    # 注册战士
    summarizer = IntelligenceSummarizer()
    dispatcher.register_soldier(summarizer)

    # 分发任务
    mission = dispatcher.dispatch(
        soldier_role="scout_summarizer",
        task_data={"items": [
            {"title": "DeepSeek发布V3模型", "source": "36氪", "link": "https://example.com"},
            {"title": "企业AI改革新趋势2024", "source": "机器之心", "link": "https://example2.com"},
        ]},
        title="每日情报简报",
        priority=3,
    )

    # 查看状态
    import json
    status = dispatcher.get_all_status()
    print(json.dumps(status, ensure_ascii=False, indent=2))
