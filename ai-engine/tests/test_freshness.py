"""Only current posts: old news is dropped at research, prepare, fact, post and fallback level (offline)."""

from datetime import date, timedelta

from anchor import generate, prepare, research
from anchor.models import Card, Evidence, MinedFact, PostDraft, RolloutResult, Slide
from anchor.verify import STALE, announces, check_fact, check_post, stale_years

from conftest import CAPTION, LINKEDIN, SLIDES

TODAY = date(2026, 11, 20)


def _days_ago(n):
    return (TODAY - timedelta(days=n)).isoformat()


def _article(eid, when, text="Alsulaiman Group partners with Inhabitr to support its Middle East launch."):
    return Evidence(id=eid, kind="article", url=f"https://news.example/{eid}", date=when, text=text)


def _fact(category, quote="Alsulaiman Group partners with Inhabitr to support its Middle East launch."):
    return MinedFact(headline="Alsulaiman Group supports Inhabitr's Middle East launch", category=category,
                     evidence_ids=["E1"], quote=quote, why_it_matters="w")


def test_old_partnership_is_not_news():
    # The real failure: a May 2024 partnership article posted as news in November 2026.
    old = {"E1": _article("E1", "2024-05-01")}
    problems = check_fact(_fact("Partnership"), old, "Inhabitr", today=TODAY)
    assert problems and all(p.startswith(STALE) for p in problems)
    assert any("is news" in p for p in problems)
    assert not check_fact(_fact("Partnership"), {"E1": _article("E1", _days_ago(20))}, "Inhabitr", today=TODAY)
    # 60-day news window: a 75-day-old partnership is no longer news.
    assert check_fact(_fact("Partnership"), {"E1": _article("E1", _days_ago(75))}, "Inhabitr", today=TODAY)


def test_skill_time_sensitive_list_and_pattern():
    assert announces("Collection drop") and announces("Funding round") and announces("Award")
    assert announces("Store news", ["Store news"]) and announces("Big moment", ["Big moment"])
    assert not announces("Feature how-to") and not announces("Customer story") and not announces("Event")


def test_old_dated_evidence_backs_no_post_type():
    # Old figures ("furnished over 20,000 units" from 2024) are dropped, even as a Proof point.
    old = {"E1": _article("E1", "2024-05-04", "Inhabitr has furnished over 20,000 units across the US.")}
    fact = MinedFact(headline="Inhabitr has furnished over 20,000 units", category="Proof point",
                     evidence_ids=["E1"], quote="Inhabitr has furnished over 20,000 units across the US.",
                     metrics=["20,000"], why_it_matters="w")
    assert any("older than 100 days" in p for p in check_fact(fact, old, "Inhabitr", today=TODAY))
    recent = {"E1": old["E1"].model_copy(update={"date": _days_ago(90)})}
    assert not check_fact(fact, recent, "Inhabitr", today=TODAY)


def test_undated_site_copy_is_fine_for_evergreen_posts():
    ev = {"E1": Evidence(id="E1", kind="site", url="https://acme.example/docs",
                         text="Acme integrates with Slack and GitHub so release notes reach every team.")}
    fact = MinedFact(headline="Release notes in Slack and GitHub", category="Feature how-to", evidence_ids=["E1"],
                     quote="Acme integrates with Slack and GitHub so release notes reach every team.",
                     why_it_matters="w")
    assert not check_fact(fact, ev, "Acme", today=TODAY)
    assert check_fact(fact.model_copy(update={"category": "Release"}), ev, "Acme", today=TODAY)


def test_past_years_in_the_text_are_old_news():
    assert stale_years("We won the 2024 Travelers' Choice award", TODAY) == [2024]
    assert stale_years("In 2025 we launched Pulse", TODAY) == [2025]  # 2025 ended 324 days ago
    assert stale_years("Serving guests since 2012. Founded in 2009. © 2021 Acme", TODAY) == []
    assert stale_years("Our 2026 roadmap", TODAY) == []
    assert stale_years("Last year's highlights from 2025", date(2026, 1, 20)) == []  # within 100 days
    assert stale_years("12,000 stores and 2,024 rooms", TODAY) == []

    ev = {"E1": Evidence(id="E1", kind="site", url="https://acme.example/about",
                         text="In 2023 we launched our first hotel analytics product for 40 groups.")}
    fact = MinedFact(headline="Our hotel analytics product", category="Spotlight", evidence_ids=["E1"],
                     quote="In 2023 we launched our first hotel analytics product for 40 groups.", why_it_matters="w")
    assert any("old news" in p for p in check_fact(fact, ev, "Acme", today=TODAY))


def _draft(linkedin=LINKEDIN):
    return PostDraft(voice="insightful", linkedin=linkedin, instagram_caption=CAPTION,
                     hashtags=["#devops", "#retail", "#cicd"], poster_headline="Globex ships to 12,000 stores",
                     poster_kicker="Customer story", poster_stat="40%", slides=[Slide(**s) for s in SLIDES])


