from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.printer import WindowsPrinter
from app.queue_store import QueueStore
from app.routers.web import router as web_router
from app.security import ip_access_middleware
from app.worker import PrintWorker


def configure_logging() -> None:
    settings = get_settings()
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    log_path = settings.log_file.resolve()
    if any(isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", "") == str(log_path) for handler in root_logger.handlers):
        return

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()

    store = QueueStore(settings.database_path)
    store.initialize()
    printer = WindowsPrinter(settings)

    app.state.settings = settings
    app.state.store = store
    app.state.printer = printer

    worker_task: asyncio.Task | None = None
    worker: PrintWorker | None = None
    if settings.worker_enabled:
        worker = PrintWorker(store, printer, poll_seconds=settings.worker_poll_seconds)
        worker_task = asyncio.create_task(worker.run())

    try:
        yield
    finally:
        if worker is not None:
            worker.stop()
        if worker_task is not None:
            try:
                await asyncio.wait_for(worker_task, timeout=max(5.0, settings.worker_poll_seconds + 1))
            except asyncio.TimeoutError:
                worker_task.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.middleware("http")(ip_access_middleware)
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(web_router)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    return app


app = create_app()
