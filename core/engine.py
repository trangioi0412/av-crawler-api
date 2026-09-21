"""The generic synchronization engine.

`sync_manufacturer_data()` is the single entry point every manufacturer sync
goes through. It contains zero manufacturer-specific logic: it resolves an
adapter (see `core/manufacturer_resolution.py`), then runs the fixed
pipeline

    crawl -> normalize -> validate -> deduplicate -> transform -> persist

against whatever that adapter yields. Adding a new manufacturer never
touches this file.

Persistence is Google Sheets (see `services/google_sheets.py`) -- there is
no database. Cross-run deduplication (create vs. update an existing row) is
therefore delegated entirely to `GoogleSheetsExporter.upsert_rows`, which
matches against the live sheet by natural key; this module's `Deduplicator`
only needs to catch duplicates *within* one crawl run (e.g. a product listed
under two categories) -- see the `deduplicator.resolve(candidate, {})` call
below.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.config import settings
from core.logging import get_logger
from core.manufacturer_resolution import resolve_manufacturer
from core.models.job import JobStatus, SyncMode, SyncResult
from core.models.product import CanonicalProduct, ValidationStatus
from core.pipeline.deduplicator import DedupAction, Deduplicator
from core.pipeline.normalizer import Normalizer
from core.pipeline.transformer import Transformer
from core.pipeline.validator import Validator
from core.registry import registry
from manufacturers.base import ManufacturerConfig
from services import job_store
from services.google_sheets import GoogleSheetsExporter, build_sheet_row

logger = get_logger(__name__)


def sync_manufacturer_data(manufacturer: str, *, mode: str = SyncMode.FULL.value, job_id: str | None = None) -> SyncResult:
    """Synchronize one manufacturer's product catalog.

    `manufacturer` resolves to an adapter at runtime (a hand-written code
    adapter, or a sheet-driven AI adapter via System_Config) -- never a
    branch in an if/elif chain. Call it the same way for every manufacturer:

        sync_manufacturer_data(manufacturer="hdcvt")
        sync_manufacturer_data(manufacturer="yealink")   # once onboarded via System_Config
    """
    log = get_logger(__name__)
    started_at = datetime.now(timezone.utc)

    if mode not in (SyncMode.FULL.value,):
        raise NotImplementedError(
            f"Sync mode '{mode}' is not implemented yet. Only 'full' is supported today; "
            "the pipeline (dedup by key, create-vs-update) already supports incremental "
            "sync once an adapter can report 'changed since <cursor>'."
        )

    manufacturer_key = manufacturer.strip().lower()
    adapter_cls, config = resolve_manufacturer(manufacturer_key)  # raises UnknownManufacturerError for unknown keys
    adapter = registry.get_ad_hoc(adapter_cls, config)
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
        if job_id:
            job_store.mark_running(job_id, started_at)

        urls = list(adapter.discover_product_urls())
        total = len(urls)
        log.info("Products discovered: %d", total, extra=log_ctx)
        if job_id:
            job_store.update_progress(job_id, total=total, processed=0, success=0, failed=0, skipped=0)

        for crawl_result in adapter.crawl_urls(urls):
            processed += 1

            if not crawl_result.ok:
                failed += 1
                msg = f"{crawl_result.source_url}: {crawl_result.error}"
                warnings.append(msg)
                log.error("Failed to crawl product: %s", msg, extra=log_ctx)
                _flush_progress(job_id, total, processed, success, failed, skipped)
                continue

            candidate = normalizer.normalize(crawl_result.raw_product, base_url=adapter.config.base_url)
            validation = validator.validate(candidate)

            if validation.status == ValidationStatus.INVALID:
                failed += 1
                msg = f"{candidate.source_url}: INVALID - {'; '.join(validation.messages)}"
                warnings.append(msg)
                log.error("Rejected invalid product: %s", msg, extra=log_ctx)
                _flush_progress(job_id, total, processed, success, failed, skipped)
                continue

            if validation.status == ValidationStatus.WARNING:
                msg = f"{candidate.source_url}: WARNING - {'; '.join(validation.messages)}"
                warnings.append(msg)
                log.warning(msg, extra=log_ctx)

            # Cross-run identity (create vs. update an existing sheet row) is
            # GoogleSheetsExporter's job now -- pass an empty index so this
            # only catches duplicates seen earlier in *this* run.
            decision = deduplicator.resolve(candidate, {})

            if decision.action == DedupAction.SKIP_DUPLICATE_IN_RUN:
                skipped += 1
                log.warning(
                    "Skipped duplicate within this sync run: %s (key=%s)",
                    candidate.source_url,
                    decision.dedup_key,
                    extra=log_ctx,
                )
            else:
                success += 1
                synced_products.append(candidate)

            log.info("Processing product %d/%d", processed, total, extra=log_ctx)
            _flush_progress(job_id, total, processed, success, failed, skipped)

        try:
            _persist_to_google_sheets(adapter.config, synced_products, log_ctx)
        except Exception as exc:  # noqa: BLE001 - surfaced as a job failure below, not swallowed
            # Google Sheets is the only persistence layer now: a failed
            # export means nothing from this run was actually saved, even
            # though crawling/validation succeeded -- that must show up as
            # a failed job, not a quiet no-op.
            completed_at = datetime.now(timezone.utc)
            error = f"Google Sheets export failed: {type(exc).__name__}: {exc}"
            log.exception("Google Sheets export failed -- sync results were NOT persisted", extra=log_ctx)
            if job_id:
                job_store.fail(
                    job_id, error=error, total=total, processed=processed,
                    success=success, failed=failed, skipped=skipped, completed_at=completed_at,
                )
            return SyncResult(
                job_id=job_id, manufacturer=manufacturer_key, mode=mode, status=JobStatus.FAILED,
                total=total, processed=processed, success=success, failed=failed, skipped=skipped,
                started_at=started_at, completed_at=completed_at, error=error, warnings=warnings,
            )

        completed_at = datetime.now(timezone.utc)
        if failed == 0:
            status = JobStatus.COMPLETED
        elif success > 0 or skipped > 0:
            status = JobStatus.COMPLETED_WITH_WARNINGS
        else:
            status = JobStatus.FAILED

        if job_id:
            job_store.finish(
                job_id, status=status.value, total=total, processed=processed, success=success,
                failed=failed, skipped=skipped, warnings=warnings, completed_at=completed_at,
            )

        log.info(
            "Sync completed: status=%s success=%d failed=%d skipped=%d",
            status.value, success, failed, skipped, extra=log_ctx,
        )

        return SyncResult(
            job_id=job_id, manufacturer=manufacturer_key, mode=mode, status=status,
            total=total, processed=processed, success=success, failed=failed, skipped=skipped,
            started_at=started_at, completed_at=completed_at, warnings=warnings,
        )
    except Exception as exc:  # noqa: BLE001 - top-level guard: a crash must still mark the job failed
        completed_at = datetime.now(timezone.utc)
        log.exception("Sync failed with an unexpected error", extra=log_ctx)
        if job_id:
            try:
                job_store.fail(
                    job_id, error=f"{type(exc).__name__}: {exc}", total=total, processed=processed,
                    success=success, failed=failed, skipped=skipped, completed_at=completed_at,
                )
            except Exception:  # noqa: BLE001
                log.exception("Additionally failed to persist job-failure state", extra=log_ctx)
        return SyncResult(
            job_id=job_id, manufacturer=manufacturer_key, mode=mode, status=JobStatus.FAILED,
            total=total, processed=processed, success=success, failed=failed, skipped=skipped,
            started_at=started_at, completed_at=completed_at, error=f"{type(exc).__name__}: {exc}",
            warnings=warnings,
        )
    finally:
        adapter.http.close()


def _persist_to_google_sheets(
    config: ManufacturerConfig,
    products: list[CanonicalProduct],
    log_ctx: dict[str, str],
) -> None:
    """Exports this run's products to the manufacturer's Google Sheets tab.
    Raises if Sheets isn't configured or the export itself fails -- there is
    no other persistence layer to fall back on, so callers must treat a
    raised exception here as the sync having failed.
    """
    if not settings.google_spreadsheet_id or not settings.google_sheets_credentials_path:
        raise RuntimeError(
            "Google Sheets is not configured (GOOGLE_SPREADSHEET_ID / credentials) -- "
            "there is no database to persist products to instead."
        )
    if not products:
        logger.info("No products to persist this run", extra=log_ctx)
        return

    exporter = GoogleSheetsExporter(settings.google_sheets_credentials_path, settings.google_spreadsheet_id)
    rows = [build_sheet_row(p, brand_display_name=config.display_name) for p in products]
    summary = exporter.upsert_rows(config.key, rows)
    logger.info(
        "Google Sheets export: tab='%s' created=%d updated=%d",
        config.key, summary["created"], summary["updated"], extra=log_ctx,
    )


def _flush_progress(job_id: str | None, total: int, processed: int, success: int, failed: int, skipped: int) -> None:
    if not job_id:
        return
    job_store.update_progress(job_id, total=total, processed=processed, success=success, failed=failed, skipped=skipped)
