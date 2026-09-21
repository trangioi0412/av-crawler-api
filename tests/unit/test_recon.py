"""Unit tests for the manufacturer-website recon checks (sitemap.xml,
robots.txt, static-vs-JS heuristic). Uses `responses` to mock HTTP -- never
touches a real website.
"""
from __future__ import annotations

import responses

from services.recon import probe_manufacturer_website


@responses.activate
def test_probe_detects_sitemap_and_entry_count():
    long_body = "<html><body>" + ("This is a real, server-rendered product page with plenty of visible text. " * 5) + "</body></html>"
    responses.add(responses.GET, "https://example.com/", body=long_body, status=200)
    responses.add(
        responses.GET,
        "https://example.com/sitemap.xml",
        body='<?xml version="1.0"?><urlset><url><loc>https://example.com/a</loc></url><url><loc>https://example.com/b</loc></url></urlset>',
        status=200,
        content_type="application/xml",
    )
    responses.add(responses.GET, "https://example.com/robots.txt", body="User-agent: *\nDisallow:", status=200)

    result = probe_manufacturer_website("https://example.com/")

    assert result.reachable is True
    assert result.sitemap_found is True
    assert result.sitemap_entry_count == 2
    assert result.robots_found is True
    assert result.robots_disallows_all is False
    assert result.likely_requires_js is False
    assert "Có sitemap.xml" in result.to_notes()


@responses.activate
def test_probe_detects_no_sitemap_and_blocked_robots():
    responses.add(responses.GET, "https://example.com/", body="<html><body>Some real content here for the homepage.</body></html>", status=200)
    responses.add(responses.GET, "https://example.com/sitemap.xml", status=404)
    responses.add(responses.GET, "https://example.com/sitemap_index.xml", status=404)
    responses.add(responses.GET, "https://example.com/robots.txt", body="User-agent: *\nDisallow: /", status=200)

    result = probe_manufacturer_website("https://example.com/")

    assert result.sitemap_found is False
    assert result.robots_disallows_all is True
    assert "CHẶN crawl" in result.to_notes()


@responses.activate
def test_probe_flags_likely_js_rendered_page():
    responses.add(
        responses.GET,
        "https://example.com/",
        body='<html><body><div id="root"></div><script>/* big bundle */</script></body></html>',
        status=200,
    )
    responses.add(responses.GET, "https://example.com/sitemap.xml", status=404)
    responses.add(responses.GET, "https://example.com/sitemap_index.xml", status=404)
    responses.add(responses.GET, "https://example.com/robots.txt", status=404)

    result = probe_manufacturer_website("https://example.com/")

    assert result.likely_requires_js is True
    assert "JavaScript" in result.to_notes()


@responses.activate
def test_probe_unreachable_site_returns_error_notes():
    responses.add(responses.GET, "https://example.com/", status=500)

    result = probe_manufacturer_website("https://example.com/")

    assert result.reachable is False
    assert "thất bại" in result.to_notes()
