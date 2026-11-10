"""One real Chrome window, driven by Playwright, shared by every tool.

Why a visible (but offscreen) window and not headless
----------------------------------------------------
As of Nov 2026 Reddit answers headless Chrome with a "Prove your humanity"
page, and returns 403 to its .json endpoints for every anonymous client,
including a real browser. A normal, headful Chrome window loads Reddit's
pages fine. So we launch the user's installed Chrome with its own profile
and park the window offscreen.

What this deliberately does NOT do
----------------------------------
No fingerprint spoofing, no stealth patches, no CAPTCHA solving. If Reddit
shows a human check, the window is moved onto the screen and the tool call
fails with a message asking the user to complete it. After that, the saved
profile carries the clearance.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

BASE = "https://www.reddit.com"
DEFAULT_PROFILE = Path.home() / ".reddit-mcp-chrome" / "profile"
OFFSCREEN = {"left": -2400, "top": -2400}
ONSCREEN = {"left": 80, "top": 80, "width": 1200, "height": 900}


class HumanCheckRequired(RuntimeError):
    """Reddit wants a human to complete a check in the browser window."""


class RedditBrowser:
    def __init__(self) -> None:
        self.profile_dir = Path(
            os.environ.get("REDDIT_MCP_PROFILE_DIR", DEFAULT_PROFILE)
        ).expanduser()
        self.show_window = os.environ.get("REDDIT_MCP_SHOW_WINDOW") == "1"
        self.min_interval = float(os.environ.get("REDDIT_MCP_MIN_INTERVAL", "2.0"))
        self.lock = asyncio.Lock()
        self._pw = None
        self._ctx = None
        self._page = None
        self._last_nav = 0.0
        self._onscreen = False

    async def page(self):
        """Return the shared page, launching Chrome on first use."""
        if self._page is not None and not self._page.is_closed():
            return self._page
        await self.close()
        from playwright.async_api import async_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        args = [] if self.show_window else [
            f"--window-position={OFFSCREEN['left']},{OFFSCREEN['top']}"
        ]
        launch = dict(headless=False, args=args, viewport=None)
        try:
            self._ctx = await self._pw.chromium.launch_persistent_context(
                str(self.profile_dir), channel="chrome", **launch
            )
        except Exception as chrome_err:  # Chrome not installed: try Playwright's Chromium
            try:
                self._ctx = await self._pw.chromium.launch_persistent_context(
                    str(self.profile_dir), **launch
                )
            except Exception as chromium_err:
                await self.close()
                raise RuntimeError(
                    "Couldn't start a browser. Install Google Chrome, or install "
                    "Playwright's Chromium with: "
                    "uvx --from reddit-mcp-chrome playwright install chromium. "
                    f"(chrome: {chrome_err}; chromium: {chromium_err})"
                ) from chromium_err
        self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        self._onscreen = self.show_window
        return self._page

    async def goto(self, path_or_url: str):
        """Load a Reddit page, pacing requests and surfacing human checks."""
        page = await self.page()
        wait = self.min_interval - (time.monotonic() - self._last_nav)
        if wait > 0:
            await asyncio.sleep(wait)
        url = path_or_url if path_or_url.startswith("http") else BASE + path_or_url
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self._last_nav = time.monotonic()
        await page.wait_for_timeout(1500)

        status = resp.status if resp else 0
        title = (await page.title()) or ""
        rendered = await page.locator("shreddit-app").count() > 0
        if "prove your humanity" in title.lower() or (status in (403, 429) and not rendered):
            await self._move_window(onscreen=True)
            raise HumanCheckRequired(
                f"Reddit is asking for a human check (HTTP {status}). A Chrome window "
                "showing Reddit is now on your screen: complete the check there, then "
                "retry this request."
            )
        await self._move_window(onscreen=False)
        if status == 404:
            raise LookupError(f"Not found on Reddit: {url}")
        if status == 403:
            raise PermissionError(
                f"Reddit returned 403 for {url}. The community may be private, "
                "quarantined or banned."
            )
        return page

    async def collect(
        self, js: str, key: str, limit: int, ready: str | None = None, max_rounds: int = 12
    ) -> list[dict]:
        """Run an extractor, scrolling for more until `limit` unique items or no growth.

        Reddit's feeds are virtualised (old cards leave the DOM as you scroll), so
        items are accumulated by `key` across rounds rather than counted in the DOM.
        """
        page = self._page
        if ready:
            # Reddit renders results client-side, often 2-4 s after load.
            try:
                await page.wait_for_selector(ready, state="attached", timeout=8000)
            except Exception:
                return []  # nothing rendered: genuinely empty (or a layout change)
        items: dict[str, dict] = {}
        stale = 0
        for _ in range(max_rounds + 1):
            before = len(items)
            for item in await page.evaluate(js) or []:
                k = item.get(key)
                if k and k not in items:
                    items[k] = item
            if len(items) >= limit:
                break
            stale = stale + 1 if len(items) == before else 0
            if stale >= 3:
                break
            await page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            await page.wait_for_timeout(1300)
        return list(items.values())[:limit]

    async def _move_window(self, onscreen: bool) -> None:
        if self.show_window or onscreen == self._onscreen or self._ctx is None:
            return
        try:
            cdp = await self._ctx.new_cdp_session(self._page)
            win = await cdp.send("Browser.getWindowForTarget")
            await cdp.send("Browser.setWindowBounds",
                           {"windowId": win["windowId"], "bounds": {"windowState": "normal"}})
            bounds = dict(ONSCREEN) if onscreen else dict(OFFSCREEN)
            await cdp.send("Browser.setWindowBounds",
                           {"windowId": win["windowId"], "bounds": bounds})
            await cdp.detach()
            if onscreen:
                await self._page.bring_to_front()
            self._onscreen = onscreen
        except Exception:
            pass  # Window placement is a convenience; never fail a call over it.

    async def close(self) -> None:
        ctx, pw = self._ctx, self._pw
        self._ctx = self._page = self._pw = None
        try:
            if ctx is not None:
                await ctx.close()
        except Exception:
            pass
        try:
            if pw is not None:
                await pw.stop()
        except Exception:
            pass
