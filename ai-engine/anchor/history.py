"""What each brand has already been posted about, so a rerun writes NEW posts.

One record per brand domain: the headline, quote and post type of every verified (non-fallback)
post, newest first. Kept on disk next to the Harness² library and, when DATABASE_URL is set, in
Postgres (engine_state), because Render's disk is wiped on every deploy. Set
ANCHOR_BRAND_HISTORY=0 to turn it off (e.g. for repeatable evaluations).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from pathlib import Path

from . import storage
from .config import Settings

log = logging.getLogger("anchor.history")
KEEP = 60  # most recent posts remembered per brand


def enabled() -> bool:
    return os.environ.get("ANCHOR_BRAND_HISTORY", "1").strip() != "0"


def _key(domain: str) -> str:
    return "brand_history:" + re.sub(r"^www\.", "", (domain or "").lower())


def _file(cfg: Settings, domain: str) -> Path:
    return cfg.library_dir / "brands" / (re.sub(r"[^a-z0-9.-]+", "-", _key(domain).split(":", 1)[1]) + ".json")


def load(cfg: Settings, domain: str) -> list[dict]:
    if not enabled():
        return []
    data = storage.get_state(_key(domain))
    if data is None:
        f = _file(cfg, domain)
        try:
            data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        except ValueError:
            data = {}
    return list((data or {}).get("posts", []))[:KEEP]


def record(cfg: Settings, domain: str, task_id: str, cards) -> None:
    """Prepend this run's delivered posts (fallbacks excluded: they were not really published)."""
    if not enabled():
        return
    new = [{"headline": c.fact.headline, "quote": c.fact.quote[:300], "category": c.fact.category,
            "task_id": task_id, "date": date.today().isoformat()}
           for c in cards if c.status == "verified" and not c.fallback]
    if not new:
        return
    posts = (new + load(cfg, domain))[:KEEP]
    data = {"domain": domain, "posts": posts}
    f = _file(cfg, domain)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    storage.put_state(_key(domain), data)
    log.info("[history] %s: %d post(s) recorded (%d remembered)", domain, len(new), len(posts))
