"""后勤兵 - 定时任务调度器

基于APScheduler实现定时任务管理。
支持：Cron表达式、间隔执行、一次性任务。
"""

from datetime import datetime
from typing import Any, Callable
from dataclasses import dataclass, field
import asyncio

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from loguru import logger


@dataclass
class ScheduledTask:
    """定时任务定义"""
    name: str
    func: Callable
    trigger_type: str  # cron / interval / date
    trigger_config: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    enabled: bool = True
    last_run: datetime | None = None
    run_count: int = 0


class TaskScheduler:
    """统一任务调度器

    使用示例：
        scheduler = TaskScheduler()

        @scheduler.cron("0 8 * * *")  # 每天8点
        def daily_briefing():
            ...

        @scheduler.interval(hours=1)
        def hourly_check():
            ...

        scheduler.start()
    """

    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler(
            timezone="Asia/Shanghai",
            job_defaults={"coalesce": True, "max_instances": 3},
        )
        self._tasks: dict[str, ScheduledTask] = {}
        logger.info("[调度器] 初始化完成")

    def add_task(self, task: ScheduledTask) -> None:
        """添加定时任务"""
        if not task.enabled:
            return

        trigger: CronTrigger | IntervalTrigger | DateTrigger
        if task.trigger_type == "cron":
            trigger = CronTrigger.from_crontab(task.trigger_config.get("cron", "0 8 * * *"))
        elif task.trigger_type == "interval":
            trigger = IntervalTrigger(**task.trigger_config)
        elif task.trigger_type == "date":
            trigger = DateTrigger(**task.trigger_config)
        else:
            raise ValueError(f"不支持的触发器类型: {task.trigger_type}")

        def _wrapped() -> None:
            try:
                task.last_run = datetime.now()
                task.run_count += 1
                logger.info(f"[调度器] 执行任务: {task.name}")
                # 支持同步和异步函数
                result = task.func()
                if asyncio.iscoroutine(result):
                    asyncio.get_event_loop().run_until_complete(result)
                logger.info(f"[调度器] 任务完成: {task.name}")
            except Exception as e:
                logger.error(f"[调度器] 任务失败 {task.name}: {e}")

        self._scheduler.add_job(
            _wrapped,
            trigger=trigger,
            id=task.name,
            name=task.name,
            replace_existing=True,
        )
        self._tasks[task.name] = task
        logger.info(f"[调度器] 已注册任务: {task.name} ({task.trigger_type})")

    def cron(self, cron_expr: str, name: str | None = None, description: str = ""):
        """装饰器：Cron定时任务

        Args:
            cron_expr: Cron表达式，如 "0 8 * * *" (每天8点)
            name: 任务名（默认用函数名）
            description: 任务描述
        """
        def decorator(func: Callable) -> Callable:
            task_name = name or func.__name__
            self.add_task(ScheduledTask(
                name=task_name,
                func=func,
                trigger_type="cron",
                trigger_config={"cron": cron_expr},
                description=description,
            ))
            return func
        return decorator

    def interval(self, seconds: int = 0, minutes: int = 0, hours: int = 0,
                 name: str | None = None, description: str = ""):
        """装饰器：间隔定时任务"""
        def decorator(func: Callable) -> Callable:
            task_name = name or func.__name__
            config = {}
            if seconds: config["seconds"] = seconds
            if minutes: config["minutes"] = minutes
            if hours: config["hours"] = hours
            self.add_task(ScheduledTask(
                name=task_name,
                func=func,
                trigger_type="interval",
                trigger_config=config,
                description=description,
            ))
            return func
        return decorator

    def start(self) -> None:
        """启动调度器"""
        self._scheduler.start()
        logger.info(f"[调度器] 启动成功，已注册 {len(self._tasks)} 个任务")
        for name, task in self._tasks.items():
            logger.info(f"  - {name}: {task.description or task.trigger_type}")

    def stop(self) -> None:
        """停止调度器"""
        self._scheduler.shutdown(wait=False)
        logger.info("[调度器] 已停止")

    def get_status(self) -> list[dict[str, Any]]:
        """获取所有任务状态"""
        status: list[dict[str, Any]] = []
        for name, task in self._tasks.items():
            job = self._scheduler.get_job(name)
            status.append({
                "name": name,
                "description": task.description,
                "enabled": task.enabled,
                "last_run": task.last_run.isoformat() if task.last_run else None,
                "run_count": task.run_count,
                "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
            })
        return status

    def pause_task(self, name: str) -> bool:
        """暂停任务"""
        try:
            self._scheduler.pause_job(name)
            logger.info(f"[调度器] 已暂停: {name}")
            return True
        except Exception as e:
            logger.error(f"[调度器] 暂停失败: {e}")
            return False

    def resume_task(self, name: str) -> bool:
        """恢复任务"""
        try:
            self._scheduler.resume_job(name)
            logger.info(f"[调度器] 已恢复: {name}")
            return True
        except Exception as e:
            logger.error(f"[调度器] 恢复失败: {e}")
            return False


# ====== 预定义军团队列 ======
def create_default_tasks(scheduler: TaskScheduler) -> None:
    """创建默认的军团定时任务"""

    @scheduler.cron("0 8 * * *", description="每日情报简报（8:00）")
    async def daily_intelligence_briefing() -> None:
        from src.scouts.crawler import crawl_all
        from src.scouts.summarizer import IntelligenceSummarizer
        from src.scouts.push import push_briefing

        items = crawl_all()
        if items:
            summarizer = IntelligenceSummarizer()
            result = summarizer.execute({"items": items})
            push_briefing(result["briefing"])

    @scheduler.cron("0 18 * * *", description="每日工作总结（18:00）")
    def daily_summary() -> None:
        logger.info("[调度] 生成每日工作总结...")

    @scheduler.interval(hours=4, description="竞品监控")
    def competitor_check() -> None:
        logger.info("[调度] 竞品检查...")


# ====== 使用示例 ======
if __name__ == "__main__":
    scheduler = TaskScheduler()

    # 方式1：使用装饰器
    @scheduler.cron("*/5 * * * *", description="每5分钟健康检查")
    def health_check():
        logger.info("✅ 系统运行正常")

    # 方式2：手动添加
    scheduler.add_task(ScheduledTask(
        name="test_interval",
        func=lambda: logger.info("⏰ 每30秒执行"),
        trigger_type="interval",
        trigger_config={"seconds": 30},
        description="测试任务",
    ))

    scheduler.start()
    logger.info("调度器运行中... 按Ctrl+C停止")

    try:
        import time
        while True:
            time.sleep(10)
            status = scheduler.get_status()
            for s in status:
                logger.info(f"  任务: {s['name']} | 下次: {s['next_run']} | 次数: {s['run_count']}")
    except KeyboardInterrupt:
        scheduler.stop()
        logger.info("调度器已停止")
