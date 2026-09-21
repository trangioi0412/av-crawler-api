"""Common interface every manufacturer adapter implements.

This module is the entire contract between the generic sync engine and any
manufacturer-specific code. The engine only ever calls `adapter.crawl()`,
`adapter.config`, and `registry.get(key)` -- it never imports a concrete
adapter class, and it never branches on manufacturer name.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterable, Iterator

from core.models.product import CrawlResult, RawProduct
from services.http_client import CrawlHttpClient


@dataclass(frozen=True)
class ManufacturerConfig:
    """Manufacturer-specific settings, kept out of the core engine.

    Adding a manufacturer means creating one of these plus an adapter class
    -- never editing shared code.
    """

    key: str
    display_name: str
    base_url: str
    category_paths: tuple[str, ...] = field(default_factory=tuple)
    request_delay_seconds: float = 1.0
    timeout_seconds: float = 15.0
    max_retries: int = 3
    user_agent: str | None = None
    respect_robots_txt: bool = True
    max_products: int | None = None  # optional cap on discovered URLs (e.g. to bound AI-extraction cost)


class BaseManufacturerAdapter(ABC):
    """Base class for all manufacturer adapters.

    Subclasses implement the three manufacturer-specific steps
    (`discover_product_urls`, `fetch_product`, `parse`). This base class
    wires them together in `crawl()` and, critically, isolates per-product
    failures so one broken page doesn't abort the whole sync -- that
    resilience lives here once, not duplicated in every adapter.
    """

    def __init__(self, config: ManufacturerConfig, http_client: CrawlHttpClient) -> None:
        self.config = config
        self.http = http_client

    @abstractmethod
    def discover_product_urls(self) -> Iterator[str]:
        """Yield absolute product-detail URLs by crawling category/listing pages."""

    @abstractmethod
    def fetch_product(self, url: str) -> str:
        """Fetch the raw page content (HTML) for a single product URL."""

    @abstractmethod
    def parse(self, raw_content: str, source_url: str) -> RawProduct:
        """Parse raw page content into a RawProduct using canonical field names."""

    def crawl_urls(self, urls: Iterable[str]) -> Iterator[CrawlResult]:
        """Fetch + parse a known list of product URLs, yielding one
        CrawlResult per URL. Never raises for a single-product failure --
        the error is captured on the CrawlResult instead so the pipeline
        can keep going. Split out from `crawl()` so callers that need the
        total product count up front (e.g. for job progress) can call
        `discover_product_urls()` once and reuse the list here, instead of
        crawling the category/listing pages twice.
        """
        for url in urls:
            try:
                raw_content = self.fetch_product(url)
                product = self.parse(raw_content, url)
                yield CrawlResult(source_url=url, raw_product=product)
            except Exception as exc:  # noqa: BLE001 - intentional: isolate per-item failures
                yield CrawlResult(source_url=url, error=f"{type(exc).__name__}: {exc}")

    def crawl(self) -> Iterator[CrawlResult]:
        """Convenience: discover and crawl in one call, for callers that
        don't need the total count ahead of time.
        """
        yield from self.crawl_urls(self.discover_product_urls())
