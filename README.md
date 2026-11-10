# Reddit MCP Server — Reads Reddit Through Chrome

[![PyPI](https://img.shields.io/pypi/v/reddit-mcp-chrome?label=pypi&color=blue)](https://pypi.org/project/reddit-mcp-chrome/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](#)

A local MCP server that gives Claude Desktop **six Reddit tools** (search all of Reddit, search a subreddit, browse a subreddit, read a post with its comments, see a user's activity, list a user's posts) by **reading Reddit through a real Chrome window** kept out of sight. No Reddit API key, no OAuth app.

Why a browser: as of November 2026 Reddit blocks its `.json` endpoints for every anonymous client and isn't approving new API apps. A normal Chrome window still loads Reddit's pages, so that's what this uses.

---

## How it fits together

```
Claude Desktop ── stdio ──▶ this package (Python) ── Playwright ──▶ Chrome window (offscreen)
                                   │                                     │
                                   │                                     ▼
                                   │                               www.reddit.com pages
                                   │                                     │
                                   └──── reads posts/comments from ◀────┘
                                         the rendered page
```

On the first tool call the server starts your installed Google Chrome with its own profile (`~/.reddit-mcp-chrome/profile`, separate from your everyday Chrome) and parks the window offscreen. Each tool loads the matching Reddit page and reads the structured data Reddit's web app puts on its post and comment elements. One window serves every call, with about 2 seconds between page loads.

---

## Files in this repo

- **`src/reddit_mcp_chrome/server.py`** — the six MCP tools. Names and arguments match [`reddit-no-auth-mcp-server`](https://pypi.org/project/reddit-no-auth-mcp-server/), so prompts written for v0.1 keep working.
- **`src/reddit_mcp_chrome/browser.py`** — starts and owns the Chrome window, paces page loads, detects human checks and moves the window on screen when one appears.
- **`src/reddit_mcp_chrome/extract.py`** — the JavaScript that reads posts, comments and search results from Reddit's pages. If Reddit changes its markup, this is the only file to update.
- **`src/reddit_mcp_chrome/__main__.py`** — entry point, plus the `--login` option.
- **`pyproject.toml`** — package metadata. Pins `fastmcp<4` and `playwright<2`.
- **`examples/claude_desktop_config.example.json`** — copy-paste config.
- **`docs/how-it-works.md`** — the full story: the v0.1 design, why it stopped working, what we tested, and why this one is built the way it is.

---

## Setup — Part 1: Add to Claude Desktop (~1 min, one-time)

**Needs:** macOS, Google Chrome, and [`uv`](https://docs.astral.sh/uv/getting-started/installation/).

### Fastest path — have Claude do it for you

If Claude Desktop has filesystem access to your home directory (Cowork mode does by default), paste this into a new chat:

```
Add a Reddit MCP entry to my Claude Desktop config named `reddit`.
The command should be `uvx reddit-mcp-chrome` (it's on PyPI).
No env vars or API keys. Make a backup of my existing config first.
```

Claude backs up `claude_desktop_config.json`, adds the entry next to your existing ones, and tells you when to restart. Then skip to **Restart Claude Desktop**.

### Alternate route — edit `claude_desktop_config.json` yourself

**1. Open the config.** On macOS:

```
~/Library/Application Support/Claude/claude_desktop_config.json
```

**2. Add this entry under `mcpServers`.**

```jsonc
{
  "mcpServers": {
    "reddit": {
      "command": "uvx",
      "args": ["reddit-mcp-chrome"]
    }
  }
}
```

### Restart Claude Desktop

Cmd+Q (a full quit, not just closing the window) and reopen.

### Sanity check

Ask: *"Using the reddit MCP, show me this week's top posts in r/salesforce."* You should get a list of posts with scores and comment counts.

---

## Setup — Part 2: The Chrome window and the first-run check

- **A second Chrome icon appears in your Dock** while the server is running. That's its window, parked offscreen. Your normal Chrome isn't touched.
- **Reddit may ask you to prove you're human on first use.** When that happens the window moves onto your screen and the tool call returns a message saying so. Complete the check in that window and ask Claude again. The profile remembers it, so this is usually a one-time step. The server never solves these checks itself.
- **Signing in is optional.** Everything works signed out. If you want results as your account sees them, run this once in Terminal, sign in, then close the window:

  ```bash
  uvx reddit-mcp-chrome --login
  ```

---

## The six tools

| Tool | What it does | Arguments |
| --- | --- | --- |
| `reddit_search` | Search all of Reddit for posts | `query`, `limit` (25), `sort`: relevance, hot, top, new, comments |
| `reddit_search_subreddit` | Search posts in one subreddit | `subreddit`, `query`, `limit`, `sort` |
| `reddit_get_subreddit_posts` | Browse a subreddit's feed | `subreddit`, `limit`, `category`: hot, new, top, rising; `time_filter` with top: hour, day, week, month, year, all |
| `reddit_get_post` | A post plus its comments | `permalink` (path or full URL), `comment_limit` (100) |
| `reddit_get_user` | A user's recent posts and comments, newest first | `username`, `limit` |
| `reddit_get_user_posts` | Posts a user submitted | `username`, `limit`, `category`: hot, new, top; `time_filter` |

Subreddit and user names work with or without the `r/` or `u/` prefix. `limit` caps at 100.

Posts come back with title, author, subreddit, score, comment count, timestamp, permalink and (for text posts) the body. Comments come back flat in page order with a `depth` field (0 = top level).

---

## Typical response times

Measured on a MacBook in November 2026:

| Call | Time |
| --- | --- |
| `reddit_get_user` (25 items) | ~2 s |
| `reddit_get_subreddit_posts` (30 posts) | ~5 s |
| `reddit_get_post` (35 comments) | ~7 s |
| `reddit_search` (20 results) | ~20 s |

The first call after Claude Desktop starts adds a few seconds while Chrome launches. Search is the slowest because Reddit loads results as you scroll.

---

## Why it's built this way (vs. alternatives we tried)

- **v0.1's approach, Chrome cookies + `curl_cffi` Chrome impersonation against `.json` endpoints**, worked from September to early November 2026, then started returning 403 on every call. We tested every `curl_cffi` Chrome profile (142 to 152), with and without cookies: all 403.
- **The official Reddit API** isn't an option: Reddit isn't approving new API apps.
- **Headless Chrome** gets a "Prove your humanity" page.
- **A real Chrome window** loads Reddit normally. Even inside it, `.json` returns 403, so the tools read the rendered pages instead.
- **Stealth or fingerprint-spoofing browsers and automated CAPTCHA solving** were deliberately left out. If Reddit wants a human check, a human does it.

Details, including the full test matrix, are in [`docs/how-it-works.md`](docs/how-it-works.md).

---

## Settings

All optional, set as `env` in the Claude Desktop config entry:

| Variable | Default | What it does |
| --- | --- | --- |
| `REDDIT_MCP_PROFILE_DIR` | `~/.reddit-mcp-chrome/profile` | Where the Chrome profile lives |
| `REDDIT_MCP_SHOW_WINDOW` | off | Set to `1` to keep the window on screen (useful for debugging) |
| `REDDIT_MCP_MIN_INTERVAL` | `2.0` | Minimum seconds between page loads |

---

## Local development

```bash
git clone https://github.com/kugamon/reddit-mcp-chrome.git
cd reddit-mcp-chrome
uv sync

# Run the server the way Claude Desktop does
uv run reddit-mcp-chrome
```

To point Claude Desktop at a local checkout:

```jsonc
"args": ["run", "--directory", "/absolute/path/to/reddit-mcp-chrome", "reddit-mcp-chrome"]
```

---

## Limits and use

- Reddit's terms restrict automated access. This is built for personal, human-scale research: a few calls at a time, paced. Don't use it to bulk-collect Reddit.
- `reddit_get_user_posts` with `top`: Reddit doesn't show that view to signed-out visitors, so the tool returns the user's recent posts sorted by score instead.
- Image- or GIF-only comments come back without a body.
- Comments are what the post page renders on load, plus a few scrolls. Deeply nested threads behind "more replies" aren't expanded.
- If you have a monitor arranged above or left of your main screen, the parked window may appear on it. Use `REDDIT_MCP_SHOW_WINDOW=1` or rearrange displays.

---

## Troubleshooting

**"Reddit is asking for a human check"**: The Chrome window is now on your screen. Complete the check there and ask Claude again.

**"Server disconnected" at startup**: Check `~/Library/Logs/Claude/mcp-server-reddit.log` for the traceback. `uvx --refresh reddit-mcp-chrome` fixes most install problems.

**"Couldn't start a browser"**: Install Google Chrome. Or install Playwright's bundled Chromium: `uvx --from reddit-mcp-chrome playwright install chromium`.

**Tools return empty lists for pages that clearly have content**: Reddit probably changed its markup. Open an issue, or update the selectors in `extract.py`.

**A Chrome window is visible when it shouldn't be**: It stays on screen after a human check until the next successful call moves it back. Ask Claude for anything on Reddit and it will park itself.

---

## Version history

- **v0.2.0** — Rewritten to read Reddit through a real Chrome window (Playwright, installed Chrome, own profile, kept offscreen). Same six tool names and arguments. Adds `--login`, human-check hand-off, pacing, user-top fallback. Drops `reddit-no-auth-mcp-server`, `redd`, `curl_cffi` and `pycookiecheat`. Pins `fastmcp<4` and `playwright<2`.
- **v0.1.0** — Wrapped `reddit-no-auth-mcp-server`, adding Chrome session cookies and `curl_cffi` Chrome TLS impersonation. Stopped working in November 2026 when Reddit blocked `.json` for anonymous clients.
