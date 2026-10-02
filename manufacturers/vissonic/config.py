"""VISSONIC (Shenzhen Vissonic Electronics Co., Ltd.) manufacturer
configuration.

Verified against the live site on 2026-09-23:
  - https://www.vissonic.com/sitemap.xml lists every page, including all
    product-detail pages, which follow "/products/<model-slug>.html" (e.g.
    /products/vis-dcp2000-w.html). Pages under /products/ that end in "/"
    instead (e.g. /products/cleacon-v1-wifi-wireless-conference-system/)
    are "solution" family pages that list several individual products
    each and are JS-rendered on top of that -- excluded by the adapter's
    discovery regex, same idea as HDCVT's non-product-slug filter.
  - Product pages render server-side (no JS rendering required for the
    content the adapter reads: name, model, description, images, docs).
  - robots.txt is "User-agent: *" with no Disallow -- unrestricted.
  - Unlike HDCVT, there is no HTML specifications table anywhere on a
    product page -- specs are only published as downloadable PDFs
    (datasheet + dimension drawing). `specifications` is therefore always
    empty for this adapter; the PDFs are still captured as document_urls.
"""
from __future__ import annotations

from manufacturers.base import ManufacturerConfig

VISSONIC_CONFIG = ManufacturerConfig(
    key="vissonic",
    display_name="VISSONIC",
    base_url="https://www.vissonic.com",
    request_delay_seconds=1.5,
    timeout_seconds=20.0,
    max_retries=3,
    user_agent="DataCrawlerSyncBot/1.0 (+contact: jace.tran@avs-tek.vn)",
    respect_robots_txt=True,
)
