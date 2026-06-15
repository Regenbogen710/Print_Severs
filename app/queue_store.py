from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import threading

from app.schemas import PrintJobOut, ServerState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def dt_to_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def text_to_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class QueueStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_filename TEXT NOT NULL,
                    safe_filename TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    mime_type TEXT,
                    size_bytes INTEGER NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    print_order INTEGER NOT NULL DEFAULT 0,
                    scheduled_at TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    error_message TEXT
                )
                """
            )
            self._ensure_job_columns(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            now = dt_to_text(utcnow())
            conn.execute("INSERT OR IGNORE INTO state(key, value) VALUES ('paused', 'false')")
            conn.execute("INSERT OR IGNORE INTO state(key, value) VALUES ('pause_reason', '')")
            conn.execute("INSERT OR IGNORE INTO state(key, value) VALUES ('updated_at', ?)", (now,))
            conn.commit()

    def create_job(
        self,
        *,
        original_filename: str,
        safe_filename: str,
        stored_path: Path,
        extension: str,
        mime_type: str | None,
        size_bytes: int,
        priority: int = 0,
        scheduled_at: datetime | None = None,
    ) -> PrintJobOut:
        created_at = utcnow()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO jobs (
                    original_filename, safe_filename, stored_path, extension, mime_type,
                    size_bytes, priority, scheduled_at, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting', ?)
                """,
                (
                    original_filename,
                    safe_filename,
                    str(stored_path),
                    extension,
                    mime_type,
                    size_bytes,
                    priority,
                    dt_to_text(scheduled_at),
                    dt_to_text(created_at),
                ),
            )
            conn.execute(
                "UPDATE jobs SET print_order = ? WHERE id = ?",
                (cursor.lastrowid, cursor.lastrowid),
            )
            conn.commit()
            return self.get_job(cursor.lastrowid)

    def get_job(self, job_id: int) -> PrintJobOut:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"job not found: {job_id}")
        return self._row_to_job(row)

    def list_jobs(self, limit: int = 100) -> list[PrintJobOut]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                ORDER BY
                    CASE
                        WHEN status = 'waiting' THEN 0
                        WHEN status = 'printing' THEN 1
                        ELSE 2
                    END ASC,
                    print_order ASC,
                    created_at ASC,
                    id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def get_next_waiting(self) -> PrintJobOut | None:
        return self.get_next_schedulable()

    def get_next_schedulable(
        self,
        *,
        now: datetime | None = None,
        rule: str = "fifo",
    ) -> PrintJobOut | None:
        now_text = dt_to_text(now or utcnow())
        order_by = "print_order ASC, created_at ASC, id ASC"
        if rule == "priority_fifo":
            order_by = "priority DESC, print_order ASC, created_at ASC, id ASC"
        elif rule != "fifo":
            raise ValueError(f"unsupported schedule rule: {rule}")

        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM jobs
                WHERE status = 'waiting'
                  AND (scheduled_at IS NULL OR scheduled_at <= ?)
                ORDER BY {order_by}
                LIMIT 1
                """,
                (now_text,),
            ).fetchone()
        return self._row_to_job(row) if row is not None else None

    def reorder_waiting_jobs(self, job_ids: list[int]) -> list[PrintJobOut]:
        unique_ids = list(dict.fromkeys(job_ids))
        if not unique_ids:
            raise ValueError("排序列表不能为空")

        placeholders = ",".join("?" for _ in unique_ids)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT id, status FROM jobs WHERE id IN ({placeholders})",
                unique_ids,
            ).fetchall()
            found_ids = {row["id"] for row in rows}
            missing_ids = [job_id for job_id in unique_ids if job_id not in found_ids]
            if missing_ids:
                raise KeyError(f"任务不存在：{missing_ids[0]}")

            non_waiting = [row["id"] for row in rows if row["status"] != "waiting"]
            if non_waiting:
                raise ValueError(f"只能调整等待中的任务：{non_waiting[0]}")

            waiting_rows = conn.execute(
                """
                SELECT id FROM jobs
                WHERE status = 'waiting'
                ORDER BY print_order ASC, created_at ASC, id ASC
                """
            ).fetchall()
            waiting_ids = [row["id"] for row in waiting_rows]
            provided = set(unique_ids)
            final_ids = unique_ids + [job_id for job_id in waiting_ids if job_id not in provided]

            for index, job_id in enumerate(final_ids, start=1):
                conn.execute(
                    "UPDATE jobs SET print_order = ? WHERE id = ? AND status = 'waiting'",
                    (index, job_id),
                )
            conn.commit()

        return [self.get_job(job_id) for job_id in final_ids]

    def update_job_status(
        self,
        job_id: int,
        status: str,
        *,
        error_message: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> PrintJobOut:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    error_message = ?,
                    started_at = COALESCE(?, started_at),
                    completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (
                    status,
                    error_message,
                    dt_to_text(started_at),
                    dt_to_text(completed_at),
                    job_id,
                ),
            )
            conn.commit()
        return self.get_job(job_id)

    def delete_job(self, job_id: int) -> PrintJobOut:
        job = self.get_job(job_id)
        if job.status == "printing":
            raise ValueError("正在打印的任务不能删除")
        return self.update_job_status(job_id, "deleted", completed_at=utcnow())

    def retry_job(self, job_id: int) -> PrintJobOut:
        job = self.get_job(job_id)
        if job.status != "failed":
            raise ValueError("只有失败任务可以重新加入队列")
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'waiting',
                    error_message = NULL,
                    started_at = NULL,
                    completed_at = NULL
                WHERE id = ?
                """,
                (job_id,),
            )
            conn.commit()
        return self.get_job(job_id)

    def get_state(self) -> ServerState:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM state").fetchall()
        values = {row["key"]: row["value"] for row in rows}
        updated_at = text_to_dt(values.get("updated_at")) or utcnow()
        reason = values.get("pause_reason") or None
        return ServerState(
            paused=values.get("paused", "false") == "true",
            pause_reason=reason,
            updated_at=updated_at,
        )

    def set_paused(self, paused: bool, reason: str | None = None) -> ServerState:
        now = dt_to_text(utcnow())
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO state(key, value) VALUES ('paused', ?)",
                ("true" if paused else "false",),
            )
            conn.execute(
                "INSERT OR REPLACE INTO state(key, value) VALUES ('pause_reason', ?)",
                (reason or "",),
            )
            conn.execute(
                "INSERT OR REPLACE INTO state(key, value) VALUES ('updated_at', ?)",
                (now,),
            )
            conn.commit()
        return self.get_state()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_job_columns(self, conn: sqlite3.Connection) -> None:
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        if "priority" not in existing_columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
        if "print_order" not in existing_columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN print_order INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE jobs SET print_order = id WHERE print_order = 0")
        if "scheduled_at" not in existing_columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN scheduled_at TEXT")

    def _row_to_job(self, row: sqlite3.Row) -> PrintJobOut:
        return PrintJobOut(
            id=row["id"],
            original_filename=row["original_filename"],
            safe_filename=row["safe_filename"],
            stored_path=row["stored_path"],
            extension=row["extension"],
            mime_type=row["mime_type"],
            size_bytes=row["size_bytes"],
            priority=row["priority"],
            print_order=row["print_order"],
            scheduled_at=text_to_dt(row["scheduled_at"]),
            status=row["status"],
            created_at=text_to_dt(row["created_at"]) or utcnow(),
            started_at=text_to_dt(row["started_at"]),
            completed_at=text_to_dt(row["completed_at"]),
            error_message=row["error_message"],
        )
