"""Fetch a job description from a URL.

Two-stage pipeline:

1. Plain HTTP + trafilatura. Works for server-rendered job pages and is
   cheap.
2. Playwright + Chromium fallback. Only fires when the HTTP pass finds
   too little useful text - most job boards render server-side, some
   (Workday, Greenhouse embeds, LinkedIn) don't.

Every failure lands as ``JdFetchError`` with a ``status_code`` the router
maps directly to an HTTP status. 4xx = the user pasted a bad URL; 5xx =
we couldn't run the browser.

Both HTTP and browser paths are injectable so tests can run without
network. Same idiom as ``scoring.score(call=...)``. The DNS resolver used
by the SSRF guard is likewise injectable.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

import httpx
import trafilatura
from pydantic import BaseModel


logger = logging.getLogger(__name__)

MIN_EXTRACTED_CHARS = 200
MAX_REDIRECTS = 5
USER_AGENT = (
    "Mozilla/5.0 (compatible; JobFit/1.0; +https://github.com/tam1511/jobfit)"
)


class JdFetchError(RuntimeError):
    """Raised when a JD cannot be produced from a URL.

    ``status_code`` is the HTTP status the router should return: 400 for
    user-fixable problems (bad URL, page has no JD), 502 for our own
    failures (browser crash).
    """

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class FetchedJd(BaseModel):
    jd_text: str
    final_url: str
    used_browser: bool


@dataclass(frozen=True)
class RawFetch:
    """Raw response from the HTTP or browser fetcher, pre-extraction."""

    html: str
    final_url: str


Resolver = Callable[[str], list[str]]
HttpCall = Callable[[str, float], RawFetch]
BrowserCall = Callable[[str, float], RawFetch]


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def _default_resolve(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _validate_url(url: str, resolve: Resolver) -> str:
    """Return the URL if safe to fetch, else raise ``JdFetchError``.

    Rejects non-http(s) schemes and hosts that resolve to a private,
    loopback, link-local, or multicast address. Must be called on every
    redirect target too - a public host that 302s to
    ``http://169.254.169.254/`` would otherwise defeat the guard.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise JdFetchError(f"Not a valid URL: {exc}") from exc
    if parts.scheme not in {"http", "https"}:
        raise JdFetchError("Only http:// and https:// URLs are supported.")
    if not parts.hostname:
        raise JdFetchError("URL is missing a host.")

    try:
        addrs = resolve(parts.hostname)
    except socket.gaierror as exc:
        raise JdFetchError(f"Could not resolve host: {exc}") from exc

    for addr in addrs:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise JdFetchError("URL resolves to a non-public address.")
    return url.strip()


# ---------------------------------------------------------------------------
# HTTP path
# ---------------------------------------------------------------------------

def _walk_redirects(client: httpx.Client, start_url: str, resolve: Resolver) -> RawFetch:
    """Follow redirects manually so ``_validate_url`` runs at each hop.

    ``httpx.Client`` must be built with ``follow_redirects=False``.
    """
    current = start_url
    for _ in range(MAX_REDIRECTS + 1):
        _validate_url(current, resolve)
        try:
            response = client.get(current)
        except httpx.HTTPError as exc:
            raise JdFetchError(f"Could not reach that URL: {exc}") from exc
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                raise JdFetchError("Redirect with no Location header.")
            current = str(httpx.URL(current).join(location))
            continue
        if response.status_code >= 400:
            raise JdFetchError(
                f"The page returned HTTP {response.status_code}.", status_code=400
            )
        return RawFetch(html=response.text, final_url=str(response.url))
    raise JdFetchError("Too many redirects.")


def _make_default_http_call(resolve: Resolver) -> HttpCall:
    def call(url: str, timeout: float) -> RawFetch:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
        ) as client:
            return _walk_redirects(client, url, resolve)
    return call


# ---------------------------------------------------------------------------
# Browser path
# ---------------------------------------------------------------------------

def _make_default_browser_call(resolve: Resolver) -> BrowserCall:
    """Load a URL in headless Chromium and re-validate the final URL.

    Playwright is imported lazily so tests that inject ``browser_call``
    don't need the package installed.
    """
    def call(url: str, timeout: float) -> RawFetch:
        try:
            from playwright.sync_api import Error as PlaywrightError, sync_playwright
        except ImportError as exc:
            raise JdFetchError(
                "Headless browser is not available in this environment.",
                status_code=502,
            ) from exc

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    context = browser.new_context(user_agent=USER_AGENT)
                    page = context.new_page()
                    page.goto(url, timeout=int(timeout * 1000), wait_until="domcontentloaded")
                    page.wait_for_load_state("networkidle", timeout=int(timeout * 1000))
                    final_url = page.url
                    _validate_url(final_url, resolve)
                    html = page.content()
                finally:
                    browser.close()
        except PlaywrightError as exc:
            raise JdFetchError(f"Browser failed to load that URL: {exc}", status_code=502) from exc
        return RawFetch(html=html, final_url=final_url)
    return call


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _extract(html: str) -> str:
    """Return the main-content text of ``html`` or an empty string.

    trafilatura strips nav, footer, cookie banners, script and style tags
    without any ML dependencies.
    """
    if not html:
        return ""
    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    return (text or "").strip()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_jd(
    url: str,
    *,
    http_timeout: float = 5.0,
    browser_timeout: float = 10.0,
    max_bytes: int = 20 * 1024,
    resolve_fn: Resolver | None = None,
    http_call: HttpCall | None = None,
    browser_call: BrowserCall | None = None,
) -> FetchedJd:
    """Fetch a JD from ``url`` and return the extracted text.

    HTTP first; if extraction produces less than ``MIN_EXTRACTED_CHARS``
    characters (page is JS-heavy or empty), fall back to a headless
    browser. Raise ``JdFetchError`` if neither pass yields usable text.
    """
    resolve = resolve_fn or _default_resolve
    safe_url = _validate_url(url, resolve)
    http = http_call or _make_default_http_call(resolve)
    browser = browser_call or _make_default_browser_call(resolve)

    raw = http(safe_url, http_timeout)
    text = _extract(raw.html)
    used_browser = False

    if len(text) < MIN_EXTRACTED_CHARS:
        logger.info("HTTP extraction was short (%d chars); trying browser.", len(text))
        raw = browser(safe_url, browser_timeout)
        text = _extract(raw.html)
        used_browser = True

    if len(text) < MIN_EXTRACTED_CHARS:
        raise JdFetchError(
            "Could not find a job description on that page. "
            "Try pasting the text instead."
        )

    if len(text.encode("utf-8")) > max_bytes:
        raise JdFetchError(
            "That page has more text than we accept. "
            "Paste the job description directly."
        )

    return FetchedJd(jd_text=text, final_url=raw.final_url, used_browser=used_browser)
