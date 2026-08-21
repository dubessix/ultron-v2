"""
Lightweight, keyless real-web-search helper.
Tries multiple free, public sources and returns REAL top results so tools can
open the actual answer page in the browser instead of a generic search URL.

Fallback chain (robust, no single point of failure):
  1. DuckDuckGo Lite HTML scrape (may be rate-limited).
  2. Wikipedia search API (very reliable, free, returns real article pages).

Used whenever no paid API key (Tavily) is configured.
"""
import re
import httpx
from urllib.parse import urlparse, parse_qs, unquote

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120 Safari/537.36")


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    return (s.replace("&amp;", "&").replace("&#x27;", "'")
             .replace("&quot;", '"').replace("&nbsp;", " ").strip())


def _decode_ddg(url: str) -> str:
    if "/l/?" in url:
        qs = parse_qs(urlparse(url).query)
        if qs.get("uddg"):
            url = unquote(qs["uddg"][0])
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    return url


def _is_organic_result_url(url: str) -> bool:
    """Reject DuckDuckGo/Bing ad trackers and search-navigation links."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    query_keys = {key.lower() for key in parse_qs(parsed.query)}
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host == "duckduckgo.com" or host.endswith(".duckduckgo.com"):
        return False
    if host == "bing.com" or host.endswith(".bing.com"):
        if parsed.path.lower().endswith("/aclick") or "ad_provider" in query_keys:
            return False
    return not ({"ad_domain", "ad_provider", "click_metadata"} & query_keys)


async def _ddg(query: str, limit: int) -> list:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get("https://lite.duckduckgo.com/lite/", params={"q": query})
            if resp.status_code != 200:
                return []
            html = resp.text
    except Exception:
        return []
    if "result-snippet" not in html and "result-link" not in html:
        return []

    links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)
    snippets = re.findall(r"<td class=['\"]result-snippet['\"][^>]*>(.*?)</td>", html, re.DOTALL)
    out = []
    for i, (url, title) in enumerate(links):
        decoded_url = _decode_ddg(url.strip())
        if not _is_organic_result_url(decoded_url):
            continue
        snippet = _clean(snippets[i]) if i < len(snippets) else ""
        out.append({"title": _clean(title) or "Result", "url": decoded_url, "snippet": snippet[:200]})
        if len(out) >= limit:
            break
    return out


async def _wikipedia(query: str, limit: int) -> list:
    """Wikipedia search API: very reliable free source returning real article pages."""
    try:
        async with httpx.AsyncClient(timeout=10.0,
                                     headers={"User-Agent": "UltronAssistant/1.0 (personal assistant; contact: local)"}) as client:
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query", "list": "search", "srsearch": query,
                    "format": "json", "srlimit": limit,
                },
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception:
        return []
    hits = data.get("query", {}).get("search", [])
    out = []
    for h in hits:
        title = h.get("title", "")
        url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
        out.append({
            "title": title,
            "url": url,
            "snippet": _clean(h.get("snippet", "")),
            "source": "wikipedia",
        })
        if len(out) >= limit:
            break
    return out


async def real_web_search(query: str, limit: int = 3) -> list:
    """Return real top results. Tries DuckDuckGo, then Wikipedia fallback."""
    for fetcher in (_ddg, _wikipedia):
        try:
            results = await fetcher(query, limit)
        except Exception:
            continue
        if results:
            return results
    return []
