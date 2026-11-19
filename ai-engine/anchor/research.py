"""Off-site evidence: news/press about the brand, as citable chunks.

Articles must mention the brand by name (or domain) in their body, or they are dropped:
for common-word brand names, search engines return unrelated stories.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx
from bs4 import BeautifulSoup

from . import market
from .config import Settings
from .crawl import UA
from .extract import clean, informativeness, prose
from .verify import dominant_script, norm

log = logging.getLogger("anchor.research")


def _bing(query: str, n: int = 8) -> list[dict]:
    url = f"https://www.bing.com/news/search?q={urllib.parse.quote(query)}&format=rss"
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=12, follow_redirects=True)
        root = ET.fromstring(r.content)
    except Exception as exc:
        status = getattr(locals().get("r"), "status_code", None)
        log.warning("news search failed for %r (HTTP %s): %s", query, status, exc)
        return []
    if not root.findall(".//item"):
        # Search engines often answer datacenter IPs with an empty feed or a captcha page.
        log.warning("news search for %r returned no items (HTTP %s, %d bytes, final url %s)",
                    query, r.status_code, len(r.content), r.url)
    out = []
    for item in root.findall(".//item")[:n]:
        link = item.findtext("link") or ""
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
        out.append({
            "title": clean(item.findtext("title") or ""),
            "url": qs.get("url", [link])[0],
            "date": _date(item.findtext("pubDate") or ""),
        })
    return out


def _date(raw: str) -> str | None:
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        return None


def _article(hit: dict, brand: str, domain: str, script: str = "LATIN") -> list[dict]:
    try:
        r = httpx.get(hit["url"], headers={"User-Agent": UA}, timeout=12, follow_redirects=True)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return []
    except httpx.HTTPError:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup.find_all(["nav", "header", "footer", "aside", "script", "style", "form"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body
    if not root:
        return []
    paras = [clean(p.get_text(" ")) for p in root.find_all("p")]
    paras = [p for p in paras if prose(p, 40, 1200)]
    body = " ".join(paras)
    if dominant_script(body, script) != script:
        # Press in another language (e.g. a Japanese-edition article about an English-language
        # brand): its names and dates would leak into the posts untranslated.
        log.info("skip %s: written in %s, site is %s", hit["url"], dominant_script(body), script)
        return []
    if norm(brand) not in norm(body) and domain.split(".")[0] not in norm(body):
        return []
    # Lead paragraph plus the most specific paragraphs, max 3 chunks per article.
    lead = paras[:1]
    rest = sorted(paras[1:], key=informativeness, reverse=True)[:2]
    chunks = [p for p in lead + rest if norm(brand) in norm(p) or informativeness(p) > 4]
    return [{"kind": "article", "url": str(r.url), "title": hit["title"], "date": hit["date"], "text": c[:900],
             "_rank": informativeness(c) + 2.5} for c in chunks]


def news_evidence(brand: str, domain: str, templates: list[str], max_articles: int,
                  script: str = "LATIN", cfg: Settings | None = None) -> list[dict]:
    year = datetime.now().year
    queries = [t.replace("{brand_name}", brand).replace("{current_year}", str(year)) for t in templates[:3]]
    queries = queries or [f'"{brand}" (launch OR partnership OR award OR announces) {year}']
    hits, seen = [], set()
    use_dfs = cfg is not None and cfg.dataforseo_news and market.enabled(cfg)
    for q in queries:
        # Google News via DataForSEO first (when configured), then Bing's RSS feed.
        for h in (market.news_hits(q, cfg) if use_dfs else []) + _bing(q):
            if (h["url"].startswith("http") and h["url"] not in seen and domain not in h["url"]
                    and dominant_script(h["title"], script) == script):
                seen.add(h["url"])
                hits.append(h)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda h: _article(h, brand, domain, script), hits[: max_articles * 3]))
    items: list[dict] = []
    used = 0
    for chunks in results:
        if chunks and used < max_articles:
            items += chunks
            used += 1
    log.info("News: %d candidate links, %d on-topic articles kept", len(hits), used)
    return items
