from __future__ import annotations

from dataclasses import dataclass
import logging

from app.queue_store import QueueStore, utcnow
from app.schemas import PrintJobOut


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduleDecision:
    job: PrintJobOut | None
    rule: str
    reason: str


class PrintScheduler:
    def __init__(self, store: QueueStore, *, rule: str = "fifo") -> None:
        self.store = store
        self.rule = rule

    def select_next(self) -> ScheduleDecision:
        state = self.store.get_state()
        if state.paused:
            return ScheduleDecision(None, self.rule, "服务已暂停")

        job = self.store.get_next_schedulable(now=utcnow(), rule=self.rule)
        if job is None:
            return ScheduleDecision(None, self.rule, "没有可调度任务")
        if job.status != "waiting":
            logger.warning("scheduler skipped non-waiting job %s: %s", job.id, job.status)
            return ScheduleDecision(None, self.rule, f"任务状态不可调度：{job.status}")

        logger.info("scheduler selected job %s by %s", job.id, self.rule)
        return ScheduleDecision(job, self.rule, "已选择下一个任务")
