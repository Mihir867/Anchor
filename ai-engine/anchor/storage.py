"""Persistence: runs and posts in Postgres, rendered images in Cloudinary.

Both are optional and independent:
    DATABASE_URL            postgres://user:pass@host:5432/db   (Neon/Supabase/RDS/local)
    CLOUDINARY_URL          cloudinary://<api_key>:<api_secret>@<cloud_name>
      or CLOUDINARY_CLOUD_NAME + CLOUDINARY_API_KEY + CLOUDINARY_API_SECRET
    CLOUDINARY_FOLDER       folder prefix for uploads (default "anchor")

Without DATABASE_URL nothing is stored (the run folders on disk remain the record). Without
Cloudinary, asset URLs point at the engine's /static/runs/... mount instead. A storage failure
never fails a generation run: the posts are already on disk and can be re-synced with
`python -m anchor.storage backfill`.

The Next.js client reads these tables directly (client/lib/db.ts); keep the column names in
sync with it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

log = logging.getLogger("anchor.storage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,          -- job id the client polls (task_id for imported runs)
    task_id         TEXT UNIQUE,               -- run folder: <domain>-<yyyymmdd-hhmmss>
    url             TEXT NOT NULL,
    domain          TEXT,
    brand           TEXT,
    industry        TEXT,
    mode            TEXT,
    status          TEXT NOT NULL,             -- queued | running | done | failed | cancelled
    stage           TEXT,
    error           TEXT,
    note            TEXT,
    verified_posts  INTEGER NOT NULL DEFAULT 0,
    request         JSONB,
    brand_kit       JSONB,
    token_usage     JSONB,
    logo_url        TEXT,
    posts_md        TEXT,
    report_md       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS runs_created_at_idx ON runs (created_at DESC);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS progress JSONB;  -- live stage details (anchor/progress.py)

CREATE TABLE IF NOT EXISTS posts (
    id                TEXT PRIMARY KEY,        -- <run id>:<card id>
    run_id            TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    card_id           TEXT NOT NULL,
    position          INTEGER NOT NULL,
    status            TEXT NOT NULL,           -- verified | rejected
    voice             TEXT,
    headline          TEXT,
    category          TEXT,
    linkedin          TEXT,
    instagram_caption TEXT,
    hashtags          JSONB NOT NULL DEFAULT '[]',
    poster_headline   TEXT,
    poster_kicker     TEXT,
    poster_stat       TEXT,
    slides            JSONB NOT NULL DEFAULT '[]',
    fact              JSONB,
    sources           JSONB NOT NULL DEFAULT '[]',
    notes             JSONB NOT NULL DEFAULT '[]',
    problems          JSONB NOT NULL DEFAULT '[]',
    attempts          INTEGER NOT NULL DEFAULT 0,
    slide_urls        JSONB NOT NULL DEFAULT '[]',
    pdf_url           TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS posts_run_idx ON posts (run_id, position);

CREATE TABLE IF NOT EXISTS assets (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    post_id     TEXT REFERENCES posts(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                 -- slide | carousel_pdf | logo
    position    INTEGER NOT NULL DEFAULT 0,
    url         TEXT NOT NULL,
    public_id   TEXT,
    provider    TEXT NOT NULL,                 -- cloudinary | local
    format      TEXT,
    width       INTEGER,
    height      INTEGER,
    bytes       INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS assets_run_idx ON assets (run_id);
"""

_init_lock = threading.Lock()
_initialised = False


# ---- configuration --------------------------------------------------------------------

def database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def enabled() -> bool:
    return bool(database_url())