def test_post_recency_wording_needs_recent_source(pack):
    fact = MinedFact(headline="Globex ships to 12,000 stores", category="Customer story", evidence_ids=["E1"],
                     quote=pack.evidence[0].text[:60], why_it_matters="w")
    src = pack.evidence[:1]
    just = LINKEDIN.replace("At Acme, we cut", "At Acme, we just launched a pipeline that cut")
    assert not any(p.startswith(STALE) for p in check_post(_draft(just), fact, src, "Acme", []))
    old_src = [src[0].model_copy(update={"date": (date.today() - timedelta(days=80)).isoformat()})]
    problems = check_post(_draft(just), fact, old_src, "Acme", [])
    assert any(p.startswith(STALE) and "just launched" in p for p in problems)


def test_research_drops_old_and_undated_press(cfg, monkeypatch):
    today = date.today()
    monkeypatch.setattr(research, "_bing", lambda q: [
        {"title": "Acme partners with Globex", "url": "https://news.example/old", "date": "2024-05-01"},
        {"title": "Acme ships Pulse", "url": "https://news.example/new", "date": (today - timedelta(days=5)).isoformat()},
        {"title": "Acme expands", "url": "https://news.example/mid", "date": (today - timedelta(days=40)).isoformat()},
    ])
    read = []
    monkeypatch.setattr(research, "_article", lambda h, *a: read.append(h["url"]) or
                        [{"kind": "article", "url": h["url"], "date": h["date"], "text": "t"}])
    items = research.news_evidence("Acme", "acme.example", ['"{brand_name}" {current_year}'], 3, cfg=cfg)
    assert read == ["https://news.example/new", "https://news.example/mid"]  # newest first, old never fetched
    assert [i["url"] for i in items] == read


def test_article_without_any_date_is_dropped(monkeypatch):
    import httpx

    page = ("<html><body><article><p>Acme launched Pulse, a release dashboard used by 40 teams at Globex, "
            "the company said.</p></article></body></html>")
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(
        200, text=page, headers={"content-type": "text/html"}, request=httpx.Request("GET", url)))
    hit = {"title": "Acme launches Pulse", "url": "https://news.example/a", "date": None}
    assert research._article(hit, "Acme", "acme.example") == []
    dated = page.replace("<html>", f'<html><head><meta property="article:published_time" '
                                   f'content="{date.today().isoformat()}T09:00:00Z"></head>')
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(
        200, text=dated, headers={"content-type": "text/html"}, request=httpx.Request("GET", url)))
    got = research._article(hit, "Acme", "acme.example")
    assert got and got[0]["date"] == date.today().isoformat()


def test_prepare_drops_stale_dated_items_but_keeps_undated_and_home():
    old = (date.today() - timedelta(days=200)).isoformat()
    items = [
        {"url": "https://acme.example/blog/2024-recap", "date": old, "text": "old blog"},
        {"url": "https://acme.example/", "date": old, "text": "home with a stray <time>"},
        {"url": "https://acme.example/features", "date": None, "text": "undated features"},
        {"url": "https://news.example/x", "date": date.today().isoformat(), "text": "fresh press"},
    ]
    kept, dropped = prepare.fresh_only(items, "https://acme.example", 100)
    assert dropped == 1 and [d["text"] for d in kept] == ["home with a stray <time>", "undated features", "fresh press"]


def test_rank_prefers_fresh_over_old_and_undated():
    today = date.today()
    ev = {
        "E1": Evidence(id="E1", kind="article", url="https://n.example/1", date=(today - timedelta(days=90)).isoformat(), text="a"),
        "E2": Evidence(id="E2", kind="article", url="https://n.example/2", date=(today - timedelta(days=10)).isoformat(), text="b"),
        "E3": Evidence(id="E3", kind="site", url="https://acme.example/x", text="c"),
    }
    mk = lambda i, h, c: MinedFact(headline=h, category=c, evidence_ids=[i], quote="q" * 30, why_it_matters="w")
    facts = [mk("E1", "Older press about pricing tiers", "Proof point"),
             mk("E3", "Undated feature walkthrough", "Feature how-to"),
             mk("E2", "Fresh launch of reporting dashboards", "Release")]
    assert generate.rank(facts, ev, 3)[0].evidence_ids == ["E2"]


def test_fallback_never_delivers_old_news(pack, cfg, tmp_path):
    from anchor.generate import Trajectory

    stale_card = Card(id="post_1", status="rejected", fact=_fact("Partnership"), post=_draft(),
                      problems=[f"{STALE} says 'just launched', but no cited item is recent"])
    result = RolloutResult(task_id="t", brand="Acme", industry="saas", skills_loaded=[], cards=[stale_card])
    old = Evidence(id="E9", kind="site", url="https://acme.example/blog/old", title="Old",
                   date="2023-01-01", text="In 2023 we won the Best DevOps Tool award from 12 judges.")
    pack = pack.model_copy(update={"evidence": [old] + pack.evidence})
    assert generate._intro_fact(pack, 100).evidence_ids == ["E2"]  # current site copy, not the 2023 page
    cfg = cfg.__class__(**{**cfg.__dict__, "api_key": ""})  # the model is unreachable: template post
    out = generate.ensure_post(result, pack, tmp_path / "no-harness", cfg, Trajectory(tmp_path / "t.md"))
    delivered = [c for c in out.verified]
    assert len(delivered) == 1 and delivered[0].id != "post_1" and delivered[0].fact.evidence_ids == ["E2"]
