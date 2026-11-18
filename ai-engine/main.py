"""
FastAPI Microservice for Anchor AI Post Generation Engine
Exposes REST endpoints for the Node.js Express backend.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from engine.pipeline import run_post_generation_pipeline, PostDeck

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("fastapi_service")

app = FastAPI(
    title="Anchor AI Engine",
    description="Post Generation & Harness² Decision Engine Microservice",
    version="1.0.0",
)

# Enable CORS for local Express and React dev servers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    url: Optional[str] = None
    visual_data: Optional[Dict[str, Any]] = None
    semantic_data: Optional[Dict[str, Any]] = None
    max_cards: int = 3


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Anchor AI Microservice"}


@app.post("/api/generate", response_model=PostDeck)
def generate_posts(req: GenerateRequest):
    """
    Generates a certified PostDeck from visual and semantic crawl payloads.
    If payloads are omitted, loads the latest output_visuals.json and output_semantic.json.
    """
    ai_engine_dir = Path(__file__).resolve().parent

    visual = req.visual_data
    semantic = req.semantic_data

    # Fallback to local files if not passed in request body
    if not visual:
        v_path = ai_engine_dir / "output_visuals.json"
        if v_path.exists():
            with open(v_path, "r", encoding="utf-8") as f:
                visual = json.load(f)
        else:
            raise HTTPException(status_code=400, detail="visual_data not provided and output_visuals.json missing.")

    if not semantic:
        s_path = ai_engine_dir / "output_semantic.json"
        if s_path.exists():
            with open(s_path, "r", encoding="utf-8") as f:
                semantic = json.load(f)
        else:
            raise HTTPException(status_code=400, detail="semantic_data not provided and output_semantic.json missing.")

    try:
        deck = run_post_generation_pipeline(
            visual_data=visual,
            semantic_data=semantic,
            max_angles=req.max_cards,
        )
        return deck
    except Exception as e:
        logger.error(f"Generation pipeline error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