def cloudinary_creds() -> tuple[str, str, str] | None:
    """(cloud_name, api_key, api_secret) or None when Cloudinary is not configured."""
    raw = os.environ.get("CLOUDINARY_URL", "").strip()
    if raw:
        u = urlparse(raw)
        if u.scheme == "cloudinary" and u.hostname and u.username and u.password:
            return u.hostname, unquote(u.username), unquote(u.password)
        log.warning("CLOUDINARY_URL is set but not of the form cloudinary://key:secret@cloud_name")
    parts = tuple(os.environ.get(k, "").strip() for k in
                  ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"))
    return parts if all(parts) else None  # type: ignore[return-value]


def status() -> dict:
    return {"database": enabled(), "cloudinary": cloudinary_creds() is not None}


# ---- Postgres -------------------------------------------------------------------------

def _connect():
    import psycopg

    return psycopg.connect(database_url(), connect_timeout=10)


def init() -> None:
    """Create the tables once per process (idempotent)."""
    global _initialised
    if _initialised or not enabled():
        return
    with _init_lock:
        if _initialised:
            return
        with _connect() as conn:
            conn.execute(SCHEMA)
        _initialised = True
        log.info("[storage] Postgres schema ready")


def _jsonb(value):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def record_job(job_id: str, request: dict, status: str, stage: str | None = None,
               error: str | None = None) -> None:
    """Upsert the job row so the client can show queued/running/failed runs straight from the DB."""
    if not enabled():
        return
    try:
        init()
        url = request.get("url", "")
        with _connect() as conn:
            conn.execute(
                """INSERT INTO runs (id, url, domain, mode, status, stage, error, request)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, stage = EXCLUDED.stage,
                     error = EXCLUDED.error, updated_at = now(),
                     finished_at = CASE WHEN EXCLUDED.status IN ('done', 'failed', 'cancelled') THEN now()
                                        ELSE runs.finished_at END""",
                (job_id, url, _domain(url), request.get("mode"), status, stage or status, error,
                 _jsonb(request)))
    except Exception as exc:  # storage must never break a run
        log.warning("[storage] could not record job %s (%s): %s", job_id, status, exc)


def cancel_job(job_id: str) -> bool:
    """Mark an in-flight job cancelled. Returns False if it was not queued/running."""
    if not enabled():
        return False
    try:
        init()
        with _connect() as conn:
            cur = conn.execute(
                """UPDATE runs SET status = 'cancelled', stage = 'cancelled', error = NULL,
                          updated_at = now(), finished_at = now()
                    WHERE id = %s AND status IN ('queued', 'running')""", (job_id,))
            return cur.rowcount > 0
    except Exception as exc:
        log.warning("[storage] could not cancel job %s: %s", job_id, exc)
        return False


def fail_interrupted() -> int:
    """At startup, nothing is running yet: any queued/running row was cut off by a restart or
    deploy. Mark those failed so the client stops showing them as in progress."""
    if not enabled():
        return 0
    try:
        init()
        with _connect() as conn:
            cur = conn.execute(
                """UPDATE runs SET status = 'failed', stage = 'failed', error = 'interrupted: engine restarted',
                          updated_at = now(), finished_at = now()
                    WHERE status IN ('queued', 'running')""")
            return cur.rowcount
    except Exception as exc:
        log.warning("[storage] could not clean up interrupted jobs: %s", exc)
        return 0


# One writer thread keeps progress updates ordered and off the pipeline's critical path.
_progress_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="anchor-progress")


def _write_progress(job_id: str, stage: str, info: dict) -> None:
    try:
        init()
        with _connect() as conn:
            # Only while the job is in flight: a late update must not overwrite done/failed.
            conn.execute(
                """UPDATE runs SET status = 'running', stage = %s, progress = %s, updated_at = now()
                    WHERE id = %s AND status IN ('queued', 'running')""",
                (stage, _jsonb(info), job_id))
    except Exception as exc:
        log.warning("[storage] could not record progress for %s (%s): %s", job_id, stage, exc)


def record_progress(job_id: str, stage: str, info: dict) -> None:
    """Queue a live-progress update for a running job (non-blocking; no-op without a database)."""
    if enabled():
        _progress_writer.submit(_write_progress, job_id, stage, info)


