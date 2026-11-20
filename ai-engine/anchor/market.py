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

from pydantic import BaseModel, Field

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


def post(path: str, body: dict, cfg: Settings, retry_codes: frozenset[int] | None = None) -> list[dict]:
    """POST one task to a DataForSEO live endpoint; returns its `result[0].items` (or []).

    `retry_codes` overrides which task status codes get one more try (default _TRANSIENT)."""
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
    codes = _TRANSIENT if retry_codes is None else retry_codes
    items = _call(path, payload, cfg, retry=True, codes=codes)
    if items is _RETRY:
        time.sleep(2)
        items = _call(path, payload, cfg, retry=False, codes=codes)
    if items is None:
        return []
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(items), encoding="utf-8")
    return items


_RETRY: list = []  # sentinel: a transient DataForSEO error worth one more try
# 40101 Internal SE Server Error (the search-engine scrape failed), 50000 internal error,
# 50301/50401 temporary unavailability: transient on DataForSEO's side.
_TRANSIENT = frozenset({40101, 50000, 50301, 50401})
# Google News answers some queries with 40101 every time (long boolean queries with no matches,
# e.g. '"Brand" (a OR b OR c OR d) 2026'), so retrying it there only costs ~20s per query.
NEWS_RETRY = _TRANSIENT - {40101}


def _call(path: str, payload: list, cfg: Settings, retry: bool, codes: frozenset[int] = _TRANSIENT):
    """One live request: its items, None on a lasting failure, or _RETRY on a transient one
    (only when `retry`; the final attempt reports it as a failure)."""
    try:
        r = httpx.post(f"{API}/{path}", json=payload, timeout=cfg.dataforseo_timeout,
                       auth=(cfg.dataforseo_login, cfg.dataforseo_password))
    except httpx.HTTPError as exc:
        log.warning("DataForSEO %s failed: %s", path, exc)
        return None
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code in (401, 402, 403):
        # Wrong credentials (40100), unverified account (40104), no funds (40200): every later
        # call would fail the same way, so stop calling for the rest of this process.
        _blocked.append(f"{data.get('status_code', r.status_code)} {data.get('status_message', '')}".strip())
        log.warning("DataForSEO disabled for this run: HTTP %s, %s", r.status_code, _blocked[0])
        return None
    if r.status_code >= 500 and retry:
        log.info("DataForSEO %s: HTTP %s, retrying once", path, r.status_code)
        return _RETRY
    if r.status_code != 200:
        log.warning("DataForSEO %s failed: HTTP %s %s", path, r.status_code, data.get("status_message", r.text[:200]))
        return None
    if data.get("status_code") != 20000:
        if retry and data.get("status_code") in codes:
            log.info("DataForSEO %s: %s %s, retrying once", path, data.get("status_code"), data.get("status_message"))
            return _RETRY
        log.warning("DataForSEO %s: %s %s", path, data.get("status_code"), data.get("status_message"))
        return None
    task = (data.get("tasks") or [{}])[0]
    with _cost_lock:
        _cost["calls"] += 1
        _cost["usd"] += float(task.get("cost") or 0)
    if task.get("status_code") != 20000:
        if retry and task.get("status_code") in codes:
            log.info("DataForSEO %s task: %s %s, retrying once", path, task.get("status_code"),
                     task.get("status_message"))
            return _RETRY
        if task.get("status_code") == 40101 and path.startswith("serp/"):
            # Google rejected this query (usually too narrow to match anything); callers fall back.
            log.info("DataForSEO %s: Google rejected the query (40101), skipping it", path)
            return None
        # 40501/40102 etc.: bad params, no data for this target, out of credit.
        log.warning("DataForSEO %s task: %s %s", path, task.get("status_code"), task.get("status_message"))
        return None
    return [i for res in (task.get("result") or []) if res for i in (res.get("items") or [])]


# ---- geography -------------------------------------------------------------------------

