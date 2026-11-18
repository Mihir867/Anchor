"""Rendered HTML -> brand identity + citable evidence items. Deterministic, no LLM."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .crawl import Page
from .verify import norm

_WS = re.compile(r"\s+")
_DATE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
_TESTIMONIAL = re.compile(r"(testimonial|review|quote|customer-stor|client-quote|feedback|endorsement)", re.I)
_PRICE = re.compile(r"([$€£₹]\s?\d[\d,.]*\s?(?:/\s?\w+)?|\bfree\b)", re.I)
_LOGOWALL = re.compile(r"(customer|client|partner|trusted|logo-?wall|logos|used-by|loved-by)", re.I)
_JUNK = ("cookie", "privacy policy", "all rights reserved", "subscribe to", "javascript", "sign up for our newsletter")


def clean(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def prose(text: str, lo: int = 40, hi: int = 900) -> bool:
    if not lo <= len(text) <= hi:
        return False
    if any(t in text for t in ("{", "}", "=>", "function(", "var ", "===")):
        return False
    low = text.lower()
    if any(j in low for j in _JUNK):
        return False
    return sum(c.isalpha() for c in text) / max(len(text), 1) > 0.6


def json_ld(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        out += [i for i in items if isinstance(i, dict)]
    return out


def _types(item: dict) -> set[str]:
    t = item.get("@type", "")
    return {str(x) for x in (t if isinstance(t, list) else [t])}


def page_date(soup: BeautifulSoup, ld: list[dict]) -> str | None:
    cands = [
        (soup.find("meta", property="article:published_time") or {}).get("content", ""),
        (soup.find("meta", attrs={"name": "date"}) or {}).get("content", ""),
        (soup.find("time") or {}).get("datetime", "") if soup.find("time") else "",
    ] + [str(i.get("datePublished", "")) for i in ld]
    for c in cands:
        m = _DATE.search(c or "")
        if m:
            return m.group(0)
    return None


def brand_name(home: Page, tokens: dict, ld: list[dict]) -> str:
    domain_label = urlparse(home.url).netloc.removeprefix("www.").split(".")[0]
    site = clean(tokens.get("site_name", ""))
    if site and len(site) <= 40:
        return site
    for item in ld:
        if _types(item) & {"Organization", "Corporation", "Hotel", "LodgingBusiness", "Store", "Brand"}:
            name = clean(str(item.get("name", "")))
            if 1 < len(name) <= 40:
                return name
    segments = [clean(s) for s in re.split(r"\s[|\-–—:·]\s|\s?[|·]\s?", tokens.get("title", "")) if clean(s)]
    for seg in segments:
        if domain_label.lower() in seg.lower().replace(" ", "") and len(seg) <= 40:
            return seg
    return domain_label.replace("-", " ").title()


def structured_facts(ld: list[dict]) -> list[str]:
    facts: list[str] = []
    keys = ("name", "foundingDate", "founder", "numberOfEmployees", "award", "slogan", "numberOfRooms",
            "starRating", "priceRange", "checkinTime", "checkoutTime", "areaServed", "brand")
    for item in ld:
        types = _types(item)
        if types & {"BreadcrumbList", "WebSite", "WebPage", "SiteNavigationElement", "FAQPage", "ImageObject"}:
            continue
        bits = []
        for k in keys:
            v = item.get(k)
            if isinstance(v, dict):
                v = v.get("name") or v.get("value")
            if isinstance(v, list):
                v = ", ".join(str(x.get("name", x)) if isinstance(x, dict) else str(x) for x in v[:8])
            if v:
                bits.append(f"{k}: {clean(str(v))[:200]}")
        rating = item.get("aggregateRating")
        if isinstance(rating, dict) and rating.get("ratingValue"):
            bits.append(f"aggregateRating: {rating.get('ratingValue')} from {rating.get('reviewCount') or rating.get('ratingCount') or '?'} reviews")
        amen = item.get("amenityFeature")
        if isinstance(amen, list):
            names = [clean(str(a.get("name", ""))) for a in amen if isinstance(a, dict)]
            if names:
                bits.append("amenities: " + ", ".join(n for n in names if n)[:300])
        addr = item.get("address")
        if isinstance(addr, dict):
            bits.append("address: " + ", ".join(clean(str(addr.get(k, ""))) for k in ("streetAddress", "addressLocality", "addressCountry") if addr.get(k)))
        if len(bits) >= 2:
            facts.append(f"{'/'.join(sorted(types))} — " + "; ".join(bits))
    return facts


def testimonials(soup: BeautifulSoup, ld: list[dict]) -> list[str]:
    out: list[str] = []
    for item in ld:
        if _types(item) & {"Review"} and item.get("reviewBody"):
            author = item.get("author", {})
            author = author.get("name", "") if isinstance(author, dict) else str(author or "")
            out.append(f'"{clean(item["reviewBody"])}" — {clean(author) or "reviewer"}')
    for q in soup.find_all(["blockquote", "q"]):
        text = clean(q.get_text(" "))
        cite = q.find_parent().find(["cite", "figcaption"]) if q.find_parent() else None
        if prose(text, 25, 600):
            out.append(f'"{text}"' + (f" — {clean(cite.get_text(' '))[:80]}" if cite else ""))
    for box in soup.find_all(["div", "section", "li", "figure"], class_=_TESTIMONIAL)[:20]:
        p = box.find(["p", "blockquote"])
        who = box.find(["cite", "figcaption", "strong", "h4", "h5"])
        text = clean(p.get_text(" ")) if p else ""
        if prose(text, 25, 600):
            out.append(f'"{text}"' + (f" — {clean(who.get_text(' '))[:80]}" if who else ""))
    return list(dict.fromkeys(out))[:10]


def pricing(soup: BeautifulSoup) -> list[str]:
    lines = []
    for card in soup.find_all(["div", "section", "li"], class_=re.compile(r"(plan|tier|price|pricing|package)", re.I))[:12]:
        name = card.find(["h2", "h3", "h4"])
        price = card.find(string=_PRICE)
        if price:
            lines.append(clean(f"{clean(name.get_text(' ')) + ': ' if name else ''}{clean(str(price))}")[:140])
    return list(dict.fromkeys(lines))[:8]


def logo_wall(soup: BeautifulSoup) -> list[str]:
    names: list[str] = []
    for sec in soup.find_all(["section", "div"], class_=_LOGOWALL)[:10]:
        for img in sec.find_all("img")[:30]:
            alt = re.sub(r"\s*(logo|icon)\s*$", "", clean(img.get("alt", "")), flags=re.I)
            if 2 < len(alt) < 40 and alt.lower() not in ("logo", "image", "icon"):
                names.append(alt)
    return list(dict.fromkeys(names))[:24]


def page_chunks(soup: BeautifulSoup, max_chars: int = 700) -> list[str]:
    for tag in soup.find_all(["nav", "header", "footer", "aside", "script", "style", "noscript", "svg", "form"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    chunks, cur = [], ""
    for el in root.find_all(["h1", "h2", "h3", "p", "li"]):
        text = clean(el.get_text(" "))
        if el.name in ("h1", "h2", "h3"):
            if 8 <= len(text) <= 140:
                if cur:
                    chunks.append(cur)
                cur = text + ":"
            continue
        if not prose(text, 30 if el.name == "li" else 40):
            continue
        if len(cur) + len(text) + 1 > max_chars and cur:
            chunks.append(cur)
            cur = ""
        cur = f"{cur} {text}".strip()
    if cur:
        chunks.append(cur)
    return [c for c in chunks if len(c) >= 60 and not c.endswith(":")]


def informativeness(text: str) -> float:
    """Prefer text that carries checkable specifics: numbers, names, quotes, dates."""
    digits = len(re.findall(r"\d+", text))
    caps = len(re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+", text))
    quotes = text.count('"') + text.count("“")
    return min(digits, 6) * 1.5 + min(caps, 6) + min(quotes, 2) * 2 + min(len(text), 700) / 350


def site_evidence(home: Page, pages: list[Page]) -> tuple[list[dict], dict]:
    """Return (evidence dicts without ids, identity extras)."""
    items: list[dict] = []
    seen: set[str] = set()
    extras: dict = {"ld": [], "customers": [], "taglines": []}

    def add(kind: str, url: str, title: str, date: str | None, text: str, boost: float = 0.0) -> None:
        key = norm(text)[:160]
        if key in seen:
            return
        seen.add(key)
        items.append({"kind": kind, "url": url, "title": title[:120], "date": date, "text": text[:900],
                      "_rank": informativeness(text) + boost})

    for idx, pg in enumerate([home] + pages):
        soup = BeautifulSoup(pg.html, "html.parser")
        ld = json_ld(soup)
        extras["ld"] += ld
        date = page_date(soup, ld)
        title = clean(pg.title)
        boost = 1.5 if re.search(r"(press|news|blog|case|customer|award|stor)", urlparse(pg.url).path, re.I) else 0.0
        for fact in structured_facts(ld):
            add("structured", pg.url, title, date, fact, 3.0)
        for t in testimonials(soup, ld):
            add("testimonial", pg.url, title, date, t, 3.0)
        prices = pricing(soup)
        if prices:
            add("pricing", pg.url, title, date, "Pricing shown: " + "; ".join(prices), 2.0)
        names = logo_wall(soup)
        if names:
            extras["customers"] += names
            add("structured", pg.url, title, date, "Customer/partner logos displayed on the site: " + ", ".join(names), 2.0)
        for chunk in page_chunks(soup):
            add("site", pg.url, title, date, chunk, boost - idx * 0.05)
    extras["customers"] = list(dict.fromkeys(extras["customers"]))
    return items, extras
