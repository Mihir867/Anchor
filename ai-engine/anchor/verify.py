"""Deterministic grounding checks. These run in code, so no model can talk its way past them.

Each check returns a list of human-readable problems; an empty list means it passed. The
problems are fed back verbatim to the writer for repair, and logged to the trajectory where
Harness² proposers read them.
"""

from __future__ import annotations

import re
import unicodedata

from .models import Evidence, MinedFact, PostDraft

GLOBAL_BANNED = [
    "game-changer", "game changer", "in today's fast-paced world", "unlock the power",
    "dive deep", "deep dive", "delve", "revolutionize", "revolutionary", "supercharge",
    "look no further", "seamlessly", "cutting-edge", "next-level", "elevate your",
    "agree? thoughts?", "let me know in the comments",
]

_TRANSLATE = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
    "‑": "-", "‐": "-", " ": " ", "…": "...",
})
_NUM = re.compile(
    r"(?P<cur>[$€£₹])?\s?(?P<val>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s?(?P<suf>%|percent\b|per cent\b|x\b|×|k\b|m\b|b\b|bn\b|million\b|billion\b|thousand\b|trillion\b|crore\b|lakh\b)?",
    re.I,
)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9,
          "billion": 1e9, "trillion": 1e12, "crore": 1e7, "lakh": 1e5}
_PLACEHOLDER = re.compile(r"\[[^\]]{0,40}\]|\{[^}]{0,40}\}|\bTBD\b|lorem ipsum|\bXX+\b", re.I)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


_KANA_HAN = ("CJK", "HIRAGANA", "KATAKANA", "HALFWIDTH", "IDEOGRAPHIC", "KANGXI", "BOPOMOFO")


def script_of(ch: str) -> str | None:
    """Writing system of one letter ('LATIN', 'CJK', 'HANGUL', 'CYRILLIC', ...); None for
    digits, punctuation, symbols and spaces, which every script shares."""
    if not ch.isalpha():
        return None
    name = unicodedata.name(ch, "")
    if not name:
        return None
    if name.startswith("FULLWIDTH LATIN"):
        return "LATIN"
    if name.startswith("HALFWIDTH HANGUL"):
        return "HANGUL"
    first = name.split(" ", 1)[0]
    return "CJK" if first.startswith(_KANA_HAN) else first


def dominant_script(text: str, default: str = "LATIN") -> str:
    counts: dict[str, int] = {}
    for ch in text or "":
        s = script_of(ch)
        if s:
            counts[s] = counts.get(s, 0) + 1
    return max(counts, key=counts.get) if counts else default


def foreign_text(text: str, script: str = "LATIN") -> list[str]:
    """Runs of letters in a writing system other than `script` (Latin is always allowed: brand
    and product names are Latin everywhere). These are what render as box glyphs on a poster
    and read as gibberish to the post's audience."""
    allowed = {script, "LATIN"}
    runs, cur = [], ""
    for ch in text or "":
        s = script_of(ch)
        if s and s not in allowed:
            cur += ch
        elif cur and (s is None and not ch.isspace()):
            cur += ch  # keep 'オーアール・ラボ' as one run
        else:
            if cur:
                runs.append(cur.strip("・、。,.;: "))
            cur = ""
    if cur:
        runs.append(cur.strip("・、。,.;: "))
    return [r for r in dict.fromkeys(runs) if r]


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(_TRANSLATE).lower()
    return re.sub(r"\s+", " ", text).strip()


def numbers(text: str) -> set[tuple[float, bool]]:
    """Canonical numeric claims: (value, is_percent). '$27M' and '27 million' both -> 27e6."""
    found: set[tuple[float, bool]] = set()
    clean = norm(text)
    clean = re.sub(r"#\w+", " ", clean)  # hashtags are not claims
    for m in _NUM.finditer(clean):
        raw = m.group("val").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        suf = (m.group("suf") or "").lower()
        is_pct = suf in ("%", "percent", "per cent")
        if suf in _SCALE:
            value *= _SCALE[suf]
        is_marked = bool(m.group("cur") or suf)
        # Small bare integers ("3 reasons", "step 2") are structure, not factual claims.
        if not is_marked and value < 10 and raw.isdigit():
            continue
        found.add((round(value, 6), is_pct))
    return found