# DataForSEO location codes for the markets brands most often target.
LOCATIONS = {
    "us": 2840, "in": 2356, "gb": 2826, "uk": 2826, "no": 2578, "de": 2276, "fr": 2250, "es": 2724,
    "it": 2380, "nl": 2528, "se": 2752, "dk": 2208, "fi": 2246, "au": 2036, "ca": 2124, "jp": 2392,
    "br": 2076, "mx": 2484, "sg": 2702, "ae": 2784, "ie": 2372, "nz": 2554, "za": 2710, "kr": 2410,
    "be": 2056, "ch": 2756, "at": 2040, "pt": 2620, "pl": 2616, "id": 2360, "ph": 2608, "my": 2458,
}
# Country-code TLDs that are used as generic tech TLDs and say nothing about the market.
_GENERIC_CC = {"ai", "io", "co", "me", "tv", "dev", "app", "cc", "ly", "fm", "gg", "so", "sh", "to", "xyz"}
_LANG_ALIASES = {"nb": "no", "nn": "no", "iw": "he", "in": "id"}


def geo_for(url: str, html_lang: str, cfg: Settings) -> tuple[int, str, str]:
    """(location_code, language_code, how) for the brand's own market.

    An explicit DATAFORSEO_LOCATION_CODE wins. Otherwise: a country path segment (/in/, /en-gb/),
    the <html lang> region (en-GB), then the country-code TLD (.no, .co.uk); default US."""
    from urllib.parse import urlparse

    lang_tag = (html_lang or "").strip().lower().replace("_", "-")
    lang = _LANG_ALIASES.get(lang_tag.split("-")[0], lang_tag.split("-")[0]) if lang_tag else ""
    if cfg.dataforseo_language_code:
        lang = cfg.dataforseo_language_code
    lang = lang if re.fullmatch(r"[a-z]{2}", lang or "") else "en"
    if cfg.dataforseo_location_code:
        return cfg.dataforseo_location_code, lang, "configured"
    u = urlparse(url)
    first = (u.path.strip("/").split("/") or [""])[0].lower()
    m = re.fullmatch(r"(?:[a-z]{2}-)?([a-z]{2})", first)
    if m and m.group(1) in LOCATIONS and first not in ("en", "es", "de", "fr", "it", "pt", "nl", "ja"):
        return LOCATIONS[m.group(1)], lang, f"url path /{first}/"
    if "-" in lang_tag and lang_tag.split("-")[1] in LOCATIONS:
        return LOCATIONS[lang_tag.split("-")[1]], lang, f"html lang {lang_tag}"
    tld = u.netloc.lower().split(":")[0].rsplit(".", 1)[-1]
    if tld in LOCATIONS and tld not in _GENERIC_CC:
        return LOCATIONS[tld], lang, f".{tld} domain"
    return 2840, lang, "default (US)"


def _geo(loc: int, lang: str) -> dict:
    return {"location_code": loc, "language_code": lang}


def _bare(domain: str) -> str:
    return (domain or "").lower().removeprefix("www.").strip("/")


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ---- filters ---------------------------------------------------------------------------

def _label(domain: str) -> str:
    """Second-level label: 'inhabitr' for inhabitr.ai, 'thesavoylondon' for www.thesavoylondon.com."""
    parts = _bare(domain).split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov"):
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


def _close(a: str, b: str, ratio: float = 0.8) -> bool:
    from difflib import SequenceMatcher

    return bool(a and b) and (a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a))
                              or SequenceMatcher(None, a, b).ratio() >= ratio)


def brand_terms(brand: str, domain: str) -> list[str]:
    core = re.sub(r"\W+", "", (brand or "").lower())
    out = [t for t in {core, _label(domain).replace("-", "")} if len(t) >= 3]
    out += [w for w in re.findall(r"[a-z0-9]{4,}", (brand or "").lower()) if w not in out]
    return out


def is_branded(keyword: str, terms: list[str]) -> bool:
    """The brand's name, a typo of it ("inhabitor" for Inhabitr) or the name glued to a word."""
    kw = keyword.lower()
    squashed = re.sub(r"\W+", "", kw)
    tokens = re.findall(r"[a-z0-9]+", kw)
    for t in terms:
        if t in squashed or any(_close(tok, t, 0.8) for tok in tokens if len(tok) >= 4):
            return True
    return False


