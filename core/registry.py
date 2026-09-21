"""Manufacturer registry: the only place that maps a manufacturer key to
concrete adapter code.

The sync engine calls `registry.get(key)` and never contains
`if manufacturer == "hdcvt"` style branching. Each adapter module registers
itself on import (see `manufacturers/hdcvt/__init__.py`), so adding a new
manufacturer never requires editing this file or the engine.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from services.http_client import CrawlHttpClient

if TYPE_CHECKING:
    # Deferred: importing `manufacturers.base` at module load time would
    # import the `manufacturers` package, which imports every adapter,
    # which imports `core.registry` to self-register -- a circular import.
    # Only type checkers need this; `from __future__ import annotations`
    # keeps it out of the runtime path.
    from manufacturers.base import BaseManufacturerAdapter, ManufacturerConfig


class UnknownManufacturerError(Exception):
    def __init__(self, key: str, known: list[str]) -> None:
        self.key = key
        self.known = known
        super().__init__(f"Unknown manufacturer '{key}'. Known manufacturers: {', '.join(known) or '(none registered)'}")


class ManufacturerRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, type[BaseManufacturerAdapter]] = {}
        self._configs: dict[str, ManufacturerConfig] = {}

    def register(self, key: str, adapter_cls: type[BaseManufacturerAdapter], config: ManufacturerConfig) -> None:
        normalized = key.strip().lower()
        if normalized in self._adapters:
            raise ValueError(f"Manufacturer '{normalized}' is already registered")
        self._adapters[normalized] = adapter_cls
        self._configs[normalized] = config

    def is_registered(self, key: str) -> bool:
        return key.strip().lower() in self._adapters

    def list_manufacturers(self) -> list[ManufacturerConfig]:
        return list(self._configs.values())

    def get_config(self, key: str) -> ManufacturerConfig:
        normalized = key.strip().lower()
        if normalized not in self._configs:
            raise UnknownManufacturerError(normalized, sorted(self._configs.keys()))
        return self._configs[normalized]

    def get(self, key: str) -> BaseManufacturerAdapter:
        """Instantiate the adapter registered for `key`, wired up with a
        fresh HTTP client configured from that manufacturer's own settings.
        """
        normalized = key.strip().lower()
        if normalized not in self._adapters:
            raise UnknownManufacturerError(normalized, sorted(self._adapters.keys()))

        return self.get_ad_hoc(self._adapters[normalized], self._configs[normalized])

    def get_ad_hoc(
        self, adapter_cls: type[BaseManufacturerAdapter], config: ManufacturerConfig
    ) -> BaseManufacturerAdapter:
        """Instantiate an adapter class directly from a config, without it
        being registered. Used for the AI-assisted "preview before you
        approve" flow (`api/routes/manufacturer_requests.py`), where a
        manufacturer might never end up registered at all if the preview
        looks bad.
        """
        http_client = CrawlHttpClient(
            user_agent=config.user_agent or "DataCrawlerSyncBot/1.0",
            request_delay_seconds=config.request_delay_seconds,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            respect_robots_txt=config.respect_robots_txt,
        )
        return adapter_cls(config, http_client)


# Module-level singleton shared by the whole service.
registry = ManufacturerRegistry()
