"""Monkey-patch `redd`'s HTTP adapters to use curl_cffi + Chrome cookies.

Why monkey-patch?
-----------------
`reddit-no-auth-mcp-server` uses the `redd` library for all HTTP calls. `redd`
in turn uses `requests` (sync) and `httpx` (async), both of which have TLS
fingerprints Reddit's anti-bot layer easily identifies. Even sending a
Chrome User-Agent doesn't help — Reddit inspects the JA3 hash, HTTP/2
settings frames, and header order.

Rather than fork `redd` or `reddit-no-auth-mcp-server`, we patch the one
method in each of `redd`'s sync + async HTTP adapters, replacing the
underlying HTTP client with `curl_cffi` — a Python binding around curl
that impersonates real browsers' TLS handshakes byte-for-byte.

Combined with the user's real Chrome session cookies (see auth.py), Reddit
treats requests as coming from the user's actual Chrome browser.
"""
from __future__ import annotations

from typing import Any

from .auth import read_reddit_cookies_from_chrome

# Chrome version to impersonate. curl_cffi ships new profiles as Chrome
# releases; if Reddit tightens further, bump this to the latest available.
IMPERSONATE = "chrome131"


def install() -> None:
    """Install the curl_cffi + Chrome-cookies patch on both `redd` HTTP adapters.

    Call this exactly once, before importing/starting `reddit-no-auth-mcp-server`.
    The patch is class-level and persists for the lifetime of the process.

    Cookies are read from Chrome once at install time. They stay usable for
    the duration of the MCP server process because Reddit's session cookies
    have hour(s)-long lifetimes and Chrome refreshes them whenever the user
    loads a Reddit page. If a long-running session goes stale, restart Claude
    Desktop to re-read cookies.
    """
    from curl_cffi import requests as cffi_requests
    from curl_cffi.requests import AsyncSession as CffiAsyncSession
    from redd.adapters import http_sync, http_async

    cookies = read_reddit_cookies_from_chrome()
    sync_session = cffi_requests.Session(impersonate=IMPERSONATE)
    async_session = CffiAsyncSession(impersonate=IMPERSONATE)

    def _patched_sync_get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        effective_timeout = timeout if timeout is not None else self._timeout
        r = sync_session.get(url, params=params, cookies=cookies, timeout=effective_timeout)
        r.raise_for_status()
        return r.json()

    async def _patched_async_get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        effective_timeout = timeout if timeout is not None else self._timeout
        r = await async_session.get(url, params=params, cookies=cookies, timeout=effective_timeout)
        r.raise_for_status()
        return r.json()

    http_sync.RequestsHttpAdapter.get = _patched_sync_get
    http_async.HttpxAsyncAdapter.get = _patched_async_get
