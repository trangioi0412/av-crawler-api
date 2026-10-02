"""EIZO (EIZO Corporation) manufacturer configuration.

Verified against the live site (eizoglobal.com, the domain "eizo.com"
redirects to) on 2026-09-23:
  - `/sitemap.xml` is stale (dated ~2013 -- old CSR/ISO PDFs, no current
    product pages) and unusable for discovery, unlike HDCVT/VISSONIC.
    Product listing pages (e.g. /products/coloredge/) render their grid
    via JS/AJAX, so they're empty in the raw HTML too. What *does* work:
    every individual product page (e.g. /products/coloredge/cg3200x/)
    has a static left-nav sidebar (`#side`) listing every sibling product
    in its own division only. `category_paths` below is one known-good
    product page per division, used as a seed to enumerate that whole
    division via its sidebar -- see adapter.py.
  - robots.txt: `Disallow: /support/db/comparison*`, `Crawl-Delay: 20` --
    the 20s `request_delay_seconds` below is not a stylistic choice, it's
    what the site's own robots.txt asks for.
  - This only covers eizoglobal.com's four monitor divisions (ColorEdge,
    FlexScan, DuraVision, RadiForce). EIZO's ATC (air traffic control)
    line and CuratOR-branded surgical displays (seen as pre-existing rows
    in this project's "eizo" sheet tab, entered from elsewhere) are out
    of scope -- ATC is a different, low-relevance niche, and CuratOR
    appears to live on an entirely different domain not investigated here.
  - eizoglobal.com's server sends an incomplete TLS chain (missing
    intermediate CA cert), which fails Python's default certificate
    verification even though it works in a browser -- see
    `manufacturers/eizo/ca_bundle.py` for the fix wired in below.
"""
from __future__ import annotations

from manufacturers.base import ManufacturerConfig
from manufacturers.eizo.ca_bundle import combined_ca_bundle_path

EIZO_CONFIG = ManufacturerConfig(
    key="eizo",
    display_name="EIZO",
    base_url="https://www.eizoglobal.com",
    category_paths=(
        "/products/coloredge/cg3200x/",
        "/products/flexscan/ev2760/",
        "/products/duravision/fds1921t/",
        "/products/radiforce/rx1270/",
    ),
    request_delay_seconds=20.0,  # robots.txt: Crawl-Delay: 20
    timeout_seconds=20.0,
    max_retries=3,
    user_agent="DataCrawlerSyncBot/1.0 (+contact: jace.tran@avs-tek.vn)",
    respect_robots_txt=True,
    ca_bundle_path=combined_ca_bundle_path(),
)
