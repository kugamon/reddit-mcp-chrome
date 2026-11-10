# How it works

The architecture, the history, and the decisions behind them. Read this before changing anything load-bearing, or if you're hitting the same kind of wall on another site.

## Timeline

| When | What happened |
| --- | --- |
| Sep 2026 | v0.1.0 ships. Wraps `reddit-no-auth-mcp-server`, which scrapes Reddit's `.json` endpoints via the `redd` library. Our addition: Chrome session cookies plus a `curl_cffi` Chrome TLS fingerprint, because plain Python HTTP clients already got 403. |
| Early Nov 2026 | Every tool call starts returning `HTTP 403`. Server still starts and lists tools fine. |
| Nov 2026 | v0.2.0: rewritten to read Reddit through a real Chrome window. |

## The November 2026 diagnosis

We tested each layer separately to find what broke.

| Test | Result |
| --- | --- |
| Chrome still has Reddit cookies (`reddit_session`, `loid`, `csv`, ...) | Yes, 18 of them |
| Our patch still attaches to `redd`'s HTTP adapters | Yes, `redd` 0.2.1 kept the same classes |
| `curl_cffi` chrome142, 145, 146, 150, 151, 152 (and `_macos` variants), with cookies | 403 on every one |
| Same profiles without cookies | 403 |
| Latest upstream `redd` 0.2.1, no patch at all | 403 "Blocked" |
| Plain `curl` to an HTML page (`/r/salesforce/`) | 200 |
| Real Chrome, headless, fresh profile | "Prove your humanity" page, then 403 |
| Real Chrome, visible window, fresh profile | Pages load normally, no challenge |
| `fetch('/r/salesforce/hot.json')` from inside that visible window | **403** |
| Official API | Not an option: Reddit isn't approving new API apps |

Two conclusions:

1. **The `.json` route is closed for anonymous clients everywhere**, including a genuine browser. It's not a fingerprint problem we can fix by impersonating better. `reddit-no-auth-mcp-server` is affected the same way.
2. **Reddit's rendered pages still load in a normal browser window.** That's the remaining route.

A side finding: v0.1 pinned `curl_cffi`'s `chrome131` profile, and `curl_cffi` 0.17 no longer ships it. That would have broken v0.1 eventually regardless.

## Architecture

```
Claude Desktop
   │ stdio (MCP)
   ▼
server.py      six tools, input validation, result clean-up
   │ holds one lock: one page load at a time
   ▼
browser.py     launches installed Chrome via Playwright on first call
   │           profile: ~/.reddit-mcp-chrome/profile
   │           window parked at (-2400, -2400)
   │           ≥ 2 s between page loads
   │           human check → move window on screen, fail the call
   ▼
extract.py     JavaScript run inside the page, returns plain dicts
   ▼
www.reddit.com rendered pages
```

The server is our own [FastMCP](https://gofastmcp.com) app now, not a wrapper. We kept the six tool names and argument names from `reddit-no-auth-mcp-server` so prompts and skills written for v0.1 work unchanged.

## Reading the rendered pages

Reddit's current web app renders content as custom elements, and most of the useful data sits in their attributes rather than in visible text. That makes extraction far more stable than scraping text.

| Element | Where it appears | What we read |
| --- | --- | --- |
| `<shreddit-post>` | Feeds, post pages, user pages | `id`, `post-title`, `author`, `score`, `comment-count`, `created-timestamp`, `permalink`, `subreddit-prefixed-name`, `post-type`; body from `[slot="text-body"]` |
| `<shreddit-comment>` | Post pages | `thingid`, `author`, `score`, `depth`, `created`, `permalink`; body from `#<thingid>-comment-rtjson-content` |
| `[data-testid="search-post-unit"]` | Search results | A `search-telemetry-tracker` inside carries JSON (post id, title, author, subreddit); votes and comment counts parsed from the card text |
| `<shreddit-profile-comment>` | User overview | `comment-id`, `href`; body from an `*rtjson-content` node |

All selectors live in `extract.py`. If Reddit renames something, only that file changes.

Three details that took testing to get right:

- **Results render 2–4 seconds after the page loads.** `collect()` waits for the expected element (up to 8 s) before reading. Without this, subreddit search returned nothing.
- **Feeds are virtualised**: older cards are removed from the page as you scroll. Items are accumulated by id across scroll rounds instead of counted on the page.
- **Collapsed replies have empty `innerText`.** Comment bodies fall back to `textContent`.

## What we deliberately don't do

- **No headless mode.** Headless gets challenged. A visible window parked offscreen is honest about what it is: a normal Chrome window.
- **No fingerprint spoofing or stealth patches.** We use the installed Chrome as-is via Playwright.
- **No CAPTCHA solving.** On a human check, the window moves on screen and the call fails with a message asking the user to complete it. The saved profile keeps the result.
- **No bulk collection.** One window, one page load at a time, at least 2 seconds apart, at most 100 items per call.

If Reddit tightens further so that a plain, paced, real browser window no longer works, the right response is to stop, not to escalate.

## Why our own profile, not your everyday Chrome

Chrome locks a profile while it's open, so automating your main profile would mean closing your browser. A separate profile also keeps the automation's cookies and history out of your own. Use `--login` once if you want it signed in.

## Lessons

1. **When a scraping route breaks, test from the most legitimate client first.** Checking `.json` from inside a real browser window told us in one step that no amount of impersonation would help, before we spent time on newer TLS profiles.
2. **Keep all site-specific selectors in one file.** Markup changes are the most likely future breakage; they should be a one-file fix.
3. **Wait for what you need, not a fixed delay.** Client-rendered sites finish at different times per page type.
4. **Pin every SDK major you depend on.** `mcp` 2.0 broke `mcp-salesforce-connector` and `fastmcp` 4.0 broke `mcp-server-linkedin`. This package pins `fastmcp<4` and `playwright<2` from day one.
5. **Keep tool names stable across rewrites.** Users' prompts and skills reference tool names; v0.2 changed everything underneath without changing them.
