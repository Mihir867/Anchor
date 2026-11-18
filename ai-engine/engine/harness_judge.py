"""
Harness² Recursive Probe & Compose Engine (v3)
Audits multi-archetype narrative campaigns for fact-grounding, anti-cliché, and platform voice.
"""

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from .brand_profile import BrandMemory
from .campaign_story import DynamicCampaign
from .groq_client import call_groq_json

logger = logging.getLogger("harness_judge")


class AuditScore(BaseModel):
    anti_cliche_score: float = Field(..., description="0-10 score for avoiding buzzwords and generic AI tone")
    fact_grounding_score: float = Field(..., description="0-10 score verifying claims match scraped brand facts")
    narrative_tension_score: float = Field(..., description="0-10 score for story flow, metric punch, and hook")
    platform_voice_score: float = Field(..., description="0-10 score for platform-native cadence and tone")
    overall_score: float = Field(..., description="Weighted average score")
    passed: bool = Field(..., description="True if overall_score >= 8.5")
    critique_points: List[str] = Field(default_factory=list, description="Specific feedback on what to fix")


CAMPAIGN_JUDGE_PROMPT = """You are an unforgiving, elite editorial director and fact-checking auditor inspired by Native.no.

Audit this storytelling campaign against 4 criteria:
1. ANTI-CLICHE (0-10): Zero buzzwords ("game-changer", "in today's fast-paced world", "revolutionize"). No emoji spam.
2. FACT GROUNDING (0-10): All metrics, solutions, and claims must match the provided brand context.
3. NARRATIVE TENSION (0-10): Does the headline and visual angle stop the scroll?
4. PLATFORM VOICE (0-10): High-signal, peer-to-peer execution.

Output strictly valid raw JSON.
"""


def probe_campaign(campaign: DynamicCampaign, brand: BrandMemory) -> AuditScore:
    """
    Evaluates a dynamic multi-archetype campaign.
    """
    grounding = brand.to_grounding_context()

    user_prompt = f"""Audit the following campaign for brand '{brand.business_name}':

BRAND CONTEXT:
{grounding}

ARCHETYPE: {campaign.story.visual_layout}
HEADLINE: {campaign.story.headline}
STORY BODY / SUBHEAD: {campaign.story.body_text or campaign.story.subheadline}

LINKEDIN COPY:
{campaign.linkedin_text}

INSTAGRAM CAPTION:
{campaign.instagram_caption}

Return JSON with this exact structure:
{{
  "anti_cliche_score": 9.0,
  "fact_grounding_score": 9.0,
  "narrative_tension_score": 8.5,
  "platform_voice_score": 9.0,
  "overall_score": 8.85,
  "passed": true,
  "critique_points": ["Strong hook", "Well-grounded"]
}}
"""

    raw_json = call_groq_json(
        system_prompt=CAMPAIGN_JUDGE_PROMPT,
        user_prompt=user_prompt,
        temperature=0.2,
    )

    anti = float(raw_json.get("anti_cliche_score", 8.5))
    fact = float(raw_json.get("fact_grounding_score", 8.5))
    narrative = float(raw_json.get("narrative_tension_score", 8.5))
    voice = float(raw_json.get("platform_voice_score", 8.5))
    overall = round((anti * 0.25) + (fact * 0.35) + (narrative * 0.25) + (voice * 0.15), 2)
    passed = overall >= 8.5

    return AuditScore(
        anti_cliche_score=anti,
        fact_grounding_score=fact,
        narrative_tension_score=narrative,
        platform_voice_score=voice,
        overall_score=overall,
        passed=passed,
        critique_points=raw_json.get("critique_points", []),
    )
