"""The executor: one rollout = TaskPack + harness tree -> verified posts.md + trajectory.md.

This is what Harness² runs and re-runs while it refines the harness. Behaviour comes from the
tree (system prompt, guardrails, memory, tool guidance, skills); output contracts and the
deterministic checks come from code. Every decision is logged in the [ACTION]/[OBSERVATION]/
[ERROR] grammar Harness² proposers read to find what to change.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

from . import harness as harness_mod
from . import market, progress
from .config import Settings
from .llm import LLM, LLMError
from .models import (Card, CriticReport, Evidence, MinedFact, MinedFacts, PostDraft,
                     RolloutResult, SkillChoice, Slide, TaskPack)
from .verify import GLOBAL_BANNED, check_fact, check_post, norm, normalize_post, same_topic

log = logging.getLogger("anchor.generate")


class Trajectory:
    def __init__(self, path: Path, append: bool = False):
        self.path = path
        self.lines: list[str] = (path.read_text(encoding="utf-8").splitlines()
                                 if append and path.is_file() else [])

    def _add(self, tag: str, text: str) -> None:
        self.lines.append(f"[{tag}] {text.strip()}")
        self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")

    def action(self, text: str) -> None:
        self._add("ACTION", text)

    def observe(self, text: str) -> None:
        self._add("OBSERVATION", text)

    def error(self, text: str) -> None:
        self._add("ERROR", text)


MINE_TASK = """STAGE 1 OF 2 -- SELECT FACTS FOR {brand}

{brand} will post these on its OWN LinkedIn and Instagram, to people who already follow it. From
the evidence below, select up to {n} distinct facts that would give those followers something
new, following the loaded skill's guidance.

POST TYPES (set `category` to exactly one; use a different type for each fact where the evidence
allows): {post_types}
{already_posted}
Rules for every fact:
- `evidence_ids`: the ids of the items that prove it. Only ids that appear below.
- `quote`: copy ONE full sentence or clause CHARACTER-FOR-CHARACTER from a cited item. It will
  be machine-checked as an exact substring; paraphrase fails.
- `metrics`: numbers exactly as written in the cited items. `named_entities`: partners,
  customers, people, places exactly as written. Leave lists empty rather than guess.
- `headline`: factual, no number or name that is not in the cited items. Not an introduction
  ("Meet...", "X is a platform that...").
- Types that announce something new (Release, Launch, Opening, Collection drop, News) need a
  dated item from the last 18 months; undated site copy is a how-to, spotlight or proof point.
- Prefer specific, recent, third-party-confirmed facts and deeper pages (case studies, blog
  posts, changelogs, press, reviews) over homepage taglines, which followers already know.
- Never pick two facts about the same topic. Never combine facts from different items into a
  claim neither item makes.
{market}
EVIDENCE ({count} items, most specific first):
{evidence}
"""

WRITE_TASK = """STAGE 2 OF 2 -- WRITE THE POSTS FOR ONE FACT

