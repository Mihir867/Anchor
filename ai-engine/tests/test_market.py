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
    "dataforseo_labs/google/ranked_keywords/live": [
        {"keyword_data": {"keyword": "acme login", "keyword_info": {"search_volume": 9000}}},
        {"keyword_data": {"keyword": "acmee", "keyword_info": {"search_volume": 700}}},  # typo of the brand
        {"keyword_data": {"keyword": "globex careers", "keyword_info": {"search_volume": 500},
                          "search_intent_info": {"main_intent": "navigational"}}},
        {"keyword_data": {"keyword": "deployment pipeline", "keyword_info": {"search_volume": 2400},
                          "search_intent_info": {"main_intent": "commercial"}},
         "ranked_serp_element": {"serp_item": {"rank_group": 4, "url": "https://acme.example/pipelines"}}},
        {"keyword_data": {"keyword": "how to automate release notes", "keyword_info": {"search_volume": 900},
                          "search_intent_info": {"main_intent": "informational"}}},
        {"keyword_data": {"keyword": "release notes slack", "keyword_info": {"search_volume": 400}}},
    ],
    "dataforseo_labs/google/serp_competitors/live": [
        {"domain": "acme.example", "keywords_count": 3},
        {"domain": "acme.com", "keywords_count": 3},                 # the brand's other domain
        {"domain": "acmetools.example", "keywords_count": 2},        # name-alike
        {"domain": "www.rivalco.example", "keywords_count": 3, "avg_position": 7.25, "etv": 12345.6},
        {"domain": "en.wikipedia.org", "keywords_count": 3},
        {"domain": "shipfast.example", "keywords_count": 2, "avg_position": 11},
    ],
    "dataforseo_labs/google/domain_intersection/live": [
        {"keyword_data": {"keyword": "release notes tool", "keyword_info": {"search_volume": 800}},
         "first_domain_serp_element": {"rank_group": 3, "title": "Release notes, automated"}},
        {"keyword_data": {"keyword": "google headquarters", "keyword_info": {"search_volume": 22200}},
         "first_domain_serp_element": {"rank_group": 9}},           # off-topic for Acme
        {"keyword_data": {"keyword": "rivalco pricing", "keyword_info": {"search_volume": 3000}},
         "first_domain_serp_element": {"rank_group": 1}},           # the rival's own name
    ],
    "dataforseo_labs/google/keywords_for_site/live": [],
    "dataforseo_labs/google/competitors_domain/live": [],
    "serp/google/news/live/advanced": [
        {"type": "news_search", "url": "https://news.example/acme", "title": "Acme ships",
         "timestamp": "2026-10-02 09:00:00 +00:00"},
        {"type": "top_stories", "url": "https://x.example"},
    ],
}
VOCAB = market.content_words("We run your deployment pipeline and automate release notes in Slack. "
                             "A release notes tool for every team.")


def fake_api(calls, responses=None):
    responses = responses or RESPONSES

    def post(url, json=None, **kw):
        path = url.split("/v3/", 1)[1]
        calls.append((path, json[0]))
        body = {"status_code": 20000, "tasks": [{"status_code": 20000, "cost": 0.01,
                                                  "result": [{"items": responses[path]}]}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))
    return post


def test_market_intel_filters_brand_noise_and_caches(cfg, monkeypatch):
    cfg = replace(cfg, dataforseo_login="l", dataforseo_password="p")
    calls: list = []
    monkeypatch.setattr(httpx, "post", fake_api(calls))
    market.reset_cost()
    intel, note = market.market_intel("acme.example", "Acme", cfg, url="https://acme.example/", vocab=VOCAB)
    assert note.startswith("used:")
    # Own other domain, name-alikes and generic sites are not competitors.
    assert [c.domain for c in intel.competitors] == ["rivalco.example", "shipfast.example"]
    assert intel.competitors[0].organic_traffic == 12345 and intel.competitors[0].shared_keywords == 3
    # Brand name, its typo and navigational searches are not market demand.
    assert [k.keyword for k in intel.brand_keywords] == [
        "deployment pipeline", "how to automate release notes", "release notes slack"]
    # Off-topic and rival-branded gaps are dropped.
    assert [k.keyword for k in intel.gap_keywords] == ["release notes tool"]
    assert intel.gap_keywords[0].competitor == "rivalco.example"
    # Competitors come from the NON-branded keywords.
    serp = next(body for path, body in calls if path.endswith("serp_competitors/live"))
    assert "acme login" not in serp["keywords"] and "deployment pipeline" in serp["keywords"]
    n = len(calls)
    market.market_intel("acme.example", "Acme", cfg, url="https://acme.example/", vocab=VOCAB)
    assert len(calls) == n  # second run served from the disk cache
    md = market.render(intel, "Acme")
    assert "NOT EVIDENCE" in md and "rivalco.example" in md and "how to automate release notes" in md
    assert market.news_hits("Acme launches", cfg) == [
        {"title": "Acme ships", "url": "https://news.example/acme", "date": "2026-10-02"}]


