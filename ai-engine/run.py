"""Anchor CLI.

    python run.py https://example.com                 # one rollout with the best learned harness (cheap)
    python run.py https://example.com --refine        # Harness² Propose-Probe-Compose (~5x the tokens)
    python run.py https://example.com --k 2 --posts 3 --industry hospitality
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from anchor.pipeline import run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evidence-grounded LinkedIn + Instagram posts for any brand URL")
    ap.add_argument("url")
    ap.add_argument("--refine", action="store_true",
                    help="run Harness² refinement (4 rollouts + improver calls, ~5x the tokens of a normal run); "
                         "the adopted harness is reused by later normal runs in the same industry")
    ap.add_argument("--fast", action="store_true", help=argparse.SUPPRESS)  # old flag; fast is the default
    ap.add_argument("--k", type=int, default=1, help="Harness² task-level recursion budget (4k rollouts)")
    ap.add_argument("--posts", type=int, default=3, help="max posts to publish")
    ap.add_argument("--industry", help="force a skill (saas, hospitality, ecommerce, ...)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    summary = run(args.url, mode="refine" if args.refine else "fast", k=args.k, max_posts=args.posts,
                  industry=args.industry)
    print(json.dumps(summary, indent=2))
    return 0 if summary["verified_posts"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
