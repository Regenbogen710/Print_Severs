from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dependencies import get_store
from app.queue_store import QueueStore
from app.routers.web import router


def build_client(tmp_path: Path) -> tuple[TestClient, QueueStore]:
    store = QueueStore(tmp_path / "queue.sqlite3")
    store.initialize()
    settings = Settings(
        data_dir=tmp_path / "data",
        allowed_extensions=[".pdf", ".txt"],
        max_upload_mb=1,
        worker_enabled=False,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app), store


def test_first_single_upload_is_enqueued(tmp_path: Path) -> None:
    client, store = build_client(tmp_path)

    response = client.post(
        "/api/upload",
        files={"upload": ("first.pdf", b"%PDF-1.7\nbody", "application/pdf")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["original_filename"] == "first.pdf"
    assert payload["status"] == "waiting"
    assert store.list_jobs()[0].original_filename == "first.pdf"


def test_batch_upload_accepts_valid_files_and_reports_invalid_files(tmp_path: Path) -> None:
    client, store = build_client(tmp_path)

    response = client.post(
        "/api/uploads",
        files=[
            ("uploads", ("ok.pdf", b"%PDF-1.7\nbody", "application/pdf")),
            ("uploads", ("bad.exe", b"MZ", "application/octet-stream")),
        ],
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["accepted_count"] == 1
    assert payload["rejected_count"] == 1
    assert payload["results"][0]["accepted"] is True
    assert payload["results"][1]["accepted"] is False
    assert "不支持的文件类型" in payload["results"][1]["error"]
    assert [job.original_filename for job in store.list_jobs()] == ["ok.pdf"]
