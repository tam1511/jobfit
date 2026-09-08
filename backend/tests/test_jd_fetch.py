"""Unit tests for the JD fetch pipeline.

All tests inject fake ``http_call`` / ``browser_call`` / ``resolve_fn`` so
no network or Playwright binary is required. The extraction stage runs
trafilatura for real against synthetic HTML.
"""

from __future__ import annotations

import httpx
import pytest

from app.jd_fetch import (
    JdFetchError,
    MIN_EXTRACTED_CHARS,
    RawFetch,
    _walk_redirects,
    fetch_jd,
)


LONG_JD_TEXT = (
    "We are hiring a senior backend engineer for our platform team. "
    "You will design and operate distributed systems that process large "
    "volumes of financial data. Requirements: seven years of Python or "
    "Go, deep familiarity with PostgreSQL and Kafka, hands-on with AWS. "
    "You will lead architecture reviews, mentor engineers, and drive "
    "reliability initiatives across the platform."
)
assert len(LONG_JD_TEXT) >= MIN_EXTRACTED_CHARS


def _resolve_public(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _resolve_loopback_v4(_host: str) -> list[str]:
    return ["127.0.0.1"]


def _resolve_loopback_v6(_host: str) -> list[str]:
    return ["::1"]


def _resolve_link_local_v6(_host: str) -> list[str]:
    return ["fe80::1"]


def _wrap(html_body: str, final_url: str = "https://example.com/jobs/1") -> RawFetch:
    return RawFetch(
        html=f"<html><body>{html_body}</body></html>",
        final_url=final_url,
    )


def _http_returning(body: str, url: str = "https://example.com/jobs/1"):
    def call(_url: str, _timeout: float) -> RawFetch:
        return _wrap(body, url)
    return call


def _browser_returning(body: str, url: str = "https://example.com/jobs/1"):
    def call(_url: str, _timeout: float) -> RawFetch:
        return _wrap(body, url)
    return call


def _boom_browser(_url: str, _timeout: float) -> RawFetch:
    raise AssertionError("Browser must not be called on the happy path.")


def test_http_pass_returns_text_without_touching_browser() -> None:
    result = fetch_jd(
        "https://example.com/jobs/1",
        http_call=_http_returning(f"<article><p>{LONG_JD_TEXT}</p></article>"),
        browser_call=_boom_browser,
        resolve_fn=_resolve_public,
    )
    assert LONG_JD_TEXT[:40] in result.jd_text
    assert result.used_browser is False
    assert result.final_url == "https://example.com/jobs/1"


def test_falls_back_to_browser_when_http_extraction_is_short() -> None:
    http_call = _http_returning("<div>too short</div>")
    browser_call = _browser_returning(
        f"<article><p>{LONG_JD_TEXT}</p></article>",
        url="https://example.com/jobs/1?rendered=1",
    )
    result = fetch_jd(
        "https://example.com/jobs/1",
        http_call=http_call,
        browser_call=browser_call,
        resolve_fn=_resolve_public,
    )
    assert result.used_browser is True
    assert result.final_url.endswith("?rendered=1")


def test_raises_when_neither_pass_finds_enough_text() -> None:
    with pytest.raises(JdFetchError) as exc:
        fetch_jd(
            "https://example.com/jobs/1",
            http_call=_http_returning("<p>tiny</p>"),
            browser_call=_browser_returning("<p>also tiny</p>"),
            resolve_fn=_resolve_public,
        )
    assert exc.value.status_code == 400
    assert "Could not find" in str(exc.value)


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(JdFetchError) as exc:
        fetch_jd(
            "file:///etc/passwd",
            http_call=_http_returning("<p>x</p>"),
            browser_call=_boom_browser,
            resolve_fn=_resolve_public,
        )
    assert exc.value.status_code == 400
    assert "http" in str(exc.value)


def test_rejects_loopback_host() -> None:
    with pytest.raises(JdFetchError) as exc:
        fetch_jd(
            "http://127.0.0.1/jobs/1",
            http_call=_http_returning("<p>x</p>"),
            browser_call=_boom_browser,
            resolve_fn=_resolve_loopback_v4,
        )
    assert exc.value.status_code == 400
    assert "non-public" in str(exc.value)


def test_rejects_ipv6_loopback() -> None:
    with pytest.raises(JdFetchError) as exc:
        fetch_jd(
            "http://[::1]/jobs/1",
            http_call=_http_returning("<p>x</p>"),
            browser_call=_boom_browser,
            resolve_fn=_resolve_loopback_v6,
        )
    assert exc.value.status_code == 400
    assert "non-public" in str(exc.value)


def test_rejects_ipv6_link_local() -> None:
    with pytest.raises(JdFetchError) as exc:
        fetch_jd(
            "http://[fe80::1]/jobs/1",
            http_call=_http_returning("<p>x</p>"),
            browser_call=_boom_browser,
            resolve_fn=_resolve_link_local_v6,
        )
    assert exc.value.status_code == 400
    assert "non-public" in str(exc.value)


def test_rejects_link_local_metadata_host() -> None:
    with pytest.raises(JdFetchError):
        fetch_jd(
            "http://169.254.169.254/latest/meta-data/",
            http_call=_http_returning("<p>x</p>"),
            browser_call=_boom_browser,
            resolve_fn=lambda _h: ["169.254.169.254"],
        )


def test_rejects_output_over_max_bytes() -> None:
    huge = LONG_JD_TEXT * 200
    with pytest.raises(JdFetchError) as exc:
        fetch_jd(
            "https://example.com/jobs/1",
            max_bytes=1024,
            http_call=_http_returning(f"<article><p>{huge}</p></article>"),
            browser_call=_boom_browser,
            resolve_fn=_resolve_public,
        )
    assert "more text than we accept" in str(exc.value)


def test_http_error_bubbles_as_400() -> None:
    def broken(_url: str, _timeout: float) -> RawFetch:
        raise JdFetchError("Could not reach that URL: timeout", status_code=400)

    with pytest.raises(JdFetchError) as exc:
        fetch_jd(
            "https://example.com/jobs/1",
            http_call=broken,
            browser_call=_boom_browser,
            resolve_fn=_resolve_public,
        )
    assert exc.value.status_code == 400


def test_browser_crash_bubbles_as_502() -> None:
    def http_short(_url: str, _timeout: float) -> RawFetch:
        return _wrap("<p>too short</p>")

    def browser_broken(_url: str, _timeout: float) -> RawFetch:
        raise JdFetchError("Browser failed to load that URL: crashed", status_code=502)

    with pytest.raises(JdFetchError) as exc:
        fetch_jd(
            "https://example.com/jobs/1",
            http_call=http_short,
            browser_call=browser_broken,
            resolve_fn=_resolve_public,
        )
    assert exc.value.status_code == 502


# ---------------------------------------------------------------------------
# Redirect handling: the SSRF guard must re-check each hop.
# ---------------------------------------------------------------------------

def _resolve_map(mapping: dict[str, list[str]]):
    def resolve(host: str) -> list[str]:
        if host in mapping:
            return mapping[host]
        raise AssertionError(f"Unexpected host resolution: {host}")
    return resolve


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_walk_redirects_follows_public_chain_to_html() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://a.example.com/jobs/1":
            return httpx.Response(302, headers={"location": "https://b.example.com/jobs/1"})
        if str(request.url) == "https://b.example.com/jobs/1":
            return httpx.Response(200, text=f"<html><body><article><p>{LONG_JD_TEXT}</p></article></body></html>")
        raise AssertionError(f"Unexpected URL: {request.url}")

    resolve = _resolve_map({"a.example.com": ["93.184.216.34"], "b.example.com": ["93.184.216.35"]})
    with _mock_client(handler) as client:
        raw = _walk_redirects(client, "https://a.example.com/jobs/1", resolve)
    assert LONG_JD_TEXT[:40] in raw.html
    assert raw.final_url == "https://b.example.com/jobs/1"


def test_walk_redirects_blocks_redirect_to_metadata_ip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://public.example.com/jobs/1":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        raise AssertionError(f"Fetch reached forbidden URL: {request.url}")

    resolve = _resolve_map({
        "public.example.com": ["93.184.216.34"],
        "169.254.169.254": ["169.254.169.254"],
    })
    with _mock_client(handler) as client:
        with pytest.raises(JdFetchError) as exc:
            _walk_redirects(client, "https://public.example.com/jobs/1", resolve)
    assert exc.value.status_code == 400
    assert "non-public" in str(exc.value)


def test_walk_redirects_stops_after_max_hops() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://loop.example.com/next"})

    resolve = _resolve_map({"loop.example.com": ["93.184.216.34"]})
    with _mock_client(handler) as client:
        with pytest.raises(JdFetchError) as exc:
            _walk_redirects(client, "https://loop.example.com/start", resolve)
    assert "Too many redirects" in str(exc.value)


def test_walk_redirects_rejects_redirect_without_location() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302)

    resolve = _resolve_map({"public.example.com": ["93.184.216.34"]})
    with _mock_client(handler) as client:
        with pytest.raises(JdFetchError) as exc:
            _walk_redirects(client, "https://public.example.com/jobs/1", resolve)
    assert "Location" in str(exc.value)


def test_walk_redirects_maps_http_error_status_to_400() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    resolve = _resolve_map({"public.example.com": ["93.184.216.34"]})
    with _mock_client(handler) as client:
        with pytest.raises(JdFetchError) as exc:
            _walk_redirects(client, "https://public.example.com/jobs/1", resolve)
    assert exc.value.status_code == 400
    assert "404" in str(exc.value)
