"""Run one Harness² task-level recursion step (Propose-Probe-Compose) for a brand.

    base rollout(s)  -> INV + DOM harness edits proposed from their trajectories
                     -> each edited harness probed with a real rollout
                     -> compositions built from the behavioural contrasts, then rolled
                     -> blind, answer-free selection among the composed finals (k >= 2)
                     -> experience reflection appended to the industry's library

The library under runs/library/<mode>/<industry>/ persists across runs, which is Harness²'s
harnessing-level recursion: the 10th hotel starts from what the first nine taught.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from harness2.core import library as h2_library
from harness2.core.schedule import run_task

from .. import storage
from ..config import Settings
from ..llm import LLM
from ..models import TaskPack
from ..score import score_rollout
from .adapter import AnchorAdapter
from .proposer import LLMProposer

log = logging.getLogger("anchor.h2")


LIBRARY_KEY = "harness_library"  # engine_state row holding runs/library as tar.gz
PROMOTED = "PROMOTED.json"       # written into a library entry only when it beat the base


@dataclass
class GatedLibrary(h2_library.Library):
    """A Harness² library whose writes wait for proof: `add` only stages the adopted harness, and
    `commit` stores it after it scored better than the base harness on the same evidence. Without
    this, a k=1 run stores whatever its single composed final was, even a no-op edit."""

    pending: list = field(default_factory=list)

    def add(self, task_id, harness, **kw):  # type: ignore[override]
        self.pending.append((task_id, harness, kw))
        return None

    def commit(self, promotion: dict) -> Path | None:
        stored = None
        for task_id, harness, kw in self.pending:
            stored = super().add(task_id, harness, **kw) or stored
            if stored:
                (Path(stored) / PROMOTED).write_text(json.dumps(promotion, indent=1), encoding="utf-8")
        self.pending.clear()
        return stored


@dataclass
class RefineOutcome:
    chosen_run_dir: Path
    chosen_label: str
    harness_dir: Path
    summary_path: Path
    fell_back_to_base: bool
    notes: str
    adopted: bool = False
    scores: dict = field(default_factory=dict)


def refine(pack: TaskPack, run_dir: Path, cfg: Settings, *, k: int = 1, mode: str = "agg") -> RefineOutcome:
    adapter = AnchorAdapter(run_dir, pack, cfg, cfg.harness_dir)
    audit = run_dir / "h2" / "sessions"
    proposer = LLMProposer(
        adapter.spec.channels["proposer"], audit_dir=audit,
        llm=LLM(cfg.proposer_model, cfg=cfg, max_tokens=cfg.proposer_max_tokens),
        context_chars=cfg.proposer_context_chars,
    )
    selector = LLMProposer(
        adapter.spec.channels["selector"], audit_dir=audit / "selector",
        llm=LLM(cfg.selector_model, cfg=cfg, max_tokens=cfg.max_tokens),
        context_chars=cfg.proposer_context_chars,
    )
    lib = GatedLibrary(root=cfg.library_dir / mode, domain=pack.industry, surface=adapter.substrate.surface())
    log.info("[harness2] k=%d mode=%s industry=%s library_entries=%d", k, mode, pack.industry,
             len(lib.entries()))
    res = run_task(pack.task_id, k, adapter=adapter, prop=proposer, runs_root=adapter.spec.runs_root,
                   modes=(mode,), library=lib, selector_prop=selector)
    summary = adapter.spec.runs_root / "summary.json"
    data = res.to_dict() if hasattr(res, "to_dict") else {}
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    sel = res.selections.get(mode) or {}
    chosen_dir = Path(sel.get("chosen_run_dir") or "")
    label = sel.get("chosen_label") or ""
    stages = (res.modes.get(mode) or {}).get("stages", [])
    notes = "\n".join(f"- {s['label']}: {'kept base' if s.get('kept_base') else 'fell back' if s.get('fell_back') else 'edited'}"
                      f" — {(s.get('notes') or s.get('error') or '')[:300]}" for s in stages)
    fell_back = False
    rollouts = [Path(b["run_dir"]) for b in res.base] + [
        p.parent for p in (adapter.spec.runs_root / "rollouts").glob("**/cards.json")]
    rollouts = list(dict.fromkeys(d for d in rollouts if (d / "cards.json").is_file()))
    if not rollouts:
        raise RuntimeError("Harness² produced no rollout output; see " + str(summary))
    judge = LLM(cfg.critic_model, cfg=cfg)
    score = {str(d): score_rollout(d, pack, cfg, judge)["score"] for d in rollouts}
    bases = [Path(b["run_dir"]) for b in res.base if (Path(b["run_dir"]) / "cards.json").is_file()]
    best_base = max(bases, key=lambda d: score[str(d)], default=None)
    base_score = score[str(best_base)] if best_base else 0.0

    if not sel.get("ok") or not chosen_dir.is_dir() or not adapter.delivered(chosen_dir):
        # Selection had nothing deliverable: hand back the best-scoring rollout, adopt nothing.
        fell_back = True
        chosen_dir = max(rollouts, key=lambda d: score[str(d)])
        label = chosen_dir.name
    margin = float(os.environ.get("ANCHOR_ADOPT_MARGIN", "0.25"))
    chosen_score = score.get(str(chosen_dir), 0.0)
    is_base = best_base is not None and (chosen_dir in bases or label.startswith("base"))
    adopted = False
    if not fell_back and not is_base and chosen_score >= base_score + margin:
        stored = lib.commit({"task_id": pack.task_id, "label": label, "score": chosen_score,
                             "base_score": base_score, "gain": round(chosen_score - base_score, 3),
                             "promoted_at": datetime.now(timezone.utc).isoformat()})
        adopted = stored is not None
        if adopted:
            storage.save_dir(LIBRARY_KEY, cfg.library_dir)
        verdict = (f"adopted `{label}`: quality {chosen_score:.2f} vs base {base_score:.2f}"
                   + ("" if adopted else " (no transferable lesson, so not stored in the library)"))
    else:
        lib.pending.clear()
        if not fell_back and not is_base and best_base is not None:
            # The edited harness did not beat the base on this brand: deliver the base's posts.
            verdict = (f"kept base: `{label}` scored {chosen_score:.2f} vs base {base_score:.2f} "
                       f"(needs +{margin:g}); nothing stored")
            chosen_dir, label = best_base, best_base.name
        else:
            verdict = f"kept base: no edited harness to promote (delivered `{label}`, quality {chosen_score:.2f})"
    delivered_base = chosen_dir in bases or label.startswith("base")
    harness_dir = adapter.base_harness() if delivered_base else _harness_for(adapter, label)
    notes = (notes + "\n" if notes else "") + f"- adoption: {verdict}"
    log.info("[harness2] %s", verdict)
    return RefineOutcome(chosen_dir, label, harness_dir, summary, fell_back, notes, adopted,
                         {"chosen": chosen_score, "base": base_score})


def _harness_for(adapter: AnchorAdapter, label: str) -> Path:
    hits = sorted(adapter.spec.runs_root.glob(f"**/harnesses/{label}"))
    return hits[0] if hits else adapter.base_harness()
