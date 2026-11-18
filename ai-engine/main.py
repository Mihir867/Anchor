"""HTTP service: runs are jobs (minutes long), so the API enqueues and you poll.

    POST /runs        {"url": "...", "mode": "refine"|"fast", "k": 1, "posts": 3}  -> {"job_id"}
    GET  /runs/{id}   -> status, and the result summary when done
    GET  /runs/{id}/posts.md
"""

from __future__ import annotations

import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from anchor.pipeline import run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = FastAPI(title="Anchor AI Engine", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("ANCHOR_CORS_ORIGINS", "http://localhost:3000").split(",") if o],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
_pool = ThreadPoolExecutor(max_workers=int(os.environ.get("ANCHOR_WORKERS", "2")))
_jobs: dict[str, dict] = {}  # in-process; swap for Redis/RQ or a DB table to scale horizontally


class RunRequest(BaseModel):
    url: str
    mode: Literal["refine", "fast"] = "fast"
    k: int = Field(1, ge=1, le=4)
    posts: int = Field(3, ge=1, le=6)
    industry: Optional[str] = None


def _work(job_id: str, req: RunRequest) -> None:
    _jobs[job_id]["status"] = "running"
    try:
        _jobs[job_id].update(status="done", result=run(req.url, mode=req.mode, k=req.k,
                                                       max_posts=req.posts, industry=req.industry))
    except Exception as exc:  # surfaced to the caller, never swallowed
        logging.exception("job %s failed", job_id)
        _jobs[job_id].update(status="failed", error=f"{type(exc).__name__}: {exc}")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/runs", status_code=202)
def create_run(req: RunRequest) -> dict:
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "queued", "request": req.model_dump()}
    _pool.submit(_work, job_id, req)
    return {"job_id": job_id}


@app.get("/runs/{job_id}")
def get_run(job_id: str) -> dict:
    if job_id not in _jobs:
        raise HTTPException(404, "unknown job")
    return _jobs[job_id]


@app.get("/runs/{job_id}/posts.md", response_class=PlainTextResponse)
def get_posts(job_id: str) -> str:
    job = _jobs.get(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(404, "not ready")
    return Path(job["result"]["posts_md"]).read_text(encoding="utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000)
