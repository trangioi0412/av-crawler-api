"""Sync job status vocabulary, shared by the engine, the API, and the DB layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class SyncMode(str, Enum):
    FULL = "full"
    INCREMENTAL = "incremental"


@dataclass
class SyncResult:
    job_id: str | None
    manufacturer: str
    mode: str
    status: JobStatus
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
