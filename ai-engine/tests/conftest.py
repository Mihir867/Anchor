import json
import re
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anchor.config import Settings  # noqa: E402
from anchor.models import BrandKit, Evidence, TaskPack  # noqa: E402

E1 = ("Acme cut deployment time by 40% for Globex, the company said on Tuesday. "
      "Globex now ships updates to 12,000 stores from a single pipeline.")


@pytest.fixture(autouse=True)
def _no_real_services(monkeypatch):
    """.env may hold real DATABASE_URL / Cloudinary credentials (config loads it at import). No
    test may write to them; test_storage opts in explicitly via TEST_DATABASE_URL."""
    for name in ("DATABASE_URL", "CLOUDINARY_URL", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY",
                 "CLOUDINARY_API_SECRET"):
        monkeypatch.delenv(name, raising=False)


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: drives a real Chromium against a local test site (slow)")


@pytest.fixture
def cfg(tmp_path):
    # Never reach the real DataForSEO API from tests, even when .env has credentials.
    return replace(Settings(), api_key="test-key", runs_dir=tmp_path / "runs", repair_rounds=1,
                   dataforseo_login="", dataforseo_password="")


@pytest.fixture
def pack():
    return TaskPack(
        task_id="acme-test", url="https://acme.example", created_at="2026-01-01T00:00:00Z",
        industry="saas", max_posts=2,
        brand=BrandKit(url="https://acme.example", domain="acme.example", name="Acme"),
        evidence=[
            Evidence(id="E1", kind="article", url="https://news.example/acme", title="Acme and Globex",
                     date=date.today().isoformat(), text=E1),
            Evidence(id="E2", kind="site", url="https://acme.example/integrations", title="Integrations",
                     text="Acme integrates with Slack and GitHub so release notes reach every team."),
        ],
    )


LINKEDIN = (
    "Globex now ships updates to 12,000 stores from one pipeline.\n\n"
    "At Acme, we cut Globex's deployment time by 40%. That is the difference between a release "
    "train that waits for a maintenance window and one that runs whenever the code is ready.\n\n"
    "The interesting part is not the tooling. It is that a retailer with that many locations "
    "treats a deploy as a non-event.\n\n"
    "If you run releases across many sites, what still forces you to batch them?"
)
CAPTION = ("One pipeline. 12,000 stores. We helped Globex cut deployment time by 40% at Acme, so updates "
           "reach every location without a maintenance window.")
SLIDES = [{"title": "What changed at Globex", "bullets": ["Deployment time cut by 40%", "One pipeline for 12,000 stores"]},
          {"title": "Why it matters", "bullets": ["Releases no longer wait for a window", "The change came with our pipeline"]}]
LINKEDIN_E2 = (
    "Release notes are only useful if the people who need them actually see them.\n\n"
    "At Acme, we integrate with Slack and GitHub so release notes reach every team, without someone copying "
    "changelogs between tools after each deploy.\n\n"
    "That matters most for teams whose support and sales staff learn about changes after customers do, "
    "and for anyone who has had to answer a question about a release they never heard about.\n\n"
    "Where do your release notes live today, and who actually reads them?"
)
CAPTION_E2 = ("Release notes where your team already works. Acme integrates with Slack and GitHub so "
              "release notes reach every team, straight from the tools you ship with.")
SLIDES_E2 = [{"title": "Two integrations", "bullets": ["Slack", "GitHub"]},
             {"title": "The point", "bullets": ["Release notes reach every team"]}]


def fake_complete(self, system, user, *, temperature=0.4, json_mode=False, history=None):
    """A scripted model that answers each stage the way a compliant model would."""
    if "harness improver working through a text-only interface" in system:
        return ('<file path="context/harness/guardrails.md">\n'
                + _current_guardrails(user)
                + "\n- Copy quotes as whole sentences from a single evidence item.\n</file>\n"
                "<notes>Added a quoting rule: base rollout notes show quotes are checked verbatim.</notes>")
    if "Write two things for a library" in user:
        return ("<edits>\ncomponent: guardrails.md\ncandidates: inv1\nchange: added quoting rule\n"
                "observed: facts accepted on first round\nverdict: confounded\n</edits>\n\n"
                "<experience>\ncue: When evidence items are long press paragraphs\n"
                "lesson: In guardrails.md, require whole-sentence quotes from one item.\n"
                "evidence: guardrails.md row; facts passed the verbatim check.\n"
                "confidence: low, single rollout\n</experience>")
    if "choose which of" in user or "```choice" in user:
        ids = re.findall(r"candidates/([A-Z]+)\.md", user)
        return f"<why>Only faithful candidate.</why>\n```choice\n{ids[0] if ids else 'A'}\n```"
    if "You review a brand's social posts" in system:  # score.py judge: middling, equal for all
        ids = re.findall(r'"post_id": "([^"]+)"', user)
        return json.dumps({"posts": [{"post_id": i, "specificity": 3, "new_to_followers": 3, "hook": 3,
                                      "brand_voice": 3, "channel_fit": 3} for i in ids]})
    if "independent fact-checker" in system:
        return json.dumps({"unsupported_claims": [], "voice_problems": []})
    if "STAGE 1 OF 2" in user:
        return json.dumps({"facts": [{
            "headline": "Acme cut Globex deployment time by 40%", "category": "Customer story",
            "evidence_ids": ["E1"], "quote": "Acme cut deployment time by 40% for Globex, the company said on Tuesday.",
            "metrics": ["40%"], "named_entities": ["Globex"], "why_it_matters": "Faster releases."}, {
            "headline": "Acme integrates with Slack and GitHub", "category": "Integration",
            "evidence_ids": ["E2"], "quote": "Acme integrates with Slack and GitHub so release notes reach every team.",
            "metrics": [], "named_entities": ["Slack", "GitHub"], "why_it_matters": "Notes reach everyone."}]})
    if "STAGE 2 OF 2" in user:
        if '"E2"' in user.split("THE ONLY MATERIAL")[0]:
            return json.dumps({"linkedin": LINKEDIN_E2, "instagram_caption": CAPTION_E2,
                               "hashtags": ["#devtools", "#releasenotes"], "poster_headline": "Release notes in Slack and GitHub",
                               "poster_kicker": "Integrations", "poster_stat": "", "slides": SLIDES_E2})
        return json.dumps({"linkedin": LINKEDIN, "instagram_caption": CAPTION,
                           "hashtags": ["#devops", "#retailtech", "#cicd"],
                           "poster_headline": "Globex deploys to 12,000 stores from one pipeline",
                           "poster_kicker": "Customer outcome", "poster_stat": "40%", "slides": SLIDES})
    if "Optional skills" in user or "classify" in system:
        return json.dumps({"skills": []})
    raise AssertionError(f"unexpected prompt: {system[:80]!r} / {user[:120]!r}")


def _current_guardrails(user: str) -> str:
    m = re.search(r'<context_file path="context/harness/guardrails.md">\n(.*?)\n</context_file>', user, re.S)
    return m.group(1) if m else "# Guardrails\n"
