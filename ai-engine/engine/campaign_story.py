"""
Dynamic Story Archetype & Campaign Engine (v4 — Bulletproof Normalization)
Generates diversified storytelling campaigns with defensive parsing and brand-aware image prompts.
"""

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from .brand_profile import BrandMemory
from .groq_client import call_groq_json

logger = logging.getLogger("campaign_story")


class DynamicStoryData(BaseModel):
    visual_layout: str = Field(
        default="cinematic_hero",
        description="One of: 'cinematic_hero', 'before_after', 'quote_spotlight', 'contrarian_minimal', 'step_flow', 'case_mosaic'"
    )
    badge_label: str = Field(default="CASE STUDY", description="Top tag/badge")
    headline: str = Field(default="Product Innovation", description="Main headline")
    subheadline: Optional[str] = Field(default="", description="Secondary context")
    body_text: Optional[str] = Field(default="", description="Core narrative or quote body")
    author_name: Optional[str] = Field(default="", description="Author name (for quote_spotlight)")
    author_role: Optional[str] = Field(default="", description="Author title")
    step_1: Optional[str] = Field(default="", description="Step 1 for step_flow")
    step_2: Optional[str] = Field(default="", description="Step 2 for step_flow")
    step_3: Optional[str] = Field(default="", description="Step 3 for step_flow")
    before_label: Optional[str] = Field(default="Before", description="Label for before frame")
    after_label: Optional[str] = Field(default="After", description="Label for after frame")
    metric_badge: Optional[str] = Field(default="", description="Center metric badge")
    image_prompt_primary: Optional[str] = Field(default="", description="Primary image prompt")
    image_prompt_secondary: Optional[str] = Field(default="", description="Secondary image prompt")
    image_prompt_tertiary: Optional[str] = Field(default="", description="Tertiary image prompt")


class DynamicCampaign(BaseModel):
    campaign_id: str
    campaign_title: str
    story: DynamicStoryData
    linkedin_text: str
    instagram_caption: str


CampaignPost = DynamicCampaign


ARCHETYPE_SYSTEM_PROMPT = """You are an elite creative director who matches the STORY GOAL to the IDEAL VISUAL FORMAT.

You MUST diversify visual layouts. Each campaign must use a DIFFERENT visual_layout from these 6:
1. 'cinematic_hero': Full-bleed photo with dark bottom gradient text.
2. 'before_after': Split-screen comparison (top vs bottom) with a bold metric badge in the center.
3. 'quote_spotlight': Magazine-style testimonial card with an executive headshot + powerful quote.
4. 'contrarian_minimal': Bold Swiss-style typography poster with zero photos.
5. 'step_flow': Numbered 3-step playbook (01, 02, 03) with 1 supporting contextual photo.
6. 'case_mosaic': 3-photo asymmetrical grid with metric headline.

CRITICAL RULES FOR IMAGE PROMPTS:
- Create photorealistic, detailed prompts strictly tailored to the BRAND'S ACTUAL INDUSTRY and products (software, AI, dev tools, e-commerce, real estate, etc.).
- Never use generic or unrelated industry prompts.

Output must be valid raw JSON only.
"""


