"""Anchor HTTP Service.

Endpoints:
    POST /runs                 {"url": "...", "mode": "refine"|"fast", "k": 1, "posts": 3} -> {"job_id"}
    GET  /runs                 -> List all runs (in-memory + historical on disk)
    GET  /runs/{job_id}        -> Status, result summary, and full deck
    GET  /runs/{job_id}/posts.md -> Rendered markdown of verified posts
    GET  /runs/{job_id}/files/{filename} -> Direct download of posters / PDFs
    GET  /health               -> Health check (+ which storage backends are configured)

Storage: with DATABASE_URL set, every job is written to Postgres (queued -> running -> done/failed)
and finished runs' slides/PDFs are uploaded to Cloudinary when CLOUDINARY_URL is set. See
anchor/storage.py. The Next.js client reads those tables directly.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from anchor import progress, storage
from anchor.config import Settings, settings
from anchor.pipeline import run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("anchor.api")

app = FastAPI(title="Anchor AI Engine", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cfg: Settings = settings()
runs_dir = cfg.runs_dir
runs_dir.mkdir(parents=True, exist_ok=True)

# Mount runs directory so posters, slides, and PDFs can be accessed directly
app.mount("/static/runs", StaticFiles(directory=str(runs_dir)), name="runs")

_pool = ThreadPoolExecutor(max_workers=int(os.environ.get("ANCHOR_WORKERS", "2")))
_jobs: dict[str, dict] = {}


class RunRequest(BaseModel):
    url: str
    mode: Literal["refine", "fast"] = "fast"
    k: int = Field(1, ge=1, le=4)
    posts: int = Field(3, ge=1, le=6)
    industry: Optional[str] = None


def _format_result(res: dict, task_id: str) -> dict:
    """Enrich result with web URLs and parsed deck JSON."""
    out_dir = Path(res.get("output_dir", ""))
    deck_path = out_dir / "deck.json"
    if deck_path.is_file():
        try:
            res["deck"] = json.loads(deck_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Provide web relative URLs for posters and carousels
    if "posters" in res:
        res["poster_urls"] = [f"/static/runs/{task_id}/output/{Path(p).name}" for p in res["posters"]]
    if "carousels" in res:
        res["carousel_urls"] = [f"/static/runs/{task_id}/output/{Path(p).name}" for p in res["carousels"]]
    res["posts_md_url"] = f"/runs/{task_id}/posts.md"
    return res


def _work(job_id: str, req: RunRequest) -> None:
    _jobs[job_id]["status"] = "running"
    _jobs[job_id]["stage"] = "crawling"
    storage.record_job(job_id, req.model_dump(), "running", "crawling")

    def on_progress(stage: str, info: dict) -> None:
        _jobs[job_id].update(stage=stage, progress=info)
        storage.record_progress(job_id, stage, info)

    try:
        with progress.reporting(on_progress):
            raw_result = run(
                req.url,
                mode=req.mode,
                k=req.k,
                max_posts=req.posts,
                industry=req.industry,
                cfg=cfg,
            )
        task_id = raw_result.get("task_id", job_id)
        formatted = _format_result(raw_result, task_id)
        if storage.enabled():
            on_progress("saving", {**_jobs[job_id].get("progress", {}),
                                   "verified": raw_result.get("verified_posts")})
            storage.flush_progress()
            try:
                formatted["storage"] = storage.save_run(job_id, runs_dir / task_id, req.model_dump())
            except Exception as exc:  # the posts exist on disk; `python -m anchor.storage backfill` re-syncs
                log.exception("job %s: saving to Postgres/Cloudinary failed", job_id)
                formatted["storage_error"] = f"{type(exc).__name__}: {exc}"
                storage.record_job(job_id, req.model_dump(), "done", "done", f"storage: {exc}")
        _jobs[job_id].update(status="done", stage="done", result=formatted, task_id=task_id)
    except Exception as exc:
        logging.exception("job %s failed", job_id)
        error = f"{type(exc).__name__}: {exc}"
        _jobs[job_id].update(status="failed", stage="failed", error=error)
        storage.flush_progress()
        storage.record_job(job_id, req.model_dump(), "failed", "failed", error)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "Anchor AI Engine", "version": "2.0.0", "storage": storage.status()}


@app.get("/runs")
def list_runs() -> list[dict]:
    """List all available runs, combining in-memory active jobs and historical runs on disk."""
    items = []
    seen = set()

    # Active/recent in-memory jobs
    for jid, job in _jobs.items():
        seen.add(jid)
        task_id = job.get("task_id") or jid
        seen.add(task_id)
        res = job.get("result", {})
        items.append({
            "id": jid,
            "task_id": task_id,
            "status": job.get("status"),
            "brand": res.get("brand") or job.get("request", {}).get("url"),
            "industry": res.get("industry"),
            "verified_posts": res.get("verified_posts", 0),
            "created_at": res.get("task_id", "").split("-")[-1] if "-" in res.get("task_id", "") else "",
            "mode": res.get("mode") or job.get("request", {}).get("mode", "fast"),
        })

    # Disk runs
    for run_path in sorted(runs_dir.iterdir(), reverse=True):
        if not run_path.is_dir() or run_path.name.startswith("."):
            continue
        task_id = run_path.name
        if task_id in seen:
            continue
        seen.add(task_id)

        result_file = run_path / "result.json"
        deck_file = run_path / "output" / "deck.json"
        brand_name = task_id.split("-")[0].capitalize()
        industry = "general"
        verified = 0

        if result_file.is_file():
            try:
                res_data = json.loads(result_file.read_text(encoding="utf-8"))
                brand_name = res_data.get("brand", brand_name)
                industry = res_data.get("industry", industry)
                verified = res_data.get("verified_posts", 0)
            except Exception:
                pass
        elif deck_file.is_file():
            try:
                deck_data = json.loads(deck_file.read_text(encoding="utf-8"))
                brand_name = deck_data.get("brand", brand_name)
                industry = deck_data.get("industry", industry)
                verified = len([c for c in deck_data.get("cards", []) if c.get("status") == "verified"])
            except Exception:
                pass

        items.append({
            "id": task_id,
            "task_id": task_id,
            "status": "done",
            "brand": brand_name,
            "industry": industry,
            "verified_posts": verified,
            "created_at": task_id.split("-")[-1] if "-" in task_id else "",
            "mode": "fast",
        })

    return items


@app.post("/runs", status_code=202)
def create_run(req: RunRequest) -> dict:
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "status": "queued",
        "stage": "queued",
        "request": req.model_dump(),
        "job_id": job_id,
    }
    storage.record_job(job_id, req.model_dump(), "queued")
    _pool.submit(_work, job_id, req)
    return {"job_id": job_id, "status": "queued"}


@app.get("/runs/{job_id}")
def get_run(job_id: str) -> dict:
    # 1. In-memory job
    if job_id in _jobs:
        return _jobs[job_id]

    # 2. Check disk for historical task_id matching job_id
    matches = [p for p in runs_dir.iterdir() if p.is_dir() and (p.name == job_id or p.name.startswith(job_id))]
    if matches:
        target = matches[0]
        result_file = target / "result.json"
        if result_file.is_file():
            try:
                res = json.loads(result_file.read_text(encoding="utf-8"))
                formatted = _format_result(res, target.name)
                return {"status": "done", "stage": "done", "job_id": job_id, "result": formatted}
            except Exception:
                pass

        # Try reconstruct from output/deck.json
        deck_file = target / "output" / "deck.json"
        if deck_file.is_file():
            try:
                deck = json.loads(deck_file.read_text(encoding="utf-8"))
                verified_cards = [c for c in deck.get("cards", []) if c.get("status") == "verified"]
                out_dir = target / "output"
                posters = sorted([str(p) for p in out_dir.glob("*.png")])
                carousels = sorted([str(p) for p in out_dir.glob("*.pdf")])
                res = {
                    "task_id": target.name,
                    "brand": deck.get("brand", "Unknown"),
                    "industry": deck.get("industry", "general"),
                    "verified_posts": len(verified_cards),
                    "output_dir": str(out_dir),
                    "deck": deck,
                    "posters": posters,
                    "carousels": carousels,
                    "poster_urls": [f"/static/runs/{target.name}/output/{Path(p).name}" for p in posters],
                    "carousel_urls": [f"/static/runs/{target.name}/output/{Path(p).name}" for p in carousels],
                    "posts_md_url": f"/runs/{target.name}/posts.md",
                }
                return {"status": "done", "stage": "done", "job_id": job_id, "result": res}
            except Exception as e:
                log.error("Failed to parse disk run %s: %s", target, e)

    raise HTTPException(404, f"unknown job or run: {job_id}")


@app.get("/runs/{job_id}/posts.md", response_class=PlainTextResponse)
def get_posts(job_id: str) -> str:
    # Check in-memory
    job = _jobs.get(job_id)
    if job and job.get("status") == "done" and "result" in job:
        md_path = Path(job["result"].get("posts_md", ""))
        if md_path.is_file():
            return md_path.read_text(encoding="utf-8")

    # Check disk
    matches = [p for p in runs_dir.iterdir() if p.is_dir() and (p.name == job_id or p.name.startswith(job_id))]
    if matches:
        md_file = matches[0] / "output" / "posts.md"
        if md_file.is_file():
            return md_file.read_text(encoding="utf-8")

    raise HTTPException(404, "posts.md not ready or not found")


@app.get("/runs/{job_id}/files/{filename}")
def get_run_file(job_id: str, filename: str):
    matches = [p for p in runs_dir.iterdir() if p.is_dir() and (p.name == job_id or p.name.startswith(job_id))]
    if matches:
        target_file = matches[0] / "output" / filename
        if target_file.is_file():
            return FileResponse(target_file)
    raise HTTPException(404, f"file {filename} not found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
