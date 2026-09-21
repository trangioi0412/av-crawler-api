"""Tests the HDCVT adapter's parsing logic against saved HTML snapshots
(`tests/fixtures/hdcvt_*.html`, captured from the live site on 2026-09-18).
No network access -- these never hit hdcvt.com.
"""
from __future__ import annotations

from pathlib import Path

from manufacturers.hdcvt.adapter import HdcvtAdapter
from manufacturers.hdcvt.config import HDCVT_CONFIG
from services.http_client import CrawlHttpClient

FIXTURES = Path(__file__).parent.parent / "fixtures"


def make_adapter() -> HdcvtAdapter:
    http = CrawlHttpClient(user_agent="test", request_delay_seconds=0)
    return HdcvtAdapter(HDCVT_CONFIG, http)


def test_parse_extracts_core_fields_from_real_product_page():
    html = (FIXTURES / "hdcvt_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, "https://www.hdcvt.com/HDBaseTExtender/330.html")

    assert product.manufacturer == "hdcvt"
    assert product.name == "HDBaseT Extender (70m)"
    assert product.model == "HBT-E70S"
    assert product.category == "Extenders"
    assert product.subcategory == "HDBaseT Extender"
    assert product.description and "230fts/70meters" in product.description


def test_parse_extracts_bullet_features_separately_from_description():
    html = (FIXTURES / "hdcvt_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, "https://www.hdcvt.com/HDBaseTExtender/330.html")

    assert product.description is not None
    assert "☆" not in product.description
    assert len(product.features) > 0
    assert any("POC (Power Over Cable)" in f for f in product.features)
    assert all("☆" not in f for f in product.features)


def test_parse_extracts_image_gallery():
    html = (FIXTURES / "hdcvt_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, "https://www.hdcvt.com/HDBaseTExtender/330.html")

    assert len(product.image_urls) == 4
    assert all(url.startswith("/static/upload/image/") for url in product.image_urls)


def test_parse_extracts_specifications_table_and_skips_section_headers():
    html = (FIXTURES / "hdcvt_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, "https://www.hdcvt.com/HDBaseTExtender/330.html")

    assert product.specifications["Power Supply"] == "DC 24V 1A"
    assert product.specifications["Frequency Bandwidth"] == "297MHz[10.2Gbps]"
    # Decorative rowspan/colspan header cells must not leak in as fields.
    assert "Specifications" not in product.specifications
    assert "Technical" not in product.specifications


def test_parse_handles_product_with_no_documents():
    html = (FIXTURES / "hdcvt_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, "https://www.hdcvt.com/HDBaseTExtender/330.html")

    # This product's "Download" panel is empty on the live site -- the
    # adapter must return an empty list, not raise.
    assert product.document_urls == []


def test_discover_product_urls_filters_sitemap_to_product_detail_pages(monkeypatch):
    sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.hdcvt.com/HDBaseTExtender/</loc></url>
      <url><loc>https://www.hdcvt.com/HDBaseTExtender/330.html</loc></url>
      <url><loc>https://www.hdcvt.com/HDBaseTExtender/331.html</loc></url>
      <url><loc>https://www.hdcvt.com/CompanyProfile/</loc></url>
      <url><loc>https://www.hdcvt.com/Notice/441.html</loc></url>
      <url><loc>https://www.hdcvt.com/IndustryNews/465.html</loc></url>
      <url><loc>https://www.hdcvt.com</loc></url>
    </urlset>"""

    adapter = make_adapter()
    monkeypatch.setattr(adapter.http, "get_text", lambda url: sitemap_xml)

    urls = list(adapter.discover_product_urls())

    assert urls == [
        "https://www.hdcvt.com/HDBaseTExtender/330.html",
        "https://www.hdcvt.com/HDBaseTExtender/331.html",
    ]
