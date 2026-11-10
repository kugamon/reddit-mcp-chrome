"""MCP tools. Names and arguments match reddit-no-auth-mcp-server, so prompts
and skills written against v0.1.x keep working."""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from urllib.parse import quote_plus, urlparse

from fastmcp import FastMCP

from . import __version__, extract
from .browser import RedditBrowser

browser = RedditBrowser()


@asynccontextmanager
async def _lifespan(_server):
    try:
        yield
    finally:
        await browser.close()


mcp = FastMCP(
    "reddit-mcp-chrome",
    version=__version__,
    lifespan=_lifespan,
    instructions=(
        "Read Reddit through a real Chrome window: search, subreddit feeds, posts with "
        "comments, and user activity. Calls are paced (about 2 seconds between page "
        "loads), so prefer one well-targeted call over many. If a call reports a human "
        "check, tell the user to complete it in the Chrome window, then retry."
    ),
)

_NAME = re.compile(r"^[A-Za-z0-9_-]{1,50}$")
_SORTS = {"relevance", "hot", "top", "new", "comments"}
_FEEDS = {"hot", "new", "top", "rising"}
_TIMES = {"hour", "day", "week", "month", "year", "all"}


def _name(value: str, kind: str) -> str:
    n = re.sub(r"^/?(r|u|user)/", "", value.strip().strip("/"), flags=re.I)
    if not _NAME.match(n):
        raise ValueError(f"Not a valid {kind} name: {value!r}")
    return n


def _pick(value: str | None, allowed: set[str], default: str) -> str:
    v = (value or default).lower()
    return v if v in allowed else default


def _clamp(limit: int) -> int:
    return max(1, min(int(limit or 25), 100))


def _num(v):
    if v in (None, ""):
        return None
    s = str(v).strip().lower().replace(",", "")
    mult = 1
    if s.endswith("k"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def _tidy(item: dict) -> dict:
    for k in ("score", "num_comments"):
        if k in item:
            item[k] = _num(item[k])
    if item.get("upvote_ratio") not in (None, ""):
        try:
            item["upvote_ratio"] = round(float(item["upvote_ratio"]), 3)
        except ValueError:
            item["upvote_ratio"] = None
    return {k: v for k, v in item.items() if v not in (None, "")}


@mcp.tool
async def reddit_search(query: str, limit: int = 25, sort: str = "relevance") -> list[dict]:
    """Search all of Reddit for posts. sort: relevance, hot, top, new, comments."""
    sort = _pick(sort, _SORTS, "relevance")
    async with browser.lock:
        await browser.goto(f"/search/?q={quote_plus(query)}&type=posts&sort={sort}")
        rows = await browser.collect(extract.SEARCH_RESULTS, "permalink", _clamp(limit), ready='[data-testid="search-post-unit"]')
    return [_tidy(r) for r in rows]


@mcp.tool
async def reddit_search_subreddit(
    subreddit: str, query: str, limit: int = 25, sort: str = "relevance"
) -> list[dict]:
    """Search posts within one subreddit. sort: relevance, hot, top, new, comments."""
    sub = _name(subreddit, "subreddit")
    sort = _pick(sort, _SORTS, "relevance")
    async with browser.lock:
        await browser.goto(
            f"/r/{sub}/search/?q={quote_plus(query)}&type=posts&sort={sort}&restrict_sr=1"
        )
        rows = await browser.collect(extract.SEARCH_RESULTS, "permalink", _clamp(limit), ready='[data-testid="search-post-unit"]')
    return [_tidy(r) for r in rows]


@mcp.tool
async def reddit_get_subreddit_posts(
    subreddit: str, limit: int = 25, category: str = "hot", time_filter: str = "all"
) -> list[dict]:
    """List posts from a subreddit. category: hot, new, top, rising.
    time_filter (used with top): hour, day, week, month, year, all."""
    sub = _name(subreddit, "subreddit")
    cat = _pick(category, _FEEDS, "hot")
    path = f"/r/{sub}/{cat}/"
    if cat == "top":
        path += f"?t={_pick(time_filter, _TIMES, 'all')}"
    async with browser.lock:
        await browser.goto(path)
        rows = await browser.collect(extract.FEED_POSTS, "id", _clamp(limit), ready="shreddit-post")
    return [_tidy(r) for r in rows]


@mcp.tool
async def reddit_get_post(permalink: str, comment_limit: int = 100) -> dict:
    """Get a post and its comments. permalink: a /r/.../comments/... path or full URL.
    Comments come back flat in page order with a depth field (0 = top level)."""
    path = urlparse(permalink).path if permalink.startswith("http") else permalink
    if not re.match(r"^/r/[A-Za-z0-9_-]+/comments/", path or ""):
        raise ValueError(f"Not a Reddit post permalink: {permalink!r}")
    async with browser.lock:
        page = await browser.goto(path)
        post = await page.evaluate(extract.POST_DETAIL)
        if not post:
            raise LookupError(f"No post found at {permalink}")
        comments = await browser.collect(extract.COMMENTS, "id", max(0, min(int(comment_limit), 500)) or 1,
                                         ready="shreddit-comment")
    out = _tidy(post)
    out["comments"] = [_tidy(c) for c in comments][: max(0, int(comment_limit))]
    return out


@mcp.tool
async def reddit_get_user(username: str, limit: int = 25) -> list[dict]:
    """Get a user's recent public activity: posts and comments, newest first."""
    user = _name(username, "username")
    async with browser.lock:
        await browser.goto(f"/user/{user}/")
        rows = await browser.collect(extract.USER_OVERVIEW, "id", _clamp(limit),
                                      ready="shreddit-post, shreddit-profile-comment")
    rows.sort(key=lambda r: r.get("created") or "", reverse=True)
    return [_tidy(r) for r in rows]


@mcp.tool
async def reddit_get_user_posts(
    username: str, limit: int = 25, category: str = "new", time_filter: str = "all"
) -> list[dict]:
    """List posts a user submitted. category: hot, new, top.
    time_filter (used with top): hour, day, week, month, year, all.
    Reddit doesn't render the top view for signed-out visitors; when it comes back
    empty, this returns the user's recent posts sorted by score instead."""
    user = _name(username, "username")
    cat = _pick(category, {"hot", "new", "top"}, "new")
    tf = _pick(time_filter, _TIMES, "all")
    async with browser.lock:
        await browser.goto(f"/user/{user}/submitted/?sort={cat}&t={tf}")
        rows = await browser.collect(extract.FEED_POSTS, "id", _clamp(limit), ready="shreddit-post")
        if not rows and cat == "top":
            await browser.goto(f"/user/{user}/submitted/?sort=new")
            rows = await browser.collect(extract.FEED_POSTS, "id", 100, ready="shreddit-post")
            rows.sort(key=lambda r: _num(r.get("score")) or 0, reverse=True)
            rows = rows[: _clamp(limit)]
    return [_tidy(r) for r in rows]
