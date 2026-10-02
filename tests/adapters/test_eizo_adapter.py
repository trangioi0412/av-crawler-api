"""Tests the EIZO adapter's parsing logic against a saved HTML snapshot
(`tests/fixtures/eizo_product.html`, captured from the live site on
2026-09-23). No network access -- these never hit eizoglobal.com.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from manufacturers.eizo.adapter import EizoAdapter
from manufacturers.eizo.config import EIZO_CONFIG
from services.http_client import CrawlHttpClient

FIXTURES = Path(__file__).parent.parent / "fixtures"
PRODUCT_URL = "https://www.eizoglobal.com/products/coloredge/cg3200x/"


def make_adapter() -> EizoAdapter:
    http = CrawlHttpClient(user_agent="test", request_delay_seconds=0)
    return EizoAdapter(EIZO_CONFIG, http)


def test_parse_extracts_core_fields_from_real_product_page():
    html = (FIXTURES / "eizo_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert product.manufacturer == "eizo"
    assert product.name == "ColorEdge CG3200X"
    assert product.model == "CG3200X"
    assert product.category == "ColorEdge"
    assert product.description == '31.5" Color Management OLED Monitor'


def test_parse_extracts_subcategory_from_the_active_series_marker():
    html = (FIXTURES / "eizo_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert product.subcategory == "CG Series"


def test_parse_extracts_features_from_the_notes_frame_table_of_contents():
    html = (FIXTURES / "eizo_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert len(product.features) > 0
    assert "EIZO's Proprietary ABL Control System" in product.features


def test_parse_returns_empty_features_when_page_has_no_notes_frame_toc():
    """Verified on some DuraVision product pages -- the Features tab has
    no `.notes-frame` table of contents at all, unlike ColorEdge/FlexScan.
    """
    html = "<html><body><div id='tab01_content'><p>Some prose, no ToC.</p></div></body></html>"
    adapter = make_adapter()

    product = adapter.parse(html, "https://www.eizoglobal.com/products/duravision/fds1921t/")

    assert product.features == []


def test_parse_returns_no_subcategory_when_side_nav_is_missing():
    product = make_adapter().parse("<html><body></body></html>", PRODUCT_URL)
    assert product.subcategory is None


def test_parse_extracts_product_photo_gallery():
    html = (FIXTURES / "eizo_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert len(product.image_urls) == 5
    assert all(url.startswith("https://www.eizoglobal.com/products/coloredge/cg3200x/") for url in product.image_urls)


def test_parse_extracts_specifications_and_keeps_model_variations_row():
    html = (FIXTURES / "eizo_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert product.specifications["Type"] == "QD-OLED (Anti-Glare, Low-Reflection)"
    assert product.specifications["Native Resolution"] == "3840 x 2160 (16:9 aspect ratio)"
    # "Model Variations" is th.head2 like the section dividers, but has a
    # real value ("CG3200X-BK") and must be kept.
    assert product.specifications["Model Variations"] == "CG3200X-BK"


def test_parse_skips_empty_section_divider_rows():
    html = (FIXTURES / "eizo_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    # "Panel" / "Video Signals" etc. are th.head2 rows with an empty
    # ("&nbsp;"-only) value cell -- decorative section headers, not specs.
    assert "Panel" not in product.specifications
    assert "Video Signals" not in product.specifications


def test_parse_only_reads_the_own_spec_table_not_the_compatibility_table():
    """A later, unrelated `table.standard` further down the page (a
    "Compatibility" changelog with Date/Subject columns) must not leak
    into `specifications`.
    """
    html = (FIXTURES / "eizo_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert "Date" not in product.specifications
    assert "Subject" not in product.specifications


def test_parse_extracts_pdf_documents():
    html = (FIXTURES / "eizo_product.html").read_text(encoding="utf-8")
    adapter = make_adapter()

    product = adapter.parse(html, PRODUCT_URL)

    assert len(product.document_urls) > 0
    assert all(url.lower().endswith(".pdf") for url in product.document_urls)
    assert len(product.document_urls) == len(set(product.document_urls))  # deduped


def test_discover_product_urls_extracts_sibling_links_and_excludes_non_products(monkeypatch):
    nav_html = """<html><body>
    <div id="side">
      <ul class="level01"><li><a href="//www.eizoglobal.com/products/coloredge/"><span>ColorEdge</span></a></li></ul>
      <ul>
        <li class="btn_01"><span class="on">CG Series</span>
          <ul class="active">
            <li><a href="/products/coloredge/cg1/">CG1</a></li>
            <li><a href="/products/coloredge/cg3200x/">CG3200X</a></li>
          </ul>
        </li>
      </ul>
      <a href="/products/coloredge/ambassadors/">Ambassadors</a>
      <a href="/products/coloredge/">ColorEdge index (no slug, must not match)</a>
      <a href="/products/coloredge/coloredge_cg.html">Family page (.html, must not match)</a>
    </div>
    </body></html>"""

    single_seed_config = replace(EIZO_CONFIG, category_paths=("/products/coloredge/cg3200x/",))
    http = CrawlHttpClient(user_agent="test", request_delay_seconds=0)
    adapter = EizoAdapter(single_seed_config, http)
    monkeypatch.setattr(adapter.http, "get_text", lambda url: nav_html)

    urls = list(adapter.discover_product_urls())

    assert urls == [
        "https://www.eizoglobal.com/products/coloredge/cg1/",
        "https://www.eizoglobal.com/products/coloredge/cg3200x/",
    ]


def test_discover_product_urls_dedupes_across_multiple_seed_pages(monkeypatch):
    nav_html = """<html><body><div id="side">
      <a href="/products/coloredge/cg3200x/">CG3200X</a>
      <a href="/products/coloredge/cg1/">CG1</a>
    </div></body></html>"""

    two_seed_config = replace(
        EIZO_CONFIG,
        category_paths=("/products/coloredge/cg3200x/", "/products/coloredge/cg1/"),
    )
    http = CrawlHttpClient(user_agent="test", request_delay_seconds=0)
    adapter = EizoAdapter(two_seed_config, http)
    monkeypatch.setattr(adapter.http, "get_text", lambda url: nav_html)

    urls = list(adapter.discover_product_urls())

    assert urls == [
        "https://www.eizoglobal.com/products/coloredge/cg3200x/",
        "https://www.eizoglobal.com/products/coloredge/cg1/",
    ]
