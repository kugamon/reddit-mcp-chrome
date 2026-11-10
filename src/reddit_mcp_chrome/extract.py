"""JavaScript extractors that read Reddit's rendered pages.

Reddit's current web app ("shreddit") renders content as custom elements whose
attributes carry clean, structured data:

  <shreddit-post>             id, post-title, author, score, comment-count,
                              created-timestamp, permalink, subreddit-prefixed-name...
  <shreddit-comment>          thingid, author, score, depth, created, permalink;
                              body lives in #<thingid>-comment-rtjson-content
  [data-testid=search-post-unit]  each wraps a search-telemetry-tracker whose
                              data-faceplate-tracking-context is JSON (id, title,
                              author, subreddit)
  <shreddit-profile-comment>  comment-id, href; body in an *rtjson-content node

If Reddit renames these, this file is the only place that needs to change.
"""

_POST = r"""
const post = (p, bodyMax) => {
  const g = n => p.getAttribute(n);
  const b = p.querySelector('[slot="text-body"]');
  return {
    type: 'post', id: g('id'), title: g('post-title'), author: g('author'),
    subreddit: g('subreddit-prefixed-name'), score: g('score'),
    num_comments: g('comment-count'), upvote_ratio: g('upvote-ratio'),
    created: g('created-timestamp'), permalink: g('permalink'),
    url: g('content-href'), post_type: g('post-type'), domain: g('domain'),
    selftext: b ? b.innerText.trim().slice(0, bodyMax) : ''
  };
};
"""

FEED_POSTS = "() => {" + _POST + """
  return [...document.querySelectorAll('shreddit-post')].map(p => post(p, 1500));
}"""

POST_DETAIL = "() => {" + _POST + """
  const p = document.querySelector('shreddit-post');
  return p ? post(p, 20000) : null;
}"""

COMMENTS = r"""() => [...document.querySelectorAll('shreddit-comment')].map(c => {
  const id = c.getAttribute('thingid');
  const b = id && document.getElementById(id + '-comment-rtjson-content');
  return {
    id, author: c.getAttribute('author'), score: c.getAttribute('score'),
    depth: Number(c.getAttribute('depth') || 0), created: c.getAttribute('created'),
    permalink: c.getAttribute('permalink'), parent_id: c.getAttribute('parentid'),
    body: b ? (b.innerText.trim() || b.textContent.trim()).slice(0, 4000) : ''
  };
})"""

SEARCH_RESULTS = r"""() => {
  const out = [], seen = new Set();
  for (const u of document.querySelectorAll('[data-testid="search-post-unit"]')) {
    const a = u.querySelector('a[data-testid="post-title"]');
    if (!a) continue;
    const href = a.getAttribute('href');
    if (seen.has(href)) continue;
    seen.add(href);
    let ctx = {};
    const t = u.querySelector('search-telemetry-tracker[data-faceplate-tracking-context]');
    try { ctx = JSON.parse(t.getAttribute('data-faceplate-tracking-context')); } catch (e) {}
    const txt = u.innerText.replace(/\s+/g, ' ');
    const votes = (txt.match(/([\d.,]+[kKmM]?)\s+votes?/) || [])[1] || null;
    const comments = (txt.match(/([\d.,]+[kKmM]?)\s+comments?/) || [])[1] || null;
    const ts = u.querySelector('faceplate-timeago');
    out.push({
      type: 'post', id: ctx.post && ctx.post.id,
      title: (ctx.post && ctx.post.title) || a.innerText.trim(),
      author: ctx.profile && ctx.profile.name,
      subreddit: ctx.subreddit ? 'r/' + ctx.subreddit.name : null,
      score: votes, num_comments: comments,
      created: ts && ts.getAttribute('ts'), permalink: href
    });
  }
  return out;
}"""

USER_OVERVIEW = "() => {" + _POST + r"""
  const out = [];
  for (const el of document.querySelectorAll('shreddit-post, shreddit-profile-comment')) {
    if (el.tagName.toLowerCase() === 'shreddit-post') { out.push(post(el, 1500)); continue; }
    const href = el.getAttribute('href') || '';
    const m = href.match(/^\/r\/([^/]+)\//);
    const ts = el.querySelector('faceplate-timeago');
    const b = el.querySelector('[id*="rtjson-content"]');
    out.push({
      type: 'comment', id: el.getAttribute('comment-id'),
      subreddit: m ? 'r/' + m[1] : null, permalink: href,
      created: ts && ts.getAttribute('ts'),
      body: b ? b.innerText.trim().slice(0, 1500) : '',
      context: el.innerText.replace(/\s+/g, ' ').slice(0, 300)
    });
  }
  return out;
}"""
