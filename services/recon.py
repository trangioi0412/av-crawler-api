"""Best-effort website "reconnaissance" for the manufacturer-request intake
form. Runs a handful of fast, low-impact checks against a submitted website
so whoever picks up the request (developer or AI) starts from an answered
checklist instead of from scratch:

  - Does a sitemap.xml exist, and roughly how many URLs does it list?
  - Does robots.txt disallow crawling?
  - Does the homepage look server-rendered (static HTML/BeautifulSoup will
    work) or JS-heavy (a browser-automation adapter like Playwright would
    be needed instead)?

This does NOT replace manual verification (see backend/README.md "Adding a
new manufacturer") -- it only answers the network-observable questions
automatically so a human/AI only has to do the part that actually requires
looking at real page structure and picking selectors.

Every check uses a short timeout and swallows its own errors, since this
runs synchronously while a user is submitting a form -- it must never hang
or fail the request creation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests

_TIMEOUT_SECONDS = 5.0
_USER_AGENT = "DataCrawlerSyncBot/1.0 (+recon; contact: jace.tran@avs-tek.vn)"
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class ReconResult:
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reachable: bool = False
    sitemap_found: bool = False
    sitemap_url: str | None = None
    sitemap_entry_count: int | None = None
    robots_found: bool = False
    robots_disallows_all: bool = False
    likely_requires_js: bool | None = None  # None = couldn't determine (site unreachable)
    error: str | None = None

    def to_notes(self) -> str:
        """Renders the findings as a checklist a developer can act on
        directly, instead of a raw data dump.
        """
        if not self.reachable:
            return (
                "Kiểm tra sơ bộ tự động (thất bại):\n"
                f"- Không truy cập được website: {self.error or 'unknown error'}\n"
                "- Cần kiểm tra lại link website có đúng không trước khi làm tiếp."
            )

        lines = ["Kiểm tra sơ bộ tự động:"]

        if self.sitemap_found:
            count = f", ~{self.sitemap_entry_count} URL" if self.sitemap_entry_count is not None else ""
            lines.append(f"- ✅ Có sitemap.xml ({self.sitemap_url}{count}) -- ưu tiên dùng để liệt kê sản phẩm.")
        else:
            lines.append("- ⚠️ Không tìm thấy sitemap.xml -- sẽ cần quét danh mục/phân trang thủ công.")

        if self.robots_disallows_all:
            lines.append("- 🛑 robots.txt CHẶN crawl toàn bộ -- cần xem lại trước khi tiếp tục.")
        elif self.robots_found:
            lines.append("- ✅ robots.txt tồn tại, không chặn crawl toàn bộ.")
        else:
            lines.append("- ℹ️ Không có robots.txt riêng (không bị chặn).")

        if self.likely_requires_js is True:
            lines.append(
                "- ⚠️ Trang có vẻ render bằng JavaScript (HTML tĩnh gần như rỗng) "
                "-- có thể cần Playwright thay vì requests + BeautifulSoup."
            )
        elif self.likely_requires_js is False:
            lines.append("- ✅ Trang trả về HTML tĩnh có nội dung -- dùng requests + BeautifulSoup được.")

        lines.append("- Việc còn lại (cần làm thủ công): mở 1 trang danh mục + 1 trang sản phẩm thật, xác định selector cho tên/model/ảnh/thông số, rồi viết adapter.")
        return "\n".join(lines)


def _probe_sitemap(session: requests.Session, base_url: str) -> tuple[bool, str | None, int | None]:
    for path in ("/sitemap.xml", "/sitemap_index.xml"):
        url = urljoin(base_url, path)
        try:
            response = session.get(url, timeout=_TIMEOUT_SECONDS)
            if response.status_code != 200 or "xml" not in response.headers.get("content-type", "").lower():
                continue
            try:
                root = ElementTree.fromstring(response.content)
                count = sum(1 for el in root.iter() if el.tag.endswith("loc"))
            except ElementTree.ParseError:
                count = None
            return True, url, count
        except requests.RequestException:
            continue
    return False, None, None


def _probe_robots(session: requests.Session, base_url: str) -> tuple[bool, bool]:
    url = urljoin(base_url, "/robots.txt")
    try:
        response = session.get(url, timeout=_TIMEOUT_SECONDS)
        if response.status_code != 200:
            return False, False
        text = response.text.lower()
        # Heuristic: a blanket "disallow: /" not scoped to a specific bot.
        disallows_all = bool(re.search(r"disallow:\s*/\s*$", text, re.MULTILINE))
        return True, disallows_all
    except requests.RequestException:
        return False, False


def _probe_js_requirement(session: requests.Session, base_url: str) -> bool | None:
    try:
        response = session.get(base_url, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        stripped = _TAG_RE.sub(" ", _SCRIPT_STYLE_RE.sub(" ", response.text))
        visible_text_length = len(" ".join(stripped.split()))
        # A near-empty body after stripping tags/scripts strongly suggests a
        # client-side-rendered SPA shell rather than server-rendered HTML.
        return visible_text_length < 200
    except requests.RequestException:
        return None


def probe_manufacturer_website(website_url: str) -> ReconResult:
    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})
    try:
        response = session.get(website_url, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        return ReconResult(reachable=False, error=f"{type(exc).__name__}: {exc}")

    sitemap_found, sitemap_url, sitemap_count = _probe_sitemap(session, website_url)
    robots_found, robots_disallows_all = _probe_robots(session, website_url)
    likely_requires_js = _probe_js_requirement(session, website_url)

    return ReconResult(
        reachable=True,
        sitemap_found=sitemap_found,
        sitemap_url=sitemap_url,
        sitemap_entry_count=sitemap_count,
        robots_found=robots_found,
        robots_disallows_all=robots_disallows_all,
        likely_requires_js=likely_requires_js,
    )
