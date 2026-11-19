"""Competitive and search-demand context from DataForSEO (optional; needs DATAFORSEO_LOGIN/PASSWORD).

What it adds to a run, before any rollout (so every Harness² candidate sees the same context):
  competitors     domains that compete with the brand for the same organic keywords
  brand keywords  what the brand's audience actually searches for and the brand ranks on
  content gaps    high-volume keywords the top competitors rank for and the brand does not
  news            Google News results for the brand's press queries (research.py uses them
                  alongside Bing, whose RSS feed often comes back empty on datacenter IPs)

This is MARKET CONTEXT, never evidence: it steers which facts are picked and how posts are
angled and worded. Nothing from it may be stated as fact in a post, and posts may not name a
competitor the cited evidence does not mention (verify.check_post enforces that in code).

Every call is cached on disk (ANCHOR_DATAFORSEO_CACHE_DAYS) so Harness² refines and reruns of
the same brand do not pay twice, and any failure degrades to "no market context", never a
failed run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path

import httpx

from .config import Settings
from .models import Competitor, MarketIntel, SearchKeyword

log = logging.getLogger("anchor.market")
API = "https://api.dataforseo.com/v3"

# Domains that "compete" for every keyword but are not business competitors.
_NOT_COMPETITORS = re.compile(
    r"(^|\.)(wikipedia\.org|youtube\.com|reddit\.com|quora\.com|amazon\.[a-z.]+|facebook\.com|"
    r"linkedin\.com|instagram\.com|twitter\.com|x\.com|pinterest\.com|medium\.com|github\.com|"
    r"tripadvisor\.[a-z.]+|booking\.com|expedia\.[a-z.]+|yelp\.[a-z.]+|google\.[a-z.]+|apple\.com|"
    r"microsoft\.com|forbes\.com|g2\.com|capterra\.com|trustpilot\.com)$")

_cost_lock = threading.Lock()
_cost = {"calls": 0, "usd": 0.0}
_blocked: list[str] = []  # set after an auth/verification/funds error: skip further calls


def reset_cost() -> None:
    with _cost_lock:
        _cost.update(calls=0, usd=0.0)
    _blocked.clear()  # a new run retries (e.g. after the account was verified)


def blocked_reason() -> str:
    return _blocked[0] if _blocked else ""


def cost_snapshot() -> dict:
    with _cost_lock:
        return dict(_cost)


def enabled(cfg: Settings) -> bool:
    return bool(cfg.dataforseo_login and cfg.dataforseo_password)


def post(path: str, body: dict, cfg: Settings) -> list[dict]:
    """POST one task to a DataForSEO live endpoint; returns its `result[0].items` (or [])."""
    payload = [body]
    key = hashlib.sha256(json.dumps([path, payload], sort_keys=True).encode()).hexdigest()[:24]
    cache = cfg.cache_dir / "dataforseo" / f"{key}.json"
    if cache.is_file() and time.time() - cache.stat().st_mtime < cfg.dataforseo_cache_days * 86400:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            pass
    if _blocked:
        return []
    try:
        r = httpx.post(f"{API}/{path}", json=payload, timeout=cfg.dataforseo_timeout,
                       auth=(cfg.dataforseo_login, cfg.dataforseo_password))
    except httpx.HTTPError as exc:
        log.warning("DataForSEO %s failed: %s", path, exc)
        return []
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code in (401, 402, 403):
        # Wrong credentials (40100), unverified account (40104), no funds (40200): every later
        # call would fail the same way, so stop calling for the rest of this process.
        _blocked.append(f"{data.get('status_code', r.status_code)} {data.get('status_message', '')}".strip())
        log.warning("DataForSEO disabled for this run: HTTP %s, %s", r.status_code, _blocked[0])
        return []
    if r.status_code != 200:
        log.warning("DataForSEO %s failed: HTTP %s %s", path, r.status_code, data.get("status_message", r.text[:200]))
        return []
    if data.get("status_code") != 20000:
        log.warning("DataForSEO %s: %s %s", path, data.get("status_code"), data.get("status_message"))
        return []
    task = (data.get("tasks") or [{}])[0]
    with _cost_lock:
        _cost["calls"] += 1
        _cost["usd"] += float(task.get("cost") or 0)
    if task.get("status_code") != 20000:
        # 40501/40102 etc.: bad params, no data for this target, out of credit.
        log.warning("DataForSEO %s task: %s %s", path, task.get("status_code"), task.get("status_message"))
        return []
    items = [i for res in (task.get("result") or []) if res for i in (res.get("items") or [])]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(items), encoding="utf-8")
    return items


def _geo(cfg: Settings) -> dict:
    return {"location_code": cfg.dataforseo_location_code, "language_code": cfg.dataforseo_language_code}


def _bare(domain: str) -> str:
    return (domain or "").lower().removeprefix("www.").strip("/")


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def competitors(domain: str, cfg: Settings) -> list[Competitor]:
    items = post("dataforseo_labs/google/competitors_domain/live",
                 {"target": domain, **_geo(cfg), "limit": 30, "exclude_top_domains": True,
                  "order_by": ["intersections,desc"]}, cfg)
    me = _bare(domain)
    out: list[Competitor] = []
    for it in items:
        d = _bare(it.get("domain", ""))
        if not d or d == me or d.endswith("." + me) or me.endswith("." + d) or _NOT_COMPETITORS.search(d):
            continue
        organic = ((it.get("full_domain_metrics") or {}).get("organic") or {})
        out.append(Competitor(domain=d, shared_keywords=int(_num(it.get("intersections"))),
                              avg_position=round(_num(it.get("avg_position")), 1),
                              organic_traffic=int(_num(organic.get("etv")))))
        if len(out) >= cfg.dataforseo_max_competitors:
            break
    return out


def _keyword(it: dict, *, page_key: str = "ranked_serp_element", domain: str = "") -> SearchKeyword | None:
    kd = it.get("keyword_data") or {}
    kw = (kd.get("keyword") or "").strip()
    if not kw:
        return None
    info = kd.get("keyword_info") or {}
    serp = (it.get(page_key) or {}).get("serp_item") or (it.get(page_key) or {})
    intent = ((kd.get("search_intent_info") or {}).get("main_intent")) or None
    return SearchKeyword(keyword=kw, search_volume=int(_num(info.get("search_volume"))),
                         position=int(_num(serp.get("rank_group"))) or None,
                         url=serp.get("url") or None, title=(serp.get("title") or "")[:160] or None,
                         intent=intent, competitor=domain or None)


def brand_keywords(domain: str, cfg: Settings) -> list[SearchKeyword]:
    items = post("dataforseo_labs/google/ranked_keywords/live",
                 {"target": domain, **_geo(cfg), "limit": 60, "load_rank_absolute": False,
                  "order_by": ["keyword_data.keyword_info.search_volume,desc"]}, cfg)
    return _dedupe([k for k in (_keyword(i) for i in items) if k], cfg.dataforseo_max_keywords)


def content_gaps(domain: str, rivals: list[Competitor], cfg: Settings) -> list[SearchKeyword]:
    """Keywords each top competitor ranks for (top 20) and the brand does not rank for at all."""
    gaps: list[SearchKeyword] = []
    for rival in rivals[:2]:
        items = post("dataforseo_labs/google/domain_intersection/live",
                     {"target1": rival.domain, "target2": domain, "intersections": False, **_geo(cfg),
                      "limit": 30, "filters": [["first_domain_serp_element.rank_group", "<=", 20]],
                      "order_by": ["keyword_data.keyword_info.search_volume,desc"]}, cfg)
        gaps += [k for k in (_keyword(i, page_key="first_domain_serp_element", domain=rival.domain)
                             for i in items) if k]
    return _dedupe(sorted(gaps, key=lambda k: k.search_volume, reverse=True), cfg.dataforseo_max_keywords)


def _dedupe(kws: list[SearchKeyword], n: int) -> list[SearchKeyword]:
    seen, out = set(), []
    for k in kws:
        key = re.sub(r"\W+", " ", k.keyword.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(k)
    return out[:n]


def market_intel(domain: str, brand: str, cfg: Settings) -> MarketIntel | None:
    """Competitors, the audience's searches and competitor content gaps; None if unavailable."""
    if not enabled(cfg):
        return None
    domain = _bare(domain)
    rivals = competitors(domain, cfg)
    keywords = brand_keywords(domain, cfg)
    gaps = content_gaps(domain, rivals, cfg) if rivals else []
    if not (rivals or keywords or gaps):
        log.info("DataForSEO returned no market data for %s", domain)
        return None
    # Brand-name searches tell us nothing about the market; keep them out of "demand".
    core = re.sub(r"\W+", "", brand.lower())
    keywords = [k for k in keywords if not core or core not in re.sub(r"\W+", "", k.keyword.lower())] or keywords
    intel = MarketIntel(location_code=cfg.dataforseo_location_code, language_code=cfg.dataforseo_language_code,
                        competitors=rivals, brand_keywords=keywords, gap_keywords=gaps)
    log.info("[market] %s: %d competitors (%s), %d brand keywords, %d gap keywords", domain, len(rivals),
             ", ".join(c.domain for c in rivals[:5]), len(keywords), len(gaps))
    return intel


