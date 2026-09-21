"""Resolves a manufacturer key to a concrete adapter, whether it's a
hand-written code adapter (e.g. `manufacturers/hdcvt`, self-registered into
`core.registry`) or a brand onboarded through the "Yeu cau them hang moi"
flow, whose crawl source (website URL) lives in the System_Config sheet
rather than in code.

This is what lets `GET /api/manufacturers` and `POST /api/sync/manufacturer`
work over *every* brand sheet in the spreadsheet (see
`services/admin_sheets.py::list_brand_sheet_names`), not just the ones with
a hand-written adapter -- without the engine or the routes needing to know
which brands are code-registered and which are sheet-driven.
"""
from __future__ import annotations

from core.config import settings
from core.registry import UnknownManufacturerError, registry
from manufacturers.base import BaseManufacturerAdapter, ManufacturerConfig
from manufacturers.generic_ai.adapter import GenericAIAdapter
from services.admin_sheets import SystemConfigStore, open_admin_spreadsheet


def build_ai_config(key: str, display_name: str, base_url: str) -> ManufacturerConfig:
    return ManufacturerConfig(
        key=key,
        display_name=display_name,
        base_url=base_url,
        request_delay_seconds=1.5,
        timeout_seconds=20.0,
        max_products=200,  # bound cost: each product costs one local LLM call
    )


def _system_config_store() -> SystemConfigStore:
    if not settings.google_spreadsheet_id or not settings.google_sheets_credentials_path:
        raise RuntimeError(
            "Google Sheets is not configured (GOOGLE_SPREADSHEET_ID / credentials) -- "
            "System_Config is the only place brand websites are looked up."
        )
    spreadsheet = open_admin_spreadsheet(settings.google_sheets_credentials_path, settings.google_spreadsheet_id)
    return SystemConfigStore(spreadsheet)


def resolve_manufacturer(key: str) -> tuple[type[BaseManufacturerAdapter], ManufacturerConfig]:
    """Returns (adapter_class, config) for `key`.

    1. A hand-written adapter registered in code (e.g. "hdcvt") always wins.
    2. Otherwise, looks up the brand's website in System_Config and uses
       the generic AI-assisted adapter.

    Raises UnknownManufacturerError if neither knows about `key`.
    """
    normalized = key.strip().lower()
    if registry.is_registered(normalized):
        return registry.get_adapter_class(normalized), registry.get_config(normalized)

    row = _system_config_store().get_manufacturer(normalized)
    if row is None or not row.get("Website"):
        raise UnknownManufacturerError(normalized, known=sorted(c.key for c in registry.list_manufacturers()))

    config = build_ai_config(normalized, row.get("Tên hãng") or normalized, row["Website"])
    return GenericAIAdapter, config
