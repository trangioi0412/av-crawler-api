"""HDCVT (Shenzhen HDCVT Technology Co., Ltd.) manufacturer configuration.

Verified against the live site on 2026-09-18:
  - https://www.hdcvt.com/sitemap.xml lists every page, including all
    product detail pages, which follow the pattern
    `/<category-slug>/<numeric-id>.html` (e.g. /HDBaseTExtender/330.html).
    This is a stable, official discovery mechanism -- no need to scrape or
    guess the nav's category tree (see adapter.py for the regex).
  - Product listing pages (e.g. /HDBaseTExtender/) render server-side
    (no JS rendering required) with all items on one page -- no pagination
    observed.
  - robots.txt returns a 301 to the homepage (i.e. no real robots.txt),
    so crawling is unrestricted; `respect_robots_txt` is still left on so
    the client fails safe if that ever changes.
"""
from __future__ import annotations

from manufacturers.base import ManufacturerConfig

HDCVT_CONFIG = ManufacturerConfig(
    key="hdcvt",
    display_name="HDCVT",
    base_url="https://www.hdcvt.com",
    request_delay_seconds=1.5,
    timeout_seconds=20.0,
    max_retries=3,
    user_agent="DataCrawlerSyncBot/1.0 (+contact: jace.tran@avs-tek.vn)",
    respect_robots_txt=True,
)
