"""Regression test for a real bug found against the live HDCVT site: pages
served as `Content-Type: text/html` with no charset parameter decoded as
ISO-8859-1 by default (`requests`' RFC 2616 fallback), mangling UTF-8
characters like "±" into "�". Uses `responses` to mock the HTTP layer --
no real network access.
"""
from __future__ import annotations

import responses

from services.http_client import CrawlHttpClient


@responses.activate
def test_get_text_corrects_encoding_when_no_charset_declared():
    body_bytes = "Human body model: ±8kV, Operating Temperature: 0°C".encode("utf-8")
    responses.add(
        responses.GET,
        "https://example.com/page",
        body=body_bytes,
        content_type="text/html",  # no charset, matching hdcvt.com's real headers
    )

    client = CrawlHttpClient(user_agent="test", request_delay_seconds=0, respect_robots_txt=False)
    text = client.get_text("https://example.com/page")

    assert "±8kV" in text
    assert "0°C" in text
    assert "�" not in text


@responses.activate
def test_get_text_honors_explicit_charset_when_declared():
    body_bytes = "±8kV".encode("utf-8")
    responses.add(
        responses.GET,
        "https://example.com/page",
        body=body_bytes,
        content_type="text/html; charset=utf-8",
    )

    client = CrawlHttpClient(user_agent="test", request_delay_seconds=0, respect_robots_txt=False)
    text = client.get_text("https://example.com/page")

    assert "±8kV" in text


def test_ca_bundle_path_is_left_default_when_not_given():
    client = CrawlHttpClient(user_agent="test", request_delay_seconds=0)
    # requests.Session.verify defaults to True (use certifi's own trust
    # store) -- must stay untouched for every manufacturer that doesn't
    # need an extra CA bundle.
    assert client._session.verify is True


def test_ca_bundle_path_is_applied_to_the_session_when_given():
    """See manufacturers/eizo/ca_bundle.py: a site whose server sends an
    incomplete TLS chain needs a CA bundle beyond certifi's default.
    """
    client = CrawlHttpClient(user_agent="test", request_delay_seconds=0, ca_bundle_path="/some/combined-bundle.pem")
    assert client._session.verify == "/some/combined-bundle.pem"
