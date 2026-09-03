"""Read Reddit session cookies from Chrome on macOS.

When you're logged into Reddit in Chrome (or even just browsing anonymously
past a page or two), Chrome accumulates a set of cookies — `loid`, `csv`,
`edgebucket`, and optionally `reddit_session` — that Reddit's anti-bot
layer uses to distinguish "real browser session" from "unauthenticated
script." Without these cookies, Reddit returns HTTP 403 to `.json` endpoints
even when the request has a perfect Chrome User-Agent and TLS fingerprint.

This module extracts those cookies via `pycookiecheat`, which reads Chrome's
encrypted cookie store on disk and uses macOS Keychain to decrypt them.

The first time the wrapper runs, macOS shows a Keychain permission prompt
(*"Claude wants to use your confidential information stored in 'Chrome Safe
Storage'"*). Click **Always Allow** to suppress future prompts.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

REDDIT_URL = "https://www.reddit.com"


def read_reddit_cookies_from_chrome() -> dict[str, str]:
    """Read all Reddit cookies from Chrome for `reddit.com`.

    Returns:
        A dict of cookie name → value. Returns an empty dict (rather than
        raising) on any failure — cookie store missing, Keychain locked,
        pycookiecheat error, etc. The caller can then decide whether to try
        the request without cookies (it will likely 403) or fail loudly.
    """
    try:
        from pycookiecheat import chrome_cookies
    except ImportError as e:
        log.error("pycookiecheat not installed: %s", e)
        return {}

    try:
        cookies = chrome_cookies(REDDIT_URL)
    except Exception as e:  # noqa: BLE001 — intentional broad catch
        log.warning("cookie read failed for %s: %s: %s", REDDIT_URL, type(e).__name__, e)
        return {}

    if not cookies:
        log.warning("no cookies found in Chrome for %s — Reddit will likely 403", REDDIT_URL)
    else:
        log.info("loaded %d Reddit cookies from Chrome", len(cookies))
    return cookies
