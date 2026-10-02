"""Tests the VISSONIC adapter's parsing logic against a saved HTML
snapshot (`tests/fixtures/vissonic_product.html`, captured from the live
site on 2026-09-23). No network access -- these never hit vissonic.com.
"""
from __future__ import annotations

from pathlib import Path

from manufacturers.vissonic.adapter import VissonicAdapter
from manufacturers.vissonic.config import VISSONIC_CONFIG
from services.http_client import CrawlHttpClient

FIXTURES = Path(__file__).parent.parent / "fixtures"
PRODUCT_URL = "https://www.vissonic.com/products/vis-dcp2000-w.html"


def make_adapter() -> VissonicAdapter:
    http = CrawlHttpClient(user_agent="test", request_delay_seconds=0)
    return VissonicAdapter(VISSONIC_CONFIG, http)


def test_parse_extracts_core_fields_from_real_product_page():
    html = (FIXTURES / "vissonic_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert product.manufacturer == "vissonic"
    assert product.name == "5G WIFI Wireless Conference Processor"
    assert product.model == "VIS-DCP2000-W"
    assert product.subcategory == "CLEACON V1 Wi-Fi Wireless Conference System"


def test_parse_extracts_bullet_features_separately_from_description():
    html = (FIXTURES / "vissonic_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert product.description is not None
    assert "●" not in product.description
    assert len(product.features) > 0
    assert any("AUDIO-LINK digital ring network technology" in f for f in product.features)
    assert all("●" not in f for f in product.features)


def test_parse_excludes_the_trailing_model_for_order_line_from_the_last_feature():
    html = (FIXTURES / "vissonic_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert all("Model for Order" not in f for f in product.features)
    assert product.description and "Model for Order" not in product.description


def test_parse_extracts_short_description_highlights():
    html = (FIXTURES / "vissonic_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert product.short_description is not None
    assert "64 Channels Interpretation" in product.short_description


def test_parse_falls_back_to_highlights_when_overview_tab_has_no_bullets():
    """Verified on some product pages (e.g. the compact videowall
    processor) -- the "Overview" tab has plain prose with no "●" bullets
    at all, which used to leave "Main Feature" empty even though the
    `.cpms` highlights right next to the photo had real content.
    """
    html = """<html><body>
    <div class="game-content">
      <span class="game-tag">Some Series</span>
      <h1><a class="game-title">Some Product</a></h1>
      <div class="game-meta"><a class="game-date">VIS-TEST</a></div>
      <div class="cpms"><p>8 HDMI inputs</p><p>9 seamless outputs</p></div>
    </div>
    <section id="tab1"><p>Plain marketing prose with no bullet markers at all.</p></section>
    </body></html>"""
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert product.features == ["8 HDMI inputs", "9 seamless outputs"]


def test_parse_extracts_images_and_pdf_documents():
    html = (FIXTURES / "vissonic_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert product.image_urls == ["https://www.vissonic.com/uploads/img/vis_dcp2000_w_r.jpg"]
    assert len(product.document_urls) == 2
    assert all(url.lower().endswith(".pdf") for url in product.document_urls)


def test_parse_has_no_specifications_table_on_this_site():
    """VISSONIC never publishes an HTML spec table (see config.py) --
    specs live only in the downloadable PDFs above.
    """
    html = (FIXTURES / "vissonic_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert product.specifications == {}


def test_model_falls_back_to_url_slug_when_game_date_element_is_missing():
    adapter = make_adapter()
    product = adapter.parse("<html><body></body></html>", "https://www.vissonic.com/products/vis-wch1.html")
    assert product.model == "VIS-WCH1"


def test_discover_product_urls_filters_sitemap_to_individual_product_pages(monkeypatch):
    sitemap_xml = """<?xml version="1.0" encoding="utf-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.vissonic.com/</loc></url>
      <url><loc>https://www.vissonic.com/products/cleacon-v1-wifi-wireless-conference-system/</loc></url>
      <url><loc>https://www.vissonic.com/products/vis-dcp2000-w.html</loc></url>
      <url><loc>https://www.vissonic.com/products/vis-wch1.html</loc></url>
      <url><loc>https://www.vissonic.com/news/</loc></url>
    </urlset>"""

    adapter = make_adapter()
    monkeypatch.setattr(adapter.http, "get_text", lambda url: sitemap_xml)

    urls = list(adapter.discover_product_urls())

    assert urls == [
        "https://www.vissonic.com/products/vis-dcp2000-w.html",
        "https://www.vissonic.com/products/vis-wch1.html",
    ]
