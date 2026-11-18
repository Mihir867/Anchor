"""
Standalone Test Runner for Fact-Grounded Milestone Posts & Harness² Audit
"""

import json
import logging
import sys
from pathlib import Path
from engine.pipeline import run_post_generation_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("test_runner")


def main():
    ai_engine_dir = Path(__file__).resolve().parent

    visual_path = ai_engine_dir / "output_visuals.json"
    semantic_path = ai_engine_dir / "output_semantic.json"

    if not visual_path.exists() or not semantic_path.exists():
        logger.error("Crawl outputs not found! Ensure output_visuals.json and output_semantic.json exist.")
        sys.exit(1)

    logger.info("Loading crawled data...")
    with open(visual_path, "r", encoding="utf-8") as f:
        visual_data = json.load(f)
    with open(semantic_path, "r", encoding="utf-8") as f:
        semantic_data = json.load(f)

    logger.info(f"Target Brand: {semantic_data.get('business_name', 'Unknown')}")
    logger.info("Executing Fact-Grounded Milestone Extraction & Post Generation Pipeline...")

    deck = run_post_generation_pipeline(
        visual_data=visual_data,
        semantic_data=semantic_data,
        max_angles=3,
    )

    output_deck_path = ai_engine_dir / "output_deck_v2.json"
    with open(output_deck_path, "w", encoding="utf-8") as f:
        json.dump(deck.model_dump(), f, indent=2)

    logger.info(f"Generated Deck saved to {output_deck_path.resolve()}")

    print("\n" + "=" * 70)
    print(f"🎉 TOP 3 VERIFIED MILESTONE POSTS GENERATED FOR: {deck.brand_name.upper()}")
    print("=" * 70)

    for card in deck.cards:
        m = card.milestone
        print(f"\n📌 CARD [{card.card_id.upper()}]: {m.headline}")
        print(f"📂 Category:        {m.category}")
        print(f"🔗 Source URL:      {m.source_url}")
        print(f"📅 Published Date:  {m.published_date or 'Recent'}")
        print(f"📜 Raw Evidence:    \"{m.raw_evidence_quote[:120]}...\"")
        print(f"👥 Partners/Clients: {', '.join(m.named_partners_or_clients) if m.named_partners_or_clients else 'None'}")
        print(f"📊 Hard Metrics:    {', '.join(m.quantified_metrics) if m.quantified_metrics else 'None'}")
        print(f"⭐ Harness² Score:  {card.harness_fact_score}/10 (Audit: {card.audit_notes[0]})")
        print(f"🖼️  Image Prompt:    {card.image_prompt[:90]}...")
        print(f"🎨 Poster Path:     {card.poster_image_path}")
        print("-" * 60)
        print("🔷 [LINKEDIN COPY]:")
        print(card.linkedin_text)
        print("-" * 60)
        print("🐦 [TWITTER / X COPY]:")
        print(card.twitter_text)
        print("-" * 60)
        print("📸 [INSTAGRAM CAPTION]:")
        print(card.instagram_caption)
        print("=" * 70)


if __name__ == "__main__":
    main()
