from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dependencies import get_printer, get_store
from app.queue_store import QueueStore
from app.routers.web import router
from app.schemas import PrinterStatusOut


class FakePrinter:
    def status(self) -> PrinterStatusOut:
        return PrinterStatusOut(
            ready=True,
            name="Test Printer",
            message="测试打印机可用",
            raw_status={"test": True},
        )


def build_client(
    tmp_path: Path,
    *,
    admin_username: str = "admin",
    admin_password: str = "change-this-password",
) -> tuple[TestClient, QueueStore]:
    store = QueueStore(tmp_path / "queue.sqlite3")
    store.initialize()
    settings = Settings(
        data_dir=tmp_path / "data",
        allowed_extensions=[".pdf", ".txt"],
        max_upload_mb=1,
        worker_enabled=False,
        admin_username=admin_username,
        admin_password=admin_password,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_printer] = lambda: FakePrinter()
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


def test_uploaded_waiting_job_renders_drag_handle_for_admin_sorting(tmp_path: Path) -> None:
    client, store = build_client(tmp_path)

    upload_response = client.post(
        "/api/upload",
        files={"upload": ("queued.pdf", b"%PDF-1.7\nbody", "application/pdf")},
    )
    page_response = client.get("/")

    assert upload_response.status_code == 201
    job = store.list_jobs()[0]
    assert page_response.status_code == 200
    html = page_response.text
    assert f'data-job-id="{job.id}" data-status="waiting"' in html
    assert 'class="drag-handle"' in html
    assert "管理员认证后可拖动" in html


def test_admin_can_reorder_waiting_jobs(tmp_path: Path) -> None:
    client, store = build_client(tmp_path)
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

    response = client.post(
        "/api/admin/jobs/reorder",
        json={"job_ids": [second.id, first.id]},
        auth=("admin", "change-this-password"),
    )

    assert response.status_code == 200
    assert [job["id"] for job in response.json()] == [second.id, first.id]
    assert store.get_next_waiting().id == second.id


def test_admin_password_check_accepts_correct_password(tmp_path: Path) -> None:
    client, _store = build_client(tmp_path)

    response = client.post(
        "/api/admin/auth/check",
        json={"password": "change-this-password"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_admin_password_check_rejects_wrong_password(tmp_path: Path) -> None:
    client, _store = build_client(tmp_path)

    response = client.post(
        "/api/admin/auth/check",
        json={"password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "管理员密码错误"


def test_admin_auth_uses_configured_credentials(tmp_path: Path) -> None:
    client, store = build_client(tmp_path, admin_username="root", admin_password="from-config")
    first = store.create_job(
        original_filename="first.pdf",
        safe_filename="first.pdf",
        stored_path=tmp_path / "first.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
    )

    rejected = client.post(
        "/api/admin/auth/check",
        json={"password": "change-this-password"},
    )
    accepted = client.post(
        "/api/admin/auth/check",
        json={"password": "from-config"},
    )
    reordered = client.post(
        "/api/admin/jobs/reorder",
        json={"job_ids": [first.id]},
        auth=("root", "from-config"),
    )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert reordered.status_code == 200


def test_reorder_requires_admin_basic_auth(tmp_path: Path) -> None:
    client, store = build_client(tmp_path)
    job = store.create_job(
        original_filename="first.pdf",
        safe_filename="first.pdf",
        stored_path=tmp_path / "first.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
    )

    response = client.post(
        "/api/admin/jobs/reorder",
        json={"job_ids": [job.id]},
    )

    assert response.status_code == 401


def test_delete_and_pause_require_admin_basic_auth(tmp_path: Path) -> None:
    client, store = build_client(tmp_path)
    job = store.create_job(
        original_filename="first.pdf",
        safe_filename="first.pdf",
        stored_path=tmp_path / "first.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
    )

    delete_response = client.post(f"/api/admin/jobs/{job.id}/delete")
    pause_response = client.post("/api/admin/pause", data={"reason": "manual"})

    assert delete_response.status_code == 401
    assert pause_response.status_code == 401


def test_home_hides_admin_controls_before_auth_and_does_not_render_password(tmp_path: Path) -> None:
    client, store = build_client(tmp_path)
    job = store.create_job(
        original_filename="first.pdf",
        safe_filename="first.pdf",
        stored_path=tmp_path / "first.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
    )

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'id="adminPanel" class="admin-panel" hidden' in html
    assert f'action="/admin/jobs/{job.id}/delete" method="post" hidden' in html
    assert "change-this-password" not in html


def test_home_file_input_does_not_block_js_upload_submit(tmp_path: Path) -> None:
    client, _store = build_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    upload_form = response.text.split('id="uploadForm"', 1)[1].split(">", 1)[0]
    file_input = response.text.split('id="fileInput"', 1)[1].split(">", 1)[0]
    assert "novalidate" in upload_form
    assert "required" not in file_input
    assert "multiple" in file_input


def test_reorder_rejects_non_waiting_jobs(tmp_path: Path) -> None:
    client, store = build_client(tmp_path)
    job = store.create_job(
        original_filename="first.pdf",
        safe_filename="first.pdf",
        stored_path=tmp_path / "first.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        size_bytes=12,
    )
    store.update_job_status(job.id, "completed")

    response = client.post(
        "/api/admin/jobs/reorder",
        json={"job_ids": [job.id]},
        auth=("admin", "change-this-password"),
    )

    assert response.status_code == 400
    assert "只能调整等待中的任务" in response.json()["detail"]
