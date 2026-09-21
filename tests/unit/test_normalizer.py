from __future__ import annotations

from core.models.product import RawProduct
from core.pipeline.normalizer import Normalizer, build_dedup_key


def test_normalize_trims_whitespace_and_absolutizes_urls():
    raw = RawProduct(
        manufacturer="hdcvt",
        source_url="/HDBaseTExtender/330.html",
        name="  HDBaseT   Extender (70m)  ",
        model=" HBT-E70S ",
        category="extenders",
        subcategory="hdbaset extender",
        image_urls=["/static/a.png", "/static/a.png", "static/b.png"],
        document_urls=["/docs/manual.pdf"],
        specifications={" Power Supply ": " DC 24V 1A "},
    )

    candidate = Normalizer().normalize(raw, base_url="https://www.hdcvt.com")

    assert candidate.name == "HDBaseT Extender (70m)"
    assert candidate.model == "HBT-E70S"
    assert candidate.category == "Extenders"
    assert candidate.subcategory == "Hdbaset Extender"
    assert candidate.image_urls == [
        "https://www.hdcvt.com/static/a.png",
        "https://www.hdcvt.com/static/b.png",
    ]
    assert candidate.document_urls == ["https://www.hdcvt.com/docs/manual.pdf"]
    assert candidate.source_url == "https://www.hdcvt.com/HDBaseTExtender/330.html"
    assert candidate.specifications == {"Power Supply": "DC 24V 1A"}


def test_normalize_drops_invalid_urls():
    raw = RawProduct(
        manufacturer="hdcvt",
        source_url="https://www.hdcvt.com/p/1.html",
        name="Thing",
        image_urls=["", "javascript:void(0)"],
    )

    candidate = Normalizer().normalize(raw, base_url="https://www.hdcvt.com")

    # "javascript:void(0)" absolutizes to a scheme with no netloc, so it's dropped.
    assert candidate.image_urls == []


def test_dedup_key_prefers_model_over_name():
    key_a = build_dedup_key("hdcvt", "HBT-E70S", "HDBaseT Extender (70m)", "https://x/1")
    key_b = build_dedup_key("hdcvt", "hbt-e70s", "A totally different name", "https://x/2")

    assert key_a == key_b
    assert key_a == "hdcvt:model:hbte70s"


def test_dedup_key_falls_back_to_name_and_url_hash_when_no_model():
    key = build_dedup_key("hdcvt", None, "Some Product", "https://www.hdcvt.com/p/1.html")

    assert key.startswith("hdcvt:hash:")

    # Same name + url -> same key (stable across re-syncs).
    key_again = build_dedup_key("hdcvt", None, "Some Product", "https://www.hdcvt.com/p/1.html")
    assert key == key_again

    # Different url -> different key.
    key_other_url = build_dedup_key("hdcvt", None, "Some Product", "https://www.hdcvt.com/p/2.html")
    assert key != key_other_url