def flush_progress(timeout: float = 15) -> None:
    """Wait for queued progress updates, so they land before the final done/failed write."""
    if enabled():
        try:
            _progress_writer.submit(lambda: None).result(timeout=timeout)
        except Exception as exc:
            log.warning("[storage] progress updates still pending: %s", exc)


def save_run(job_id: str, run_dir: Path, request: dict | None = None,
             created_at: datetime | None = None) -> dict:
    """Upload a finished run's images and write the run + its posts. Idempotent: re-saving a
    run replaces its posts and assets. Returns {"slide_urls": {card_id: [...]}, ...}."""
    init()
    run_dir = Path(run_dir)
    out = run_dir / "output"
    deck = json.loads((out / "deck.json").read_text(encoding="utf-8"))
    summary = _read_json(run_dir / "result.json")
    pack = _read_json(run_dir / "pack" / "pack.json")
    brand = pack.get("brand", {})
    task_id = run_dir.name
    url = pack.get("url") or brand.get("url") or (request or {}).get("url", "")
    cards = deck.get("cards", [])
    verified = [c for c in cards if c.get("status") == "verified"]

    # 1. Assets (uploaded in parallel; each falls back to the engine's static URL on failure).
    jobs: list[tuple[str, str | None, int, Path]] = []  # (kind, card_id, position, file)
    for c in verified:
        # Older runs rendered a single poster (poster_path) and no carousel.
        slides = c.get("slide_paths") or ([c["poster_path"]] if c.get("poster_path") else [])
        for i, p in enumerate(slides, 1):
            jobs.append(("slide", c["id"], i, _local(p, out)))
        if c.get("pdf_path"):
            jobs.append(("carousel_pdf", c["id"], 0, _local(c["pdf_path"], out)))
    logo = brand.get("logo_path")
    if logo and Path(logo).is_file():
        jobs.append(("logo", None, 0, Path(logo)))
    jobs = [j for j in jobs if j[3].is_file()]
    with ThreadPoolExecutor(max_workers=4) as pool:
        uploaded = list(pool.map(lambda j: _store_file(j[3], task_id, run_dir), jobs))

    slide_urls: dict[str, list[str]] = {}
    pdf_urls: dict[str, str] = {}
    logo_url = None
    for (kind, card_id, _, _), asset in zip(jobs, uploaded):
        if kind == "slide":
            slide_urls.setdefault(card_id, []).append(asset["url"])
        elif kind == "carousel_pdf":
            pdf_urls[card_id] = asset["url"]
        else:
            logo_url = asset["url"]

    # 2. Rows, in one transaction.
    report = out / "report.md"
    posts_md = out / "posts.md"
    created = created_at or _task_time(task_id) or datetime.now(timezone.utc)
    with _connect() as conn, conn.transaction():
        # The same run folder may already be stored under another id (imported by `backfill`
        # before the live job saved it); the newest save wins.
        conn.execute("DELETE FROM runs WHERE task_id = %s AND id <> %s", (task_id, job_id))
        conn.execute(
            """INSERT INTO runs (id, task_id, url, domain, brand, industry, mode, status, stage, error, note,
                                 verified_posts, request, brand_kit, token_usage, logo_url, posts_md,
                                 report_md, created_at, finished_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'done','done',NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
               ON CONFLICT (id) DO UPDATE SET task_id = EXCLUDED.task_id, url = EXCLUDED.url,
                 domain = EXCLUDED.domain, brand = EXCLUDED.brand, industry = EXCLUDED.industry,
                 mode = EXCLUDED.mode, status = 'done', stage = 'done', error = NULL, note = EXCLUDED.note,
                 verified_posts = EXCLUDED.verified_posts, request = COALESCE(EXCLUDED.request, runs.request),
                 brand_kit = EXCLUDED.brand_kit, token_usage = EXCLUDED.token_usage,
                 logo_url = EXCLUDED.logo_url, posts_md = EXCLUDED.posts_md,
                 report_md = EXCLUDED.report_md, updated_at = now(),
                 finished_at = COALESCE(runs.finished_at, now())""",
            (job_id, task_id, url, brand.get("domain") or _domain(url),
             summary.get("brand") or deck.get("brand") or brand.get("name"),
             summary.get("industry") or deck.get("industry"),
             summary.get("mode") or (request or {}).get("mode") or "fast",
             summary.get("note") or None, len(verified),
             _jsonb(request) if request else None, _jsonb(_public_brand(brand)),
             _jsonb(summary.get("token_usage") or {}), logo_url,
             posts_md.read_text(encoding="utf-8") if posts_md.is_file() else None,
             report.read_text(encoding="utf-8") if report.is_file() else None, created))
        conn.execute("DELETE FROM posts WHERE run_id = %s", (job_id,))
        conn.execute("DELETE FROM assets WHERE run_id = %s", (job_id,))
        for pos, c in enumerate(cards, 1):
            post = c.get("post") or {}
            fact = c.get("fact") or {}
            pid = f"{job_id}:{c['id']}"
            conn.execute(
                """INSERT INTO posts (id, run_id, card_id, position, status, voice, headline, category,
                                      linkedin, instagram_caption, hashtags, poster_headline, poster_kicker,
                                      poster_stat, slides, fact, sources, notes, problems, attempts,
                                      slide_urls, pdf_url)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (pid, job_id, c["id"], pos, c.get("status", "rejected"), post.get("voice") or None,
                 fact.get("headline"), fact.get("category"), post.get("linkedin"),
                 post.get("instagram_caption"), _jsonb(post.get("hashtags") or []),
                 post.get("poster_headline"), post.get("poster_kicker"), post.get("poster_stat"),
                 _jsonb(post.get("slides") or []), _jsonb(fact), _jsonb(c.get("sources") or []),
                 _jsonb(c.get("notes") or []), _jsonb(c.get("problems") or []), c.get("attempts") or 0,
                 _jsonb(slide_urls.get(c["id"], [])), pdf_urls.get(c["id"])))
        for (kind, card_id, position, _), asset in zip(jobs, uploaded):
            conn.execute(
                """INSERT INTO assets (run_id, post_id, kind, position, url, public_id, provider, format,
                                       width, height, bytes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (job_id, f"{job_id}:{card_id}" if card_id else None, kind, position, asset["url"],
                 asset.get("public_id"), asset["provider"], asset.get("format"), asset.get("width"),
                 asset.get("height"), asset.get("bytes")))
    n_cloud = sum(a["provider"] == "cloudinary" for a in uploaded)
    log.info("[storage] saved run %s (%s): %d posts, %d assets (%d on Cloudinary)",
             job_id, task_id, len(cards), len(uploaded), n_cloud)
    return {"slide_urls": slide_urls, "pdf_urls": pdf_urls, "logo_url": logo_url}


# ---- Cloudinary -----------------------------------------------------------------------

def signature(params: dict[str, str], secret: str) -> str:
    """Cloudinary request signature: sha1 of the sorted `k=v` pairs joined by '&', plus the secret."""
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params) if params[k] != "") + secret
    return hashlib.sha1(to_sign.encode()).hexdigest()


