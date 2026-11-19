"""Deterministic grounding checks. These run in code, so no model can talk its way past them.

Each check returns a list of human-readable problems; an empty list means it passed. The
problems are fed back verbatim to the writer for repair, and logged to the trajectory where
Harness² proposers read them.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

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


# Post types that announce something new: they need a dated, recent cited item, otherwise undated
# site copy ("an AI platform that connects budgeting...") gets dressed up as a launch.
ANNOUNCING = re.compile(r"\b(launch\w*|release\w*|new\b|announce\w*|opening|opens|reopen\w*|drop|"
                        r"general availability|now available|news)\b", re.I)
RECENT_DAYS = 548  # ~18 months


def announces(category: str) -> bool:
    return bool(ANNOUNCING.search(category or ""))


def newest_date(items: list[Evidence]) -> date | None:
    dates = []
    for e in items:
        try:
            dates.append(date.fromisoformat((e.date or "")[:10]))
        except ValueError:
            pass
    return max(dates) if dates else None


_MONTHS = {m: i for i, m in enumerate(("january february march april may june july august september october "
                                       "november december").split(), 1)}
_MON = r"(january|february|march|april|may|june|july|august|september|october|november|december|" \
       r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?"
_D_MON_Y = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON},?\s+(20\d\d)\b", re.I)
_MON_D_Y = re.compile(rf"\b{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", re.I)
_ISO = re.compile(r"\b(20\d\d)-(\d{2})-(\d{2})\b")
TIMED = re.compile(r"\b(event|webinar|summit|conference|meetup|offer|deadline|registration|festival|sale)\b", re.I)


def _month(name: str) -> int:
    name = name.lower().rstrip(".")
    return next(v for k, v in _MONTHS.items() if k.startswith(name[:3]))


def dates_in(text: str) -> list[date]:
    """Calendar dates written in the text ("12 November 2026", "Nov 12, 2026", "2026-11-12")."""
    out = []
    for m in _D_MON_Y.finditer(text or ""):
        out.append((int(m.group(3)), _month(m.group(2)), int(m.group(1))))
    for m in _MON_D_Y.finditer(text or ""):
        out.append((int(m.group(3)), _month(m.group(1)), int(m.group(2))))
    for m in _ISO.finditer(text or ""):
        out.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    found = []
    for y, mo, d in out:
        try:
            found.append(date(y, mo, d))
        except ValueError:
            pass
    return found


def check_fact(fact: MinedFact, ev: dict[str, Evidence], brand: str = "", today: date | None = None) -> list[str]:
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
    if announces(fact.category):
        newest = newest_date(cited)
        if newest is None or ((today or date.today()) - newest).days > RECENT_DAYS:
            problems.append(
                f"post type {fact.category!r} announces something new, but no cited item is dated within "
                f"the last 18 months ({'newest is ' + newest.isoformat() if newest else 'all are undated'}); "
                "pick a post type for existing material instead (e.g. Feature how-to, Proof point, "
                "Product detail) or cite the dated announcement")
    if TIMED.search(fact.category or "") or TIMED.search(fact.headline or ""):
        # An event or offer is only worth inviting people to while its date is ahead.
        when = dates_in(" ".join([fact.headline, fact.quote] + [e.text for e in cited]))
        if when and max(when) < (today or date.today()):
            problems.append(f"the {fact.category or 'event'} took place on {max(when).isoformat()}, which has passed; "
                            "pick a current fact (a past event is only usable as a recap of what happened there, "
                            "if the evidence reports it)")
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


_STOPWORDS = set("""a an and are as at be by for from has have how in into is it its of on or our
that the their this to was we were what when which who why will with you your new now more""".split())


def topic_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9+#.-]*", norm(text)) if len(w) > 2 and w not in _STOPWORDS}


def same_topic(a: str, b: str, threshold: float = 0.5) -> bool:
    """Two facts (headline + quote) are about the same thing when their content words mostly
    overlap. "Max plan provides 6,000 tokens monthly" vs "Max plan includes 6,000 tokens per
    month" -> same topic, so a set never carries the same news twice."""
    wa, wb = topic_words(a), topic_words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= threshold


def _brand_rx(brand: str) -> str:
    core = re.sub(r"^the ", "", norm(brand))
    return re.escape(core) if core else r"(?!x)x"


