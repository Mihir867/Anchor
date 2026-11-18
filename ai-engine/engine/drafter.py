"""
Multi-Channel Post Drafter
Drafts channel-native social posts (LinkedIn, X/Twitter, Instagram Carousel)
tailored to a specific Norn Angle and verified Brand facts.
"""

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from .brand_profile import BrandMemory
from .norn_ideator import AngleIdea
from .groq_client import call_groq_json

logger = logging.getLogger("drafter")


class CarouselSlide(BaseModel):
    slide_number: int
    header: str
    body: str


class GeneratedDraft(BaseModel):
    angle_id: str
    angle_type: str
    angle_title: str
    
    # LinkedIn
    linkedin_text: str
    linkedin_hook: str
    
    # X / Twitter
    twitter_text: str
    
    # Instagram
    instagram_caption: str
    instagram_slides: List[CarouselSlide] = Field(default_factory=list)


DRAFTER_SYSTEM_PROMPT = """You are an elite, top-1% social media ghostwriter for founders, tech executives, and high-growth brands.
Your posts routinely get thousands of reposts, bookmarks, and meaningful comments because they are deeply insightful, human, and zero-cringe.

CRITICAL VOICE & ANTI-CLICHÉ RULES:
1. BANNED PHRASES: Never use "In today's fast-paced world", "Unlock the power of", "Game changer", "Dive deep", "delve", "Revolutionize", "Leverage", "Look no further", or "Supercharge".
2. BANNED FORMATTING: No emoji soup (limit to 0-2 purposeful emojis per post). Do not end LinkedIn posts with "Agree? Thoughts? Let me know in the comments 👇".
3. CHANNEL SPECIFICS:
   - LINKEDIN: Lines 1-2 MUST hook the reader before the "see more" truncate. Use generous single-line breaks. Sound like an experienced operator talking peer-to-peer, not a corporate press release.
   - X (TWITTER): Crisp, sharp, punchy. Under 280 characters OR a 2-3 tweet mini thread where every word counts. No filler.
   - INSTAGRAM CAROUSEL: 4 to 5 punchy slides. Slide 1 is a bold curiosity hook. Slides 2-4 deliver the core meat. Final slide is the punchline / save trigger.
4. Output must be strictly valid JSON.
"""


def draft_multi_channel_posts(brand: BrandMemory, angle: AngleIdea) -> GeneratedDraft:
    """
    Drafts posts for LinkedIn, X, and Instagram for a given angle.
    """
    logger.info(f"Drafting posts for angle: '{angle.title}' ({angle.angle_type})...")

    grounding_data = brand.to_grounding_context()

    user_prompt = f"""Draft high-performing social posts across LinkedIn, X (Twitter), and Instagram for this angle:

BRAND: {brand.business_name}
TARGET AUDIENCE: {angle.target_audience}
CHOSEN ANGLE TYPE: {angle.angle_type}
HOOK PREMISE: {angle.hook_premise}
CORE INSIGHT: {angle.core_insight}
VERIFIED FACTS TO ANCHOR TO: {', '.join(angle.key_facts_used)}

VERIFIED BRAND CONTEXT:
{grounding_data}

Return JSON with this exact structure:
{{
  "angle_id": "{angle.angle_id}",
  "angle_type": "{angle.angle_type}",
  "angle_title": "{angle.title}",
  "linkedin_hook": "First 1-2 lines before the fold",
  "linkedin_text": "Full LinkedIn post text with proper linebreaks and whitespace formatting",
  "twitter_text": "High-impact tweet under 280 characters or punchy breakdown",
  "instagram_caption": "Captivating IG caption with 3-4 natural hashtags at the end",
  "instagram_slides": [
    {{"slide_number": 1, "header": "Slide 1 Hook", "body": "1-2 lines of teaser text"}},
    {{"slide_number": 2, "header": "Slide 2 Concept", "body": "Core insight"}},
    {{"slide_number": 3, "header": "Slide 3 Proof/Method", "body": "Concrete fact or breakdown"}},
    {{"slide_number": 4, "header": "Slide 4 Takeaway", "body": "Actionable takeaway / CTA"}}
  ]
}}
"""

    raw_json = call_groq_json(
        system_prompt=DRAFTER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.7,
    )

    slides = []
    for s in raw_json.get("instagram_slides", []):
        try:
            slides.append(CarouselSlide(**s))
        except Exception:
            pass

    return GeneratedDraft(
        angle_id=angle.angle_id,
        angle_type=angle.angle_type,
        angle_title=angle.title,
        linkedin_hook=raw_json.get("linkedin_hook", ""),
        linkedin_text=raw_json.get("linkedin_text", ""),
        twitter_text=raw_json.get("twitter_text", ""),
        instagram_caption=raw_json.get("instagram_caption", ""),
        instagram_slides=slides,
    )
