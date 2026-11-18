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
from .config import Settings
from .llm import LLM, LLMError
from .models import (Card, CriticReport, Evidence, MinedFact, MinedFacts, PostDraft,
                     RolloutResult, SkillChoice, TaskPack)
from .verify import GLOBAL_BANNED, check_fact, check_post, norm, normalize_post

log = logging.getLogger("anchor.generate")


class Trajectory:
    def __init__(self, path: Path):
        self.path = path
        self.lines: list[str] = []

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

From the evidence below, select up to {n} distinct, post-worthy facts about {brand}, following
the loaded skill's guidance on what is worth posting for this industry.

Rules for every fact:
- `evidence_ids`: the ids of the items that prove it. Only ids that appear below.
- `quote`: copy ONE full sentence or clause CHARACTER-FOR-CHARACTER from a cited item. It will
  be machine-checked as an exact substring; paraphrase fails.
- `metrics`: numbers exactly as written in the cited items. `named_entities`: partners,
  customers, people, places exactly as written. Leave lists empty rather than guess.
- `headline`: factual, no number or name that is not in the cited items.
- Prefer specific, recent, third-party-confirmed facts over generic marketing claims.
- Never combine facts from different items into a claim neither item makes.

EVIDENCE ({count} items, most specific first):
{evidence}
"""

WRITE_TASK = """STAGE 2 OF 2 -- WRITE THE POSTS FOR ONE FACT

Brand: {brand} ({url})
Today's date: {today}

THE FACT
{fact}

THE ONLY MATERIAL YOU MAY STATE AS FACT (cited evidence, verbatim):
{sources}

Write, following the loaded skill's LinkedIn and Instagram guidance:
- `linkedin`: 600-1800 characters. The first line is the hook (under 200 characters) and must
  work before "see more". Short paragraphs separated by blank lines. Name {brand}. End with a
  specific, non-generic close (no "Thoughts?"). 0-2 emojis. No hashtags or at most 3 at the end.
- `instagram_caption`: 150-1200 characters, opens with a hook line, names {brand}.
- `hashtags`: 3-5, specific to the subject (no #success/#motivation filler).
- `poster_headline` (<= 80 chars) for the COVER slide, `poster_kicker` (<= 48 chars: a neutral topic
  label such as "Customer story", "Dining", "Offer" -- never "Launch"/"New" unless the evidence says
  so), `poster_stat` (optional; ONE number+unit copied from the evidence, else empty).
- `slides`: exactly {n_slides} carousel slides that follow the cover and EXPLAIN it, one idea each
  (e.g. what happened -> how it works / the details -> the proof or who it is for). Each slide has a
  `title` (<= 60 chars) and 2-3 `bullets` (<= 120 chars), every bullet a specific fact from the
  material. Together with the cover they read as one swipeable story.

Every number, name, date, award or superlative you write must appear in the material above.
If the material does not say it, do not say it -- write around the gap instead. In particular:
- Do NOT state benefits, outcomes, scope ("all", "every"), audience impact or reasons the material
  does not state ("reducing overhead", "so teams can..."). Perspective is allowed only as an explicit
  question to the reader or an attributed view ("{brand} says...").
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
Check every factual statement in the posts against the SOURCE EVIDENCE only. A statement is
unsupported if the evidence does not state it, if it exaggerates it (e.g. "leading", "first",
"largest", "award-winning" without the evidence saying so), merges separate facts into a new
claim, or invents a person, quote, number, date, place, price or outcome. Opinions framed as
opinion and generic calls to action are fine. Also flag voice problems that would embarrass the
brand: clichés, hype, emoji spam, engagement bait, or a tone that contradicts the playbook below.
Return empty lists when everything is supported. Do not rewrite the posts."""


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
         batches: range | None = None, known: list[MinedFact] | None = None) -> list[MinedFact]:
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
        task = MINE_TASK.format(brand=pack.brand.name, n=pack.max_posts, count=count, evidence=block)
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


def _same(a: MinedFact, b: MinedFact) -> bool:
    return set(a.evidence_ids) == set(b.evidence_ids) or norm(a.quote) == norm(b.quote)


def rank(facts: list[MinedFact], ev: dict[str, Evidence], n: int) -> list[MinedFact]:
    today = date.today()

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
        return recency + min(len(f.metrics), 3) * 0.8 + min(len(f.named_entities), 3) * 0.6 + third_party + proof

    ordered = sorted(facts, key=value, reverse=True)
    distinct: list[MinedFact] = []
    for f in ordered:
        if all(f.evidence_ids[0] != p.evidence_ids[0] for p in distinct):
            distinct.append(f)
    rest = [f for f in ordered if f not in distinct]
    return (distinct + rest)[:n]


def write_card(idx: int, fact: MinedFact, pack: TaskPack, h: harness_mod.Harness, skills: list[str],
               writer: LLM, critic: LLM, cfg: Settings, traj: Trajectory) -> Card:
    ev = pack.evidence_by_id()
    sources = [ev[i] for i in fact.evidence_ids if i in ev]
    system = h.context(skills)
    banned = GLOBAL_BANNED + h.banned_phrases(skills)
    task = WRITE_TASK.format(
        brand=pack.brand.name, url=pack.brand.url, today=date.today().isoformat(), n_slides=cfg.detail_slides,
        fact=json.dumps(fact.model_dump(), indent=1, ensure_ascii=False),
        sources="\n\n".join(e.render() for e in sources),
    )
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
        draft = normalize_post(draft, fact, cfg.detail_slides)
        problems = check_post(draft, fact, sources, pack.brand.name, banned, cfg.detail_slides)
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
                {**{k: getattr(draft, k) for k in ("linkedin", "instagram_caption", "poster_headline",
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
    facts = mine(pack, system, writer, cfg, traj)
    queue = rank(facts, ev, len(facts))
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
            more = mine(pack, system, writer, cfg, traj, range(next_batch, next_batch + 2), facts)
            next_batch += 2
            facts += more
            queue = rank(more, ev, len(more))
            if not queue:
                continue
        fact = queue.pop(0)
        if cards:
            traj.action(f"backfill: writing next fact ({sum(c.status == 'verified' for c in cards)} verified so far)")
        cards.append(write_card(len(cards) + 1, fact, pack, h, skills, writer, critic, cfg, traj))
    verified_n = sum(c.status == "verified" for c in cards)
    if verified_n < cfg.min_posts:
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


def render_markdown(result: RolloutResult, pack: TaskPack, posters: dict[str, list[str]] | None = None) -> str:
    posters = posters or {}
    lines = [f"# {result.brand} — LinkedIn & Instagram posts", "",
             f"Source site: {pack.url} · Industry playbook: `{result.industry}` · "
             f"Generated {date.today().isoformat()} · {len(result.verified)} verified post(s)", ""]
    if not result.verified:
        lines += ["No post passed verification, so nothing is published. "
                  "See trajectory.md for the reasons each candidate was dropped.", ""]
    for n, card in enumerate(result.verified, 1):
        p, f = card.post, card.fact
        lines += [f"## Post {n} — {f.headline}", "",
                  f"**Category:** {f.category} · **Evidence:** {', '.join(f.evidence_ids)}", ""]
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
        if card.notes:
            lines += ["", "_Style notes from the reviewer (no factual issues):_ " + "; ".join(card.notes)]
        lines += ["", "**Sources**", ""]
        for e in card.sources:
            lines.append(f"- [{e.id}] {e.title or e.kind} — {e.url}" + (f" ({e.date})" if e.date else ""))
        lines += ["", f"> {f.quote}", "", "---", ""]
    return "\n".join(lines)
