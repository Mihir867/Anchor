"""Harness² outside the user's request: refine saved runs in the background.

A user's run always uses the best PROMOTED harness for its industry (pipeline.learned_harness)
and returns as soon as its posts are ready. Refinement (4 rollouts per k plus improver calls,
roughly 5x a run's tokens) happens afterwards on the run's frozen evidence pack, so it never
delays the user and can use a slower or cheaper improver model. An edit is promoted only when it
beats the base harness on the quality score (h2.refine.GatedLibrary).

    python -m anchor.h2.background runs/<task_id> [runs/<task_id> ...]    refine these runs
    python -m anchor.h2.background --recent 5 [--industry saas]           newest N saved runs

The API does the same after each finished job when ANCHOR_AUTO_REFINE=1 (one at a time, in its
own thread, never blocking user jobs).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from ..config import Settings, settings
from ..prepare import load_pack

log = logging.getLogger("anchor.h2.background")


def refine_saved(run_dir: Path, cfg: Settings, k: int | None = None) -> dict:
    """Refine one finished run's pack. Never touches the run's delivered output/."""
    from ..pipeline import refine_blocker
    from .refine import refine

    run_dir = Path(run_dir)
    pack_dir = run_dir / "pack"
    if not (pack_dir / "pack.json").is_file():
        return {"run": run_dir.name, "skipped": "no frozen pack (pack/pack.json)"}
    blocker = refine_blocker(cfg)
    if blocker:
        return {"run": run_dir.name, "skipped": blocker}
    if (run_dir / "h2" / "summary.json").is_file():
        return {"run": run_dir.name, "skipped": "already refined"}
    pack = load_pack(pack_dir)
    if pack.thin:
        return {"run": run_dir.name, "skipped": f"thin evidence pack ({pack.thin_reason})"}
    k = k or int(os.environ.get("ANCHOR_REFINE_K", "1") or 1)
    log.info("[background] refining %s (%s, k=%d)", run_dir.name, pack.industry, k)
    outcome = refine(pack, run_dir, cfg, k=k)
    out = {"run": run_dir.name, "industry": pack.industry, "adopted": outcome.adopted,
           "chosen": outcome.chosen_label, "scores": outcome.scores}
    log.info("[background] %s: %s", run_dir.name, outcome.notes.splitlines()[-1] if outcome.notes else out)
    return out


def recent_runs(cfg: Settings, n: int, industry: str | None = None) -> list[Path]:
    runs = []
    for d in sorted((p for p in cfg.runs_dir.iterdir() if p.is_dir() and (p / "pack" / "pack.json").is_file()),
                    key=lambda p: p.stat().st_mtime, reverse=True):
        if industry and load_pack(d / "pack").industry != industry:
            continue
        runs.append(d)
        if len(runs) >= n:
            break
    return runs


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="python -m anchor.h2.background")
    ap.add_argument("runs", nargs="*", type=Path)
    ap.add_argument("--recent", type=int, default=0)
    ap.add_argument("--industry")
    ap.add_argument("--k", type=int)
    args = ap.parse_args(argv)
    cfg = settings()
    targets = list(args.runs) + (recent_runs(cfg, args.recent, args.industry) if args.recent else [])
    if not targets:
        ap.error("give run folders or --recent N")
    for d in targets:
        try:
            print(refine_saved(d, cfg, args.k))
        except Exception as exc:  # one bad run must not stop the batch
            log.exception("refining %s failed", d)
            print({"run": Path(d).name, "error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
