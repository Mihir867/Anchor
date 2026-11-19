"""DataForSEO market context: parsing, caching, prompts, ranking and the competitor-name check (offline)."""

import json
from dataclasses import replace

import httpx

from anchor import generate, market
from anchor.config import ENGINE_DIR
from anchor.llm import LLM
from anchor.models import Competitor, MarketIntel, MinedFact, PostDraft, SearchKeyword
from anchor.verify import check_post

from conftest import CAPTION, LINKEDIN, SLIDES, fake_complete

RESPONSES = {
    "dataforseo_labs/google/competitors_domain/live": [
        {"domain": "acme.example", "intersections": 999},
        {"domain": "www.rivalco.example", "intersections": 420, "avg_position": 7.25,
         "full_domain_metrics": {"organic": {"etv": 12345.6}}},
        {"domain": "en.wikipedia.org", "intersections": 300},
        {"domain": "shipfast.example", "intersections": 120, "avg_position": 11},
    ],
    "dataforseo_labs/google/ranked_keywords/live": [
        {"keyword_data": {"keyword": "acme login", "keyword_info": {"search_volume": 9000}}},
        {"keyword_data": {"keyword": "deployment pipeline", "keyword_info": {"search_volume": 2400},
                          "search_intent_info": {"main_intent": "commercial"}},
         "ranked_serp_element": {"serp_item": {"rank_group": 4, "url": "https://acme.example/pipelines"}}},
    ],
    "dataforseo_labs/google/domain_intersection/live": [
        {"keyword_data": {"keyword": "release notes tool", "keyword_info": {"search_volume": 800}},
         "first_domain_serp_element": {"rank_group": 3, "title": "Release notes, automated"}},
    ],
    "serp/google/news/live/advanced": [
        {"type": "news_search", "url": "https://news.example/acme", "title": "Acme ships",
         "timestamp": "2026-10-02 09:00:00 +00:00"},
        {"type": "top_stories", "url": "https://x.example"},
    ],
}


def fake_api(calls):
    def post(url, json=None, **kw):
        path = url.split("/v3/", 1)[1]
        calls.append(path)
        body = {"status_code": 20000, "tasks": [{"status_code": 20000, "cost": 0.01,
                                                  "result": [{"items": RESPONSES[path]}]}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))
    return post


def test_market_intel_parses_filters_and_caches(cfg, monkeypatch):
    cfg = replace(cfg, dataforseo_login="l", dataforseo_password="p")
    calls: list[str] = []
    monkeypatch.setattr(httpx, "post", fake_api(calls))
    market.reset_cost()
    intel = market.market_intel("acme.example", "Acme", cfg)
    assert [c.domain for c in intel.competitors] == ["rivalco.example", "shipfast.example"]
    assert intel.competitors[0].organic_traffic == 12345 and intel.competitors[0].avg_position == 7.2
    # Brand-name searches are not market demand.
    assert [k.keyword for k in intel.brand_keywords] == ["deployment pipeline"]
    assert intel.brand_keywords[0].position == 4 and intel.brand_keywords[0].intent == "commercial"
    assert intel.gap_keywords[0].keyword == "release notes tool"
    assert intel.gap_keywords[0].competitor == "rivalco.example"
    assert market.cost_snapshot()["calls"] == len(calls) == 4  # competitors, keywords, 2 gap lookups
    market.market_intel("acme.example", "Acme", cfg)
    assert len(calls) == 4  # second run served from the disk cache
    md = market.render(intel, "Acme")
    assert "NOT EVIDENCE" in md and "rivalco.example" in md and "release notes tool" in md
    assert market.news_hits("Acme launches", cfg) == [
        {"title": "Acme ships", "url": "https://news.example/acme", "date": "2026-10-02"}]


