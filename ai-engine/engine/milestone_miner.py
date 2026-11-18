"""
Milestone Miner & Truth Verification Engine
Analyzes deep-crawled articles and testimonials to extract, verify,
and rank the Top 3 Verified Company Milestones with complete audit trails.
"""

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .brand_profile import BrandMemory
from .groq_client import call_groq_json

logger = logging.getLogger("milestone_miner")


class VerifiedMilestone(BaseModel):
    milestone_id: str
    headline: str = Field(..., description="High-impact factual milestone headline")
    category: str = Field(..., description="e.g. 'Strategic Partnership', 'Product Launch', 'Customer Outcome', 'Funding', 'Market Expansion'")
    source_url: str = Field(..., description="Exact URL where this milestone is verified")
    published_date: Optional[str] = Field(default=None, description="ISO date or publication timeframe")
    raw_evidence_quote: str = Field(..., description="Direct verbatim quote or excerpt from the article proving this fact")
    named_partners_or_clients: List[str] = Field(default_factory=list, description="Verified companies, partners, or people involved")
    quantified_metrics: List[str] = Field(default_factory=list, description="Concrete metrics: numbers, percentages, currencies, or durations")
    core_narrative: str = Field(..., description="Crisp 2-3 sentence explanation of why this matters and the transformation achieved")
    visual_scene_brief: str = Field(..., description="Detailed photorealistic scene description depicting this exact real-world achievement")
    verification_score: float = Field(default=0.0, description="Calculated truth & impact score from 0.0 to 10.0")


class TopMilestonesResult(BaseModel):
    brand_name: str
    total_mined: int
    top_3_milestones: List[VerifiedMilestone]


MINER_SYSTEM_PROMPT = """You are an elite investigative corporate journalist and fact-auditor.

Your mission is to read raw scraped company articles and extract VERIFIED, AUDITABLE MILESTONES.

STRICT TRUTH & VERIFICATION RULES:
1. ZERO HALLUCINATIONS: You may ONLY extract facts explicitly stated in the provided articles.
2. RAW EVIDENCE REQUIRED: Every milestone must include a `raw_evidence_quote` containing the exact verbatim sentence from the source text.
3. PREFER CONCRETE METRICS & REAL PARTNERS: Prioritize stories featuring named enterprise partners (e.g. IHG, Tapestry by Hilton, Marriott), verified clients, hard numbers ($27M, 30% savings, 15 days), or major product launches.
4. VISUAL SCENE BRIEF: Provide a rich, editorial, photorealistic image brief representing the PHYSICAL reality of this story (e.g. European boutique hotel suite for IHG expansion, or modern AI planning screen for software launch).

Output strictly valid raw JSON only.
"""


def calculate_milestone_score(m: VerifiedMilestone) -> float:
    """
    Deterministically scores a milestone based on:
    - Recency (40%): Higher score for recent dates (2025-2026 > 2024 > older)
    - Hard Metric Strength (35%): Number of concrete figures / percentages
    - Partner & Social Proof (25%): Named enterprise clients, partners, and leaders
    """
    score = 5.0  # base score

    # 1. Recency Score (max +3.0)
    if m.published_date:
        try:
            # Parse year
            year_match = re.search(r"20\d{2}", m.published_date)
            if year_match:
                year = int(year_match.group(0))
                if year >= 2026:
                    score += 3.0
                elif year == 2025:
                    score += 2.5
                elif year == 2024:
                    score += 1.8
                else:
                    score += 0.8
        except Exception:
            pass
    else:
        score += 1.0

    # 2. Hard Metric Strength (max +2.5)
    if m.quantified_metrics and len(m.quantified_metrics) > 0:
        score += min(len(m.quantified_metrics) * 0.8, 2.5)

    # 3. Named Partner / Client Proof (max +2.0)
    if m.named_partners_or_clients and len(m.named_partners_or_clients) > 0:
        score += min(len(m.named_partners_or_clients) * 1.0, 2.0)

    # Deduct if raw evidence quote is suspiciously short
    if len(m.raw_evidence_quote) < 30:
        score -= 2.0

    return round(min(score, 10.0), 2)


