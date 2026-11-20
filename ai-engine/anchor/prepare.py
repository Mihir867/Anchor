"""URL -> TaskPack (crawl, extract, research, classify). Runs ONCE per run.

Everything downstream -- every Harness² rollout, the selector, the improver -- reads this
frozen pack, so all candidates are compared on identical evidence.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import crawl, extract, harness, history, market, progress, research
from .config import Settings
from .llm import LLM, LLMError
from .models import BrandKit, Evidence, SkillChoice, TaskPack
from .verify import dominant_script

log = logging.getLogger("anchor.prepare")
MIN_EVIDENCE = 4


class PrepareError(RuntimeError):
    pass


def normalize_url(url: str) -> str:
    url = url.strip()
    return url if urlparse(url).scheme else "https://" + url.lstrip("/")


def task_id_for(url: str) -> str:
    host = urlparse(url).netloc.removeprefix("www.")
    slug = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")
    return f"{slug}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def classify(h: harness.Harness, text: str, ld_types: set[str], cfg: Settings, url: str = "") -> tuple[str, str]:
    """Industry = the skill whose keywords/schema types best match. LLM only breaks ties."""
    industries = {n: s for n, s in h.skills.items() if s.meta.get("industry")}
    if not industries:
        raise PrepareError("the harness has no industry skills (frontmatter `industry: true`)")
    low = text.lower()
    scores: dict[str, float] = {}
    for name, skill in industries.items():
        kw = sum(len(re.findall(rf"\b{re.escape(k.lower())}\b", low)) for k in skill.list_meta("keywords"))
        st = sum(4 for t in skill.list_meta("schema_types") if t in ld_types)
        scores[name] = min(kw, 12) + st
    ranked = sorted(scores, key=scores.get, reverse=True)
    best, second = ranked[0], (ranked[1] if len(ranked) > 1 else None)
    margin = scores[best] - (scores[second] if second else 0)
    reason = f"keyword/schema scores {scores}"
    if scores[best] >= 3 and margin >= 3:
        return best, reason
    try:
        menu = "\n".join(f"- {n}: {s.description}" for n, s in industries.items())
        choice = LLM(cfg.model, cfg=cfg).json(
            "You classify a business into exactly one playbook.",
            f"Playbooks:\n{menu}\n\nBusiness URL: {url or 'unknown'}\n"
            f"Business homepage text (truncated):\n{text[:3500]}\n\n"
            "Pick the single best playbook name.",
            SkillChoice,
            temperature=0.0,
        )
        lookup = {n.lower(): n for n in industries}
        picked = next((lookup[s.strip().lower()] for s in choice.skills if s.strip().lower() in lookup), None)
        if picked:
            return picked, f"{reason}; tie broken by model -> {picked}"
    except LLMError as exc:
        log.warning("industry tie-break failed: %s", exc)
    return best, reason + "; low-confidence, highest score used"


def prepare(url: str, cfg: Settings, max_posts: int = 3, task_id: str | None = None,
            industry: str | None = None) -> tuple[TaskPack, Path]:
    url = normalize_url(url)
    task_id = task_id or task_id_for(url)
    run_dir = cfg.runs_dir / task_id
    pack_dir = run_dir / "pack"
    assets = pack_dir / "assets"
    log.info("[prepare] %s -> %s", url, run_dir)
    progress.report("crawling", url=url)

    home = asyncio.run(crawl.crawl_home(url, assets))
    soup = BeautifulSoup(home.home.html, "html.parser")
    ld = extract.json_ld(soup)
    name = extract.brand_name(home.home, home.tokens, ld)
    home_text = " ".join([home.tokens.get("title", ""), home.tokens.get("description", ""),
                          home.tokens.get("h1", ""), extract.clean(soup.get_text(" "))[:6000]])
    h = harness.load(cfg.harness_dir)
    ld_types = {t for item in ld for t in extract._types(item)}
    if industry and industry in h.skills:
        reason = "forced by caller"
    else:
        # URL words count too ("grand-hyatt-mumbai", "/hotels/") when the page itself is thin.
        url_words = " ".join(re.split(r"[^a-z0-9]+", url.lower()))
        industry, reason = classify(h, home_text + " " + url_words, ld_types, cfg, url)
    skill = h.skills[industry]
    log.info("[prepare] brand=%r industry=%s (%s)", name, industry, reason)
    progress.report("crawling", brand=name, industry=industry)

    urls = crawl.candidate_urls(home, skill.list_meta("crawl_paths"), cfg.max_pages)
    pages = asyncio.run(crawl.crawl_pages(urls, cfg.max_pages, budget=cfg.subpage_budget))
    deep = crawl.article_links(pages, home.url, {home.url, *urls}, cfg.max_article_pages)
    if deep:
        log.info("[prepare] reading %d article page(s) linked from index pages", len(deep))
        progress.report("crawling", articles=len(deep))
        pages += asyncio.run(crawl.crawl_pages(deep, cfg.max_article_pages, budget=cfg.article_budget))
    site_items, extras = extract.site_evidence(home.home, pages)
    domain = urlparse(home.url).netloc.removeprefix("www.")
    progress.report("researching", pages=1 + len(pages), site_evidence=len(site_items))
    script = dominant_script(" ".join(d["text"] for d in site_items) or home_text)
    lang_tag = str(home.tokens.get("lang") or "")
    language = (lang_tag.split("-")[0].lower() or "en") if re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]+)*", lang_tag) else "en"
    geo = market.geo_for(home.url, lang_tag, cfg)[:2] if market.enabled(cfg) else None
    log.info("[prepare] %d site evidence items from %d pages; searching news for %r", len(site_items),
             1 + len(pages), name)
    news_items = research.news_evidence(name, domain, skill.list_meta("news_queries"), cfg.max_articles,
                                        script, cfg, geo=geo)
    intel, market_note = None, "off: DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD are not set"
    if market.enabled(cfg):
        progress.report("researching", step="competitors")
        log.info("[prepare] fetching DataForSEO market context for %s", domain)
        vocab = market.content_words(home_text + " " + " ".join(d["text"] for d in site_items))
        try:
            about = " ".join(x for x in (home.tokens.get("title", ""), home.tokens.get("description", ""),
                                         home.tokens.get("h1", "")) if x)
            intel, market_note = market.market_intel(domain, name, cfg, url=home.url, html_lang=lang_tag,
                                                     vocab=vocab, about=about)
        except Exception as exc:  # market context is an enhancement; never fail a run over it
            market_note = f"failed: {type(exc).__name__}: {exc}"[:300]
            log.warning("[prepare] DataForSEO market context failed: %s", exc)
        if intel:
            progress.report("researching", competitors=[c.domain for c in intel.competitors],
                            search_keywords=len(intel.brand_keywords) + len(intel.gap_keywords))

    crawled = site_items + news_items
    pooled = _pooled_evidence(cfg, domain, crawled)
    try:  # remember this crawl for the brand's next runs (before _rank is popped below)
        history.record_evidence(cfg, domain, crawled)
    except Exception as exc:
        log.warning("[prepare] could not save the evidence pool: %s", exc)
    ranked = sorted(crawled + pooled, key=lambda d: d.pop("_rank", 0), reverse=True)[:70]
    if len(ranked) < MIN_EVIDENCE:
        # Thin site (mostly images, heavy JS, little copy). Still deliver: the home page's own
        # title/description/headline become citable items, and generate.ensure_post guarantees
        # at least one (clearly labelled) post.
        log.warning("[prepare] little material for %s: %d site items from %d pages, %d news items; "
                    "continuing with home-page basics", url, len(site_items), 1 + len(pages), len(news_items))
        ranked += _home_basics(home, name, domain, {norm_key(d["text"]) for d in ranked})
    used_pool = sum(1 for d in ranked if d.pop("_pooled", False))
    evidence = [Evidence(id=f"E{i}", **d) for i, d in enumerate(ranked, start=1)]
    thin_reason = thin_pack(evidence, cfg)
    if thin_reason:
        log.warning("[prepare] thin pack for %s: %s; writing 1 post from the best fact, no refine",
                    domain, thin_reason)
        max_posts = 1

    t = home.tokens
    colors = t.get("ranked_colors") or []
    brand = BrandKit(
        url=home.url, domain=domain, name=name,
        tagline=extract.clean(t.get("h1", ""))[:160], description=extract.clean(t.get("description", ""))[:300],
        primary_color=colors[0] if colors else "#111827",
        secondary_color=colors[1] if len(colors) > 1 else None,
        accent_colors=colors[2:6],
        background_color=t.get("background") or "#FFFFFF", text_color=t.get("text") or "#111111",
        heading_font=t.get("heading_font"), body_font=t.get("body_font"),
        font_faces=t.get("font_faces", []), logo_path=home.logo_path, screenshot_path=home.screenshot_path,
        image_urls=[u for u in [t.get("og_image")] + t.get("images", []) if u][:10],
        social_links={},
    )
    pack = TaskPack(
        task_id=task_id, url=home.url, created_at=datetime.now(timezone.utc).isoformat(),
        industry=industry, industry_reason=reason, max_posts=max_posts, brand=brand, script=script,
        evidence=evidence, pages_crawled=[home.url] + [p.url for p in pages], market=intel,
        market_note=market_note, language=language,
        already_posted=[p_["headline"] for p_ in history.load(cfg, domain)],
        thin=bool(thin_reason), thin_reason=thin_reason, pooled_evidence=used_pool,
    )
    log.info("[prepare] market context %s", market_note)
    write_pack(pack, pack_dir, extras.get("customers", []))
    progress.report("mining", evidence=len(evidence), news=sum(e.kind == "article" for e in evidence))
    log.info("[prepare] %d evidence items (%d site, %d news, %d pooled from earlier runs) from %d pages",
             len(evidence), sum(e.kind != "article" for e in evidence),
             sum(e.kind == "article" for e in evidence), used_pool, len(pack.pages_crawled))
    return pack, run_dir


def thin_pack(evidence: list[Evidence], cfg: Settings) -> str:
    """Why this pack is too thin for a full set (and for Harness² refine), or "" if it is not."""
    articles = sum(e.kind == "article" for e in evidence)
    if articles == 0 and len(evidence) < cfg.thin_evidence:
        return f"{len(evidence)} evidence item(s) and no press (threshold {cfg.thin_evidence})"
    return ""


def _pooled_evidence(cfg: Settings, domain: str, crawled: list[dict]) -> list[dict]:
    """Items from the brand's earlier runs that this crawl did not see, ranked like fresh ones but
    slightly lower (the page may have changed since)."""
    try:
        past = history.load_evidence(cfg, domain)
    except Exception as exc:
        log.warning("[prepare] could not load the evidence pool: %s", exc)
        return []
    seen = {norm_key(d["text"]) for d in crawled}
    out = []
    for d in past:
        if norm_key(d["text"]) in seen or d.get("kind") not in ("site", "article", "testimonial", "pricing", "structured"):
            continue
        seen.add(norm_key(d["text"]))
        out.append({"kind": d["kind"], "url": d.get("url") or "", "title": d.get("title") or "",
                    "date": d.get("date"), "text": d["text"], "_pooled": True,
                    "_rank": extract.informativeness(d["text"]) + (2.5 if d["kind"] == "article" else 0) - 0.5})
    if out:
        log.info("[prepare] %d evidence item(s) from earlier runs of %s available", len(out), domain)
    return out


def norm_key(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()[:160]


def _home_basics(home: crawl.CrawlResult, name: str, domain: str, seen: set[str]) -> list[dict]:
    """The home page's title, meta description and headline as evidence items (deduplicated)."""
    t = home.tokens
    out: list[dict] = []
    for text in (t.get("description", ""), t.get("h1", ""), t.get("title", "")):
        text = extract.clean(text)[:900]
        if len(text) >= 8 and norm_key(text) not in seen:
            seen.add(norm_key(text))
            out.append({"kind": "site", "url": home.url, "title": extract.clean(t.get("title", ""))[:120],
                        "date": None, "text": text})
    if not out:
        out.append({"kind": "site", "url": home.url, "title": name, "date": None,
                    "text": f"{name} ({domain}) website home page."})
    return out


