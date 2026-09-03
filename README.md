# Reddit MCP Server — Uses Your Chrome Session

[![PyPI](https://img.shields.io/pypi/v/reddit-mcp-chrome?label=pypi&color=blue)](https://pypi.org/project/reddit-mcp-chrome/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](#)

A local MCP server that exposes Reddit search, subreddit browsing, and post-detail tools inside Claude Desktop — and **bypasses Reddit's anti-scraping** by using your Chrome browser's session cookies plus a real Chrome TLS fingerprint. Wraps [`reddit-no-auth-mcp-server`](https://pypi.org/project/reddit-no-auth-mcp-server/) (which uses [`redd`](https://pypi.org/project/redd/)) and swaps its HTTP layer for `curl_cffi` so Reddit treats requests as coming from your real browser.

No Reddit API key, no OAuth, no personal-use API application — just be logged into (or have recently visited) reddit.com in Chrome.

---

## How it fits together

```
Claude Desktop ── stdio ──▶ this package (Python) ── HTTPS ──▶ Reddit JSON API
       │                            │                          (via curl_cffi with
       │                            │                           Chrome TLS fingerprint)
       │                            │
       │                            └─ reads cookies ──▶ Chrome cookies on disk
       │                               once at startup      (macOS Keychain)
       │
       └── one entry in claude_desktop_config.json
```

The package is a thin Python shim around `reddit-no-auth-mcp-server`. At startup, it reads your Chrome cookies for `reddit.com` (the `loid`, `csv`, `edgebucket`, `reddit_session` set) and monkey-patches `redd`'s HTTP adapters to use `curl_cffi` — a Python HTTP client that impersonates real Chrome's TLS handshake byte-for-byte. Reddit's anti-bot layer sees requests that look identical to your real browser and lets them through.

---

## Files in this repo

- **`src/reddit_mcp_chrome/__main__.py`** — entry point. Installs the patch, then hands off to `reddit-no-auth-mcp-server`.
- **`src/reddit_mcp_chrome/patch.py`** — monkey-patches `redd.adapters.http_sync.RequestsHttpAdapter.get` and `redd.adapters.http_async.HttpxAsyncAdapter.get` to route through `curl_cffi` with Chrome cookies + `chrome131` impersonation.
- **`src/reddit_mcp_chrome/auth.py`** — reads Reddit cookies from Chrome via `pycookiecheat`. Returns an empty dict on any failure so the caller can decide how to handle it.
- **`pyproject.toml`** — package metadata + entry point. `uvx` reads this when launching.
- **`examples/claude_desktop_config.example.json`** — copy-paste-ready Claude Desktop config snippet.
- **`docs/how-it-works.md`** — full architecture write-up with the design decisions, what we tried and discarded (curl_cffi alone, cookies alone, cookies + curl_cffi together), and the lessons that generalize to other anti-scraped MCP wrappers.

---

## Setup — Part 1: Add to Claude Desktop (~1 min, one-time)

### Fastest path — have Claude do it for you

If Claude Desktop already has filesystem access to your home directory (Cowork mode users do by default), you don't need to touch JSON at all. Paste the following into a fresh Claude chat:

```
Add a Reddit MCP entry to my Claude Desktop config named `reddit`.
The MCP command should be `uvx reddit-mcp-chrome` (it's on PyPI).
No env vars, no API keys — the wrapper reads Chrome cookies at
runtime. Make a backup of my existing config first.
```

Claude reads your existing `claude_desktop_config.json`, adds the entry alongside anything already there, backs up the original, and tells you when to restart. When Claude confirms it's done, skip to **Restart Claude Desktop** below.

### Alternate route — edit `claude_desktop_config.json` yourself

If you'd rather edit JSON by hand:

**1. Open your Claude Desktop config.** On macOS the file lives at:

```
~/Library/Application Support/Claude/claude_desktop_config.json
```

**2. Add this entry to `mcpServers`.**

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

That's the entire configuration — no env vars, no tokens, no API keys.

### Restart Claude Desktop

Cmd+Q (a full quit — not just closing the window) and reopen. Claude Desktop reads the config at startup.

### Sanity check

In a new Claude conversation, ask: *"using the reddit MCP, search reddit for 'salesforce cpq' and give me the top 3 results"* — Claude will call the `reddit_search` tool. If it returns real posts, the wiring is correct.

The first time the wrapper runs, macOS will prompt for Keychain access (the dialog says *"Claude wants to use your confidential information stored in 'Chrome Safe Storage'"*). Click **Always Allow** to suppress future prompts.

---

## Setup — Part 2: Have Chrome visit Reddit at least once

You don't need to be *logged in* — Reddit's cookies for anonymous browsing are sufficient. But you do need Chrome to have visited `reddit.com` recently enough that Chrome's cookie store has entries for the domain. If you never use Reddit in Chrome, open a tab to `https://www.reddit.com/` once, dismiss whatever consent banner appears, and you're set.

If you *are* logged in, that works too — the wrapper picks up whatever cookies are present, including the authenticated session cookie.

---

## The Reddit tools

All tools come from the underlying [`reddit-no-auth-mcp-server`](https://pypi.org/project/reddit-no-auth-mcp-server/) — this package just adds the auth-bypass layer on top.

| Tool | Purpose |
| --- | --- |
| `reddit_search` | Full-text search across all of Reddit |
| `reddit_search_subreddit` | Full-text search scoped to one subreddit |
| `reddit_get_subreddit_posts` | List posts from a subreddit (`hot` / `new` / `top` / `rising`) |
| `reddit_get_post` | Get one post + its comment tree |
| `reddit_get_user` | Get a user's profile and recent activity |
| `reddit_get_user_posts` | List posts submitted by a user |

Each tool's full schema is advertised through the MCP `tools/list` method — Claude reads it automatically.

---

## How the bypass actually works

```
Claude asks for r/salesforce hot posts
  │
  ▼
this package's __main__.py already installed the patch at startup
  │
  ▼
reddit-no-auth-mcp-server calls redd.subreddit("salesforce").hot()
  │
  ▼
redd calls RequestsHttpAdapter.get()  ← OUR MONKEY-PATCH RUNS HERE
  │
  ├─ Uses curl_cffi session with impersonate="chrome131"
  │  (TLS ClientHello matches real Chrome 131 byte-for-byte)
  │
  ├─ Attaches Reddit cookies read from Chrome
  │  (loid, csv, edgebucket, reddit_session)
  │
  ▼
HTTPS GET https://www.reddit.com/r/salesforce/hot.json?limit=25
  User-Agent: (curl_cffi's Chrome 131 UA)
  Cookie: loid=…; csv=…; edgebucket=…; reddit_session=…
  │
  ▼
Reddit's anti-bot checks:
  ├─ TLS fingerprint (JA3)     ✓ matches Chrome 131
  ├─ HTTP/2 settings frame     ✓ matches Chrome 131
  ├─ Header order              ✓ matches Chrome 131
  ├─ Session cookies present   ✓ real user cookies
  ▼
200 OK, JSON body returned → MCP tool result → Claude → you
```

---

## Why we built it this way (vs. alternatives we tried)

- **Just using `curl_cffi` with Chrome impersonation** — Reddit still returned 403 from the sandbox and from a real Mac IP. The TLS fingerprint alone wasn't enough; Reddit also checks for session cookies.
- **Just using cookies with `requests`** — Reddit rejected these too. Requests has a distinctive TLS fingerprint that Reddit's anti-bot flags, cookies or no cookies.
- **Cookies AND `curl_cffi` together** — this is what worked. Both signals need to match a real browser session.
- **Reading cookies via Chrome DevTools Protocol** — would require running Chrome with `--remote-debugging-port=9222`, which is friction on every startup and a security surface. `pycookiecheat` reads Chrome's on-disk cookie store directly.
- **Using the official Reddit API** — requires creating a Reddit app, getting `client_id`/`client_secret`, and OAuth flow. Fine for production but overkill for someone who just wants to search Reddit from Claude.
- **Caching cookies across sessions** — pointless. `pycookiecheat` reads them in sub-100ms and Chrome refreshes them constantly. Simpler to just read at startup.

The full architecture write-up — including the "cookies alone" and "curl_cffi alone" failure diagnostics — is in [`docs/how-it-works.md`](docs/how-it-works.md).

---

## Local development

If you want to test changes before pushing:

```bash
# Install Python 3.12+ and uv if you don't have them
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and run from source
git clone https://github.com/kugamon/reddit-mcp-chrome.git
cd reddit-mcp-chrome
uv sync

# Smoke-test — should return real Reddit data
uv run python -c "
from reddit_mcp_chrome.patch import install
install()
from redd import Redd
for p in Redd().search('salesforce cpq', limit=3):
    print(p.title[:70])
"
```

To point your local Claude Desktop config at the working copy instead of the published version, change the args to:

```jsonc
"args": ["run", "--directory", "/absolute/path/to/your/checkout", "python", "-m", "reddit_mcp_chrome"]
```

---

## Behavior reference

| Chrome state | What happens |
| --- | --- |
| Chrome has recent Reddit cookies (any tab you've had open on reddit.com) | 200 OK, real Reddit data |
| Chrome has never visited reddit.com | HTTP 403 — visit reddit.com once in Chrome and retry |
| Keychain access denied | Warning logged, wrapper tries request with no cookies (usually 403) |

---

## Troubleshooting

**Claude shows "Server disconnected" at startup**: Almost always means the wrapper failed to import something — usually `pycookiecheat`, `curl_cffi`, or `reddit-no-auth-mcp-server`. Look at `~/Library/Logs/Claude/mcp-server-reddit.log` for the actual Python traceback. Fix is usually `uvx --reinstall reddit-mcp-chrome`.

**Every tool call returns `HTTPError 403`**: Reddit is rejecting requests. Two things to check:
1. Open `https://www.reddit.com/` in Chrome. If you haven't visited Reddit lately, Chrome may not have cookies. A single page load fixes this.
2. If Chrome has cookies but you're still getting 403, Reddit may have tightened their detection — try bumping `IMPERSONATE = "chrome131"` in `patch.py` to a newer Chrome profile that `curl_cffi` supports (see [curl_cffi impersonate list](https://github.com/lexiforest/curl_cffi#supported-impersonations)).

**Keychain prompt keeps appearing**: The first time the wrapper reads cookies, macOS asks permission to access "Chrome Safe Storage" via Keychain. Click **Always Allow** — not "Allow" — and the prompt won't return.

**`Cookie read failed: … pycookiecheat.KeychainError`**: You clicked "Don't Allow" on the Keychain prompt at some point. Open Keychain Access → search for "Chrome Safe Storage" → right-click → "Get Info" → "Access Control" → add the `uv` executable, or just delete the entry and let Chrome recreate it.

**Want to use Firefox/Safari/Brave/Arc instead of Chrome**: Not yet — today the wrapper only checks Chrome's cookie store. Adding other browsers is a small change to `auth.py` (pycookiecheat supports several). PRs welcome.

**Reddit changed their anti-bot and this stopped working**: The bypass depends on `curl_cffi` shipping current Chrome impersonation profiles. When Chrome ships a new major version, `curl_cffi` releases a matching profile within days. Bump `IMPERSONATE` in `patch.py` and file a PR.

**Want to see what the wrapper is doing?**: Logs go to stderr, which Claude Desktop captures at `~/Library/Logs/Claude/mcp-server-reddit.log`. The wrapper prints `[reddit-mcp-chrome v0.1.0] Patched redd adapters …` at startup.

---

## Version history

- **v0.1.0** — initial release on PyPI. Wraps `reddit-no-auth-mcp-server` 0.1.2. Chrome-only, macOS-only, uses `curl_cffi` `chrome131` impersonation profile.
