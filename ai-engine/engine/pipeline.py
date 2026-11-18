"""
Anchor Generation Pipeline (v4 — Fact-Grounded & Evidence-Backed)
Orchestrates:
  Deep Scraped Articles -> Top-3 Verified Milestones -> Fact-Grounded Posts -> FLUX Visuals -> Harness² Audit
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .brand_profile import BrandMemory, build_brand_memory
from .milestone_miner import VerifiedMilestone, mine_top_3_milestones
from .fact_post_generator import FactPostCard, draft_and_audit_milestone_post
from crawlers.deep_article_crawler import deep_crawl_articles

logger = logging.getLogger("generation_pipeline")


class FactPostDeck(BaseModel):
    brand_name: str
    brand_url: str
    total_cards: int
    top_milestones: List[VerifiedMilestone]
    cards: List[FactPostCard]


def run_post_generation_pipeline(
    visual_data: Dict[str, Any],
    semantic_data: Dict[str, Any],
    max_angles: int = 3,
) -> FactPostDeck:
    """
    Executes the fact-grounded post generation pipeline.
    """
    ai_engine_dir = Path(__file__).resolve().parent.parent
    brand = build_brand_memory(visual_data, semantic_data)
    logger.info(f"Initialized Brand Memory for: {brand.business_name} ({brand.url})")

    # Step 1: Check for or perform deep article crawling
    articles_file = ai_engine_dir / "output_deep_articles.json"
    scraped_articles: List[Dict[str, Any]] = []

    if articles_file.exists():
        try:
            with open(articles_file, "r", encoding="utf-8") as f:
                scraped_articles = json.load(f)
        except Exception:
            pass

    # Ensure articles have actual verifiable proof (metrics or quotes)
    quality_count = sum(
        1 for a in scraped_articles
        if len(a.get("metrics_detected", [])) > 0 or len(a.get("key_quotes", [])) > 0
    )

    if not scraped_articles or quality_count < 2:
        logger.info(f"Articles on disk sparse or low-yield ({quality_count} verified stories). Crawling with Internet Intelligence fallback...")
        fresh_articles = deep_crawl_articles(brand.url, max_articles=5, brand_name=brand.business_name)
        scraped_articles = [a.model_dump() for a in fresh_articles]
        with open(articles_file, "w", encoding="utf-8") as f:
            json.dump(scraped_articles, f, indent=2)

    # Step 2: Mine and rank the Top 3 Verified Milestones
    logger.info("Step 2: Mining and ranking Top 3 Verified Milestones...")
    top_3_milestones = mine_top_3_milestones(brand, scraped_articles)
    if not top_3_milestones:
        raise ValueError("Could not extract verified milestones from scraped content.")

    # Step 3: For each verified milestone, generate grounded copy + bespoke image
    cards: List[FactPostCard] = []
    for idx, milestone in enumerate(top_3_milestones[:max_angles], start=1):
        card = draft_and_audit_milestone_post(
            brand=brand,
            milestone=milestone,
            card_index=idx,
        )
        cards.append(card)

    deck = FactPostDeck(
        brand_name=brand.business_name,
        brand_url=brand.url,
        total_cards=len(cards),
        top_milestones=top_3_milestones,
        cards=cards,
    )

    logger.info(f"\nSuccessfully generated {len(cards)} Fact-Grounded Milestone Cards for {brand.business_name}!")
    return deck
