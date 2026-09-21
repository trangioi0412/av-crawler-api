"""Generic, AI-assisted manufacturer adapter.

Used for manufacturers with no hand-written adapter yet: instead of
site-specific CSS selectors verified by a human, an LLM (via a local Ollama
server) reads the page's visible text and extracts product fields. This is
inherently lower-accuracy than a verified adapter like
`manufacturers/hdcvt/adapter.py` -- it's meant to be reviewed via the
"request a new manufacturer" -> preview -> approve flow
(`api/routes/manufacturer_requests.py`), not treated as equivalent to a
verified adapter.

One class is reused for every manufacturer that goes through this path;
`ManufacturerConfig.base_url` (and `.key`/`.display_name`) come from the
submitted request, not from code, so this is registered dynamically rather
than self-registering like `manufacturers/hdcvt`.
"""
from __future__ import annotations

from typing import Iterator
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from core.config import settings
from core.logging import get_logger
from core.models.product import RawProduct
from manufacturers.base import BaseManufacturerAdapter
from services.ollama_client import OllamaClient

logger = get_logger(__name__)

# Path keywords that are almost never individual product pages on any AV/
# electronics manufacturer site. Generic (not tuned to one manufacturer),
# used only to cut obvious noise before spending an LLM call on a page.
_EXCLUDED_PATH_KEYWORDS = (
    "news", "blog", "about", "contact", "support", "solution", "solutions",
    "career", "careers", "privacy", "terms", "sitemap", "search", "cart",
    "checkout", "login", "register", "account", "press", "faq", "policy",
    "warranty", "case-study", "case-studies",
)

_MAX_SUB_SITEMAPS = 20  # bound cost if a sitemap index has many children
_MAX_HOMEPAGE_FALLBACK_LINKS = 500


class GenericAIAdapter(BaseManufacturerAdapter):
    def __init__(self, config, http_client) -> None:
        super().__init__(config, http_client)
        self._ollama = OllamaClient(host=settings.ollama_host, model=settings.ollama_model)

    # -- discovery -----------------------------------------------------

    def discover_product_urls(self) -> Iterator[str]:
        urls = self._discover_via_sitemap()
        if not urls:
            urls = self._discover_via_homepage_links()

        seen: set[str] = set()
        filtered: list[str] = []
        for url in urls:
            if url in seen or not self._looks_like_product_url(url):
                continue
            seen.add(url)
            filtered.append(url)
            if self.config.max_products and len(filtered) >= self.config.max_products:
                break

        yield from filtered

    def _discover_via_sitemap(self) -> list[str]:
        for path in ("/sitemap.xml", "/sitemap_index.xml"):
            url = urljoin(self.config.base_url, path)
            try:
                xml_text = self.http.get_text(url)
                root = ElementTree.fromstring(xml_text)
            except Exception:  # noqa: BLE001 - probing multiple candidate paths
                continue

            locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
            if not locs:
                continue

            is_sitemap_index = all(loc.lower().endswith(".xml") for loc in locs)
            if not is_sitemap_index:
                return locs

            entries: list[str] = []
            for sub_url in locs[:_MAX_SUB_SITEMAPS]:
                try:
                    sub_xml = self.http.get_text(sub_url)
                    sub_root = ElementTree.fromstring(sub_xml)
                    entries.extend(el.text.strip() for el in sub_root.iter() if el.tag.endswith("loc") and el.text)
                except Exception:  # noqa: BLE001
                    continue
            if entries:
                return entries

        return []

    def _discover_via_homepage_links(self) -> list[str]:
        try:
            html = self.http.get_text(self.config.base_url)
        except Exception:  # noqa: BLE001
            logger.warning("Could not fetch homepage for link-based discovery fallback")
            return []

        soup = BeautifulSoup(html, "lxml")
        base_netloc = urlparse(self.config.base_url).netloc
        links: list[str] = []
        for a in soup.select("a[href]"):
            href = urljoin(self.config.base_url, a["href"]).split("#")[0]
            if urlparse(href).netloc == base_netloc and href not in links:
                links.append(href)
            if len(links) >= _MAX_HOMEPAGE_FALLBACK_LINKS:
                break
        return links

    @staticmethod
    def _looks_like_product_url(url: str) -> bool:
        path = urlparse(url).path.lower().strip("/")
        if not path:
            return False
        segments = path.split("/")
        return not any(kw in segments for kw in _EXCLUDED_PATH_KEYWORDS)

    # -- fetch + parse ---------------------------------------------------

    def fetch_product(self, url: str) -> str:
        return self.http.get_text(url)

    def parse(self, raw_content: str, source_url: str) -> RawProduct:
        soup = BeautifulSoup(raw_content, "lxml")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        visible_text = soup.get_text(" ", strip=True)

        # Best-effort only: without site-specific selectors there's no
        # reliable way to tell a product photo from a logo/icon, so every
        # image on the page is a candidate. Reviewed in the preview step.
        image_urls = [img["src"] for img in soup.select("img[src]") if img.get("src")][:10]

        extracted = self._ollama.extract_product(url=source_url, page_text=visible_text)

        name = extracted.get("name")
        if not name:
            raise ValueError(f"AI did not identify a product on this page: {source_url}")

        return RawProduct(
            manufacturer=self.config.key,
            source_url=source_url,
            name=name,
            model=extracted.get("model"),
            category=extracted.get("category"),
            description=extracted.get("description"),
            features=list(extracted.get("features") or []),
            specifications=dict(extracted.get("specifications") or {}),
            image_urls=image_urls,
            raw={"ai_extracted": True},
        )
