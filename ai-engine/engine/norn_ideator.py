"""
Norn Ideator (Decision Layer)
Predicts and scores 3-4 distinct high-converting content angles
grounded strictly in the brand's verified scraped facts.
"""

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from .brand_profile import BrandMemory
from .groq_client import call_groq_json

logger = logging.getLogger("norn_ideator")


class AngleIdea(BaseModel):
    angle_id: str
    angle_type: str = Field(
        ...,
        description="One of: 'pain_point', 'contrarian_take', 'social_proof', 'actionable_framework'"
    )
    title: str = Field(..., description="Short internal label for this angle")
    hook_premise: str = Field(..., description="The core curiosity gap or tension to open with")
    core_insight: str = Field(..., description="The main value delivery or takeaway")
    key_facts_used: List[str] = Field(
        default_factory=list,
        description="Specific verified facts from the scraped data used in this angle"
    )
    target_audience: str = Field(..., description="Specific ICP who feels this pain most")
    target_emotion: str = Field(
        ...,
        description="Target psychological state (e.g., validation, urgency, relief, curiosity)"
    )
    confidence_score: float = Field(..., description="Predicted engagement score from 1.0 to 10.0")


class IdeationResult(BaseModel):
    brand_name: str
    angles: List[AngleIdea]


NORN_SYSTEM_PROMPT = """You are the Norn Decision Engine, a world-class viral B2B & B2C content strategist inspired by Native.no.

Your goal is to analyze verified brand facts and predict 3 to 4 distinct, high-converting social media content angles.

CRITICAL RULES:
1. ZERO GENERIC MARKETING FLUFF. Never output angles like "Why our product is great" or "Check out our new features".
2. ABSOLUTE GROUNDING: Every angle must be tethered to at least one real fact, quote, offering, or USP extracted from the website. No made-up stats or fabricated customer claims.
3. DIVERSE PSYCHOLOGICAL ANGLES: You must produce across these 4 distinct archetypes:
   - PAIN_POINT: Focus on an acute, relatable frustration your ICP suffers from daily, and the cost of ignoring it.
   - CONTRARIAN_TAKE: Challenge a widely accepted industry myth or call out how traditional software/methods are broken.
   - SOCIAL_PROOF: Anchor around real customer quotes, concrete use cases, or tangible outcomes mentioned on their site.
   - ACTIONABLE_FRAMEWORK: Provide an actionable 'how-to' or mental model that provides immediate educational value.
4. Output must be strictly valid JSON matching the requested schema.
"""


def generate_content_angles(brand: BrandMemory) -> List[AngleIdea]:
    """
    Generates 3-4 grounded content angles using Groq Llama 3.3 70B.
    """
    logger.info(f"Running Norn Ideation for brand: {brand.business_name}...")

    grounding_data = brand.to_grounding_context()

    user_prompt = f"""Analyze the following verified brand profile and generate 3 to 4 distinct, high-performing content angles for social posts:

{grounding_data}

Return JSON with this exact structure:
{{
  "brand_name": "{brand.business_name}",
  "angles": [
    {{
      "angle_id": "angle_1",
      "angle_type": "pain_point",
      "title": "Short descriptive title",
      "hook_premise": "The specific tension or observation to hook readers in the first 2 seconds",
      "core_insight": "The core educational or strategic takeaway",
      "key_facts_used": ["Scraped fact 1", "Scraped USP 2"],
      "target_audience": "Specific job title / persona",
      "target_emotion": "e.g. relief / eye-opening / validation",
      "confidence_score": 9.2
    }}
  ]
}}
"""

    raw_json = call_groq_json(
        system_prompt=NORN_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.6,
    )

    if isinstance(raw_json, list):
        items = raw_json
    elif isinstance(raw_json, dict):
        items = raw_json.get("angles", []) or raw_json.get("items", []) or [raw_json]
    else:
        items = []

    angles = []
    for item in items:
        if isinstance(item, dict):
            try:
                angles.append(AngleIdea(**item))
            except Exception as e:
                logger.warning(f"Skipping malformed angle item: {e}")

    logger.info(f"Norn generated {len(angles)} candidate content angles.")
    return angles
