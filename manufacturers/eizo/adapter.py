"""EIZO manufacturer adapter.

All selectors and the discovery strategy below were verified against the
live site on 2026-09-23 (see `manufacturers/eizo/config.py` for why
discovery seeds from one known product page per division instead of a
sitemap). Nothing outside this package knows EIZO's URL patterns or HTML
structure.
"""
from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.logging import get_logger
from core.models.product import RawProduct
from manufacturers.base import BaseManufacturerAdapter

logger = get_logger(__name__)

# Matches an individual product-detail URL within one of the four covered
# divisions, e.g. "/products/coloredge/cg3200x/". Deliberately doesn't
# match the division's own index ("/products/coloredge/") or family pages
# ending in ".html" (e.g. "coloredge_cg.html") -- neither is a product.
_PRODUCT_URL_RE = re.compile(r"/products/(coloredge|flexscan|duravision|radiforce)/([a-z0-9_-]+)/$", re.IGNORECASE)

# "/products/coloredge/ambassadors/" matches the URL shape above (it's in
# the same #side nav as real products) but is a brand-ambassador bio page,
# not a product -- the one such page found verifying all four divisions.
_NON_PRODUCT_SLUGS = {"ambassadors"}

_DIVISION_DISPLAY_NAMES = {
    "coloredge": "ColorEdge",
    "flexscan": "FlexScan",
    "duravision": "DuraVision",
    "radiforce": "RadiForce",
}

_DOC_EXTENSIONS = (".pdf",)


class EizoAdapter(BaseManufacturerAdapter):
    def discover_product_urls(self) -> Iterator[str]:
        seen: set[str] = set()
        for seed_path in self.config.category_paths:
            seed_url = urljoin(self.config.base_url, seed_path)
            html = self.http.get_text(seed_url)
            soup = BeautifulSoup(html, "lxml")

            nav = soup.select_one("#side")
            if not nav:
                logger.warning("EIZO seed page %s has no #side nav -- skipping its division", seed_url)
                continue

            for a in nav.select("a[href]"):
                href = a.get("href")
                if not href:
                    continue
                match = _PRODUCT_URL_RE.search(href)
                if not match or match.group(2).lower() in _NON_PRODUCT_SLUGS:
                    continue
                url = urljoin(seed_url, href)
                if url in seen:
                    continue
                seen.add(url)
                yield url

    def fetch_product(self, url: str) -> str:
        return self.http.get_text(url)

    def parse(self, raw_content: str, source_url: str) -> RawProduct:
        soup = BeautifulSoup(raw_content, "lxml")

        name = self._parse_name(soup)
        model = self._model_from_url(source_url)
        category = self._category_from_url(source_url)
        subcategory = self._parse_subcategory(soup)
        description = self._parse_description(soup)
        features = self._parse_features(soup)
        image_urls = self._parse_images(soup, source_url)
        specifications = self._parse_specifications(soup)
        document_urls = self._parse_documents(soup, source_url)

        return RawProduct(
            manufacturer="eizo",
            source_url=source_url,
            name=name,
            model=model,
            category=category,
            subcategory=subcategory,
            description=description,
            features=features,
            image_urls=image_urls,
            specifications=specifications,
            document_urls=document_urls,
            raw={},
        )

    # -- selector helpers -------------------------------------------------

    @staticmethod
    def _parse_name(soup: BeautifulSoup) -> str | None:
        """The page `<title>` (e.g. "ColorEdge CG3200X | EIZO") is more
        reliable than any on-page heading -- the visible "title" in the
        hero area is actually an `<img>` (alt text only, no real markup
        to select), and `.title1` is reused for dozens of unrelated
        headings throughout the page's marketing sections.
        """
        if not soup.title or not soup.title.string:
            return None
        return soup.title.string.split("|")[0].strip() or None

    @staticmethod
    def _model_from_url(url: str) -> str | None:
        match = _PRODUCT_URL_RE.search(url)
        return match.group(2).upper() if match else None

    @staticmethod
    def _category_from_url(url: str) -> str | None:
        match = _PRODUCT_URL_RE.search(url)
        return _DIVISION_DISPLAY_NAMES.get(match.group(1).lower()) if match else None

    @staticmethod
    def _parse_subcategory(soup: BeautifulSoup) -> str | None:
        """The `#side` sidebar (also used for discovery -- see
        `discover_product_urls`) marks the current product's sub-series
        with `<span class="on">`, e.g. "CG Series" for a ColorEdge CG
        model, "Basic" for a FlexScan model. A RadiForce model can appear
        under more than one series grouping (e.g. both "Multi-Series" and
        "Mammo-Series") -- the first one is used, a reasonable primary
        pick since there's no way to tell which the site itself considers
        "the" series.
        """
        marker = soup.select_one("#side span.on")
        return marker.get_text(strip=True) if marker else None

    @staticmethod
    def _parse_features(soup: BeautifulSoup) -> list[str]:
        """The "Features" tab (`#tab01_content`) is long marketing prose
        with embedded images/video, not a bullet list -- but most product
        pages open it with a `.notes-frame` table of contents linking to
        each named feature section (e.g. "EIZO's Proprietary ABL Control
        System"), which makes a clean feature list on its own. Products
        whose page has no such ToC (verified on some DuraVision models)
        just get an empty list, same as any other field this site doesn't
        expose in a structured form.
        """
        toc = soup.select_one("#tab01_content .notes-frame")
        if not toc:
            return []
        return [a.get_text(strip=True) for a in toc.select("a.arrow_bottom") if a.get_text(strip=True)]

    @staticmethod
    def _parse_description(soup: BeautifulSoup) -> str | None:
        tagline = soup.select_one("#spec_area .discription")
        return tagline.get_text(" ", strip=True) if tagline else None

    @staticmethod
    def _parse_images(soup: BeautifulSoup, source_url: str) -> list[str]:
        images = soup.select("#product_photo .photo img[src]")
        return [urljoin(source_url, img["src"]) for img in images if img.get("src")]

    @staticmethod
    def _parse_specifications(soup: BeautifulSoup) -> dict[str, str]:
        """`#tab02_content table.standard` is the model's own spec table.
        A later, unrelated `table.standard` further down the page (a
        "Compatibility" changelog, verified on FlexScan pages) is outside
        `#tab02_content` and so isn't matched here. Section-divider rows
        (`th.head2` with an empty/"&nbsp;"-only value, e.g. "Panel") are
        skipped by simply requiring a non-empty value -- "Model
        Variations" is also `th.head2` but has real content, so it's kept.
        """
        table = soup.select_one("#tab02_content table.standard")
        if not table:
            return {}

        specs: dict[str, str] = {}
        for row in table.select("tr"):
            th = row.select_one("th")
            td = row.select_one("td")
            if not th or not td:
                continue
            key = th.get_text(" ", strip=True)
            value = td.get_text(" ", strip=True)
            if not key or not value:
                continue
            specs[key] = value
        return specs

    @staticmethod
    def _parse_documents(soup: BeautifulSoup, source_url: str) -> list[str]:
        seen: set[str] = set()
        urls: list[str] = []
        for a in soup.select("a[href]"):
            href = a["href"]
            if not href.lower().endswith(_DOC_EXTENSIONS):
                continue
            url = urljoin(source_url, href)
            if url not in seen:
                seen.add(url)
                urls.append(url)
        return urls