def normalize_campaign_item(raw_item: Dict[str, Any], idx: int, brand: BrandMemory) -> Optional[DynamicCampaign]:
    """
    Bulletproof normalizer: handles flat dicts, nested 'story' dicts, missing fields,
    and alternative key names with zero crashes.
    """
    if not isinstance(raw_item, dict):
        return None

    # If the item itself accidentally contains a nested list under "campaigns"
    if "campaigns" in raw_item and isinstance(raw_item["campaigns"], list):
        return None

    campaign_id = raw_item.get("campaign_id") or f"campaign_{idx}"
    campaign_title = raw_item.get("campaign_title") or raw_item.get("title") or f"{brand.business_name} Story {idx}"
    linkedin_text = raw_item.get("linkedin_text") or raw_item.get("linkedin") or ""
    instagram_caption = raw_item.get("instagram_caption") or raw_item.get("instagram") or ""

    # Story data: could be inside raw_item["story"], or flattened directly in raw_item!
    story_source = raw_item.get("story") if isinstance(raw_item.get("story"), dict) else raw_item

    # Extract layout
    layout = (
        story_source.get("visual_layout")
        or story_source.get("layout")
        or ("before_after" if idx == 2 else ("quote_spotlight" if idx == 3 else "cinematic_hero"))
    )

    story = DynamicStoryData(
        visual_layout=str(layout).lower().strip(),
        badge_label=story_source.get("badge_label") or "INNOVATION",
        headline=story_source.get("headline") or campaign_title,
        subheadline=story_source.get("subheadline") or "",
        body_text=story_source.get("body_text") or "",
        author_name=story_source.get("author_name") or "",
        author_role=story_source.get("author_role") or "",
        step_1=story_source.get("step_1") or "",
        step_2=story_source.get("step_2") or "",
        step_3=story_source.get("step_3") or "",
        before_label=story_source.get("before_label") or "Before",
        after_label=story_source.get("after_label") or f"With {brand.business_name}"[:22],
        metric_badge=story_source.get("metric_badge") or "",
        image_prompt_primary=story_source.get("image_prompt_primary") or "",
        image_prompt_secondary=story_source.get("image_prompt_secondary") or "",
        image_prompt_tertiary=story_source.get("image_prompt_tertiary") or "",
    )

    return DynamicCampaign(
        campaign_id=str(campaign_id),
        campaign_title=str(campaign_title),
        story=story,
        linkedin_text=str(linkedin_text),
        instagram_caption=str(instagram_caption),
    )


def generate_diverse_campaigns(brand: BrandMemory, count: int = 3) -> List[DynamicCampaign]:
    """
    Generates diversified storytelling campaigns with bulletproof parsing.
    """
    logger.info(f"Generating {count} diversified multi-archetype campaigns for: {brand.business_name}...")

    grounding_data = brand.to_grounding_context()

    user_prompt = f"""Generate {count} completely different social media campaigns for this brand, each using a UNIQUE visual_layout:

{grounding_data}

Return JSON with this exact structure:
{{
  "campaigns": [
    {{
      "campaign_id": "campaign_1",
      "campaign_title": "Descriptive title",
      "visual_layout": "cinematic_hero | before_after | quote_spotlight | contrarian_minimal | step_flow | case_mosaic",
      "badge_label": "Category tag (e.g. 'FLAGSHIP', 'TRANSFORMATION', 'CASE STUDY')",
      "headline": "Bold compelling headline",
      "subheadline": "Context or outcome line",
      "body_text": "Story summary or direct quote",
      "author_name": "Executive or customer name (if applicable)",
      "author_role": "Executive title, Company",
      "step_1": "Step 1 text (if step_flow)",
      "step_2": "Step 2 text (if step_flow)",
      "step_3": "Step 3 text (if step_flow)",
      "before_label": "e.g. Manual Chaos",
      "after_label": "e.g. With {brand.business_name}",
      "metric_badge": "e.g. 10x FASTER",
      "image_prompt_primary": "Photorealistic prompt specifically about {brand.business_name}'s product or industry",
      "image_prompt_secondary": "Photorealistic prompt for secondary image",
      "image_prompt_tertiary": "Photorealistic prompt for tertiary image",
      "linkedin_text": "Full LinkedIn narrative post with line breaks",
      "instagram_caption": "Engaging caption with hashtags"
    }}
  ]
}}
"""

    raw_json = call_groq_json(
        system_prompt=ARCHETYPE_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.7,
    )

    # Flatten out any nested lists or dicts
    candidates: List[Dict[str, Any]] = []

    def extract_dicts(obj: Any):
        if isinstance(obj, list):
            for elem in obj:
                extract_dicts(elem)
        elif isinstance(obj, dict):
            # If it's a wrapper dict like {"campaigns": [...]} or {"items": [...]}
            found_inner_list = False
            for k in ["campaigns", "items", "cards", "data"]:
                if k in obj and isinstance(obj[k], list):
                    extract_dicts(obj[k])
                    found_inner_list = True
            if not found_inner_list:
                candidates.append(obj)

    extract_dicts(raw_json)

    campaigns: List[DynamicCampaign] = []
    for i, item in enumerate(candidates, start=1):
        parsed = normalize_campaign_item(item, i, brand)
        if parsed:
            campaigns.append(parsed)

    logger.info(f"Successfully normalized {len(campaigns)} multi-archetype campaign stories.")
    return campaigns
