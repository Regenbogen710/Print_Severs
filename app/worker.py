from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.printer import WindowsPrinter
from app.queue_store import QueueStore, utcnow


logger = logging.getLogger(__name__)


class PrintWorker:
    def __init__(
        self,
        store: QueueStore,
        printer: WindowsPrinter,
        *,
        poll_seconds: float,
    ) -> None:
        self.store = store
        self.printer = printer
        self.poll_seconds = poll_seconds
        self._stop_event = asyncio.Event()

    async def run(self) -> None:
        logger.info("print worker started")
        while not self._stop_event.is_set():
            try:
                await self.process_once()
            except Exception:
                logger.exception("print worker loop failed")
            await asyncio.sleep(self.poll_seconds)
        logger.info("print worker stopped")

    def stop(self) -> None:
        self._stop_event.set()

    async def process_once(self) -> None:
        state = self.store.get_state()
        if state.paused:
            return

        job = self.store.get_next_waiting()
        if job is None:
            return

        status = await asyncio.to_thread(self.printer.status)
        if not status.ready:
            reason = f"打印前状态检查失败：{status.message}"
            logger.error("job %s blocked before printing: %s", job.id, reason)
            self.store.update_job_status(
                job.id,
                "failed",
                error_message=reason,
                completed_at=utcnow(),
            )
            self.store.set_paused(True, reason)
            return

        logger.info("printing job %s: %s", job.id, job.original_filename)
        self.store.update_job_status(job.id, "printing", started_at=utcnow())
        result = await asyncio.to_thread(self.printer.print_file, Path(job.stored_path))
        if not result.success:
            reason = f"打印失败：{result.detail}"
            logger.error("job %s failed: %s", job.id, reason)
            self.store.update_job_status(
                job.id,
                "failed",
                error_message=reason,
                completed_at=utcnow(),
            )
            self.store.set_paused(True, reason)
            return

        post_status = await asyncio.to_thread(self.printer.status)
        if not post_status.ready:
            reason = f"打印提交后状态异常：{post_status.message}"
            logger.error("job %s failed after submit: %s", job.id, reason)
            self.store.update_job_status(
                job.id,
                "failed",
                error_message=reason,
                completed_at=utcnow(),
            )
            self.store.set_paused(True, reason)
            return

        logger.info("job %s completed: %s", job.id, result.detail)
        self.store.update_job_status(
            job.id,
            "completed",
            error_message=None,
            completed_at=utcnow(),
        )
