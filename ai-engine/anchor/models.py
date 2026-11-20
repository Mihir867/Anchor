"""Every data contract in the engine, defined once."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

EvidenceKind = Literal["site", "article", "testimonial", "pricing", "structured"]


class Evidence(BaseModel):
    """One citable unit of source text. Every claim in a post must trace to these ids."""

    id: str
    kind: EvidenceKind
    url: str
    title: str = ""
    date: Optional[str] = None  # ISO YYYY-MM-DD when known
    text: str

    def render(self) -> str:
        meta = ", ".join(x for x in (self.kind, self.date or "undated", self.url) if x)
        title = f" {self.title} --" if self.title else ""
        return f"[{self.id}] ({meta}){title} {self.text}"


class BrandKit(BaseModel):
    url: str
    domain: str
    name: str
    tagline: str = ""
    description: str = ""
    primary_color: str = "#111827"
    secondary_color: Optional[str] = None
    background_color: str = "#FFFFFF"
    text_color: str = "#111111"
    accent_colors: list[str] = Field(default_factory=list)
    heading_font: Optional[str] = None
    body_font: Optional[str] = None
    font_faces: list[dict] = Field(default_factory=list)
    logo_path: Optional[str] = None
    screenshot_path: Optional[str] = None
    image_urls: list[str] = Field(default_factory=list)
    social_links: dict[str, str] = Field(default_factory=dict)


class Competitor(BaseModel):
    domain: str
    shared_keywords: int = 0  # organic keywords both domains rank for
    avg_position: float = 0.0
    organic_traffic: int = 0  # DataForSEO estimated monthly organic visits


class SearchKeyword(BaseModel):
    keyword: str
    search_volume: int = 0
    position: Optional[int] = None  # rank of the brand (or `competitor`) for it
    url: Optional[str] = None
    title: Optional[str] = None
    intent: Optional[str] = None  # informational / commercial / transactional / navigational
    competitor: Optional[str] = None  # set on content gaps: the rival that ranks for it


class MarketIntel(BaseModel):
    """Competitive and search-demand context (market.py). Steers selection and angle; it is
    never evidence, so nothing in it may be stated as fact in a post."""

    source: str = "dataforseo"
    location_code: int = 2840
    language_code: str = "en"
    competitors: list[Competitor] = Field(default_factory=list)
    brand_keywords: list[SearchKeyword] = Field(default_factory=list)
    gap_keywords: list[SearchKeyword] = Field(default_factory=list)


class TaskPack(BaseModel):
    """Everything a rollout needs. Built once per run; identical input to every rollout."""

    task_id: str
    url: str
    created_at: str
    industry: str
    industry_reason: str = ""
    max_posts: int = 3
    script: str = "LATIN"  # writing system of the brand's own site; posts are written in it
    language: str = "en"  # primary language subtag of the brand's site (<html lang>), e.g. en, nb, ja
    brand: BrandKit
    evidence: list[Evidence]
    pages_crawled: list[str] = Field(default_factory=list)
    market: Optional[MarketIntel] = None  # DataForSEO context, when configured
    market_note: str = ""  # what happened with DataForSEO (off / used / empty / refused), for the report
    already_posted: list[str] = Field(default_factory=list)  # headlines this brand posted in earlier runs
    # Thin pack (little site copy, no press): one post from the best fact, and no Harness² refine,
    # because rollouts on so little evidence score ~0 and give the improver nothing to learn from.
    thin: bool = False
    thin_reason: str = ""
    pooled_evidence: int = 0  # evidence items carried over from this brand's earlier runs
    stale_dropped: int = 0  # dated items older than ANCHOR_EVIDENCE_MAX_DAYS left out of the pack

    def evidence_by_id(self) -> dict[str, Evidence]:
        return {e.id: e for e in self.evidence}


# ---- LLM output contracts -------------------------------------------------------------


class MinedFact(BaseModel):
    headline: str = Field(description="Factual headline, <= 90 chars")
    category: str = Field(description="The post type: one of the loaded skill's post types, e.g. Customer story, "
                          "Feature how-to, Proof point, Release (dated only)")
    evidence_ids: list[str] = Field(description="Ids of the evidence items that prove it")
    quote: str = Field(description="Exact verbatim span copied from one cited evidence item")
    metrics: list[str] = Field(default_factory=list, description="Numbers exactly as written in evidence")
    named_entities: list[str] = Field(default_factory=list, description="Partners, customers, people, places")
    why_it_matters: str = Field(description="1-2 sentences, for the audience named by the skill")


class MinedFacts(BaseModel):
    facts: list[MinedFact]


class SkillChoice(BaseModel):
    skills: list[str] = Field(default_factory=list)


class Slide(BaseModel):
    title: str = Field(description="<= 60 chars, the point of this slide")
    bullets: list[str] = Field(description="2-3 bullets, each <= 120 chars, each a fact from the evidence")


class PostDraft(BaseModel):
    voice: str = Field(default="", description="The register chosen for this fact: celebratory, "
                       "authoritative, storyteller, inviting, urgent or insightful")
    linkedin: str
    instagram_caption: str
    hashtags: list[str] = Field(default_factory=list)
    poster_headline: str = Field(description="<= 80 chars, for the 1080x1350 visual")
    poster_kicker: str = Field(default="", description="<= 48 chars label above the headline")
    poster_stat: str = Field(default="", description="Optional big number copied from evidence")
    slides: list[Slide] = Field(default_factory=list,
                                description="Carousel slides AFTER the cover: each explains one part of the fact")


class CriticIssue(BaseModel):
    text: str
    problem: str


class CriticReport(BaseModel):
    unsupported_claims: list[CriticIssue] = Field(default_factory=list)
    voice_problems: list[CriticIssue] = Field(default_factory=list)


# ---- Rollout outputs -------------------------------------------------------------------


class Card(BaseModel):
    id: str
    status: Literal["verified", "rejected"]
    fact: MinedFact
    post: Optional[PostDraft] = None
    sources: list[Evidence] = Field(default_factory=list)
    attempts: int = 0
    problems: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # style remarks left after repairs (not factual)
    # True when no candidate passed every check and this post was delivered anyway so a run never
    # ends empty (generate.ensure_post). Its `problems` say what was not confirmed.
    fallback: bool = False
    poster_path: Optional[str] = None
    slide_paths: list[str] = Field(default_factory=list)
    pdf_path: Optional[str] = None


class RolloutResult(BaseModel):
    task_id: str
    brand: str
    industry: str
    skills_loaded: list[str]
    cards: list[Card]

    @property
    def verified(self) -> list[Card]:
        return [c for c in self.cards if c.status == "verified"]