def write_pack(pack: TaskPack, pack_dir: Path, customers: list[str]) -> None:
    """pack.json for code; source/*.md is the human/model-readable copy Harness² shows."""
    src = pack_dir / "source"
    src.mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.json").write_text(pack.model_dump_json(indent=2), encoding="utf-8")
    b = pack.brand
    (src / "brand.md").write_text(
        f"# {b.name}\n\n- url: {b.url}\n- industry playbook: {pack.industry}\n"
        f"- tagline: {b.tagline}\n- description: {b.description}\n"
        f"- customer/partner logos on site: {', '.join(customers) or 'none found'}\n"
        f"- pages crawled: {len(pack.pages_crawled)}\n", encoding="utf-8")
    (src / "evidence.md").write_text(
        "# Evidence\n\nEvery claim in a post must be supported by one of these items. "
        "Each line is `[id] (kind, date, url) title -- text`.\n\n"
        + "\n\n".join(e.render() for e in pack.evidence) + "\n", encoding="utf-8")
    if pack.market:
        # Harness² proposers and the selector read source/, so they see the same market context.
        (src / "market.md").write_text(market.render(pack.market, b.name), encoding="utf-8")


def load_pack(pack_dir: Path) -> TaskPack:
    return TaskPack.model_validate(json.loads((pack_dir / "pack.json").read_text(encoding="utf-8")))
