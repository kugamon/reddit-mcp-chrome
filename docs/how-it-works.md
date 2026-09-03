# How it works

This doc captures the architecture and the design decisions, including the diagnostics we ran and the workarounds we discarded. If you're forking or extending this package, or hitting a similar anti-scraping wall on another site, read this before changing anything load-bearing.

## The core insight

Reddit's `.json` endpoints are the fastest way to programmatically get structured Reddit data — every subreddit page, every user profile, and every post has a `.json` variant that returns the same content as machine-readable JSON. `reddit-no-auth-mcp-server` (and the `redd` library it uses) rely on these endpoints entirely.

**Reddit systematically blocks unauthenticated `.json` requests** as part of their anti-scraping policy (tightened significantly in 2023–2024 after the API pricing changes). The block is applied on three signals:

1. **TLS fingerprint** — Python's `requests` and `httpx` use OpenSSL with a distinctive ClientHello that Chrome doesn't produce (JA3 hash).
2. **HTTP/2 fingerprint** — Chrome sends specific SETTINGS frames on connection setup; Python HTTP libraries don't.
3. **Session cookies** — Chrome accumulates cookies (`loid`, `csv`, `edgebucket`, and optionally `reddit_session`) that signal "this is a real browser session that visited Reddit at some point." Requests without these cookies are treated as bot traffic.

Any two of these failing = 403. All three failing = 403 with no retry-after. To get through, all three must look like a real Chrome browser.

## The three-signal fix

```
┌────────────────────────────────────────────────────────────────┐
│  Claude Desktop                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  claude_desktop_config.json                              │  │
│  │  "command": "uvx",                                       │  │
│  │  "args": ["reddit-mcp-chrome"]                           │  │
│  └─────────────┬────────────────────────────────────────────┘  │
└────────────────┼───────────────────────────────────────────────┘
                 │ launches via stdio
                 ▼
┌────────────────────────────────────────────────────────────────┐
│  reddit-mcp-chrome (this package)                              │
│                                                                │
│  __main__.py                                                   │
│  ├── calls patch.install()                                     │
│  └── hands off to reddit-no-auth-mcp-server's main()           │
│                                                                │
│  patch.py                                                      │
│  ├── reads Chrome's Reddit cookies via pycookiecheat            │
│  ├── creates curl_cffi Session with impersonate="chrome131"    │
│  └── monkey-patches redd.adapters.http_{sync,async} .get()     │
│                                                                │
│  auth.py                                                       │
│  └── chrome_cookies("https://www.reddit.com") → dict           │
└────────────────────────────────────────────────────────────────┘
                 │
                 │ delegates to
                 ▼
┌────────────────────────────────────────────────────────────────┐
│  reddit-no-auth-mcp-server + redd  (unmodified, from PyPI)     │
│  └── every HTTP call goes through the patched adapter          │
│      └── curl_cffi sends the request with:                     │
│          • Chrome 131 TLS ClientHello                          │
│          • Chrome 131 HTTP/2 SETTINGS                          │
│          • Chrome 131 header order                             │
│          • User's real Reddit cookies from Chrome              │
└────────────────────────────────────────────────────────────────┘
                 │
                 ▼
            Reddit's .json endpoints → 200 OK
```

## Why monkey-patch, why not fork

`redd` is a thin, actively-maintained Reddit scraping library. `reddit-no-auth-mcp-server` is an even thinner MCP-protocol shell on top. Forking either to add TLS impersonation would mean:

