"""
Brand Profile & Memory Unifier
Consolidates visual tokens (Crawler 1) and semantic intelligence (Crawler 2)
into a unified, verified BrandMemory model.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Testimonial(BaseModel):
    author: Optional[str] = None
    role: Optional[str] = None
    company: Optional[str] = None
    quote: str


class BrandMemory(BaseModel):
    url: str
    business_name: str
    tagline: str = ""
    hero_headline: str = ""
    hero_subheadline: Optional[str] = None
    description: str = ""
    
    # Value Proposition & Facts
    core_offerings: List[str] = Field(default_factory=list)
    advantages_and_usps: List[str] = Field(default_factory=list)
    customer_testimonials: List[Testimonial] = Field(default_factory=list)
    customer_names: List[str] = Field(default_factory=list)
    pricing_summary: List[str] = Field(default_factory=list)
    blog_headlines: List[str] = Field(default_factory=list)
    
    # Visual Design Tokens
    primary_color: str = "#000000"
    secondary_color: Optional[str] = None
    background_color: str = "#FFFFFF"
    text_color: str = "#111111"
    accent_colors: List[str] = Field(default_factory=list)
    heading_font: Optional[str] = None
    body_font: Optional[str] = None
    font_faces: List[Dict[str, Any]] = Field(default_factory=list)
    logo_urls: List[str] = Field(default_factory=list)
    favicon_url: Optional[str] = None
    screenshot_path: Optional[str] = None

    def to_grounding_context(self) -> str:
        """
        Formats the brand's verified facts into a concise markdown context block
        for LLM prompt grounding.
        """
        lines = [
            f"# Verified Brand Facts for {self.business_name} ({self.url})",
            f"**Tagline**: {self.tagline or self.hero_headline}",
        ]
        if self.description:
            lines.append(f"**Description**: {self.description}")
        if self.hero_subheadline:
            lines.append(f"**Hero Subhead**: {self.hero_subheadline}")

        if self.core_offerings:
            lines.append("\n### Core Offerings / Products:")
            for o in self.core_offerings[:6]:
                lines.append(f"- {o}")

        if self.advantages_and_usps:
            lines.append("\n### Advantages & USPs (Competitive Edges):")
            for u in self.advantages_and_usps[:8]:
                lines.append(f"- {u}")

        if self.customer_testimonials:
            lines.append("\n### Real Customer Quotes / Proof:")
            for t in self.customer_testimonials[:4]:
                attribution = f" — {t.author}" if t.author else ""
                lines.append(f"- \"{t.quote}\"{attribution}")

        if self.customer_names:
            lines.append(f"\n### Known Customers / Logos: {', '.join(self.customer_names[:10])}")

        if self.pricing_summary:
            lines.append("\n### Pricing / Plans:")
            for p in self.pricing_summary[:4]:
                lines.append(f"- {p}")

        if self.blog_headlines:
            lines.append("\n### Recent Themes / Blog Topics:")
            for b in self.blog_headlines[:5]:
                lines.append(f"- {b}")

        return "\n".join(lines)


def build_brand_memory(visual_data: Dict[str, Any], semantic_data: Dict[str, Any]) -> BrandMemory:
    """
    Merges visual and semantic outputs into a unified BrandMemory instance.
    """
    business_name = (
        semantic_data.get("business_name")
        or visual_data.get("title", "").split("|")[0].split("-")[0].strip()
        or "Brand"
    )

    testimonials_raw = semantic_data.get("customer_testimonials", [])
    parsed_testimonials = []
    for t in testimonials_raw:
        if isinstance(t, dict) and t.get("quote"):
            parsed_testimonials.append(Testimonial(**t))

    return BrandMemory(
        url=semantic_data.get("url") or visual_data.get("url", ""),
        business_name=business_name,
        tagline=semantic_data.get("tagline") or visual_data.get("description", ""),
        hero_headline=visual_data.get("hero_headline") or semantic_data.get("tagline", ""),
        hero_subheadline=visual_data.get("hero_subheadline"),
        description=visual_data.get("description", ""),
        core_offerings=semantic_data.get("core_offerings", []),
        advantages_and_usps=semantic_data.get("advantages_and_usps", []),
        customer_testimonials=parsed_testimonials,
        customer_names=semantic_data.get("customer_names", []),
        pricing_summary=semantic_data.get("pricing_summary", []),
        blog_headlines=semantic_data.get("blog_headlines", []),
        primary_color=visual_data.get("primary_color") or "#000000",
        secondary_color=visual_data.get("secondary_color"),
        background_color=visual_data.get("background_color") or "#FFFFFF",
        text_color=visual_data.get("text_color") or "#111111",
        accent_colors=visual_data.get("accent_colors", []),
        heading_font=visual_data.get("heading_font"),
        body_font=visual_data.get("body_font"),
        font_faces=visual_data.get("font_faces", []),
        logo_urls=visual_data.get("logo_urls", []),
        favicon_url=visual_data.get("favicon_url"),
        screenshot_path=visual_data.get("screenshot_path"),
    )