def test_disabled_without_credentials(cfg, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    assert market.market_intel("acme.example", "Acme", cfg) is None
    assert market.news_hits("Acme", cfg) == []


def test_api_error_degrades_to_no_context(cfg, monkeypatch):
    cfg = replace(cfg, dataforseo_login="l", dataforseo_password="p")
    monkeypatch.setattr(httpx, "post", lambda url, **k: httpx.Response(
        200, json={"status_code": 40200, "status_message": "Payment Required."}, request=httpx.Request("POST", url)))
    assert market.market_intel("acme.example", "Acme", cfg) is None


INTEL = MarketIntel(competitors=[Competitor(domain="rivalco.example", shared_keywords=420)],
                    brand_keywords=[SearchKeyword(keyword="deployment pipeline", search_volume=2400)],
                    gap_keywords=[SearchKeyword(keyword="release notes tool", search_volume=800,
                                                competitor="rivalco.example")])


def test_post_naming_a_competitor_fails_unless_evidence_does(pack):
    fact = MinedFact(headline="h", category="c", evidence_ids=["E1"], quote="q", why_it_matters="w")
    post = PostDraft(linkedin=LINKEDIN + "\n\nUnlike Rivalco, it needs no window.", instagram_caption=CAPTION,
                     poster_headline="One pipeline", slides=SLIDES)
    names = market.competitor_names(INTEL)
    problems = check_post(post, fact, pack.evidence[:1], "Acme", [], competitors=names)
    assert any("names competitor" in p and "rivalco" in p for p in problems)
    sources = [pack.evidence[0].model_copy(update={"text": pack.evidence[0].text + " Rivalco also bid."})]
    assert not any("names competitor" in p for p in check_post(post, fact, sources, "Acme", [], competitors=names))


def test_rollout_uses_market_context(tmp_path, pack, cfg, monkeypatch):
    seen: list[str] = []

    def spy(self, system, user, **kw):
        seen.append(user)
        return fake_complete(self, system, user, **kw)

    monkeypatch.setattr(LLM, "complete", spy)
    pack.market = INTEL
    result = generate.generate(pack, ENGINE_DIR / "harness", tmp_path / "r", cfg)
    assert len(result.verified) == 2
    mine = next(u for u in seen if "STAGE 1 OF 2" in u)
    write = next(u for u in seen if "STAGE 2 OF 2" in u)
    assert "MARKET CONTEXT" in mine and "rivalco.example" in mine and "Use it to CHOOSE" in mine
    assert "MARKET CONTEXT" in write and "Never name" in write
    assert "market context (DataForSEO" in (tmp_path / "r" / "trajectory.md").read_text()


def test_rank_prefers_facts_matching_search_demand(pack):
    ev = pack.evidence_by_id()
    a = MinedFact(headline="Acme adds a dark mode", category="Launch", evidence_ids=["E2"],
                  quote="x", why_it_matters="w")
    b = MinedFact(headline="Acme release notes reach every team", category="Integration",
                  evidence_ids=["E2"], quote="Acme integrates with Slack and GitHub so release notes reach every team.",
                  why_it_matters="w")
    assert generate.rank([a, b], ev, 2)[0] is a  # no context: original order on a tie
    assert generate.rank([a, b], ev, 2, market.keyword_terms(INTEL))[0] is b


def test_pack_without_market_still_loads(pack):
    data = json.loads(pack.model_dump_json())
    data.pop("market")
    assert type(pack).model_validate(data).market is None


def test_unverified_account_stops_further_calls(cfg, monkeypatch):
    cfg = replace(cfg, dataforseo_login="l", dataforseo_password="p")
    calls: list[str] = []

    def refuse(url, **kw):
        calls.append(url)
        return httpx.Response(403, json={"status_code": 40104, "status_message": "Please verify your account"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", refuse)
    market.reset_cost()
    assert market.news_hits("Acme", cfg) == []
    assert market.market_intel("acme.example", "Acme", cfg) is None
    assert len(calls) == 1 and "40104" in market.blocked_reason()
    market.reset_cost()
    assert market.blocked_reason() == ""