def check_fact(fact: MinedFact, ev: dict[str, Evidence], brand: str = "") -> list[str]:
    problems: list[str] = []
    cited = [ev[i] for i in fact.evidence_ids if i in ev]
    unknown = [i for i in fact.evidence_ids if i not in ev]
    if unknown:
        problems.append(f"cites evidence ids that do not exist: {unknown}")
    if not cited:
        return problems + ["cites no valid evidence"]
    corpus = " ".join(norm(f"{e.text} {e.title} {e.date or ''}") for e in cited)
    if len(fact.quote.strip()) < 20:
        problems.append("quote is shorter than 20 characters; copy a full verbatim sentence")
    elif not quote_found(fact.quote, [e.text for e in cited]):
        problems.append(f"quote is not a verbatim span of the cited evidence: {fact.quote[:120]!r}")
    for metric in fact.metrics:
        if not numbers(metric) <= numbers(corpus) or not numbers(metric):
            problems.append(f"metric {metric!r} does not appear in the cited evidence")
    for name in fact.named_entities:
        if norm(name) not in corpus:
            problems.append(f"named entity {name!r} does not appear in the cited evidence")
    missing = numbers(fact.headline) - numbers(corpus)
    if missing:
        problems.append(f"headline states numbers not in evidence: {_fmt(missing)}")
    # Off-site articles often discuss other companies; on-site pages are about the brand by default.
    core = re.sub(r"^the ", "", norm(brand))
    if brand and all(e.kind == "article" for e in cited) and core not in norm(fact.headline + " " + fact.quote):
        problems.append(f"fact is not about {brand}: the cited article text does not name it in the quote or headline")
    return problems


def quote_found(quote: str, texts: list[str]) -> bool:
    """Verbatim match after normalisation; '...' may elide text between in-order fragments."""
    q = norm(quote).strip(" \"'")
    parts = [p.strip(" \"'") for p in re.split(r"\.\.\.", q) if len(p.strip()) >= 12]
    if not parts:
        return False
    for text in texts:
        t = norm(text)
        pos = 0
        for part in parts:
            idx = t.find(part, pos)
            if idx < 0:
                break
            pos = idx + len(part)
        else:
            return True
    return False


def normalize_post(post: PostDraft, fact: MinedFact, detail_slides: int = 2) -> PostDraft:
    """Safe, deterministic fixes for cosmetic limits, so good copy is not dropped over layout:
    the optional stat is cleared if too long, an over-long poster headline falls back to the
    already-verified fact headline."""
    upd = {}
    if len(post.poster_stat) > 14:
        upd["poster_stat"] = ""
    if len(post.poster_headline) > 80 or not post.poster_headline.strip():
        upd["poster_headline"] = fact.headline if len(fact.headline) <= 80 else fact.headline[:77].rsplit(" ", 1)[0] + "…"
    if len(post.poster_kicker) > 48:
        upd["poster_kicker"] = fact.category[:48]
    if len(post.slides) > detail_slides:
        upd["slides"] = post.slides[:detail_slides]
    return post.model_copy(update=upd) if upd else post


