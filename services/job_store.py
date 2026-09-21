"""Sync job status tracking -- replaces the old `sync_jobs` SQLite table.

Two tiers, for two different needs:
  - An in-memory dict, updated after *every* crawled item. This is what
    `GET /api/sync/status/{job_id}` serves while a job is running in this
    process -- cheap, no network I/O, safe to call as often as the pipeline
    likes.
  - The `Sync_logs` Google Sheet (see `services/admin_sheets.py`), written
    only at job start and job end. Writing a row per crawled item would
    hammer the Sheets API (hundreds of writes per sync) and blow through
    its rate limits; a durable history only needs the two endpoints of each
    job, not every intermediate step.

`get()`/`list_recent()` fall back to the Sync_logs sheet when a job isn't
(or is no longer) in memory -- e.g. after a process restart.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.config import settings
from core.logging import get_logger
from services.admin_sheets import SyncLogsStore, open_admin_spreadsheet

logger = get_logger(__name__)

_lock = threading.Lock()
_jobs: dict[str, "JobRecord"] = {}


@dataclass
class JobRecord:
    job_id: str
    manufacturer: str
    mode: str
    status: str = "queued"
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    progress: float = 0.0
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _sync_logs_store() -> SyncLogsStore | None:
    if not settings.google_spreadsheet_id or not settings.google_sheets_credentials_path:
        return None
    try:
        spreadsheet = open_admin_spreadsheet(settings.google_sheets_credentials_path, settings.google_spreadsheet_id)
        return SyncLogsStore(spreadsheet)
    except Exception:  # noqa: BLE001 - job history is best-effort; must never break the sync it's tracking
        logger.exception("Could not open Sync_logs sheet -- this job's history will be in-memory only")
        return None


def create(job_id: str, manufacturer: str, mode: str) -> JobRecord:
    record = JobRecord(job_id=job_id, manufacturer=manufacturer, mode=mode, status="queued")
    with _lock:
        _jobs[job_id] = record

    store = _sync_logs_store()
    if store:
        try:
            store.create(job_id, manufacturer, mode)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write Sync_logs row for job start (job_id=%s)", job_id)
    return record


def mark_running(job_id: str, started_at: datetime) -> None:
    with _lock:
        record = _jobs.get(job_id)
        if record:
            record.status = "running"
            record.started_at = started_at


def update_progress(job_id: str, *, total: int, processed: int, success: int, failed: int, skipped: int) -> None:
    """In-memory only -- called after every crawled item, must stay cheap."""
    with _lock:
        record = _jobs.get(job_id)
        if not record:
            return
        record.total = total
        record.processed = processed
        record.success = success
        record.failed = failed
        record.skipped = skipped
        record.progress = round((processed / total) * 100, 1) if total else 0.0


def finish(
    job_id: str,
    *,
    status: str,
    total: int,
    processed: int,
    success: int,
    failed: int,
    skipped: int,
    warnings: list[str],
    completed_at: datetime,
) -> None:
    with _lock:
        record = _jobs.get(job_id)
        if record:
            record.status = status
            record.total = total
            record.processed = processed
            record.success = success
            record.failed = failed
            record.skipped = skipped
            record.progress = 100.0
            record.warnings = warnings[:200]
            record.completed_at = completed_at

    store = _sync_logs_store()
    if store:
        try:
            store.update(
                job_id,
                **{
                    "Trạng thái": status,
                    "Tổng": total,
                    "Đã xử lý": processed,
                    "Thành công": success,
                    "Lỗi": failed,
                    "Bỏ qua": skipped,
                    "Tiến độ (%)": 100.0,
                    "Hoàn tất lúc": completed_at.isoformat(timespec="seconds"),
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write Sync_logs row for job completion (job_id=%s)", job_id)


def fail(
    job_id: str,
    *,
    error: str,
    total: int,
    processed: int,
    success: int,
    failed: int,
    skipped: int,
    completed_at: datetime,
) -> None:
    with _lock:
        record = _jobs.get(job_id)
        if record:
            record.status = "failed"
            record.error = error
            record.total = total
            record.processed = processed
            record.success = success
            record.failed = failed
            record.skipped = skipped
            record.completed_at = completed_at

    store = _sync_logs_store()
    if store:
        try:
            store.update(
                job_id,
                **{
                    "Trạng thái": "failed",
                    "Chi tiết lỗi": error,
                    "Tổng": total,
                    "Đã xử lý": processed,
                    "Thành công": success,
                    "Lỗi": failed,
                    "Bỏ qua": skipped,
                    "Hoàn tất lúc": completed_at.isoformat(timespec="seconds"),
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write Sync_logs row for job failure (job_id=%s)", job_id)


def get(job_id: str) -> JobRecord | None:
    with _lock:
        record = _jobs.get(job_id)
    if record:
        return record

    store = _sync_logs_store()
    if not store:
        return None
    row = store.get(job_id)
    return _record_from_row(row) if row else None


def list_recent(*, manufacturer: str | None = None, limit: int = 20) -> list[JobRecord]:
    store = _sync_logs_store()
    if not store:
        with _lock:
            records = list(_jobs.values())
        if manufacturer:
            records = [r for r in records if r.manufacturer == manufacturer]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[:limit]

    rows = store.list_recent(manufacturer=manufacturer, limit=limit)
    return [_record_from_row(row) for row in rows]


def _as_int(value: str | None) -> int:
    try:
        return int(float(value)) if value else 0
    except ValueError:
        return 0


def _as_float(value: str | None) -> float:
    try:
        return float(value) if value else 0.0
    except ValueError:
        return 0.0


def _as_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _record_from_row(row: dict[str, str]) -> JobRecord:
    return JobRecord(
        job_id=row.get("Job ID", ""),
        manufacturer=row.get("Hãng", ""),
        mode=row.get("Chế độ", "full"),
        status=row.get("Trạng thái", "unknown"),
        total=_as_int(row.get("Tổng")),
        processed=_as_int(row.get("Đã xử lý")),
        success=_as_int(row.get("Thành công")),
        failed=_as_int(row.get("Lỗi")),
        skipped=_as_int(row.get("Bỏ qua")),
        progress=_as_float(row.get("Tiến độ (%)")),
        error=row.get("Chi tiết lỗi") or None,
        started_at=_as_datetime(row.get("Bắt đầu lúc")),
        completed_at=_as_datetime(row.get("Hoàn tất lúc")),
        created_at=_as_datetime(row.get("Tạo lúc")) or datetime.now(timezone.utc),
    )
