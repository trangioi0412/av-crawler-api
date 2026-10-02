"""VISSONIC manufacturer adapter.

All selectors and the discovery strategy below were verified against the
live site on 2026-09-23 (see `manufacturers/vissonic/config.py`). Nothing
outside this package knows VISSONIC's URL patterns or HTML structure.
"""
from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import urljoin
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from core.logging import get_logger
from core.models.product import RawProduct
from manufacturers.base import BaseManufacturerAdapter

logger = get_logger(__name__)

# Matches VISSONIC product-detail paths seen in sitemap.xml, e.g.
# "/products/vis-dcp2000-w.html". Pages under /products/ that end in "/"
# instead (e.g. "/products/cleacon-v1-wifi-wireless-conference-system/")
# are "solution" family pages listing several individual products each,
# not products themselves -- excluded since they don't match ".html$".
_PRODUCT_URL_RE = re.compile(r"/products/[^/]+\.html$")

_DOC_EXTENSIONS = (".pdf", ".doc", ".docx")

# Marks the end of the real marketing copy in the "Overview" tab -- past
# this point the page repeats the model number as free text ("Model for
# Order: VIS-DCP2000-W...................<description>"), which would
# otherwise pollute the last parsed feature bullet.
_MODEL_FOR_ORDER_MARKER = "Model for Order:"


class VissonicAdapter(BaseManufacturerAdapter):
    def discover_product_urls(self) -> Iterator[str]:
        sitemap_url = urljoin(self.config.base_url, "/sitemap.xml")
        xml_text = self.http.get_text(sitemap_url)
        root = ElementTree.fromstring(xml_text)

        seen: set[str] = set()
        for loc in root.iter():
            if not loc.tag.endswith("loc") or not loc.text:
                continue
            url = loc.text.strip()
            if not _PRODUCT_URL_RE.search(url) or url in seen:
                continue
            seen.add(url)
            yield url

    def fetch_product(self, url: str) -> str:
        return self.http.get_text(url)

    def parse(self, raw_content: str, source_url: str) -> RawProduct:
        soup = BeautifulSoup(raw_content, "lxml")

        name = self._parse_name(soup)
        model = self._parse_model(soup) or self._model_from_url(source_url)
        subcategory = self._parse_series(soup)
        short_description = self._parse_highlights(soup)
        description, features = self._parse_overview(soup)
        if not features and short_description:
            # Some product pages' "Overview" tab has no "●" bullets at all
            # (verified e.g. on /products/vis-uhd0809-vw-a.html) -- fall
            # back to the short spec highlights (`.cpms`) so "Main
            # Feature" isn't left empty when there's still something
            # useful to put there.
            features = short_description.split("\n")
        image_urls = self._parse_images(soup, source_url)
        document_urls = self._parse_documents(soup, source_url)

        return RawProduct(
            manufacturer="vissonic",
            source_url=source_url,
            name=name,
            model=model,
            subcategory=subcategory,
            description=description,
            short_description=short_description,
            image_urls=image_urls,
            document_urls=document_urls,
            specifications={},  # never published as an HTML table on this site -- see config.py
            features=features,
            raw={},
        )

    # -- selector helpers -------------------------------------------------

    @staticmethod
    def _parse_name(soup: BeautifulSoup) -> str | None:
        title = soup.select_one(".game-content .game-title")
        return title.get_text(strip=True) if title else None

    @staticmethod
    def _parse_model(soup: BeautifulSoup) -> str | None:
        date = soup.select_one(".game-content .game-date")
        return date.get_text(strip=True) or None if date else None

    @staticmethod
    def _model_from_url(url: str) -> str | None:
        """Falls back to deriving the model from the URL slug (e.g.
        "/products/vis-dcp2000-w.html" -> "VIS-DCP2000-W") for the rare
        page missing a `.game-date` element.
        """
        match = re.search(r"/products/([^/]+)\.html$", url)
        return match.group(1).upper() if match else None

    @staticmethod
    def _parse_series(soup: BeautifulSoup) -> str | None:
        tag = soup.select_one(".game-content .game-tag")
        return tag.get_text(strip=True) if tag else None

    @staticmethod
    def _parse_highlights(soup: BeautifulSoup) -> str | None:
        """`.cpms` holds a handful of short spec highlight phrases (e.g.
        "64 Channels Interpretation") shown next to the product photo --
        distinct from, and more concise than, the "Overview" tab's prose.
        """
        container = soup.select_one(".cpms")
        if not container:
            return None
        lines = [p.get_text(strip=True) for p in container.select("p") if p.get_text(strip=True)]
        return "\n".join(lines) or None

    @staticmethod
    def _parse_overview(soup: BeautifulSoup) -> tuple[str | None, list[str]]:
        """The "Overview" tab (`#tab1`) holds free-form marketing prose
        with feature bullets written as "● <feature text>" -- split out
        into a separate list instead of staying embedded in the
        description, same idea as HDCVT's "☆"-prefixed bullets.
        """
        container = soup.select_one("#tab1")
        if not container:
            return None, []

        full_text = container.get_text(" ", strip=True)
        full_text = full_text.split(_MODEL_FOR_ORDER_MARKER)[0]

        segments = full_text.split("●")
        description = segments[0].strip() or None
        features = [seg.strip() for seg in segments[1:] if seg.strip()]
        return description, features

    @staticmethod
    def _parse_images(soup: BeautifulSoup, source_url: str) -> list[str]:
        links = soup.select(".sp-wrap a[href]")
        return [urljoin(source_url, a["href"]) for a in links if a.get("href")]

    @staticmethod
    def _parse_documents(soup: BeautifulSoup, source_url: str) -> list[str]:
        links = soup.select("a.egames-btb[href]")
        return [
            urljoin(source_url, a["href"])
            for a in links
            if a.get("href") and a["href"].lower().endswith(_DOC_EXTENSIONS)
        ]