def check_post(post: PostDraft, fact: MinedFact, sources: list[Evidence], brand_name: str,
               banned: list[str], detail_slides: int = 2, script: str = "LATIN",
               competitors: list[str] | None = None) -> list[str]:
    problems: list[str] = []
    corpus = " ".join(norm(f"{e.text} {e.title} {e.date or ''}") for e in sources) + " " + norm(brand_name)
    allowed = numbers(corpus)
    for field_name, text in (
        ("linkedin", post.linkedin),
        ("instagram_caption", post.instagram_caption),
        ("poster_headline", post.poster_headline),
        ("poster_kicker", post.poster_kicker),
        ("poster_stat", post.poster_stat),
        ("hashtags", " ".join(post.hashtags)),
        *((f"slide {i} ", f"{sl.title} " + " ".join(sl.bullets)) for i, sl in enumerate(post.slides, 2)),
    ):
        missing = numbers(text) - allowed
        if missing:
            problems.append(f"{field_name} states numbers not found in the cited evidence: {_fmt(missing)}")
        lowered = norm(text)
        hits = sorted({b for b in banned if norm(b) and norm(b) in lowered})
        if hits:
            problems.append(f"{field_name} uses banned phrases: {hits}")
        if _PLACEHOLDER.search(text or ""):
            problems.append(f"{field_name} contains a placeholder or template token")
        foreign = foreign_text(text, script)
        if foreign:
            problems.append(
                f"{field_name} contains text in another writing system {foreign[:4]}: write the whole "
                f"post in the brand's language ({script.title()} script) -- translate it, use the Latin "
                "name the evidence gives, or describe it generically (e.g. 'four Japanese partners')")

    li = post.linkedin.strip()
    if not 400 <= len(li) <= 3000:
        problems.append(f"linkedin length is {len(li)} chars; keep it between 400 and 3000")
    first = li.split("\n", 1)[0]
    if len(first) > 210:
        problems.append("linkedin hook (first line) exceeds 210 chars; it gets cut at 'see more'")
    if len(_EMOJI.findall(li)) > 2:
        problems.append("linkedin uses more than 2 emojis")
    cap = post.instagram_caption.strip()
    if not 120 <= len(cap) <= 2200:
        problems.append(f"instagram_caption length is {len(cap)} chars; keep it between 120 and 2200")
    tags = [t for t in post.hashtags if t.strip()] + re.findall(r"#\w+", cap)
    if len({t.lower().lstrip('#') for t in tags}) > 6:
        problems.append("more than 6 distinct hashtags")
    if len(post.poster_headline) > 80 or not post.poster_headline.strip():
        problems.append("poster_headline must be 1-80 chars")
    if len(post.poster_kicker) > 48:
        problems.append("poster_kicker must be <= 48 chars")
    if len(post.poster_stat) > 14:
        problems.append("poster_stat must be <= 14 chars (one number with unit)")
    if len(post.slides) < detail_slides:
        problems.append(f"carousel needs {detail_slides} slides after the cover, got {len(post.slides)}")
    for i, sl in enumerate(post.slides, 2):
        if not sl.title.strip() or len(sl.title) > 60:
            problems.append(f"slide {i} title must be 1-60 chars")
        if not 1 <= len(sl.bullets) <= 3:
            problems.append(f"slide {i} needs 1-3 bullets")
        long = [b for b in sl.bullets if len(b) > 120 or not b.strip()]
        if long:
            problems.append(f"slide {i} has bullets over 120 chars or empty: {long[:1]}")
    # Competitors come from market context (search data), not evidence: naming one is only
    # allowed when the cited evidence itself does (e.g. a press article about a partnership).
    everything = norm(" ".join([li, cap, post.poster_headline, post.poster_kicker, " ".join(post.hashtags)]
                               + [f"{sl.title} " + " ".join(sl.bullets) for sl in post.slides]))
    own = norm(brand_name)
    named = sorted({c for c in competitors or [] if norm(c) and norm(c) not in own and norm(c) not in corpus
                    and re.search(rf"(?<![\w.]){re.escape(norm(c))}(?![\w])", everything)})
    if named:
        problems.append(f"names competitor(s) {named} that the cited evidence does not mention; "
                        "describe what the brand does instead of comparing")
    if brand_name and norm(brand_name) not in norm(li + " " + cap):
        problems.append(f"neither post names the brand {brand_name!r}")
    return problems


def _fmt(nums: set[tuple[float, bool]]) -> list[str]:
    return sorted(f"{v:g}{'%' if p else ''}" for v, p in nums)
