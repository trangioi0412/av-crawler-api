"""Unit tests for the Google Sheets exporter's row-mapping and upsert
logic. Never touches the real Google Sheets API or credentials -- the
gspread client/worksheet is a hand-built fake.
"""
from __future__ import annotations

from core.models.product import CanonicalProduct
from services.google_sheets import SHEET_HEADERS, _natural_key, build_sheet_row


def make_product(**overrides) -> CanonicalProduct:
    defaults = dict(
        manufacturer="hdcvt",
        source_url="https://www.hdcvt.com/HDBaseTExtender/330.html",
        name="HDBaseT Extender (70m)",
        model="HBT-E70S",
        category="Extenders",
        subcategory="HDBaseT Extender",
        description="A great extender.",
        image_urls=["https://www.hdcvt.com/a.png", "https://www.hdcvt.com/b.png"],
        document_urls=["https://www.hdcvt.com/manual.pdf"],
        specifications={"Power Supply": "DC 24V 1A", "Weight": "200g"},
        features=["POC supported", "4K30 support"],
        dedup_key="hdcvt:model:hbte70s",
    )
    defaults.update(overrides)
    return CanonicalProduct(**defaults)


def test_build_sheet_row_maps_every_header():
    row = build_sheet_row(make_product(), brand_display_name="HDCVT")

    assert set(row.keys()) == set(SHEET_HEADERS)
    assert row["Category"] == "Extenders"
    assert row["Product"] == "HDBaseT Extender"  # subcategory = product line/type
    assert row["Title"] == "HDBaseT Extender (70m)"
    assert row["product (item)"] == "HBT-E70S"  # model = specific item
    assert row["Series"] == ""
    assert row["Main Feature"] == "POC supported\n4K30 support"
    assert row["Product Overview"] == "A great extender."
    assert row["Technical Specifications"] == "Power Supply: DC 24V 1A\nWeight: 200g"
    assert row["image"] == "https://www.hdcvt.com/a.png\nhttps://www.hdcvt.com/b.png"
    assert row["Brand"] == "HDCVT"
    assert row["Datasheet"] == "https://www.hdcvt.com/manual.pdf"


def test_build_sheet_row_falls_back_to_sku_when_no_model():
    row = build_sheet_row(make_product(model=None, sku="SKU-123"), brand_display_name="HDCVT")
    assert row["product (item)"] == "SKU-123"


def test_natural_key_prefers_item_over_title():
    key_a = _natural_key({"product (item)": "HBT-E70S", "Title": "Anything"})
    key_b = _natural_key({"product (item)": "hbt-e70s", "Title": "Different"})
    assert key_a == key_b == "item:hbt-e70s"


def test_natural_key_falls_back_to_title_when_no_item():
    key = _natural_key({"product (item)": "", "Title": "Some Product"})
    assert key == "title:some product"
