from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


JobStatus = Literal["waiting", "printing", "completed", "failed", "deleted"]


class ServerState(BaseModel):
    paused: bool
    pause_reason: str | None = None
    updated_at: datetime


class PrintJobOut(BaseModel):
    id: int
    original_filename: str
    safe_filename: str
    stored_path: str
    extension: str
    mime_type: str | None = None
    size_bytes: int
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class PrinterStatusOut(BaseModel):
    ready: bool
    name: str
    message: str
    raw_status: dict[str, object] = Field(default_factory=dict)


class QueueSnapshot(BaseModel):
    state: ServerState
    printer: PrinterStatusOut
    jobs: list[PrintJobOut]
