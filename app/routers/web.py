from __future__ import annotations

import asyncio
from pathlib import Path
import logging
from urllib.parse import urlencode
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.dependencies import get_printer, get_store
from app.printer import WindowsPrinter
from app.queue_store import QueueStore
from app.schemas import PrintJobOut, QueueSnapshot, ServerState
from app.security import require_admin, require_local_request, require_upload_auth
from app.upload_validation import sanitize_filename, validate_printable_file


logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


def format_size(value: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{value} B"


templates.env.filters["format_size"] = format_size


@router.get("/")
async def home(
    request: Request,
    message: str | None = None,
    error: str | None = None,
    store: QueueStore = Depends(get_store),
    printer: WindowsPrinter = Depends(get_printer),
    settings: Settings = Depends(get_settings),
):
    snapshot = await _snapshot(store, printer)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "snapshot": snapshot,
            "message": message,
            "error": error,
            "settings": settings,
            "status_labels": {
                "waiting": "等待中",
                "printing": "打印中",
                "completed": "已完成",
                "failed": "失败",
                "deleted": "已删除",
            },
        },
    )


@router.post("/upload", dependencies=[Depends(require_upload_auth)])
async def upload_from_web(
    upload: UploadFile = File(...),
    store: QueueStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
):
    try:
        job = await _save_upload(upload, store, settings)
    except HTTPException as exc:
        return _redirect(error=str(exc.detail))
    return _redirect(message=f"任务 #{job.id} 已加入队列")


@router.get("/api/status", response_model=QueueSnapshot)
async def api_status(
    store: QueueStore = Depends(get_store),
    printer: WindowsPrinter = Depends(get_printer),
):
    return await _snapshot(store, printer)


@router.post(
    "/api/upload",
    response_model=PrintJobOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_upload_auth)],
)
async def upload_from_api(
    upload: UploadFile = File(...),
    store: QueueStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
):
    return await _save_upload(upload, store, settings)


@router.post("/admin/pause", dependencies=[Depends(require_admin)])
async def pause_from_web(
    reason: str = Form(default="管理员手动暂停"),
    store: QueueStore = Depends(get_store),
):
    state = store.set_paused(True, reason.strip() or "管理员手动暂停")
    logger.warning("service paused by admin: %s", state.pause_reason)
    return _redirect(message="服务已暂停")


@router.post("/api/admin/pause", response_model=ServerState, dependencies=[Depends(require_admin)])
async def pause_from_api(
    reason: str = Form(default="管理员手动暂停"),
    store: QueueStore = Depends(get_store),
):
    state = store.set_paused(True, reason.strip() or "管理员手动暂停")
    logger.warning("service paused by admin: %s", state.pause_reason)
    return state


@router.post(
    "/admin/resume",
    dependencies=[Depends(require_admin), Depends(require_local_request)],
)
async def resume_from_web(store: QueueStore = Depends(get_store)):
    store.set_paused(False, None)
    logger.warning("service resumed locally")
    return _redirect(message="服务已恢复")


@router.post(
    "/api/admin/resume",
    response_model=ServerState,
    dependencies=[Depends(require_admin), Depends(require_local_request)],
)
async def resume_from_api(store: QueueStore = Depends(get_store)):
    state = store.set_paused(False, None)
    logger.warning("service resumed locally")
    return state


@router.post("/admin/jobs/{job_id}/retry", dependencies=[Depends(require_admin)])
async def retry_from_web(job_id: int, store: QueueStore = Depends(get_store)):
    try:
        job = store.retry_job(job_id)
    except (KeyError, ValueError) as exc:
        return _redirect(error=str(exc))
    logger.info("job %s retried by admin", job_id)
    return _redirect(message=f"任务 #{job.id} 已重新加入队列")


@router.post("/api/admin/jobs/{job_id}/retry", response_model=PrintJobOut, dependencies=[Depends(require_admin)])
async def retry_from_api(job_id: int, store: QueueStore = Depends(get_store)):
    try:
        return store.retry_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/jobs/{job_id}/delete", dependencies=[Depends(require_admin)])
async def delete_from_web(job_id: int, store: QueueStore = Depends(get_store)):
    try:
        job = store.delete_job(job_id)
        _unlink_upload(job.stored_path)
    except (KeyError, ValueError) as exc:
        return _redirect(error=str(exc))
    logger.info("job %s deleted by admin", job_id)
    return _redirect(message=f"任务 #{job_id} 已删除")


@router.post("/api/admin/jobs/{job_id}/delete", response_model=PrintJobOut, dependencies=[Depends(require_admin)])
async def delete_from_api(job_id: int, store: QueueStore = Depends(get_store)):
    try:
        job = store.delete_job(job_id)
        _unlink_upload(job.stored_path)
        logger.info("job %s deleted by admin", job_id)
        return job
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _snapshot(store: QueueStore, printer: WindowsPrinter) -> QueueSnapshot:
    printer_status = await asyncio.to_thread(printer.status)
    return QueueSnapshot(
        state=store.get_state(),
        printer=printer_status,
        jobs=store.list_jobs(),
    )


async def _save_upload(
    upload: UploadFile,
    store: QueueStore,
    settings: Settings,
) -> PrintJobOut:
    original_filename = upload.filename or "upload"
    safe_filename = sanitize_filename(original_filename)
    head = await upload.read(8192)
    validation = validate_printable_file(safe_filename, settings.allowed_extensions, head)
    if not validation.is_valid:
        logger.warning("upload rejected: %s (%s)", original_filename, validation.reason)
        raise HTTPException(status_code=400, detail=validation.reason)

    stored_name = f"{uuid.uuid4().hex}_{safe_filename}"
    destination = settings.upload_dir / stored_name
    total_size = 0

    try:
        with destination.open("wb") as output:
            if head:
                output.write(head)
                total_size += len(head)
            if total_size > settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="文件超过上传大小限制")
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="文件超过上传大小限制")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    job = store.create_job(
        original_filename=original_filename,
        safe_filename=safe_filename,
        stored_path=destination,
        extension=validation.extension,
        mime_type=upload.content_type,
        size_bytes=total_size,
    )
    logger.info("upload accepted as job %s: %s", job.id, original_filename)
    return job


def _redirect(*, message: str | None = None, error: str | None = None) -> RedirectResponse:
    query = urlencode({key: value for key, value in {"message": message, "error": error}.items() if value})
    target = f"/?{query}" if query else "/"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


def _unlink_upload(stored_path: str) -> None:
    try:
        Path(stored_path).unlink(missing_ok=True)
    except OSError:
        logger.exception("failed to delete uploaded file: %s", stored_path)
