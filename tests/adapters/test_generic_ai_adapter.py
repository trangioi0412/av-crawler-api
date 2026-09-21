"""Tests for the generic AI-assisted adapter: URL discovery heuristics
(sitemap parsing, sitemap-index following, noise filtering, homepage-link
fallback) and page parsing. The Ollama call itself is monkeypatched --
these tests never touch a real LLM or network beyond the mocked HTTP
responses.
"""
from __future__ import annotations

import responses

from manufacturers.base import ManufacturerConfig
from manufacturers.generic_ai.adapter import GenericAIAdapter
from services.http_client import CrawlHttpClient


def make_adapter() -> GenericAIAdapter:
    config = ManufacturerConfig(
        key="acme", display_name="Acme Corp", base_url="https://example.com", request_delay_seconds=0
    )
    http = CrawlHttpClient(user_agent="test", request_delay_seconds=0)
    return GenericAIAdapter(config, http)


@responses.activate
def test_discover_via_sitemap_filters_noise_paths():
    sitemap = """<?xml version="1.0"?>
    <urlset>
      <url><loc>https://example.com/products/widget-a.html</loc></url>
      <url><loc>https://example.com/products/widget-b.html</loc></url>
      <url><loc>https://example.com/news/some-article.html</loc></url>
      <url><loc>https://example.com/about/</loc></url>
      <url><loc>https://example.com/</loc></url>
    </urlset>"""
    responses.add(
        responses.GET, "https://example.com/sitemap.xml", body=sitemap, status=200, content_type="application/xml"
    )

    adapter = make_adapter()
    urls = list(adapter.discover_product_urls())

    assert urls == ["https://example.com/products/widget-a.html", "https://example.com/products/widget-b.html"]


@responses.activate
def test_discover_follows_sitemap_index_one_level():
    index = """<?xml version="1.0"?>
    <sitemapindex>
      <sitemap><loc>https://example.com/sitemap-products.xml</loc></sitemap>
    </sitemapindex>"""
    sub = """<?xml version="1.0"?>
    <urlset><url><loc>https://example.com/products/widget-c.html</loc></url></urlset>"""
    responses.add(responses.GET, "https://example.com/sitemap.xml", body=index, status=200, content_type="application/xml")
    responses.add(responses.GET, "https://example.com/sitemap-products.xml", body=sub, status=200, content_type="application/xml")

    adapter = make_adapter()
    urls = list(adapter.discover_product_urls())

    assert urls == ["https://example.com/products/widget-c.html"]


@responses.activate
def test_discover_falls_back_to_homepage_links_when_no_sitemap():
    responses.add(responses.GET, "https://example.com/sitemap.xml", status=404)
    responses.add(responses.GET, "https://example.com/sitemap_index.xml", status=404)
    responses.add(
        responses.GET,
        "https://example.com",
        body=(
            '<html><body>'
            '<a href="/products/widget-d.html">Widget D</a>'
            '<a href="/contact/">Contact</a>'
            '<a href="https://otherdomain.com/products/x.html">Off-domain</a>'
            "</body></html>"
        ),
        status=200,
    )

    adapter = make_adapter()
    urls = list(adapter.discover_product_urls())

    assert urls == ["https://example.com/products/widget-d.html"]


@responses.activate
def test_discover_respects_max_products_cap():
    sitemap = """<?xml version="1.0"?>
    <urlset>
      <url><loc>https://example.com/products/a.html</loc></url>
      <url><loc>https://example.com/products/b.html</loc></url>
      <url><loc>https://example.com/products/c.html</loc></url>
    </urlset>"""
    responses.add(responses.GET, "https://example.com/sitemap.xml", body=sitemap, status=200, content_type="application/xml")

    config = ManufacturerConfig(
        key="acme", display_name="Acme", base_url="https://example.com", request_delay_seconds=0, max_products=2
    )
    adapter = GenericAIAdapter(config, CrawlHttpClient(user_agent="test", request_delay_seconds=0))

    urls = list(adapter.discover_product_urls())

    assert len(urls) == 2


def test_parse_uses_ollama_extraction_and_collects_images(monkeypatch):
    adapter = make_adapter()
    monkeypatch.setattr(
        adapter._ollama,
        "extract_product",
        lambda url, page_text: {
            "name": "Widget A",
            "model": "WA-1",
            "category": "Widgets",
            "description": "A fine widget.",
            "features": ["Durable"],
            "specifications": {"Color": "Red"},
        },
    )

    html = '<html><body><img src="/a.png"><img src="/b.png"><script>ignored</script></body></html>'
    product = adapter.parse(html, "https://example.com/products/widget-a.html")

    assert product.name == "Widget A"
    assert product.model == "WA-1"
    assert product.specifications == {"Color": "Red"}
    assert product.image_urls == ["/a.png", "/b.png"]
    assert product.raw == {"ai_extracted": True}


def test_parse_raises_when_ai_finds_no_product(monkeypatch):
    adapter = make_adapter()
    monkeypatch.setattr(adapter._ollama, "extract_product", lambda url, page_text: {"name": None})

    try:
        adapter.parse("<html></html>", "https://example.com/news/article.html")
        assert False, "expected ValueError"
    except ValueError:
        pass
