"""Top-level orchestration: prepare -> (generate | Harness² refine) -> finalize."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from . import generate, history, market, progress, render
from .config import Settings, settings
from . import harness as harness_mod
from .llm import LLM, model_status, reset_usage, usage_snapshot
from .models import RolloutResult
from .prepare import prepare
from .verify import age_days

log = logging.getLogger("anchor.pipeline")


def run(url: str, *, mode: str = "refine", k: int = 1, max_posts: int = 3, industry: str | None = None,
        cfg: Settings | None = None) -> dict:
    """mode="fast": one rollout with the base harness.
    mode="refine": Harness² Propose-Probe-Compose (4k rollouts) with per-industry learning."""
    cfg = cfg or settings()
    models = model_status(cfg)
    if not models["ok"]:
        # A config error, not a bad brand: fail the job instead of delivering template posts.
        raise RuntimeError("no LLM endpoint for the writer/critic: set "
                           + (", ".join(models["missing_keys"]) or "the provider API keys")
                           + " in this service's environment (see README, Models and endpoints)")
    reset_usage()
    market.reset_cost()
    skipped = ""
    if mode == "refine":
        skipped = refine_blocker(cfg)
        if skipped:
            log.warning("[pipeline] %s", skipped)
            mode = "fast"
    pack, run_dir = prepare(url, cfg, max_posts=max_posts, industry=industry)
    if mode == "refine" and pack.thin:
        # Rollouts on this little evidence all score ~0, so no edit can beat the base: refining
        # would cost ~4x the tokens and return the base harness anyway.
        skipped = (f"Harness² refine skipped: thin evidence pack ({pack.thin_reason}). Ran one "
                   "base-harness rollout for a single post instead.")
        log.warning("[pipeline] %s", skipped)
        mode = "fast"
    stages_note = skipped
    fell_back = False
    if mode == "fast":
        chosen = run_dir / "rollout"
        harness_used = learned_harness(cfg, pack.industry)
        if harness_used != cfg.harness_dir:
            stages_note = (stages_note + "\n\n" if stages_note else "") + (
                f"Used the harness Harness² adopted most recently for `{pack.industry}`: {harness_used}")
        generate.generate(pack, harness_used, chosen, cfg)
    elif mode == "refine":
        from .h2.refine import refine

        outcome = refine(pack, run_dir, cfg, k=k)
        chosen, harness_used = outcome.chosen_run_dir, outcome.harness_dir
        stages_note, fell_back = outcome.notes, outcome.fell_back_to_base
    else:
        raise ValueError(f"unknown mode {mode!r}; use 'fast' or 'refine'")
    return finalize(pack, run_dir, chosen, harness_used, cfg, mode=mode, stages_note=stages_note,
                    fell_back=fell_back)


def learned_harness(cfg: Settings, industry: str) -> Path:
    """The harness Harness² most recently PROMOTED for this industry (it beat the base harness
    on the quality score; see h2.refine.GatedLibrary), if still valid; otherwise the base harness.
    Library entries without a PROMOTED.json (stored before scoring existed) are never used."""
    root = cfg.library_dir / "agg" / industry / "harnesses"
    promoted = []
    for entry in (root.iterdir() if root.is_dir() else []):
        rec = entry / "PROMOTED.json"
        if rec.is_file() and (entry / "harness").is_dir():
            try:
                promoted.append((json.loads(rec.read_text(encoding="utf-8")).get("promoted_at", ""), entry / "harness"))
            except ValueError:
                continue
    for _, cand in sorted(promoted, reverse=True):
        if not harness_mod.problems(cand) and industry in harness_mod.load(cand).skills:
            return cand
    return cfg.harness_dir


def refine_blocker(cfg: Settings) -> str:
    """Why Harness² refinement cannot run on this endpoint, or "" if it can.

    One improver call carries the Harness² method prompt (~4k tokens) plus the harness,
    trajectories and evidence. On a tier whose per-minute token limit is below that, every
    improver call is rejected, so we say so up front instead of spending rollouts on it."""
    limit = LLM(cfg.proposer_model, cfg=cfg).token_limit()
    if limit == 0:
        return (f"Harness² refine skipped: the daily token quota for {cfg.proposer_model} is used up. "
                "Ran one base-harness rollout instead. Point ANCHOR_PROPOSER_MODEL at a provider with "
                "quota left (see README, Models and endpoints), or retry after the quota resets.")
    if limit is not None and limit < cfg.refine_min_tpm:
        return (f"Harness² refine skipped: {cfg.proposer_model} allows {limit:,} "
                f"tokens/minute, and one improver call needs about {cfg.refine_min_tpm:,}. Ran one "
                "base-harness rollout instead. Set ANCHOR_PROPOSER_MODEL to a higher-limit provider "
                "(paid Groq tier, Cerebras, OpenRouter, or local ollama:...) to enable refinement.")
    return ""


def finalize(pack, run_dir: Path, chosen: Path, harness_used: Path, cfg: Settings, *, mode: str,
             stages_note: str = "", fell_back: bool = False) -> dict:
    result = RolloutResult.model_validate_json((chosen / "cards.json").read_text(encoding="utf-8"))
    out = run_dir / "output"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(chosen / "trajectory.md", out / "trajectory.md")
    # Never finish a run with zero posts: deliver the best draft or a brand intro, flagged.
    result = generate.ensure_post(result, pack, harness_used, cfg,
                                  generate.Trajectory(out / "trajectory.md", append=True))
    progress.report("rendering", verified=len(result.verified))
    posters = render.render_all(result.verified, pack, out, cfg)
    for card in result.verified:
        names = posters[card.id]
        card.poster_path = str(out / names[0])
        card.slide_paths = [str(out / n) for n in names if n.endswith(".png")]
        card.pdf_path = str(out / names[-1])
    (out / "posts.md").write_text(generate.render_markdown(result, pack, posters), encoding="utf-8")
    (out / "deck.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    if Path(harness_used).is_dir():
        shutil.copytree(harness_used, out / "harness", dirs_exist_ok=True)
    rejected = [c for c in result.cards if c.status != "verified"]
    fallback_n = sum(c.fallback for c in result.verified)
    verified_n = len(result.verified) - fallback_n
    recent = sum(age is not None and age <= cfg.news_max_days for age in (age_days(e.date) for e in pack.evidence))
    report = [
        f"# Run report — {pack.brand.name}", "",
        f"- url: {pack.url}", f"- industry playbook: `{pack.industry}` ({pack.industry_reason})",
        f"- evidence: {len(pack.evidence)} items from {len(pack.pages_crawled)} pages "
        f"({sum(e.kind == 'article' for e in pack.evidence)} from press"
        + (f", {pack.pooled_evidence} carried over from earlier runs" if pack.pooled_evidence else "") + ")",
        f"- freshness: {pack.stale_dropped} dated item(s) older than {cfg.evidence_max_days} days left out; "
        + (f"{recent} item(s) dated within the last {cfg.news_max_days} days" if recent else
           f"no news from the last {cfg.news_max_days} days, so posts are evergreen (no release/partnership/award posts)"),
        *([f"- thin evidence: {pack.thin_reason}; wrote 1 post from the best fact"] if pack.thin else []),
        f"- mode: {mode}" + (" (selection fell back to best delivered rollout)" if fell_back else ""),
        f"- harness used: `{Path(harness_used).name}` (copied to output/harness/)",
        f"- posts verified: {verified_n} / {len(result.cards)}"
        + (f" (+{fallback_n} fallback post delivered so the run is not empty)" if fallback_n else ""), "",
    ]
    report += ["## Market context (DataForSEO)", "", f"- status: {pack.market_note or 'not recorded'}"]
    if pack.market:
        m = pack.market
        report += [
                   "Steered which facts were picked and how posts were angled; never used as evidence.", "",
                   f"- competitors: {', '.join(c.domain for c in m.competitors) or 'none found'}",
                   f"- audience searches: {', '.join(k.keyword for k in m.brand_keywords[:10]) or 'none'}",
                   f"- content gaps: {', '.join(f'{k.keyword} ({k.competitor})' for k in m.gap_keywords[:8]) or 'none'}"]
        spend = market.cost_snapshot()
        if spend["calls"]:
            report += [f"- DataForSEO: {spend['calls']} live call(s), ${spend['usd']:.4f} (cached calls are free)"]
        report += [""]
    else:
        report += ["- posts were written without competitor or search context", ""]
    if stages_note:
        report += ["## Harness²", "", stages_note, ""]
    usage = usage_snapshot()
    if usage:
        report += ["## Token usage (this run)", "", "| model | calls | prompt tokens | completion tokens |", "|---|---|---|---|"]
        report += [f"| `{m}` | {u['calls']} | {u['prompt_tokens']:,} | {u['completion_tokens']:,} |" for m, u in sorted(usage.items())]
        report += [""]
    if rejected:
        report += ["## Dropped candidates", ""] + [
            f"- **{c.fact.headline}** — " + "; ".join(c.problems[:4]) for c in rejected] + [""]
    (out / "report.md").write_text("\n".join(report), encoding="utf-8")
    summary = {
        "task_id": pack.task_id, "brand": pack.brand.name, "industry": pack.industry, "mode": mode,
        "verified_posts": len(result.verified), "fallback_posts": fallback_n, "output_dir": str(out),
        "note": "; ".join(n for n in (
            stages_note if stages_note.startswith("Harness² refine skipped") else "",
            f"{fallback_n} post(s) could not be fully verified and are marked for review" if fallback_n else "",
        ) if n),
        "token_usage": usage_snapshot(),
        "competitors": [c.domain for c in pack.market.competitors] if pack.market else [],
        "dataforseo": market.cost_snapshot(),
        "market_status": pack.market_note,
        "posts_md": str(out / "posts.md"),
        "posters": [str(out / n) for names in posters.values() for n in names if n.endswith(".png")],
        "carousels": [str(out / names[-1]) for names in posters.values()],
    }
    (run_dir / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    try:  # so the next run for this brand picks new facts
        history.record(cfg, pack.brand.domain, pack.task_id, result.verified)
    except Exception as exc:
        log.warning("[finalize] could not record post history: %s", exc)
    log.info("[finalize] %d verified posts -> %s", len(result.verified), out)
    return summary