Brand: {brand} ({url}) -- you ARE {brand}, posting on its own channels to existing followers.
Today's date: {today}
Post type: {post_type} (follow the loaded skill's guidance for this type)

THE FACT
{fact}

THE ONLY MATERIAL YOU MAY STATE AS FACT (cited evidence, verbatim):
{sources}

Write as {brand} in the first person ("we", "our"), naming {brand} at least once. Third parties
(press, partners, customers) keep their attribution. Pick ONE register from the system prompt's
Voice section that fits this fact and post type, commit to it across every field, and set
`voice` to its name. Writing as "we" is not a licence to invent our intentions, process or
history: "we built X so that...", "our team designed..." need evidence like any other claim. No introductions: followers already know {brand}; open with the result,
the detail, the story or the answer.

Write, following the loaded skill's LinkedIn and Instagram guidance and the format rules in the
pipeline guidance, entirely in {language} (translate anything the evidence says in another
language; never paste another script):
- `linkedin`: 500-2000 characters; a hook first line under 200 characters; short paragraphs
  separated by blank lines; a specific close; 0-2 emojis; at most 3 hashtags at the end.
- `instagram_caption`: 150-1000 characters; hook, 2-4 short lines with line breaks, one concrete
  detail, a closing line inviting action; 1-3 fitting emojis.
- `hashtags`: 3-5, specific to the subject.
- `poster_headline` (<= 80 chars) for the COVER slide, `poster_kicker` (<= 48 chars: a neutral
  label for the post type such as "Customer story", "How-to", "Dining"; "New"/"Launch" only for
  a dated announcement), `poster_stat` (optional; ONE number+unit copied from the evidence).
- `slides`: exactly {n_slides} carousel slides that follow the cover and EXPLAIN it, one idea each
  (e.g. what happened -> how it works / the details -> the proof or who it is for). Each slide has a
  `title` (<= 60 chars) and 2-3 `bullets` (<= 120 chars), every bullet a specific fact from the
  material. Together with the cover they read as one swipeable story.

{market}
Every number, name, date, award or superlative you write must appear in the material above.
If the material does not say it, do not say it -- write around the gap instead. In particular:
- Do NOT state outcomes, benefits, scope ("all", "every") or results the material does not
  state. Our point of view is welcome when framed as opinion ("We think...", "Our take:") or as a
  question to the reader, and it adds no new fact.
- Do NOT compute new numbers (differences, totals, multiples) from the evidence; quote them as given.
"""

REPAIR_TASK = """Your previous draft failed verification. Fix EVERY problem listed, keep everything
else that was correct, and return the full corrected JSON.

PREVIOUS DRAFT:
{draft}

PROBLEMS (each one is a hard failure):
{problems}

Fix an unsupported claim by deleting it or restating only what the evidence says -- never by
replacing it with a different unsupported claim.
"""

CRITIC_SYSTEM = """You are an independent fact-checker for a brand's social posts. You did not write them.
The posts are written BY the brand on its own channels, in the first person ("we", "our"): the
brand's own pages in the evidence are the brand speaking, so "we built X" is supported when the
brand's page says it built X. Opinions plainly framed as the brand's view ("We think...") are not
factual claims unless they smuggle in a number, name or result.
Check every factual statement in the posts against the SOURCE EVIDENCE only. A statement is
unsupported if the evidence does not state it, if it exaggerates it (e.g. "leading", "first",
"largest", "award-winning" without the evidence saying so), merges separate facts into a new
claim, or invents a person, quote, number, date, place, price or outcome. Opinions framed as
opinion, generic calls to action, and faithful translations of the evidence are fine.

The writer picked a register (`voice`) for this fact. Energy, rhythm, vivid verbs, a single
exclamation mark or a fitting emoji are NOT problems when they suit that voice -- judge the tone
against the voice and the playbook, not against a neutral press-release style. Flag as voice
problems only what would embarrass the brand: clichés, unsupported hype words, emoji spam,
engagement bait, a flat or generic opening line, a post that merely introduces the brand or
explains what it does (its followers already know), the brand described in the third person
("Acme says..."), or a register that clearly mismatches the fact (e.g. jokey about a compliance
credential). Return empty lists when everything is
supported. Do not rewrite the posts."""


_LANGUAGE = {"LATIN": "English (or, if the brand's own site is in another Latin-script language, that language)",
             "CJK": "the language of the brand's own website (Japanese or Chinese)", "HANGUL": "Korean",
             "CYRILLIC": "the brand's own Cyrillic-script language", "ARABIC": "Arabic",
             "DEVANAGARI": "Hindi", "THAI": "Thai", "HEBREW": "Hebrew", "GREEK": "Greek"}


def market_block(pack: TaskPack, stage: str) -> str:
    """Competitor and search-demand context (DataForSEO) for one stage; "" when there is none.
    It is framed as context, never as material: nothing in it may be stated or cited."""
    m = pack.market
    if not m or not (m.competitors or m.brand_keywords or m.gap_keywords):
        return ""
    b = pack.brand.name
    rivals = ", ".join(c.domain for c in m.competitors[:6]) or "unknown"
    demand = "; ".join(f"{k.keyword} ({k.search_volume:,}/mo)" for k in m.brand_keywords[:10])
    gaps = "; ".join(f"{k.keyword} ({k.search_volume:,}/mo, {k.competitor})" for k in m.gap_keywords[:8])
    lines = [f"\nMARKET CONTEXT (from search data; NOT evidence -- never cite, quote or state it):",
             f"- Competitors for the same audience: {rivals}."]
    if demand:
        lines.append(f"- What this audience searches for: {demand}.")
    if gaps:
        lines.append(f"- Topics competitors win in search and {b} does not yet: {gaps}.")
    qs = "; ".join(k.keyword for k in market.questions(m)[:8])
    if qs:
        lines.append(f"- Questions this audience searches for (an Answer post fits when the evidence answers one): {qs}.")
    if stage == "mine":
        lines.append(f"Use it to CHOOSE: prefer facts that show what sets {b} apart from these competitors "
                     "and facts that answer what this audience searches for, or fill a gap topic. A fact "
                     "still needs its own evidence; the context never makes an unsupported fact eligible.")
    else:
        lines.append(f"Use it to ANGLE and WORD the posts: frame the fact around what distinguishes {b} and "
                     "the problem the audience searches about; reuse the audience's own search terms in "
                     "the hook, slides and hashtags where the evidence supports them. Never name, link, "
                     "or compare to a competitor (a comparison is an unsupported claim), and never state "
                     "search volumes or rankings.")
    return "\n".join(lines) + "\n"


def choose_skills(h: harness_mod.Harness, pack: TaskPack, llm: LLM, traj: Trajectory) -> list[str]:
    chosen = [pack.industry] if pack.industry in h.skills else []
    extra = {n: s for n, s in h.skills.items() if not s.meta.get("industry")}
    if extra:
        menu = "\n".join(f"- {n}: {s.description}" for n, s in extra.items())
        traj.action(f"select optional skills from: {sorted(extra)}")
        try:
            pick = llm.json(
                h.context([]),
                f"Brand: {pack.brand.name} ({pack.industry}). {pack.brand.description}\n\n"
                f"Optional skills:\n{menu}\n\nList the names of the skills whose trigger applies to "
                "this brand and task (writing evidence-grounded LinkedIn and Instagram posts). "
                "Return an empty list if none apply.",
                SkillChoice, temperature=0.0)
            lookup = {n.lower(): n for n in extra}
            chosen += [lookup[s.strip().lower()] for s in pick.skills
                       if s.strip().lower() in lookup and lookup[s.strip().lower()] not in chosen]
        except LLMError as exc:
            traj.error(f"optional skill selection failed: {exc}")
    traj.observe(f"skills loaded: {chosen or 'none'}")
    return chosen


def post_types(h: harness_mod.Harness, skills: list[str]) -> list[str]:
    out: list[str] = []
    for name in skills:
        if name in h.skills:
            out += [t for t in h.skills[name].list_meta("post_types") if t not in out]
    return out or ["Customer story", "Feature how-to", "Proof point", "Release", "Partnership", "Our take"]


def _already_posted(pack: TaskPack) -> str:
    if not pack.already_posted:
        return ""
    return ("\nALREADY POSTED in earlier runs (do not pick these again, nor another fact on the same topic):\n"
            + "\n".join(f"- {h}" for h in pack.already_posted[:25]) + "\n")


def _batches(pack: TaskPack, size: int, limit: int) -> list[str]:
    """Most-specific-first evidence, split into prompt-sized batches."""
    batches, cur, used = [], [], 0
    for e in pack.evidence:
        line = e.render()
        if cur and used + len(line) > size:
            batches.append(cur)
            cur, used = [], 0
            if len(batches) == limit:
                break
        cur.append(line)
        used += len(line) + 2
    if cur and len(batches) < limit:
        batches.append(cur)
    return ["\n\n".join(b) for b in batches]


def mine(pack: TaskPack, system: str, llm: LLM, cfg: Settings, traj: Trajectory,
         batches: range | None = None, known: list[MinedFact] | None = None,
         types: list[str] | None = None) -> list[MinedFact]:
    ev = pack.evidence_by_id()
    want = pack.max_posts * 2
    good: list[MinedFact] = list(known or [])
    all_batches = _batches(pack, cfg.evidence_prompt_chars, 99)
    batches = batches or range(min(cfg.mine_batches, len(all_batches)))
    for b_idx in batches:
        if b_idx >= len(all_batches):
            break
        block = all_batches[b_idx]
        b_idx += 1
        count = block.count("\n\n[E") + 1
        task = MINE_TASK.format(brand=pack.brand.name, n=pack.max_posts, count=count, evidence=block,
                                market=market_block(pack, "mine"), post_types=", ".join(types or post_types_default()),
                                already_posted=_already_posted(pack))
        traj.action(f"mine batch {b_idx}: up to {pack.max_posts} facts from {count} evidence items")
        feedback = ""
        for round_no in (1, 2):
            try:
                got = llm.json(system, task + feedback, MinedFacts, temperature=0.3)
            except LLMError as exc:
                traj.error(f"fact mining batch {b_idx} failed: {exc}")
                break
            rejected = []
            for f in got.facts:
                problems = check_fact(f, ev, pack.brand.name)
                if not problems and any(same_topic(_topic(f), h) for h in pack.already_posted):
                    problems = ["already posted in an earlier run (same topic); pick a different fact"]
                if problems:
                    rejected.append((f, problems))
                    traj.observe(f"REJECTED fact {f.headline!r}: " + "; ".join(problems))
                elif not any(_same(f, g) for g in good):
                    good.append(f)
                    traj.observe(f"accepted fact {f.headline!r} cites {f.evidence_ids}")
            if not rejected or len(good) >= want or round_no == 2:
                break
            feedback = (
                "\n\nYOUR PREVIOUS SELECTION HAD FAILURES. Already accepted (do not repeat): "
                + json.dumps([g.headline for g in good])
                + "\nRejected, with reasons:\n"
                + "\n".join(f"- {f.headline}: {'; '.join(p)}" for f, p in rejected)
                + "\nReturn NEW or CORRECTED facts only."
            )
            traj.action(f"mining batch {b_idx} repair: {len(rejected)} facts failed checks")
        if len(good) >= want:
            break
    return good[len(known or []):]


def post_types_default() -> list[str]:
    return ["Customer story", "Feature how-to", "Proof point", "Release", "Partnership", "Our take"]


def _topic(f: MinedFact) -> str:
    return f"{f.headline} {f.quote}"


def _same(a: MinedFact, b: MinedFact) -> bool:
    """Same fact or same topic: never two posts about the same news in one set."""
    return (set(a.evidence_ids) == set(b.evidence_ids) or norm(a.quote) == norm(b.quote)
            or same_topic(a.headline, b.headline) or same_topic(_topic(a), _topic(b), 0.6))


def rank(facts: list[MinedFact], ev: dict[str, Evidence], n: int,
         terms: dict[str, float] | None = None, home_url: str = "") -> list[MinedFact]:
    """Recency, specificity and third-party proof; with market context, plus up to +1.5 for a
    fact about what the audience searches for (weighted by search volume). Homepage hero copy
    ranks lower (followers already know it). The order is then picked greedily so the first
    posts use different post types and never repeat a topic."""
    today = date.today()
    terms = terms or {}
    home = (home_url or "").rstrip("/")

    def demand(f: MinedFact) -> float:
        if not terms:
            return 0.0
        words = set(re.findall(r"[a-z0-9][a-z0-9+#.-]{2,}", norm(f"{f.headline} {f.quote} {f.category}")))
        return min(sum(w for t, w in terms.items() if t in words), 1.5)

    def value(f: MinedFact) -> float:
        cited = [ev[i] for i in f.evidence_ids if i in ev]
        dates = [date.fromisoformat(e.date) for e in cited if e.date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.date)]
        if dates:
            age = (today - max(dates)).days
            recency = 3.0 if age <= 365 else 2.0 if age <= 730 else 1.0
        else:
            recency = 0.8
        third_party = 1.2 if any(e.kind == "article" for e in cited) else 0.0
        proof = 0.6 if any(e.kind in ("testimonial", "structured") for e in cited) else 0.0
        hero = -1.0 if home and cited and all(e.kind == "site" and e.url.rstrip("/") == home for e in cited) else 0.0
        return (recency + min(len(f.metrics), 3) * 0.8 + min(len(f.named_entities), 3) * 0.6 + third_party
                + proof + demand(f) + hero)

    pool = sorted(facts, key=value, reverse=True)
    ordered: list[MinedFact] = []
    while pool:
        used = {norm(f.category) for f in ordered}
        sources = {f.evidence_ids[0] for f in ordered if f.evidence_ids}
        best = max(pool, key=lambda f: value(f) - (1.5 if norm(f.category) in used else 0.0)
                   - (1.0 if f.evidence_ids and f.evidence_ids[0] in sources else 0.0))
        pool.remove(best)
        if not any(_same(best, g) for g in ordered):
            ordered.append(best)
    return ordered[:n]


def write_card(idx: int, fact: MinedFact, pack: TaskPack, h: harness_mod.Harness, skills: list[str],
               writer: LLM, critic: LLM, cfg: Settings, traj: Trajectory) -> Card:
    ev = pack.evidence_by_id()
    sources = [ev[i] for i in fact.evidence_ids if i in ev]
    system = h.context(skills)
    banned = GLOBAL_BANNED + h.banned_phrases(skills)
    task = WRITE_TASK.format(
        brand=pack.brand.name, url=pack.brand.url, today=date.today().isoformat(), n_slides=cfg.detail_slides,
        language=_LANGUAGE.get(pack.script, f"the language of {pack.brand.name}'s own website"),
        fact=json.dumps(fact.model_dump(), indent=1, ensure_ascii=False),
        sources="\n\n".join(e.render() for e in sources), market=market_block(pack, "write"),
        post_type=fact.category or "Spotlight",
    )
    rivals = market.competitor_names(pack.market)
    skill_text = "\n\n".join(h.skills[s].body for s in skills if s in h.skills)
    card = Card(id=f"post_{idx}", status="rejected", fact=fact, sources=sources)
    draft: PostDraft | None = None
    problems: list[str] = []
    soft: list[str] = []
    last = cfg.repair_rounds
    for attempt in range(cfg.repair_rounds + 1):
        card.attempts = attempt + 1
        try:
            if draft is None:
                traj.action(f"post {idx}: write LinkedIn + Instagram for {fact.headline!r}")
                draft = writer.json(system, task, PostDraft, temperature=0.7)
            else:
                traj.action(f"post {idx}: repair attempt {attempt} for {len(problems)} problems")
                draft = writer.json(system, task + "\n\n" + REPAIR_TASK.format(
                    draft=draft.model_dump_json(indent=1), problems="\n".join(f"- {p}" for p in problems)),
                    PostDraft, temperature=0.4)
        except LLMError as exc:
            traj.error(f"post {idx}: writer failed: {exc}")
            problems = [f"writer failed: {exc}"]
            break
        draft = normalize_post(draft, fact, cfg.detail_slides, pack.brand.name)
        problems = check_post(draft, fact, sources, pack.brand.name, banned, cfg.detail_slides, pack.script,
                              competitors=rivals, language=pack.language)
        soft = []
        if not problems:
            problems, soft = _critic(draft, sources, skill_text, critic, idx, traj)
        else:
            traj.observe(f"post {idx}: deterministic checks failed: " + "; ".join(problems))
        if not problems and (not soft or attempt == last):
            card.status = "verified"
            card.notes = soft
            traj.observe(f"post {idx}: VERIFIED after {card.attempts} attempt(s)"
                         + (f" (style notes kept: {len(soft)})" if soft else ""))
            break
        problems = problems + soft
    card.post = draft
    card.problems = problems
    if card.status != "verified":
        traj.observe(f"post {idx}: DROPPED, unresolved: " + "; ".join(problems))
    return card


def _critic(draft: PostDraft, sources: list[Evidence], skill_text: str, critic: LLM, idx: int,
            traj: Trajectory) -> tuple[list[str], list[str]]:
    """(hard, soft): unsupported claims block publication; voice remarks are repaired, and if
    only they remain after the last repair the post ships with them recorded as notes."""
    try:
        report = critic.json(
            CRITIC_SYSTEM + ("\n\nPLAYBOOK:\n" + skill_text[:6000] if skill_text else ""),
            "SOURCE EVIDENCE:\n" + "\n\n".join(e.render() for e in sources)
            + "\n\nPOSTS TO CHECK:\n" + json.dumps(
                {**{k: getattr(draft, k) for k in ("voice", "linkedin", "instagram_caption", "poster_headline",
                                                    "poster_kicker", "poster_stat")},
                 "carousel_slides": [s.model_dump() for s in draft.slides]}, indent=1, ensure_ascii=False),
            CriticReport, temperature=0.0)
    except LLMError as exc:
        traj.error(f"post {idx}: independent claim check could not run: {exc}")
        return [f"independent claim check could not run: {exc}"], []
    hard = [f"unsupported claim: {i.text!r} ({i.problem})" for i in report.unsupported_claims]
    soft = [f"voice: {i.text!r} ({i.problem})" for i in report.voice_problems]
    if hard or soft:
        traj.observe(f"post {idx}: critic flagged: " + "; ".join(hard + soft))
    return hard, soft


def generate(pack: TaskPack, harness_dir: Path, out_dir: Path, cfg: Settings) -> RolloutResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    traj = Trajectory(out_dir / "trajectory.md")
    traj.action(f"start rollout for {pack.brand.name} ({pack.url}); industry={pack.industry}; "
                f"{len(pack.evidence)} evidence items; harness={harness_dir.name}")
    h = harness_mod.load(harness_dir)
    writer = LLM(cfg.model, cfg=cfg)
    critic = LLM(cfg.critic_model, cfg=cfg)
    skills = choose_skills(h, pack, writer, traj)
    system = h.context(skills)
    ev = pack.evidence_by_id()
    terms = market.keyword_terms(pack.market)
    if pack.market:
        m = pack.market
        traj.observe(f"market context (DataForSEO, not evidence): competitors {[c.domain for c in m.competitors]}; "
                     f"top searches {[k.keyword for k in m.brand_keywords[:6]]}; "
                     f"gap topics {[k.keyword for k in m.gap_keywords[:6]]}")
    types = post_types(h, skills)
    if pack.already_posted:
        traj.observe(f"{len(pack.already_posted)} headlines already posted for this brand in earlier runs; "
                     "they are excluded")
    facts = mine(pack, system, writer, cfg, traj, types=types)
    queue = rank(facts, ev, len(facts), terms, pack.url)
    traj.observe(f"{len(facts)} facts passed checks; target {pack.max_posts} posts (minimum {cfg.min_posts}); "
                 f"order: {[f.headline for f in queue]}")
    cards: list[Card] = []
    next_batch = cfg.mine_batches
    total_batches = len(_batches(pack, cfg.evidence_prompt_chars, 99))
    budget = pack.max_posts + cfg.max_extra_posts  # max posts attempted per rollout: bounds cost
    while sum(c.status == "verified" for c in cards) < pack.max_posts and len(cards) < budget:
        if not queue:
            if sum(c.status == "verified" for c in cards) >= cfg.min_posts or next_batch >= total_batches:
                break
            traj.action(f"backfill: only {sum(c.status == 'verified' for c in cards)} verified; mining more evidence")
            more = mine(pack, system, writer, cfg, traj, range(next_batch, next_batch + 2), facts, types)
            next_batch += 2
            facts += more
            queue = rank(more, ev, len(more), terms, pack.url)
            if not queue:
                continue
        fact = queue.pop(0)
        if cards:
            traj.action(f"backfill: writing next fact ({sum(c.status == 'verified' for c in cards)} verified so far)")
        progress.report("writing", post=len(cards) + 1, target=pack.max_posts, headline=fact.headline,
                        verified=sum(c.status == "verified" for c in cards), facts=len(facts))
        cards.append(write_card(len(cards) + 1, fact, pack, h, skills, writer, critic, cfg, traj))
    verified_n = sum(c.status == "verified" for c in cards)
    if verified_n < min(cfg.min_posts, pack.max_posts):
        traj.observe(f"only {verified_n} post(s) could be grounded (minimum {cfg.min_posts}); the evidence "
                     "pack does not support more without inventing details")
    result = RolloutResult(task_id=pack.task_id, brand=pack.brand.name, industry=pack.industry,
                           skills_loaded=skills, cards=cards)
    (out_dir / "cards.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "posts.md").write_text(render_markdown(result, pack), encoding="utf-8")
    traj.observe(f"done: {len(result.verified)}/{len(cards)} posts verified; LLM calls: "
                 f"writer={writer.calls} critic={critic.calls}")
    (out_dir / "DONE").write_text("ok", encoding="utf-8")
    return result


FALLBACK_NOTE = ("Fallback post: no candidate passed every verification check, so this one is "
                 "delivered so the run is not empty. Review it before publishing.")


def ensure_post(result: RolloutResult, pack: TaskPack, harness_dir: Path, cfg: Settings,
                traj: Trajectory) -> RolloutResult:
    """Guarantee at least one deliverable post. A run that ends with zero posts is a dead end
    for the user, so when nothing verified:
      1. the rejected draft with the fewest problems is delivered, flagged as a fallback;
      2. otherwise a brand-introduction post is written from the most specific evidence
         (it may even pass verification);
      3. if the model cannot write at all, a plain template post is built from the brand kit.
    Fallback posts carry `fallback=True` and a note telling the reader to review them."""
    if result.verified:
        return result
    drafted = [c for c in result.cards if c.post is not None]
    if drafted:
        card = min(drafted, key=lambda c: len(c.problems))
        _mark_fallback(card)
        traj.observe(f"no verified post; delivering {card.id} as a fallback ({len(card.problems)} unresolved problems)")
        return result
    fact = _intro_fact(pack)
    card: Card | None = None
    try:
        h = harness_mod.load(harness_dir)
        card = write_card(len(result.cards) + 1, fact, pack, h, [pack.industry] if pack.industry in h.skills else [],
                          LLM(cfg.model, cfg=cfg), LLM(cfg.critic_model, cfg=cfg), cfg, traj)
    except Exception as exc:  # harness unreadable, model unreachable...: fall through to template
        log.warning("[fallback] intro post could not be written: %s", exc)
    if card is None or card.post is None:
        card = Card(id=f"post_{len(result.cards) + 1}", status="rejected", fact=fact,
                    sources=[e for e in pack.evidence if e.id in fact.evidence_ids],
                    post=_template_post(pack, fact, cfg.detail_slides),
                    problems=["written from a template: the model could not produce a post"])
    if card.status != "verified":
        _mark_fallback(card)
    traj.observe(f"no verified post from mined facts; delivered brand intro {card.id} "
                 f"({'verified' if not card.fallback else 'fallback'})")
    result.cards.append(card)
    return result


def _mark_fallback(card: Card) -> None:
    card.status = "verified"  # deliverable: rendered, saved and shown like any other post
    card.fallback = True
    card.notes = [FALLBACK_NOTE] + [f"unconfirmed: {p}" for p in card.problems[:5]]


def _intro_fact(pack: TaskPack) -> MinedFact:
    """Last-resort fact: the most specific item the brand published itself (not a homepage
    tagline), posted as a spotlight on that detail rather than an introduction."""
    from .extract import informativeness

    b = pack.brand
    home = b.url.rstrip("/")
    own = [e for e in pack.evidence if e.kind != "article"] or list(pack.evidence)
    own.sort(key=lambda e: (e.url.rstrip("/") != home, informativeness(e.text)), reverse=True)
    cited = own[:1]
    first = cited[0].text if cited else (b.description or b.tagline or b.name)
    quote = re.split(r"(?<=[.!?])\s+", first.strip())[0][:300]
    title = (cited[0].title if cited else "") or b.tagline or b.name
    headline = re.split(r"\s[|\-–—:·]\s", title)[0].strip() or b.name
    return MinedFact(headline=headline[:90], category="Spotlight",
                     evidence_ids=[e.id for e in cited], quote=quote,
                     why_it_matters=(b.description or f"A detail from {b.name}'s own pages.")[:300])


def _template_post(pack: TaskPack, fact: MinedFact, n_slides: int) -> PostDraft:
    """Deterministic last resort: only the brand's own words, no claims added, no introduction."""
    b = pack.brand
    cited = [e for e in pack.evidence if e.id in fact.evidence_ids] or pack.evidence[:1]
    body = (cited[0].text if cited else (b.description or fact.quote or b.tagline)).strip()
    tag = "#" + re.sub(r"[^0-9A-Za-z]+", "", b.name)[:30] if re.sub(r"[^0-9A-Za-z]+", "", b.name) else ""
    hashtags = [t for t in (tag,) if t]
    lines = [s for s in re.split(r"(?<=[.!?])\s+", " ".join(e.text for e in cited + pack.evidence[:3])) if 20 <= len(s) <= 120]
    bullets = list(dict.fromkeys(lines))[: 2 * n_slides] or [body[:120]]
    slides = [Slide(title=(fact.headline if i == 0 else f"More from {b.name}")[:60],
                    bullets=bullets[i * 2:(i + 1) * 2] or bullets[:1]) for i in range(n_slides)]
    more = f"\n\nMore on our site: {cited[0].url if cited else b.url}"
    return PostDraft(
        voice="insightful",
        linkedin=f"{fact.headline}\n\n{body[:1500]}{more}" + (f"\n\n{tag}" if tag else ""),
        instagram_caption=f"{fact.headline}\n\n{body[:600]}\n\nMore at {b.domain}.",
        hashtags=hashtags, poster_headline=fact.headline[:80], poster_kicker="Spotlight",
        poster_stat="", slides=slides,
    )


def render_markdown(result: RolloutResult, pack: TaskPack, posters: dict[str, list[str]] | None = None) -> str:
    posters = posters or {}
    lines = [f"# {result.brand} — LinkedIn & Instagram posts", "",
             f"Source site: {pack.url} · Industry playbook: `{result.industry}` · "
             f"Generated {date.today().isoformat()} · {sum(not c.fallback for c in result.verified)} verified post(s)"
             + (f" + {sum(c.fallback for c in result.verified)} fallback post(s)" if any(c.fallback for c in result.verified) else ""), ""]
    if not result.verified:
        lines += ["No post passed verification, so nothing is published. "
                  "See trajectory.md for the reasons each candidate was dropped.", ""]
    for n, card in enumerate(result.verified, 1):
        p, f = card.post, card.fact
        lines += [f"## Post {n} — {f.headline}", "",
                  f"**Category:** {f.category} · " + (f"**Voice:** {p.voice} · " if p.voice else "")
                  + f"**Evidence:** {', '.join(f.evidence_ids)}", ""]
        files = posters.get(card.id, [])
        if files:
            pngs = [f for f in files if f.endswith(".png")]
            lines += [" ".join(f"![slide {i}]({f})" for i, f in enumerate(pngs, 1)), "",
                      f"Carousel: {len(pngs)} slides (Instagram: upload the PNGs in order; "
                      f"LinkedIn: upload `{files[-1]}` as a document).", ""]
        lines += ["### LinkedIn", "", p.linkedin.strip(), "", "### Instagram", "", p.instagram_caption.strip(), ""]
        tags = " ".join(t if t.startswith("#") else f"#{t}" for t in p.hashtags)
        if tags and tags not in p.instagram_caption:
            lines += [tags, ""]
        lines += ["### Carousel", "", f"1. **{p.poster_headline}** ({p.poster_kicker}"
                  + (f", {p.poster_stat}" if p.poster_stat else "") + ")"]
        for i, sl in enumerate(p.slides, 2):
            lines.append(f"{i}. **{sl.title}**")
            lines += [f"   - {b}" for b in sl.bullets]
        if card.fallback:
            lines += ["", "> **Not fully verified.** " + "; ".join(card.notes)]
        elif card.notes:
            lines += ["", "_Style notes from the reviewer (no factual issues):_ " + "; ".join(card.notes)]
        lines += ["", "**Sources**", ""]
        for e in card.sources:
            lines.append(f"- [{e.id}] {e.title or e.kind} — {e.url}" + (f" ({e.date})" if e.date else ""))
        lines += ["", f"> {f.quote}", "", "---", ""]
    return "\n".join(lines)
