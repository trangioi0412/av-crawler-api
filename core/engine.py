"""The generic synchronization engine.

`sync_manufacturer_data()` is the single entry point every manufacturer sync
goes through. It contains zero manufacturer-specific logic: it resolves an
adapter from the `registry`, then runs the fixed pipeline

    crawl -> normalize -> validate -> deduplicate -> transform -> persist

against whatever that adapter yields. Adding a new manufacturer never
touches this file -- see `manufacturers/base.py` and
`manufacturers/hdcvt/adapter.py` for the extension point.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from core.config import settings
from core.logging import get_logger
from core.models.job import JobStatus, SyncMode, SyncResult
from core.models.product import CanonicalProduct, ValidationStatus
from core.pipeline.deduplicator import DedupAction, Deduplicator
from core.pipeline.normalizer import Normalizer
from core.pipeline.transformer import Transformer
from core.pipeline.validator import Validator
from core.registry import registry
from db.database import session_scope
from db.repository import ProductRepository, SyncJobRepository
from services.google_sheets import GoogleSheetsExporter, build_sheet_row

if TYPE_CHECKING:
    from manufacturers.base import ManufacturerConfig

logger = get_logger(__name__)


def sync_manufacturer_data(manufacturer: str, *, mode: str = SyncMode.FULL.value, job_id: str | None = None) -> SyncResult:
    """Synchronize one manufacturer's product catalog.

    This function is intentionally generic: `manufacturer` is a registry key
    resolved to an adapter at runtime, not a branch in an if/elif chain.
    Call it the same way for every manufacturer:

        sync_manufacturer_data(manufacturer="hdcvt")
        sync_manufacturer_data(manufacturer="yealink")   # once registered
        sync_manufacturer_data(manufacturer="cisco")     # once registered
    """
    log = get_logger(__name__)
    started_at = datetime.now(timezone.utc)

    if mode not in (SyncMode.FULL.value,):
        # Incremental sync needs a per-manufacturer "changed since" signal
        # (e.g. a sitemap lastmod or an API updated_at filter) that no
        # adapter currently provides. The dedup/update primitives below
        # already support it -- only `discover_product_urls()` would need
        # to accept a `since` cursor. Fail loudly instead of silently
        # running a full sync under an incremental label.
        raise NotImplementedError(
            f"Sync mode '{mode}' is not implemented yet. Only 'full' is supported today; "
            "the pipeline (dedup by key, create-vs-update) already supports incremental "
            "sync once an adapter can report 'changed since <cursor>'."
        )

    manufacturer_key = manufacturer.strip().lower()
    adapter = registry.get(manufacturer)  # raises UnknownManufacturerError for unknown keys
    manufacturer_key = adapter.config.key

    normalizer = Normalizer()
    validator = Validator()
    deduplicator = Deduplicator()
    transformer = Transformer()

    total = 0
    processed = 0
    success = 0
    failed = 0
    skipped = 0
    warnings: list[str] = []
    synced_products: list[CanonicalProduct] = []
    log_ctx = {"manufacturer": manufacturer_key, "job_id": job_id or "-"}

    log.info("Sync started", extra=log_ctx)

    try:
        with session_scope() as session:
            job_repo = SyncJobRepository(session) if job_id else None
            if job_repo:
                job_repo.update(job_id, status=JobStatus.RUNNING.value, started_at=started_at)
                session.commit()

            urls = list(adapter.discover_product_urls())
            total = len(urls)
            log.info("Products discovered: %d", total, extra=log_ctx)

            product_repo = ProductRepository(session)
            existing_index = product_repo.get_dedup_index(manufacturer_key)

            for crawl_result in adapter.crawl_urls(urls):
                processed += 1

                if not crawl_result.ok:
                    failed += 1
                    msg = f"{crawl_result.source_url}: {crawl_result.error}"
                    warnings.append(msg)
                    log.error("Failed to crawl product: %s", msg, extra=log_ctx)
                    _flush_progress(job_repo, job_id, total, processed, success, failed, skipped)
                    continue

                candidate = normalizer.normalize(crawl_result.raw_product, base_url=adapter.config.base_url)
                validation = validator.validate(candidate)

                if validation.status == ValidationStatus.INVALID:
                    failed += 1
                    msg = f"{candidate.source_url}: INVALID - {'; '.join(validation.messages)}"
                    warnings.append(msg)
                    log.error("Rejected invalid product: %s", msg, extra=log_ctx)
                    _flush_progress(job_repo, job_id, total, processed, success, failed, skipped)
                    continue

                if validation.status == ValidationStatus.WARNING:
                    msg = f"{candidate.source_url}: WARNING - {'; '.join(validation.messages)}"
                    warnings.append(msg)
                    log.warning(msg, extra=log_ctx)

                decision = deduplicator.resolve(candidate, existing_index)
                fields = transformer.transform(candidate)

                if decision.action == DedupAction.CREATE:
                    created = product_repo.create(fields)
                    existing_index[decision.dedup_key] = created.id
                    success += 1
                    synced_products.append(candidate)
                elif decision.action == DedupAction.UPDATE:
                    product_repo.update(decision.existing_product_id, fields)
                    success += 1
                    synced_products.append(candidate)
                else:  # SKIP_DUPLICATE_IN_RUN
                    skipped += 1
                    log.warning(
                        "Skipped duplicate within this sync run: %s (key=%s)",
                        candidate.source_url,
                        decision.dedup_key,
                        extra=log_ctx,
                    )

                log.info("Processing product %d/%d", processed, total, extra=log_ctx)
                _flush_progress(job_repo, job_id, total, processed, success, failed, skipped)

            completed_at = datetime.now(timezone.utc)
            if failed == 0:
                status = JobStatus.COMPLETED
            elif success > 0 or skipped > 0:
                status = JobStatus.COMPLETED_WITH_WARNINGS
            else:
                status = JobStatus.FAILED

            if job_repo:
                job_repo.update(
                    job_id,
                    status=status.value,
                    total=total,
                    processed=processed,
                    success=success,
                    failed=failed,
                    skipped=skipped,
                    progress=100.0,
                    warnings=warnings[:200],
                    completed_at=completed_at,
                )
                session.commit()

            _export_to_google_sheets(adapter.config, synced_products, log_ctx)

            log.info("Sync completed: status=%s success=%d failed=%d skipped=%d", status.value, success, failed, skipped, extra=log_ctx)

            return SyncResult(
                job_id=job_id,
                manufacturer=manufacturer_key,
                mode=mode,
                status=status,
                total=total,
                processed=processed,
                success=success,
                failed=failed,
                skipped=skipped,
                started_at=started_at,
                completed_at=completed_at,
                warnings=warnings,
            )
    except Exception as exc:  # noqa: BLE001 - top-level guard: a crash must still mark the job failed
        completed_at = datetime.now(timezone.utc)
        log.exception("Sync failed with an unexpected error", extra=log_ctx)
        if job_id:
            try:
                with session_scope() as session:
                    SyncJobRepository(session).update(
                        job_id,
                        status=JobStatus.FAILED.value,
                        total=total,
                        processed=processed,
                        success=success,
                        failed=failed,
                        skipped=skipped,
                        error=f"{type(exc).__name__}: {exc}",
                        completed_at=completed_at,
                    )
            except Exception:  # noqa: BLE001
                log.exception("Additionally failed to persist job-failure state", extra=log_ctx)
        return SyncResult(
            job_id=job_id,
            manufacturer=manufacturer_key,
            mode=mode,
            status=JobStatus.FAILED,
            total=total,
            processed=processed,
            success=success,
            failed=failed,
            skipped=skipped,
            started_at=started_at,
            completed_at=completed_at,
            error=f"{type(exc).__name__}: {exc}",
            warnings=warnings,
        )
    finally:
        adapter.http.close()


def _export_to_google_sheets(
    config: ManufacturerConfig,
    products: list[CanonicalProduct],
    log_ctx: dict[str, str],
) -> None:
    """Best-effort: exports the products this run created/updated to the
    manufacturer's Google Sheets tab, if GOOGLE_SPREADSHEET_ID is
    configured. Never raises -- a Sheets failure must not fail (or even
    mark as warning) a sync that already succeeded against the database.
    """
    if not settings.google_spreadsheet_id or not settings.google_sheets_credentials_path:
        return
    if not products:
        return

    try:
        exporter = GoogleSheetsExporter(settings.google_sheets_credentials_path, settings.google_spreadsheet_id)
        rows = [build_sheet_row(p, brand_display_name=config.display_name) for p in products]
        summary = exporter.upsert_rows(config.key, rows)
        logger.info(
            "Google Sheets export: tab='%s' created=%d updated=%d",
            config.key,
            summary["created"],
            summary["updated"],
            extra=log_ctx,
        )
    except Exception:  # noqa: BLE001 - best-effort sink, must never fail the sync
        logger.exception("Google Sheets export failed (database sync already succeeded)", extra=log_ctx)


def _flush_progress(
    job_repo: SyncJobRepository | None,
    job_id: str | None,
    total: int,
    processed: int,
    success: int,
    failed: int,
    skipped: int,
) -> None:
    if not job_repo or not job_id:
        return
    progress = round((processed / total) * 100, 1) if total else 0.0
    job_repo.update(
        job_id,
        total=total,
        processed=processed,
        success=success,
        failed=failed,
        skipped=skipped,
        progress=progress,
    )
    job_repo.session.commit()