def lookalike(domain: str, brand_domain: str, terms: list[str]) -> bool:
    """The brand's own other domains (inhabitr.com for inhabitr.ai) and name-alikes
    (inhabit.com, inhabit-interiors.com) share branded searches, not the market."""
    lab = _label(domain)
    parts = [lab] + lab.split("-")
    return any(_close(part, t, 0.75) for part in parts for t in terms + [_label(brand_domain)] if len(part) >= 4)


_STOPWORDS = {"the", "and", "for", "with", "how", "what", "best", "near", "free", "top", "vs", "you", "your",
              "are", "can", "does", "from", "that", "this", "online", "near", "me", "is", "to", "of", "in",
              "a", "an", "on", "my", "do", "why", "who", "which", "when"}


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9+#-]{2,}", (text or "").lower()) if w not in _STOPWORDS}


def relevant(keyword: str, vocab: set[str], share: float = 0.5) -> bool:
    """At least `share` of the keyword's content words appear on the brand's own pages: "hotel
    furniture cost" is relevant for a hotel-furniture site, "google headquarters" is not."""
    words = content_words(keyword)
    if not words or not vocab:
        return not vocab  # no vocabulary to judge by: keep
    hits = sum(1 for w in words if w in vocab or w.rstrip("s") in vocab or (w + "s") in vocab)
    return hits / len(words) >= share


def _keep(k: "SearchKeyword", terms: list[str], vocab: set[str], share: float) -> bool:
    return (k.intent or "") != "navigational" and not is_branded(k.keyword, terms) and relevant(k.keyword, vocab, share)


# ---- DataForSEO Labs calls --------------------------------------------------------------

def _keyword(it: dict, *, page_key: str = "ranked_serp_element", domain: str = "") -> SearchKeyword | None:
    kd = it.get("keyword_data") or it  # ranked_keywords nests it; keywords_for_site does not
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


def ranked_keywords(domain: str, geo: dict, cfg: Settings) -> list[SearchKeyword]:
    items = post("dataforseo_labs/google/ranked_keywords/live",
                 {"target": domain, **geo, "limit": 100, "load_rank_absolute": False,
                  "order_by": ["keyword_data.keyword_info.search_volume,desc"]}, cfg)
    return [k for k in (_keyword(i) for i in items) if k]


def site_keywords(domain: str, geo: dict, cfg: Settings) -> list[SearchKeyword]:
    """Keywords relevant to the site's content even where it does not rank yet (small sites)."""
    items = post("dataforseo_labs/google/keywords_for_site/live",
                 {"target": domain, **geo, "limit": 100, "include_serp_info": False,
                  "order_by": ["keyword_info.search_volume,desc"]}, cfg)
    return [k for k in (_keyword(i) for i in items) if k]


def serp_competitors(keywords: list[str], brand_domain: str, terms: list[str], geo: dict,
                     cfg: Settings) -> list[Competitor]:
    """Domains that rank for the brand's NON-branded keywords: the real market competitors."""
    if not keywords:
        return []
    items = post("dataforseo_labs/google/serp_competitors/live",
                 {"keywords": keywords[:20], **geo, "limit": 30, "item_types": ["organic"]}, cfg)
    return _competitors(items, brand_domain, terms, cfg, shared_key="keywords_count")


def domain_competitors(domain: str, terms: list[str], geo: dict, cfg: Settings) -> list[Competitor]:
    items = post("dataforseo_labs/google/competitors_domain/live",
                 {"target": domain, **geo, "limit": 30, "exclude_top_domains": True,
                  "order_by": ["intersections,desc"]}, cfg)
    return _competitors(items, domain, terms, cfg, shared_key="intersections")


def _competitors(items: list[dict], brand_domain: str, terms: list[str], cfg: Settings,
                 shared_key: str) -> list[Competitor]:
    me = _bare(brand_domain)
    out: list[Competitor] = []
    for it in items:
        d = _bare(it.get("domain", ""))
        if (not d or d == me or d.endswith("." + me) or me.endswith("." + d) or _NOT_COMPETITORS.search(d)
                or lookalike(d, me, terms)):
            continue
        organic = ((it.get("full_domain_metrics") or {}).get("organic") or {})
        out.append(Competitor(domain=d, shared_keywords=int(_num(it.get(shared_key))),
                              avg_position=round(_num(it.get("avg_position")), 1),
                              organic_traffic=int(_num(organic.get("etv") or it.get("etv")))))
        if len(out) >= cfg.dataforseo_max_competitors:
            break
    return out