def news_hits(query: str, cfg: Settings, n: int = 10) -> list[dict]:
    """Google News results as research.py hits: {title, url, date}."""
    if not enabled(cfg):
        return []
    items = post("serp/google/news/live/advanced",
                 {"keyword": query, **_geo(cfg), "depth": max(10, n)}, cfg)
    out = []
    for it in items:
        if it.get("type") != "news_search" or not it.get("url"):
            continue
        ts = (it.get("timestamp") or "")[:10]
        out.append({"title": (it.get("title") or "").strip(), "url": it["url"],
                    "date": ts if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ts) else None})
    return out[:n]


def render(intel: MarketIntel | None, brand: str) -> str:
    """source/market.md: the context block shown to the miner, writer, and Harness²."""
    if not intel:
        return ""
    lines = [f"# Market context for {brand} (DataForSEO, Google, location {intel.location_code}, "
             f"language {intel.language_code})", "",
             "NOT EVIDENCE: use it to choose and angle facts, never as a claim. Do not name or compare "
             f"{brand} to these competitors unless a cited evidence item does.", ""]
    if intel.competitors:
        lines += ["## Organic search competitors", ""] + [
            f"- {c.domain}: {c.shared_keywords:,} shared keywords, avg position {c.avg_position:g}"
            + (f", ~{c.organic_traffic:,} est. monthly visits" if c.organic_traffic else "")
            for c in intel.competitors] + [""]
    if intel.brand_keywords:
        lines += [f"## What the audience searches for (and {brand} ranks on)", ""] + [
            f"- \"{k.keyword}\" ({k.search_volume:,}/mo" + (f", #{k.position}" if k.position else "")
            + (f", {k.intent}" if k.intent else "") + ")" for k in intel.brand_keywords] + [""]
    if intel.gap_keywords:
        lines += [f"## Content gaps: competitors rank, {brand} does not", ""] + [
            f"- \"{k.keyword}\" ({k.search_volume:,}/mo; {k.competitor}"
            + (f" #{k.position}" if k.position else "") + (f" with \"{k.title}\"" if k.title else "") + ")"
            for k in intel.gap_keywords] + [""]
    return "\n".join(lines)


def competitor_names(intel: MarketIntel | None) -> list[str]:
    """Names a post could use for each competitor: its domain and its distinctive first label."""
    names: list[str] = []
    for c in (intel.competitors if intel else []):
        label = c.domain.split(".")[0]
        names += [c.domain] + ([label] if len(label) >= 4 else [])
    return names


def keyword_terms(intel: MarketIntel | None) -> dict[str, float]:
    """Content words of the audience's searches and the gaps, weighted by search volume (0..1)."""
    if not intel:
        return {}
    weights: dict[str, float] = {}
    kws = intel.brand_keywords + intel.gap_keywords
    top = max((k.search_volume for k in kws), default=0) or 1
    for k in kws:
        for w in re.findall(r"[a-z0-9][a-z0-9+#.-]{2,}", k.keyword.lower()):
            if w not in _STOP:
                weights[w] = max(weights.get(w, 0.0), 0.3 + 0.7 * k.search_volume / top)
    return weights


_STOP = {"the", "and", "for", "with", "how", "what", "best", "near", "free", "top", "vs", "you", "your",
         "are", "can", "does", "from", "that", "this", "online", "2024", "2025", "2026"}
