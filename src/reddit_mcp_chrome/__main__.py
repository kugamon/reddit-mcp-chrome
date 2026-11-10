"""Entry point.

    reddit-mcp-chrome           run the MCP server over stdio (what Claude Desktop launches)
    reddit-mcp-chrome --login   open the browser window on screen so you can sign in to Reddit
"""
from __future__ import annotations

import asyncio
import os
import sys

from . import __version__


async def _login() -> None:
    os.environ["REDDIT_MCP_SHOW_WINDOW"] = "1"
    from .browser import RedditBrowser

    b = RedditBrowser()
    page = await b.page()
    await page.goto("https://www.reddit.com/login/")
    print("Sign in to Reddit in the window that opened, then close the window.", file=sys.stderr)
    try:
        await page.wait_for_event("close", timeout=0)
    finally:
        await b.close()
    print(f"Saved. Profile: {b.profile_dir}", file=sys.stderr)


def main() -> int:
    if "--login" in sys.argv[1:]:
        asyncio.run(_login())
        return 0
    print(f"[reddit-mcp-chrome v{__version__}] Reading Reddit through a Chrome window", file=sys.stderr)
    from .server import mcp

    mcp.run(show_banner=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
