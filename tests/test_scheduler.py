from datetime import timedelta
from pathlib import Path

from app.queue_store import QueueStore, utcnow
from app.scheduler import PrintScheduler


def test_scheduler_uses_fifo_by_default(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "queue.sqlite3")
    store.initialize()
    first = store.create_job(
        original_filename="first.pdf",
        safe_filename="first.pdf",
        stored_path=tmp_path / "first.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
        priority=0,
    )
    store.create_job(
        original_filename="second.pdf",
        safe_filename="second.pdf",
        stored_path=tmp_path / "second.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
        priority=10,
    )

    decision = PrintScheduler(store).select_next()

    assert decision.job is not None
    assert decision.job.id == first.id
    assert decision.rule == "fifo"


def test_scheduler_skips_future_jobs_and_respects_pause(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "queue.sqlite3")
    store.initialize()
    store.create_job(
        original_filename="future.pdf",
        safe_filename="future.pdf",
        stored_path=tmp_path / "future.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
        scheduled_at=utcnow() + timedelta(hours=1),
    )
    ready = store.create_job(
        original_filename="ready.pdf",
        safe_filename="ready.pdf",
        stored_path=tmp_path / "ready.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
    )

    scheduler = PrintScheduler(store)
    assert scheduler.select_next().job.id == ready.id

    store.set_paused(True, "manual")
    paused = scheduler.select_next()
    assert paused.job is None
    assert paused.reason == "服务已暂停"


def test_scheduler_can_use_priority_fifo_rule(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "queue.sqlite3")
    store.initialize()
    store.create_job(
        original_filename="low.pdf",
        safe_filename="low.pdf",
        stored_path=tmp_path / "low.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
        priority=0,
    )
    high = store.create_job(
        original_filename="high.pdf",
        safe_filename="high.pdf",
        stored_path=tmp_path / "high.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
        priority=10,
    )

    decision = PrintScheduler(store, rule="priority_fifo").select_next()

    assert decision.job is not None
    assert decision.job.id == high.id
    assert decision.rule == "priority_fifo"