def upload(path: Path, public_id: str, raw: bool = False) -> dict:
    """Signed upload via Cloudinary's REST API. PDFs go up as `raw` so they are downloadable
    on accounts where PDF delivery as images is disabled (the default on free plans)."""
    creds = cloudinary_creds()
    if creds is None:
        raise RuntimeError("Cloudinary is not configured")
    cloud, key, secret = creds
    params = {"overwrite": "true", "public_id": public_id, "timestamp": str(int(time.time()))}
    params.update(api_key=key, signature=signature(params, secret))
    endpoint = f"https://api.cloudinary.com/v1_1/{cloud}/{'raw' if raw else 'image'}/upload"
    last: Exception | None = None
    for attempt in range(3):
        try:
            with path.open("rb") as fh:
                r = httpx.post(endpoint, data=params, files={"file": (path.name, fh)}, timeout=60)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            if r.status_code < 500 and r.status_code != 429:
                break
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Cloudinary upload of {path.name} failed: {last}")


def _store_file(path: Path, task_id: str, run_dir: Path) -> dict:
    folder = os.environ.get("CLOUDINARY_FOLDER", "anchor").strip("/ ") or "anchor"
    is_pdf = path.suffix.lower() == ".pdf"
    if cloudinary_creds() is not None:
        # raw resources keep their extension in the public id; images must not.
        public_id = f"{folder}/{task_id}/{path.name if is_pdf else path.stem}"
        try:
            res = upload(path, public_id, raw=is_pdf)
            return {"url": res["secure_url"], "public_id": res.get("public_id"), "provider": "cloudinary",
                    "format": res.get("format") or path.suffix.lstrip("."), "width": res.get("width"),
                    "height": res.get("height"), "bytes": res.get("bytes")}
        except Exception as exc:
            log.warning("[storage] %s; serving it from the engine instead", exc)
    try:  # the engine mounts the runs directory at /static/runs
        rel = path.resolve().relative_to(run_dir.resolve().parent).as_posix()
    except ValueError:
        rel = f"{task_id}/output/{path.name}"
    return {"url": f"/static/runs/{rel}", "public_id": None, "provider": "local",
            "format": path.suffix.lstrip("."), "bytes": path.stat().st_size}


