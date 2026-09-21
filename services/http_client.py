"""Polite, reusable HTTP client for manufacturer adapters.

Shared by every adapter so crawling-safety behavior (delays, retries,
timeouts, robots.txt, connection reuse) is implemented once instead of
per-manufacturer.
"""
from __future__ import annotations

import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests

from core.logging import get_logger

logger = get_logger(__name__)


class RobotsDisallowedError(Exception):
    """Raised when robots.txt disallows fetching a URL."""


class CrawlHttpClient:
    """A `requests.Session` wrapper that adds:

    - a fixed delay between requests (rate limiting)
    - retry with exponential backoff on transient network/HTTP errors
    - a request timeout
    - optional robots.txt checking, cached per host
    """

    def __init__(
        self,
        *,
        user_agent: str,
        request_delay_seconds: float = 1.0,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        respect_robots_txt: bool = True,
    ) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})
        self._user_agent = user_agent
        self._delay = request_delay_seconds
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._respect_robots_txt = respect_robots_txt
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_request_at: float = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self._delay - elapsed
        if wait > 0:
            time.sleep(wait)

    def _robots_allowed(self, url: str) -> bool:
        if not self._respect_robots_txt:
            return True
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._robots_cache.get(origin)
        if parser is None:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(urljoin(origin, "/robots.txt"))
            try:
                parser.read()
            except Exception:
                # If robots.txt can't be fetched, fail open (assume allowed)
                # rather than blocking the sync on an unrelated network blip.
                logger.warning("Could not fetch robots.txt for %s; allowing by default", origin)
            self._robots_cache[origin] = parser
        return parser.can_fetch(self._user_agent, url)

    def _do_get(self, url: str) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            self._throttle()
            try:
                response = self._session.get(url, timeout=self._timeout)
                self._last_request_at = time.monotonic()
                response.raise_for_status()
                return response
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                self._last_request_at = time.monotonic()
                if attempt < self._max_retries:
                    backoff = min(2 ** (attempt - 1), 10)
                    logger.warning(
                        "Request to %s failed (attempt %d/%d): %s; retrying in %ds",
                        url,
                        attempt,
                        self._max_retries,
                        exc,
                        backoff,
                    )
                    time.sleep(backoff)
            except requests.HTTPError:
                # Non-transient (4xx/5xx after a successful connection): don't retry.
                self._last_request_at = time.monotonic()
                raise
        assert last_error is not None
        raise last_error

    def get_text(self, url: str) -> str:
        """Fetch `url` and return the response body as text.

        Raises `RobotsDisallowedError` if robots.txt disallows the URL, or
        `requests.RequestException` for network/HTTP failures after retries.
        """
        if not self._robots_allowed(url):
            raise RobotsDisallowedError(f"robots.txt disallows fetching {url}")
        response = self._do_get(url)
        if "charset" not in response.headers.get("content-type", "").lower():
            # No explicit charset declared -> `requests` defaults `.encoding`
            # to ISO-8859-1 per RFC 2616, which mangles non-ASCII characters
            # on UTF-8 pages served without a charset header (verified
            # against hdcvt.com: "±" and "°" came through as "�"). Trust
            # content-based detection instead, same as a browser would.
            response.encoding = response.apparent_encoding
        return response.text

    def close(self) -> None:
        self._session.close()
