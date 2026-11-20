"""All runtime settings, read once from the environment (.env files are loaded first).

Any OpenAI-compatible endpoint works: Groq (default), Ollama, vLLM, OpenRouter, Together,
Gemini's OpenAI endpoint. Point ANCHOR_BASE_URL at it and set the model ids.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ENGINE_DIR = Path(__file__).resolve().parent.parent
for _env in (ENGINE_DIR / ".env", ENGINE_DIR.parent / ".env"):
    if _env.is_file():
        load_dotenv(_env, override=False)


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _env_list(name: str, default: str) -> list[str]:
    raw = _env(name, default)
    return [] if raw.lower() == "none" else [v.strip() for v in raw.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    base_url: str = field(default_factory=lambda: _env("ANCHOR_BASE_URL", "https://api.groq.com/openai/v1"))
    api_key: str = field(
        default_factory=lambda: _env("ANCHOR_API_KEY") or _env("GROQ_API_KEY") or _env("GROQ_KEY")
    )
    # Model specs are `provider:model` (see llm.PROVIDERS). Writer/miner; the critic defaults to a
    # DIFFERENT model family so it does not grade its own style.
    model: str = field(default_factory=lambda: _env("ANCHOR_MODEL", "groq:openai/gpt-oss-120b"))
    critic_model: str = field(default_factory=lambda: _env("ANCHOR_CRITIC_MODEL", "groq:qwen/qwen3.8-27b"))
    # Harness² improver (proposes harness edits, composes, reflects) and selector.
    proposer_model: str = field(default_factory=lambda: _env("ANCHOR_PROPOSER_MODEL", "groq:openai/gpt-oss-120b"))
    selector_model: str = field(default_factory=lambda: _env("ANCHOR_SELECTOR_MODEL", "groq:qwen/qwen3.8-27b"))
    # Tried in order after each role's own model; entries whose provider has no key are skipped.
    fallback_models: list[str] = field(
        default_factory=lambda: _env_list("ANCHOR_FALLBACK_MODELS", "groq:openai/gpt-oss-20b,groq:qwen/qwen3.8-27b")
    )
    ollama_max_ctx: int = field(default_factory=lambda: int(_env("ANCHOR_OLLAMA_MAX_CTX", "32768")))
    ollama_timeout: int = field(default_factory=lambda: int(_env("ANCHOR_OLLAMA_TIMEOUT", "3600")))
    ollama_think: bool = field(default_factory=lambda: _env("ANCHOR_OLLAMA_THINK", "false").lower() == "true")
    max_tokens: int = field(default_factory=lambda: int(_env("ANCHOR_MAX_TOKENS", "3000")))
    reasoning_effort: str = field(default_factory=lambda: _env("ANCHOR_REASONING_EFFORT", "low"))  # gpt-oss
    qwen_reasoning: str = field(default_factory=lambda: _env("ANCHOR_QWEN_REASONING", "none"))  # qwen: off
    proposer_max_tokens: int = field(default_factory=lambda: int(_env("ANCHOR_PROPOSER_MAX_TOKENS", "12000")))
    proposer_context_chars: int = field(
        default_factory=lambda: int(_env("ANCHOR_PROPOSER_CONTEXT_CHARS", "50000"))
    )
    # Evidence is mined in batches of this size (small calls suit small models and low TPM tiers).
    evidence_prompt_chars: int = field(default_factory=lambda: int(_env("ANCHOR_EVIDENCE_PROMPT_CHARS", "9000")))
    mine_batches: int = field(default_factory=lambda: int(_env("ANCHOR_MINE_BATCHES", "2")))
    # Harness² improver calls carry ~4k tokens of method prompt plus harness and trajectories.
    refine_min_tpm: int = field(default_factory=lambda: int(_env("ANCHOR_REFINE_MIN_TPM", "30000")))
    runs_dir: Path = field(default_factory=lambda: Path(_env("ANCHOR_RUNS_DIR", str(ENGINE_DIR / "runs"))))
    harness_dir: Path = field(default_factory=lambda: Path(_env("ANCHOR_HARNESS_DIR", str(ENGINE_DIR / "harness"))))
    # Subpages rendered after the home page (most important first; see crawl.candidate_urls).
    max_pages: int = field(default_factory=lambda: int(_env("ANCHOR_MAX_PAGES", "6")))
    # Second crawl level: individual blog posts, case studies, changelog and press entries linked
    # from the index pages above. That is where dated, specific stories live.
    max_article_pages: int = field(default_factory=lambda: int(_env("ANCHOR_MAX_ARTICLE_PAGES", "4")))
    article_budget: float = field(default_factory=lambda: float(_env("ANCHOR_ARTICLE_BUDGET", "90")))
    # Wall-clock seconds for rendering subpages; whatever was read by then is used.
    subpage_budget: float = field(default_factory=lambda: float(_env("ANCHOR_SUBPAGE_BUDGET", "150")))
    max_articles: int = field(default_factory=lambda: int(_env("ANCHOR_MAX_ARTICLES", "6")))
    repair_rounds: int = field(default_factory=lambda: int(_env("ANCHOR_REPAIR_ROUNDS", "2")))
    max_extra_posts: int = field(default_factory=lambda: int(_env("ANCHOR_MAX_EXTRA_POSTS", "2")))
    min_posts: int = field(default_factory=lambda: int(_env("ANCHOR_MIN_POSTS", "2")))
    # A pack with fewer evidence items than this and no press is "thin": 1 post, no refine.
    thin_evidence: int = field(default_factory=lambda: int(_env("ANCHOR_THIN_EVIDENCE", "20")))
    # Evidence seen on a brand's earlier runs within this many days is pooled into new runs
    # (crawls of the same site see different pages). 0 turns pooling off.
    evidence_pool_days: float = field(default_factory=lambda: float(_env("ANCHOR_EVIDENCE_POOL_DAYS", "60")))
    # Freshness: followers only care about what is current. Time-sensitive posts (release, launch,
    # partnership, funding, award, opening...) need a cited item dated within news_max_days; any
    # dated evidence older than evidence_max_days is dropped from the pack (undated live site
    # copy is kept and can only back evergreen posts).
    news_max_days: int = field(default_factory=lambda: int(_env("ANCHOR_NEWS_MAX_DAYS", "60")))
    evidence_max_days: int = field(default_factory=lambda: int(_env("ANCHOR_EVIDENCE_MAX_DAYS", "100")))
    detail_slides: int = field(default_factory=lambda: int(_env("ANCHOR_DETAIL_SLIDES", "2")))
    # DataForSEO (optional): competitors, search demand and content gaps (market.py), plus Google
    # News results for press research. Unset login/password = the step is skipped.
    dataforseo_login: str = field(default_factory=lambda: _env("DATAFORSEO_LOGIN"))
    dataforseo_password: str = field(default_factory=lambda: _env("DATAFORSEO_PASSWORD"))
    # 0 / empty = detect from the site (URL path, <html lang>, country TLD; see market.geo_for).
    dataforseo_location_code: int = field(default_factory=lambda: int(_env("DATAFORSEO_LOCATION_CODE", "0")))
    dataforseo_language_code: str = field(default_factory=lambda: _env("DATAFORSEO_LANGUAGE_CODE", ""))
    dataforseo_max_competitors: int = field(default_factory=lambda: int(_env("DATAFORSEO_MAX_COMPETITORS", "6")))
    dataforseo_max_keywords: int = field(default_factory=lambda: int(_env("DATAFORSEO_MAX_KEYWORDS", "15")))
    dataforseo_news: bool = field(default_factory=lambda: _env("DATAFORSEO_NEWS", "true").lower() == "true")
    dataforseo_cache_days: float = field(default_factory=lambda: float(_env("DATAFORSEO_CACHE_DAYS", "7")))
    dataforseo_timeout: float = field(default_factory=lambda: float(_env("DATAFORSEO_TIMEOUT", "60")))

    @property
    def library_dir(self) -> Path:
        return self.runs_dir / "library"

    @property
    def cache_dir(self) -> Path:
        return self.runs_dir / ".cache"


def settings() -> Settings:
    return Settings()


ASSETS_DIR = ENGINE_DIR / "assets"