def content_gaps(domain: str, rivals: list[Competitor], terms: list[str], vocab: set[str], geo: dict,
                 cfg: Settings) -> list[SearchKeyword]:
    """Keywords top competitors rank for (top 20) and the brand does not, kept only when they are
    about the brand's own business (its vocabulary) and are not some company's name."""
    gaps: list[SearchKeyword] = []
    for rival in rivals[:2]:
        items = post("dataforseo_labs/google/domain_intersection/live",
                     {"target1": rival.domain, "target2": domain, "intersections": False, **geo,
                      "limit": 50, "filters": [["first_domain_serp_element.rank_group", "<=", 20]],
                      "order_by": ["keyword_data.keyword_info.search_volume,desc"]}, cfg)
        rival_terms = terms + brand_terms("", rival.domain)
        gaps += [k for k in (_keyword(i, page_key="first_domain_serp_element", domain=rival.domain) for i in items)
                 if k and _keep(k, rival_terms, vocab, 0.5)]
    return _dedupe(sorted(gaps, key=lambda k: k.search_volume, reverse=True), cfg.dataforseo_max_keywords)


def _dedupe(kws: list[SearchKeyword], n: int) -> list[SearchKeyword]:
    seen, out = set(), []
    for k in kws:
        key = re.sub(r"\W+", " ", k.keyword.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(k)
    return out[:n]


_QUESTION = re.compile(r"^(how|what|why|when|which|who|can|does|do|is|are|should|best|vs\b)|\bvs\b|\?$", re.I)


def questions(intel: MarketIntel | None) -> list[SearchKeyword]:
    """Searches phrased as questions: the raw material for Answer posts."""
    if not intel:
        return []
    return [k for k in intel.brand_keywords + intel.gap_keywords if _QUESTION.search(k.keyword)]


class _Relevant(BaseModel):
    competitors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


def screen(intel: MarketIntel, brand: str, about: str, cfg: Settings) -> MarketIntel:
    """One small model call keeps only what belongs to the brand's market. Word filters cannot
    tell, on a large site, that "have been pwned" or "sheraton room service menu" are not about a
    customer-service platform, or that investopedia.com is not a competitor. On failure the
    deterministically filtered intel is returned unchanged."""
    from .llm import LLM, LLMError

    kws = list(dict.fromkeys(k.keyword for k in intel.brand_keywords + intel.gap_keywords))
    if not (intel.competitors or kws):
        return intel
    try:
        pick = LLM(cfg.critic_model, cfg=cfg).json(
            "You screen search-marketing data for a social media team. Keep only what is about the "
            "brand's own market. Be strict.",
            f"Brand: {brand}\nWhat it does (its own words): {about[:900]}\n\n"
            "COMPETITORS (domains): " + json.dumps([c.domain for c in intel.competitors]) + "\n"
            "Keep a domain only if it sells products or services that compete with the brand's. Drop "
            "publishers, encyclopedias, directories and companies in other markets.\n\n"
            "SEARCHES: " + json.dumps(kws) + "\n"
            "Keep a search only if the brand's customers would search it about the brand's category of "
            "products or the problems they solve, and the brand could credibly post about it. Drop "
            "searches about other companies or their products (e.g. a competitor's or an AI model's "
            "name), unrelated topics, word definitions and navigational queries.\n\n"
            "Return the kept items copied exactly.", _Relevant, temperature=0.0)
    except LLMError as exc:
        log.warning("[market] relevance screen unavailable, keeping word-filtered data: %s", exc)
        return intel
    keep_c = {_bare(c) for c in pick.competitors}
    keep_k = {k.strip().lower() for k in pick.keywords}
    return intel.model_copy(update={
        "competitors": [c for c in intel.competitors if c.domain in keep_c],
        "brand_keywords": [k for k in intel.brand_keywords if k.keyword.lower() in keep_k],
        "gap_keywords": [k for k in intel.gap_keywords if k.keyword.lower() in keep_k],
    })


def market_intel(domain: str, brand: str, cfg: Settings, *, url: str = "", html_lang: str = "",
                 vocab: set[str] | None = None, about: str = "") -> tuple[MarketIntel | None, str]:
    """(intel, note). Competitors and searches come from NON-branded keywords only, filtered for
    relevance to the brand's own pages, so the context is about the market, not the name."""
    if not enabled(cfg):
        return None, "off: DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD are not set"
    domain = _bare(domain)
    vocab = vocab or set()
    terms = brand_terms(brand, domain)
    loc, lang, how = geo_for(url or f"https://{domain}/", html_lang, cfg)
    geo = _geo(loc, lang)
    log.info("[market] %s: location %s, language %s (%s)", domain, loc, lang, how)

    ranked = ranked_keywords(domain, geo, cfg)
    demand = [k for k in ranked if _keep(k, terms, vocab, 0.34)]
    source = "ranked"
    if len(demand) < 3:  # small or new site: it ranks mostly for its own name
        extra = [k for k in site_keywords(domain, geo, cfg) if _keep(k, terms, vocab, 0.5)]
        demand += [k for k in extra if k.keyword not in {d.keyword for d in demand}]
        source = "ranked + site-relevant"
    demand = _dedupe(sorted(demand, key=lambda k: k.search_volume, reverse=True), cfg.dataforseo_max_keywords)
    rivals = serp_competitors([k.keyword for k in demand], domain, terms, geo, cfg)
    if not rivals and len(ranked) - len(demand) < len(ranked) * 0.8:
        # Fallback when SERP competitors gave nothing and the ranking is not mostly branded.
        rivals = domain_competitors(domain, terms, geo, cfg)
    gaps = content_gaps(domain, rivals, terms, vocab, geo, cfg) if rivals else []
    if _blocked:
        return None, f"refused: DataForSEO {_blocked[0]}"
    if not (rivals or demand or gaps):
        branded = len(ranked) - len([k for k in ranked if not is_branded(k.keyword, terms)])
        return None, (f"empty: no usable market data for {domain} in location {loc} ({how}); "
                      f"{len(ranked)} ranked keyword(s), {branded} of them branded")
    intel = MarketIntel(location_code=loc, language_code=lang, competitors=rivals, brand_keywords=demand,
                        gap_keywords=gaps)
    if about:
        before = len(intel.competitors) + len(intel.brand_keywords) + len(intel.gap_keywords)
        intel = screen(intel, brand, about, cfg)
        rivals, demand, gaps = intel.competitors, intel.brand_keywords, intel.gap_keywords
        log.info("[market] relevance screen kept %d of %d items", len(rivals) + len(demand) + len(gaps), before)
        if not (rivals or demand or gaps):
            return None, f"empty: nothing in the search data for {domain} was about its market (location {loc})"
    note = (f"used: {len(rivals)} competitor(s), {len(demand)} audience search(es) ({source}), "
            f"{len(gaps)} content gap(s); location {loc} ({how}), language {lang}")
    log.info("[market] %s: %s; competitors %s", domain, note, ", ".join(c.domain for c in rivals[:5]))
    return intel, note


def news_hits(query: str, cfg: Settings, n: int = 10, geo: tuple[int, str] | None = None) -> list[dict]:
    """Google News results as research.py hits: {title, url, date}."""
    if not enabled(cfg):
        return []
    items = post("serp/google/news/live/advanced",
                 {"keyword": query, **_geo(*(geo or (cfg.dataforseo_location_code or 2840,
                                                     cfg.dataforseo_language_code or "en"))),
                  "depth": max(10, n)}, cfg, retry_codes=NEWS_RETRY)
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
    qs = questions(intel)
    if qs:
        lines += ["## Questions the audience searches for (raw material for Answer posts)", ""] + [
            f"- \"{k.keyword}\" ({k.search_volume:,}/mo)" for k in qs[:10]] + [""]
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


_STOP = _STOPWORDS | {"2024", "2025", "2026", "2027"}
