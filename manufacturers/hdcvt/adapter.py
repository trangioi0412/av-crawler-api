"""HDCVT manufacturer adapter -- Manufacturer Adapter #1, used to validate
the generic sync architecture. All selectors and the discovery strategy
below were verified against the live site on 2026-09-18 (see
`manufacturers/hdcvt/config.py` and `backend/tests/fixtures/hdcvt_*.html`
for saved snapshots used by the unit tests).

Nothing outside this package knows HDCVT's URL patterns or HTML structure.
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

# Matches HDCVT product-detail paths seen in sitemap.xml, e.g.
# "/HDBaseTExtender/330.html" or "/SDVOE-9/298.html". Category/listing and
# informational pages (e.g. "/HDBaseTExtender/", "/CompanyProfile/") don't
# end in "/<digits>.html" and are excluded.
_PRODUCT_URL_RE = re.compile(r"/([^/]+)/\d+\.html$")

# The site's "NEWS" (Notice, IndustryNews) and "SOLUTIONS" (Medical, game,
# Command, VideoConference) nav sections reuse the same "/<slug>/<id>.html"
# URL shape as real products but aren't catalog items -- verified by
# crawling a live sample of each: they render no product name/image/spec
# block at all. Excluded here so the sync doesn't waste requests on them or
# report them as crawl "failures".
_NON_PRODUCT_PATH_SLUGS = {"notice", "industrynews", "medical", "game", "command", "videoconference"}

_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")

_SECTION_HEADER_KEYS = {"specifications", "technical"}


class HdcvtAdapter(BaseManufacturerAdapter):
    def discover_product_urls(self) -> Iterator[str]:
        sitemap_url = urljoin(self.config.base_url, "/sitemap.xml")
        xml_text = self.http.get_text(sitemap_url)
        root = ElementTree.fromstring(xml_text)

        # The sitemap namespace varies by generator; strip it defensively
        # instead of hardcoding the exact xmlns.
        seen: set[str] = set()
        for loc in root.iter():
            if not loc.tag.endswith("loc") or not loc.text:
                continue
            url = loc.text.strip()
            match = _PRODUCT_URL_RE.search(url)
            if not match or url in seen:
                continue
            if match.group(1).lower() in _NON_PRODUCT_PATH_SLUGS:
                continue
            seen.add(url)
            yield url

    def fetch_product(self, url: str) -> str:
        return self.http.get_text(url)

    def parse(self, raw_content: str, source_url: str) -> RawProduct:
        soup = BeautifulSoup(raw_content, "lxml")

        category, subcategory = self._parse_breadcrumb(soup)
        name = self._parse_name(soup)
        model, description, features = self._parse_intro(soup)
        image_urls = self._parse_images(soup)
        specifications = self._parse_specifications(soup)
        document_urls = self._parse_documents(soup)

        return RawProduct(
            manufacturer="hdcvt",
            source_url=source_url,
            name=name,
            model=model,
            category=category,
            subcategory=subcategory,
            description=description,
            image_urls=image_urls,
            document_urls=document_urls,
            specifications=specifications,
            features=features,
            raw={},
        )

    # -- selector helpers -------------------------------------------------
    # Each of these targets one verified region of the page. Kept as small
    # functions so a future markup change only requires touching the one
    # helper that broke, not the whole adapter.

    @staticmethod
    def _parse_breadcrumb(soup: BeautifulSoup) -> tuple[str | None, str | None]:
        position = soup.select_one(".position")
        if not position:
            return None, None
        crumbs = [a.get_text(strip=True) for a in position.select("a") if a.get_text(strip=True)]
        # Observed shape: Home > PRODUCTS > <Category> > <Subcategory>
        crumbs = [c for c in crumbs if c.lower() not in ("home", "products")]
        if len(crumbs) >= 2:
            return crumbs[0], crumbs[1]
        if len(crumbs) == 1:
            return crumbs[0], None
        return None, None

    @staticmethod
    def _parse_name(soup: BeautifulSoup) -> str | None:
        heading = soup.select_one(".pro-ms h1")
        if heading:
            return heading.get_text(strip=True)
        heading = soup.select_one("h1")
        return heading.get_text(strip=True) if heading else None

    @staticmethod
    def _parse_intro(soup: BeautifulSoup) -> tuple[str | None, str | None, list[str]]:
        """The product name/model/marketing copy live together in
        `.pro-ms .f-lt`, with the model number in the first `<strong>` and
        the rest as plain paragraphs -- there's no dedicated "model" field
        in the CMS. Feature highlights are written as "☆ <feature text>"
        bullet lines within that same prose (verified against multiple real
        product pages), so they're split out into a separate list instead
        of staying embedded in the description.
        """
        container = soup.select_one(".pro-ms .f-lt")
        if not container:
            return None, None, []

        model = None
        first_strong = container.select_one("strong")
        if first_strong:
            candidate = first_strong.get_text(strip=True)
            # Model numbers on this site look like "HBT-E70S": short,
            # alphanumeric with hyphens, no spaces.
            if candidate and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-/]{2,30}", candidate):
                model = candidate

        full_text = container.get_text(" ", strip=True)
        segments = full_text.split("☆")
        description = segments[0].strip() or None
        features = [seg.strip() for seg in segments[1:] if seg.strip()]
        return model, description, features

    @staticmethod
    def _parse_images(soup: BeautifulSoup) -> list[str]:
        images = soup.select(".swiper-wrapper .swiper-slide img[src]")
        return [img["src"] for img in images if img.get("src")]

    @staticmethod
    def _parse_specifications(soup: BeautifulSoup) -> dict[str, str]:
        table = soup.select_one(".t170406 table")
        if not table:
            return {}

        specs: dict[str, str] = {}
        for row in table.select("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.select("td")]
            cells = [c for c in cells if c]
            if len(cells) < 2:
                continue
            key, *values = cells
            if key.lower() in _SECTION_HEADER_KEYS:
                # Decorative section-divider row (e.g. the rowspan
                # "Specifications" label paired with a "Technical" header).
                continue
            specs[key] = " / ".join(values)
        return specs

    @staticmethod
    def _parse_documents(soup: BeautifulSoup) -> list[str]:
        panel = soup.select_one(".page.canshu")
        if not panel:
            return []
        links = []
        for a in panel.select("a[href]"):
            href = a["href"]
            if href.lower().endswith(_DOC_EXTENSIONS):
                links.append(href)
        return links