- Maintaining a fork forever (or PR'ing upstream and waiting)
- Diverging from the upstream when they ship features or fixes
- Users tracking two packages

Instead we treat both as black boxes and patch the one method in each of `redd`'s HTTP adapters — the sync `RequestsHttpAdapter.get()` and the async `HttpxAsyncAdapter.get()`. Both live at `redd.adapters.http_sync` / `http_async` and both are called by every `redd` operation.

If `redd` ever switches its HTTP layer (unlikely — `requests` and `httpx` are the de-facto Python HTTP libraries), this package will need an update. Small risk, and easy to notice: the patch would just stop applying.

## Why curl_cffi and not selenium/playwright

We could run a headless Chrome via Playwright, load Reddit pages, and scrape the DOM. That works — it's what `stickerdaniel/linkedin-mcp-server` does for LinkedIn. But it's heavy:

- ~100 MB Chromium download
- Multi-second startup per request
- Playwright process management + resource churn
- More attack surface for LinkedIn/Reddit to detect (browser automation flags)

`curl_cffi` gives us the exact same TLS fingerprint as a real Chrome browser — because it compiles curl with BoringSSL and matches Chrome's TLS extensions byte-for-byte — but without spinning up an actual browser. Requests take ~200ms, cold start is negligible, and there's no browser process to babysit.

The trade-off: `curl_cffi` can only replay a static fingerprint. If Reddit ever adds JS-based challenges (Cloudflare Turnstile, etc.), we'd need to fall back to a real browser. But their current defenses are pure network-level fingerprinting, which `curl_cffi` handles cleanly.

## What we tried first and discarded

| Attempt | Why it failed |
|---|---|
| Realistic User-Agent header + `requests` library | 403 — Reddit checks TLS fingerprint, not just User-Agent |
| `curl_cffi` with Chrome 131 impersonation, no cookies | 403 — TLS was right, but no session cookies means "no real browser" |
| Chrome cookies + `requests` library (no TLS impersonation) | 403 — Cookies were valid but TLS gave it away |
| Read cookies via Chrome DevTools Protocol on `--remote-debugging-port=9222` | Works but requires Chrome to be started with the debug flag; way too much friction for users |
| Cache cookies to disk with a 5-minute TTL | Not worth it — `pycookiecheat` reads Chrome's store in sub-100ms |
| Use `praw` (the official Reddit API library) | Requires creating a Reddit app + OAuth flow per user; whole point of `reddit-no-auth-mcp-server` is that it doesn't need one |

## Why cookies are read at install time (not per-request)

Reddit session cookies have hour(s)-long lifetimes and Chrome refreshes them constantly (any Reddit page load extends them). Reading them once at MCP server startup is nearly always enough for the duration of a Claude Desktop session.

If a long-running Claude session goes stale — say, the user's session cookie expires mid-day — the wrapper will start returning 403 on tool calls. Restart Claude Desktop and cookies get re-read.

We could re-read on every request (like `salesforce-mcp-auto-auth-chrome` does with the `sid` cookie), but Reddit sessions are much longer-lived than Salesforce sessions and Reddit is much less critical to keep fresh mid-conversation. The added per-request latency isn't worth it.

## Why chrome131 (and how to bump it)

`curl_cffi` ships Chrome impersonation profiles named after Chrome versions: `chrome116`, `chrome120`, `chrome124`, `chrome131`, etc. Each is a snapshot of that Chrome version's TLS ClientHello, HTTP/2 SETTINGS, and header order. Newer profiles look more like current Chrome to modern anti-bot systems.

We picked `chrome131` because it's the latest profile `curl_cffi` shipped at the time of v0.1.0 release, and Reddit's anti-bot accepts it. When Reddit tightens further:

1. Check `curl_cffi`'s [supported impersonations](https://github.com/lexiforest/curl_cffi#supported-impersonations) for the newest Chrome profile.
2. Bump the `IMPERSONATE` constant in `patch.py` and release a new version.

`curl_cffi` typically ships new Chrome profiles within a few weeks of a stable Chrome release, so this is low-effort maintenance.

## What we learned that's generally useful for anti-scraping MCP wrappers

1. **Multiple detection signals combine multiplicatively.** Getting TLS right AND cookies right AND HTTP/2 right isn't optional if any one of them fails. Test each in isolation to know which one you're missing.
2. **Read the user's actual browser state, don't fake it.** Cookies from a real Chrome session are better than any synthetic session you could construct. Chrome refreshes them for free while the user browses normally.
3. **Impersonate at the network layer, not the browser layer.** `curl_cffi` gives you Chrome's TLS fingerprint without Chrome's memory footprint. Reserve headless-browser scraping (Playwright, Selenium) for sites that require JS execution or DOM interaction.
4. **Don't fork upstream.** Monkey-patching the HTTP boundary of an existing package is almost always cleaner than maintaining a fork. When the boundary is one or two functions, the patch is trivial and upstream improvements flow through.
5. **Pin transitive SDKs that reach you through another package** (see `salesforce-mcp-auto-auth-chrome`'s lesson #6 for the full story). This isn't a problem here today because `redd` is stable, but it's worth watching if `reddit-no-auth-mcp-server` ever adds new transitive deps.
