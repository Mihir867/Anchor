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
from dataclasses import dataclass
from pathlib import Path

from harness2.core import library as h2_library
from harness2.core.schedule import run_task

from ..config import Settings
from ..llm import LLM
from ..models import TaskPack
from .adapter import AnchorAdapter
from .proposer import LLMProposer

log = logging.getLogger("anchor.h2")


@dataclass
class RefineOutcome:
    chosen_run_dir: Path
    chosen_label: str
    harness_dir: Path
    summary_path: Path
    fell_back_to_base: bool
    notes: str


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
    lib = h2_library.Library(root=cfg.library_dir / mode, domain=pack.industry,
                             surface=adapter.substrate.surface())
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
    if not sel.get("ok") or not chosen_dir.is_dir() or not adapter.delivered(chosen_dir):
        # Selection had nothing deliverable (e.g. every composed final dropped all posts).
        # Fall back to the delivered rollout with the most verified posts, base included.
        fell_back = True
        candidates = [Path(b["run_dir"]) for b in res.base] + list(
            (adapter.spec.runs_root / "rollouts").glob("**/cards.json"))
        best = max((p.parent if p.name == "cards.json" else p for p in candidates),
                   key=lambda d: _verified_count(d), default=None)
        if best is None or _verified_count(best) == 0:
            raise RuntimeError("Harness² produced no rollout with a verified post; see " + str(summary))
        chosen_dir, label = best, best.name
    harness_dir = _harness_for(adapter, label)
    log.info("[harness2] selected %s (%s)", label, chosen_dir)
    return RefineOutcome(chosen_dir, label, harness_dir, summary, fell_back, notes)


def _verified_count(run_dir: Path) -> int:
    p = Path(run_dir) / "cards.json"
    return p.read_text(encoding="utf-8").count('"status": "verified"') if p.is_file() else 0


def _harness_for(adapter: AnchorAdapter, label: str) -> Path:
    hits = sorted(adapter.spec.runs_root.glob(f"**/harnesses/{label}"))
    return hits[0] if hits else adapter.base_harness()
