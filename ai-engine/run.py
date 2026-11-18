"""
Anchor End-to-End Runner
Run the entire pipeline on ANY website with a single command:
  python run.py https://example.com

Orchestrates:
  1. Visual & Brand Design Token Crawler (Colors, Typography, Logos)
  2. Semantic Intelligence Crawler (FAQs, Testimonials, Sitemap)
  3. Deep Article Crawler (Full body texts, published dates, metrics)
  4. Top 3 Verified Milestone Miner (Recency, Proof, Evidence Quotes)
  5. Social Post Drafter (LinkedIn, X, Instagram)
  6. Harness² Truth-Verification Audit & FLUX.1 Image Rendering
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("anchor_runner")

# Imports
from crawlers.visual_crawler import extract_visual_tokens
from crawlers.semantic_crawler import extract_semantic_intelligence
from crawlers.deep_article_crawler import deep_crawl_articles
from engine.pipeline import run_post_generation_pipeline


def normalize_url(url: str) -> str:
    """Ensures URL starts with https:// and has valid formatting."""
    url = url.strip()
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url.lstrip("/")
    return url


def run_full_pipeline_for_product(target_url: str, max_posts: int = 3):
    ai_engine_dir = Path(__file__).resolve().parent
    url = normalize_url(target_url)

    logger.info("=" * 70)
    logger.info(f"🚀 STARTING ANCHOR AI ENGINE FOR: {url}")
    logger.info("=" * 70)

    # -------------------------------------------------------------
    # STEP 1: Visual Asset & Design Token Extraction
    # -------------------------------------------------------------
    logger.info("\n[STAGE 1/4] Crawling Visual Design Tokens (Colors, Fonts, Logos)...")
    screenshot_path = str(ai_engine_dir / "hero_screenshot.png")
    visual_tokens = asyncio.run(
        extract_visual_tokens(url, output_screenshot_path=screenshot_path)
    )
    visual_data = visual_tokens.model_dump()
    with open(ai_engine_dir / "output_visuals.json", "w", encoding="utf-8") as f:
        json.dump(visual_data, f, indent=2)
    logger.info(f"✓ Visual Tokens Extracted: Primary Color={visual_tokens.primary_color}, Heading Font={visual_tokens.heading_font}")

    # -------------------------------------------------------------
    # STEP 2: Semantic Intelligence Extraction
    # -------------------------------------------------------------
    logger.info("\n[STAGE 2/4] Crawling Semantic Intelligence (About, FAQs, Testimonials)...")
    semantic_obj = extract_semantic_intelligence(url)
    semantic_data = semantic_obj.model_dump()
    with open(ai_engine_dir / "output_semantic.json", "w", encoding="utf-8") as f:
        json.dump(semantic_data, f, indent=2)
    logger.info(f"✓ Semantic Data Extracted: Brand={semantic_obj.business_name}, Pages Scraped={len(semantic_obj.scraped_pages)}")

    # -------------------------------------------------------------
    # STEP 3: Deep Article & Evidence Extraction
    # -------------------------------------------------------------
    logger.info("\n[STAGE 3/4] Deep Crawling Recent Articles, News & Case Studies...")
    articles = deep_crawl_articles(url, max_articles=5, brand_name=semantic_obj.business_name)
    articles_data = [a.model_dump() for a in articles]
    with open(ai_engine_dir / "output_deep_articles.json", "w", encoding="utf-8") as f:
        json.dump(articles_data, f, indent=2)
    logger.info(f"✓ Deep Articles Gathered: {len(articles)} full-body publications with timestamps.")

    # -------------------------------------------------------------
    # STEP 4: Post Generation, Harness² Audit, & Visual Rendering
    # -------------------------------------------------------------
    logger.info("\n[STAGE 4/4] Mining Top 3 Milestones & Generating Fact-Grounded Posts...")
    deck = run_post_generation_pipeline(
        visual_data=visual_data,
        semantic_data=semantic_data,
        max_angles=max_posts,
    )

    deck_path = ai_engine_dir / "output_deck_v2.json"
    with open(deck_path, "w", encoding="utf-8") as f:
        json.dump(deck.model_dump(), f, indent=2)

    # -------------------------------------------------------------
    # DISPLAY FINAL RESULTS
    # -------------------------------------------------------------
    print("\n" + "=" * 75)
    print(f"🎉 GENERATION COMPLETE FOR: {deck.brand_name.upper()} ({deck.brand_url})")
    print(f"💾 Full Deck JSON: {deck_path.resolve()}")
    print("=" * 75)

    for card in deck.cards:
        m = card.milestone
        print(f"\n📌 CARD [{card.card_id.upper()}]: {m.headline}")
        print(f"📂 Category:        {m.category}")
        print(f"🔗 Source:          {m.source_url}")
        print(f"📅 Published Date:  {m.published_date or 'Recent'}")
        print(f"📜 Raw Evidence:    \"{m.raw_evidence_quote[:120]}...\"")
        print(f"👥 Partners/Clients: {', '.join(m.named_partners_or_clients) if m.named_partners_or_clients else 'Company Release'}")
        print(f"📊 Hard Metrics:    {', '.join(m.quantified_metrics) if m.quantified_metrics else 'Strategic Action'}")
        print(f"⭐ Harness² Score:  {card.harness_fact_score}/10 (Audit: {card.audit_notes[0]})")
        print(f"🎨 Poster PNG:      {card.poster_image_path}")
        print("-" * 65)
        print("🔷 [LINKEDIN POST]:")
        print(card.linkedin_text)
        print("-" * 65)
        print("🐦 [TWITTER / X POST]:")
        print(card.twitter_text)
        print("-" * 65)
        print("📸 [INSTAGRAM CAPTION]:")
        print(card.instagram_caption)
        print("=" * 75)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://inhabitr.ai"
    posts_count = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    run_full_pipeline_for_product(target, max_posts=posts_count)