def test_inhabitr_style_junk_is_rejected(cfg, monkeypatch):
    """Regression for a real run: a small brand ranks only for its name and typos, so the old code
    reported name-alike domains as competitors and 'google headquarters' as a content gap."""
    cfg = replace(cfg, dataforseo_login="l", dataforseo_password="p")
    junk = dict(RESPONSES)
    junk["dataforseo_labs/google/ranked_keywords/live"] = [
        {"keyword_data": {"keyword": "inhabitor", "keyword_info": {"search_volume": 320}}},
        {"keyword_data": {"keyword": "inhabiter", "keyword_info": {"search_volume": 140}}},
        {"keyword_data": {"keyword": "innvision hospitality", "keyword_info": {"search_volume": 210},
                          "search_intent_info": {"main_intent": "navigational"}}},
    ]
    junk["dataforseo_labs/google/serp_competitors/live"] = []
    junk["dataforseo_labs/google/competitors_domain/live"] = [
        {"domain": "inhabitr.com", "intersections": 7}, {"domain": "inhabit.com", "intersections": 5},
        {"domain": "inhabit-interiors.com", "intersections": 5}, {"domain": "exa.ai", "intersections": 6}]
    calls: list = []
    monkeypatch.setattr(httpx, "post", fake_api(calls, junk))
    vocab = market.content_words("Hotel FF&E procurement: furniture sourcing, freight and installation.")
    intel, note = market.market_intel("inhabitr.ai", "Inhabitr", cfg, url="https://inhabitr.ai/", vocab=vocab)
    assert intel is None and note.startswith("empty:") and "3 ranked keyword(s), 2 of them branded" in note
    assert not any(path.endswith("competitors_domain/live") for path, _ in calls)  # mostly branded: skipped


def test_geo_follows_the_site():
    cfg = replace(__import__("anchor.config", fromlist=["Settings"]).Settings(), dataforseo_location_code=0,
                  dataforseo_language_code="")
    assert market.geo_for("https://www.zendesk.com/in/", "en-IN", cfg)[:2] == (2356, "en")
    assert market.geo_for("https://native.no/", "nb", cfg)[:2] == (2578, "no")
    assert market.geo_for("https://www.thesavoylondon.com/", "en-GB", cfg)[:2] == (2826, "en")
    assert market.geo_for("https://inhabitr.ai/", "en", cfg)[:2] == (2840, "en")  # .ai is not Anguilla
    assert market.geo_for("https://x.co.uk/", "", cfg)[:2] == (2826, "en")
    assert market.geo_for("https://x.example/", "en", replace(cfg, dataforseo_location_code=2036))[0] == 2036


def test_disabled_without_credentials(cfg, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    intel, note = market.market_intel("acme.example", "Acme", cfg)
    assert intel is None and note.startswith("off:")
    assert market.news_hits("Acme", cfg) == []


def test_api_error_degrades_to_no_context(cfg, monkeypatch):
    cfg = replace(cfg, dataforseo_login="l", dataforseo_password="p")
    monkeypatch.setattr(httpx, "post", lambda url, **k: httpx.Response(
        200, json={"status_code": 40200, "status_message": "Payment Required."}, request=httpx.Request("POST", url)))
    assert market.market_intel("acme.example", "Acme", cfg)[0] is None


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
    a = MinedFact(headline="Acme adds a dark mode", category="Integration", evidence_ids=["E2"],
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
    intel, note = market.market_intel("acme.example", "Acme", cfg)
    assert intel is None and note.startswith("refused:") and "40104" in note
    assert len(calls) == 1 and "40104" in market.blocked_reason()
    market.reset_cost()
    assert market.blocked_reason() == ""


def test_relevance_screen_drops_off_market_items(cfg, monkeypatch):
    from anchor.llm import LLM
    intel = MarketIntel(
        competitors=[Competitor(domain="salesforce.com"), Competitor(domain="investopedia.com")],
        brand_keywords=[SearchKeyword(keyword="help desk software"), SearchKeyword(keyword="have been pwned")],
        gap_keywords=[SearchKeyword(keyword="google gemini", competitor="ibm.com"),
                      SearchKeyword(keyword="ai customer service", competitor="ibm.com")])

    def judge(self, system, user, **kw):
        assert "screen search-marketing data" in system
        return json.dumps({"competitors": ["salesforce.com"],
                           "keywords": ["help desk software", "ai customer service"]})

    monkeypatch.setattr(LLM, "complete", judge)
    out = market.screen(intel, "Zendesk", "Customer service software and AI agents", cfg)
    assert [c.domain for c in out.competitors] == ["salesforce.com"]
    assert [k.keyword for k in out.brand_keywords] == ["help desk software"]
    assert [k.keyword for k in out.gap_keywords] == ["ai customer service"]

    def down(self, *a, **k):
        from anchor.llm import LLMError
        raise LLMError("provider unavailable")

    monkeypatch.setattr(LLM, "complete", down)
    assert market.screen(intel, "Zendesk", "x", cfg) == intel  # failure keeps the word-filtered data
