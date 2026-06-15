from pathlib import Path

from app.queue_store import QueueStore


def test_queue_store_lifecycle(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "queue.sqlite3")
    store.initialize()

    job = store.create_job(
        original_filename="a.pdf",
        safe_filename="a.pdf",
        stored_path=tmp_path / "a.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
    )

    assert job.status == "waiting"
    assert store.get_next_waiting().id == job.id

    store.update_job_status(job.id, "failed", error_message="printer offline")
    failed = store.get_job(job.id)
    assert failed.status == "failed"
    assert failed.error_message == "printer offline"

    retried = store.retry_job(job.id)
    assert retried.status == "waiting"
    assert retried.error_message is None

    paused = store.set_paused(True, "manual")
    assert paused.paused
    assert paused.pause_reason == "manual"

    resumed = store.set_paused(False, None)
    assert not resumed.paused
    assert resumed.pause_reason is None


def test_queue_store_orders_waiting_jobs_by_print_order(tmp_path: Path) -> None:
    store = QueueStore(tmp_path / "queue.sqlite3")
    store.initialize()

    first = store.create_job(
        original_filename="first.pdf",
        safe_filename="first.pdf",
        stored_path=tmp_path / "first.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
    )
    second = store.create_job(
        original_filename="second.pdf",
        safe_filename="second.pdf",
        stored_path=tmp_path / "second.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
    )

    assert [job.id for job in store.list_jobs()] == [first.id, second.id]
    assert store.get_next_waiting().id == first.id

    store.reorder_waiting_jobs([second.id, first.id])

    assert [job.id for job in store.list_jobs()] == [second.id, first.id]
    assert store.get_next_waiting().id == second.id