# ---- helpers --------------------------------------------------------------------------

def _local(p: str, out: Path) -> Path:
    """deck.json stores absolute paths from the machine that rendered it; trust the name only."""
    return out / Path(p).name


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _domain(url: str) -> str:
    return urlparse(url if "//" in url else f"https://{url}").netloc.removeprefix("www.")


def _task_time(task_id: str) -> datetime | None:
    try:
        return datetime.strptime(task_id[-15:], "%Y%m%d-%H%M%S").astimezone(timezone.utc)
    except ValueError:
        return None


def _public_brand(brand: dict) -> dict:
    """Brand kit minus local filesystem paths and the raw @font-face list."""
    drop = {"logo_path", "screenshot_path", "font_faces"}
    return {k: v for k, v in brand.items() if k not in drop}


def backfill(runs_dir: Path, force: bool = False) -> int:
    """Import finished run folders on disk that are not stored yet (id = folder name).
    `force` re-imports (and re-uploads) every run, including ones saved by live jobs."""
    init()
    with _connect() as conn:
        stored = {r[0] for r in conn.execute("SELECT task_id FROM runs WHERE task_id IS NOT NULL")}
    n = 0
    for run_dir in sorted(p for p in Path(runs_dir).iterdir() if p.is_dir() and not p.name.startswith(".")):
        if not (run_dir / "output" / "deck.json").is_file() or (run_dir.name in stored and not force):
            continue
        try:
            save_run(run_dir.name, run_dir)
            n += 1
        except Exception as exc:
            log.error("[storage] backfill of %s failed: %s", run_dir.name, exc)
    return n


def main(argv: list[str]) -> int:
    from .config import settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cmd = argv[0] if argv else "status"
    if cmd == "status":
        print(json.dumps(status()))
        return 0
    if not enabled():
        print("DATABASE_URL is not set (put it in ai-engine/.env)", file=sys.stderr)
        return 1
    if cmd == "init":
        init()
        print("schema ready")
    elif cmd == "backfill":
        print(f"imported {backfill(settings().runs_dir, force='--force' in argv)} run(s)")
    else:
        print("usage: python -m anchor.storage [status|init|backfill [--force]]", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
