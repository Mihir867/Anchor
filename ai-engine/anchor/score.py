"""Quality score for one rollout's post set: the signal Harness² adoption is gated on.

Grounding is already enforced (only verified posts are delivered), so this measures what the
grounding checks cannot: would the brand's EXISTING followers get something new and specific
from these posts, in the brand's own voice, with a hook that works on the channel?

    score = sum over delivered posts of quality (0..1)
            + 0.15 per distinct post type beyond the first
            - 0.5 per repeated topic

Quality per post = the independent judge's rubric mean (1-5 -> 0..1) minus 0.3 per deterministic
issue (introduction pattern, brand in the third person, no first person). Fallback posts count
0.1. When the judge cannot run, each clean post counts 0.6 so a score still exists.
The result is cached in <rollout>/score.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from .config import Settings
from .llm import LLM, LLMError
from .models import RolloutResult, TaskPack
from .verify import _FIRST_PERSON, intro_problems, norm, same_topic, self_reference_problems

log = logging.getLogger("anchor.score")

JUDGE_SYSTEM = """You review a brand's social posts before they go out on the brand's OWN LinkedIn
page and Instagram account, to people who ALREADY follow the brand. Facts were checked
separately; do not re-check them. Score each post 1-5 on:
- specificity: concrete numbers, names, details (5) vs generic claims anyone could make (1)
- new_to_followers: tells existing followers something they did not know (5) vs introduces the
  brand or restates what it does (1)
- hook: the first line makes a follower stop and read (5) vs throat-clearing or flat (1)
- brand_voice: written as the brand ("we", "our") with a clear point of view (5) vs a reporter
  describing the company from outside (1)
- channel_fit: LinkedIn reads like an operator talking to peers and Instagram like the brand at
  its most human (5) vs the same press-release text twice (1)
Be strict: 3 is acceptable, 5 is rare."""


class PostRubric(BaseModel):
    post_id: str
    specificity: int = Field(ge=1, le=5)
    new_to_followers: int = Field(ge=1, le=5)
    hook: int = Field(ge=1, le=5)
    brand_voice: int = Field(ge=1, le=5)
    channel_fit: int = Field(ge=1, le=5)
    note: str = ""


class SetRubric(BaseModel):
    posts: list[PostRubric] = Field(default_factory=list)


def deterministic_issues(card, brand: str, language: str = "en") -> list[str]:
    p = card.post
    if p is None:
        return ["no post"]
    issues = intro_problems(p, brand) + self_reference_problems(p, brand)
    if (language or "en").startswith("en") and not _FIRST_PERSON.search(p.linkedin):
        issues.append("not written in the brand's first person")
    return issues


def score_result(result: RolloutResult, pack: TaskPack, cfg: Settings, judge: LLM | None = None) -> dict:
    delivered = [c for c in result.cards if c.status == "verified" and c.post is not None]
    rubric: dict[str, PostRubric] = {}
    judged = False
    real = [c for c in delivered if not c.fallback]
    if real:
        try:
            out = (judge or LLM(cfg.critic_model, cfg=cfg)).json(
                JUDGE_SYSTEM,
                f"Brand: {pack.brand.name} ({pack.industry}).\n\nPOSTS:\n" + json.dumps(
                    [{"post_id": c.id, "post_type": c.fact.category, "linkedin": c.post.linkedin,
                      "instagram_caption": c.post.instagram_caption, "poster_headline": c.post.poster_headline}
                     for c in real], indent=1, ensure_ascii=False)
                + "\n\nReturn one rubric entry per post_id.",
                SetRubric, temperature=0.0)
            rubric = {r.post_id: r for r in out.posts}
            judged = bool(rubric)
        except LLMError as exc:
            log.warning("[score] judge unavailable, deterministic score only: %s", exc)

    posts, total = [], 0.0
    for c in delivered:
        issues = deterministic_issues(c, pack.brand.name, pack.language)
        r = rubric.get(c.id)
        if c.fallback:
            q = 0.1
        elif r:
            q = (r.specificity + r.new_to_followers + r.hook + r.brand_voice + r.channel_fit - 5) / 20
        else:
            q = 0.6
        q = max(0.0, q - 0.3 * len(issues))
        total += q
        posts.append({"id": c.id, "type": c.fact.category, "quality": round(q, 3), "issues": issues,
                      "rubric": r.model_dump() if r else None})
    types = {norm(c.fact.category) for c in delivered if not c.fallback}
    repeats = sum(1 for i, a in enumerate(delivered) for b in delivered[i + 1:]
                  if same_topic(a.fact.headline, b.fact.headline))
    total += 0.15 * max(0, len(types) - 1) - 0.5 * repeats
    return {"score": round(total, 3), "judged": judged, "posts": posts, "distinct_types": len(types),
            "repeated_topics": repeats}


def score_rollout(run_dir: Path, pack: TaskPack, cfg: Settings, judge: LLM | None = None) -> dict:
    run_dir = Path(run_dir)
    cached = run_dir / "score.json"
    if cached.is_file():
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except ValueError:
            pass
    cards = run_dir / "cards.json"
    if not cards.is_file():
        return {"score": 0.0, "judged": False, "posts": [], "missing": True}
    result = RolloutResult.model_validate_json(cards.read_text(encoding="utf-8"))
    out = score_result(result, pack, cfg, judge)
    cached.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out