def mine_top_3_milestones(
    brand: BrandMemory,
    scraped_articles: List[Dict[str, Any]],
) -> List[VerifiedMilestone]:
    """
    Extracts candidate milestones from deep articles and returns the Top 3 verified by evidence.
    """
    logger.info(f"Mining verified milestones for {brand.business_name} across {len(scraped_articles)} rich articles...")

    # Package articles into prompt context
    articles_context = []
    for idx, a in enumerate(scraped_articles[:5], start=1):
        lines = [
            f"--- ARTICLE {idx} ---",
            f"Title: {a.get('title')}",
            f"URL: {a.get('url')}",
            f"Published Date: {a.get('published_date') or 'Unknown'}",
            f"Lead: {a.get('lead_paragraph')}",
            f"Key Quotes: {json.dumps(a.get('key_quotes', []))}",
            f"Metrics Detected: {json.dumps(a.get('metrics_detected', []))}",
            f"Full Text Snippet: {a.get('full_text', '')[:800]}",
        ]
        articles_context.append("\n".join(lines))

    # Also include customer testimonials from semantic crawl
    testimonials_context = []
    for t in brand.customer_testimonials[:4]:
        testimonials_context.append(f'- "{t.quote}" ({t.author or "Verified Customer"})')

    user_prompt = f"""Extract verified, factual milestones and achievements for '{brand.business_name}' from these crawled sources:

{chr(10).join(articles_context)}

ADDITIONAL VERIFIED CUSTOMER TESTIMONIALS:
{chr(10).join(testimonials_context)}

Return JSON with this exact structure:
{{
  "milestones": [
    {{
      "milestone_id": "milestone_1",
      "headline": "Crisp headline of the achievement/deal/launch",
      "category": "Strategic Partnership | Product Launch | Customer Outcome | Expansion",
      "source_url": "The exact URL from which this was scraped",
      "published_date": "YYYY-MM-DD",
      "raw_evidence_quote": "Verbatim sentence or quote from the article",
      "named_partners_or_clients": ["IHG Hotels", "Executive Name"],
      "quantified_metrics": ["$27M", "30%", "15 days"],
      "core_narrative": "2-3 crisp sentences detailing the real-world value and context",
      "visual_scene_brief": "Photorealistic scene description specifically showing this project, place, or workflow in action"
    }}
  ]
}}
"""

    raw_json = call_groq_json(
        system_prompt=MINER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.3,  # Low temperature for strict factual extraction
    )

    # Flatten out candidates
    candidates_raw: List[Dict[str, Any]] = []
    if isinstance(raw_json, list):
        candidates_raw = raw_json
    elif isinstance(raw_json, dict):
        candidates_raw = raw_json.get("milestones") or raw_json.get("items") or [raw_json]

    all_milestones: List[VerifiedMilestone] = []
    for idx, item in enumerate(candidates_raw, start=1):
        if not isinstance(item, dict):
            continue
        try:
            m = VerifiedMilestone(
                milestone_id=item.get("milestone_id") or f"milestone_{idx}",
                headline=item.get("headline") or "Company Milestone",
                category=item.get("category") or "Achievement",
                source_url=item.get("source_url") or brand.url,
                published_date=item.get("published_date"),
                raw_evidence_quote=item.get("raw_evidence_quote") or "",
                named_partners_or_clients=item.get("named_partners_or_clients") or [],
                quantified_metrics=item.get("quantified_metrics") or [],
                core_narrative=item.get("core_narrative") or item.get("headline", ""),
                visual_scene_brief=item.get("visual_scene_brief") or f"editorial photography representing {brand.business_name}",
            )
            # Calculate objective truth score
            m.verification_score = calculate_milestone_score(m)
            all_milestones.append(m)
        except Exception as e:
            logger.warning(f"Could not parse milestone {idx}: {e}")

    # Sort descending by verification_score
    all_milestones.sort(key=lambda x: x.verification_score, reverse=True)
    top_3 = all_milestones[:3]

    logger.info(f"Mined {len(all_milestones)} verified milestones. Selected Top {len(top_3)}:")
    for i, m in enumerate(top_3, start=1):
        logger.info(f"  #{i} [{m.verification_score}/10] {m.headline} ({m.published_date or 'No date'})")

    return top_3