# "Meet Acme", "Introducing Acme", "Acme is a platform that..." : an outsider's introduction.
_INTRO_FIXED = re.compile(r"\b(who we are|get to know us|allow us to introduce|"
                          r"we are (?:a|an) (?:\w+[ -]){0,3}(?:company|platform|startup|team|brand|agency))\b", re.I)
_INTRO_NOUNS = (r"(?:platform|company|tool|solution|app|application|brand|startup|service|agency|marketplace|"
                r"hotel|resort|software|product|provider|business|firm|studio|network)")


def intro_problems(post: PostDraft, brand: str) -> list[str]:
    b = _brand_rx(brand)
    out: list[str] = []
    # "Introducing Acme's new spa" is fine (a named new thing); "Introducing Acme" is not.
    meet = re.compile(rf"\b(meet|introducing|welcome to|say hello to)\s+{b}\b(?!['’]s)", re.I)
    is_a = re.compile(rf"(^|[.!?]\s+){b}\s+is\s+(?:a|an|the)\s+(?:[\w-]+\s+){{0,4}}{_INTRO_NOUNS}\b", re.I)
    for field_name, text in (("linkedin", post.linkedin), ("instagram_caption", post.instagram_caption),
                             ("poster_headline", post.poster_headline)):
        t = norm(text)
        hook = norm((text or "").strip().split("\n", 1)[0])
        hit = meet.search(t) or _INTRO_FIXED.search(t) or is_a.search(hook)
        if hit:
            out.append(f"{field_name} reads as a brand introduction ({hit.group(0).strip()!r}); our followers "
                       "already know us. Lead with the specific result, detail, story or answer instead")
    return out


_SELF_VERBS = r"(?:says|said|notes|noted|states|stated|describes|described|claims|claimed|explains|reports|reported)"


def self_reference_problems(post: PostDraft, brand: str) -> list[str]:
    """The brand speaking about itself in the third person ("Acme says...", "Acme's pricing page
    states...") reads like a reporter, not the brand's own account."""
    b = _brand_rx(brand)
    rx = re.compile(rf"\b{b}(?:'s\s+(?:own\s+)?(?:website|site|pricing page|homepage|blog|page|team))?\s+{_SELF_VERBS}\b"
                    rf"|according to {b}\b", re.I)
    out = []
    for field_name, text in (("linkedin", post.linkedin), ("instagram_caption", post.instagram_caption)):
        hit = rx.search(norm(text))
        if hit:
            out.append(f"{field_name} refers to the brand from outside ({hit.group(0)!r}); write as the brand: "
                       "'we', 'our' (keep attribution only for third parties)")
    return out


_FIRST_PERSON = re.compile(r"\b(we|we're|we've|we'll|our|ours|us)\b", re.I)


def normalize_post(post: PostDraft, fact: MinedFact, detail_slides: int = 2, brand_name: str = "") -> PostDraft:
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
    # Written in the first person, a post easily never says the brand's name. A sign-off fixes
    # that without adding any claim (and before the hashtags, which stay last).
    if brand_name and norm(brand_name) not in norm(post.linkedin + " " + post.instagram_caption):
        upd["linkedin"] = _sign_off(post.linkedin, f"— The {brand_name} team")
    return post.model_copy(update=upd) if upd else post


def _sign_off(text: str, line: str) -> str:
    body = text.rstrip()
    m = re.search(r"(\n\s*(?:#\w+\s*)+)$", body)
    if m:
        return body[:m.start()].rstrip() + f"\n\n{line}" + m.group(1)
    return f"{body}\n\n{line}"


def check_post(post: PostDraft, fact: MinedFact, sources: list[Evidence], brand_name: str,
               banned: list[str], detail_slides: int = 2, script: str = "LATIN",
               competitors: list[str] | None = None, language: str = "en") -> list[str]:
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
        problems.append(f"linkedin length is {len(li)} chars; aim for 500-2000 (hard limits 400-3000)")
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
    if brand_name:
        problems += intro_problems(post, brand_name)
        problems += self_reference_problems(post, brand_name)
    # Brand voice: first person plural. Only checkable in English; other languages rely on the
    # prompt and the critic.
    if (language or "en").lower().startswith("en") and not _FIRST_PERSON.search(li):
        problems.append("linkedin is not written as the brand: use 'we'/'our' for the brand's own work "
                        "(e.g. 'At Acme, we...')")
    return problems


def _fmt(nums: set[tuple[float, bool]]) -> list[str]:
    return sorted(f"{v:g}{'%' if p else ''}" for v, p in nums)
