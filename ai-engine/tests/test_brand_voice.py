"""Posts for EXISTING brands: written as the brand, never an introduction, varied, never repeated.

The bad examples here are taken from real runs (runs/*/output/deck.json, 2026-11-18/19)."""

from datetime import date, timedelta

from anchor import crawl, generate, history
from anchor.crawl import Page
from anchor.llm import LLM
from anchor.models import Evidence, MinedFact, PostDraft
from anchor.verify import check_fact, check_post, intro_problems, same_topic, self_reference_problems

from conftest import CAPTION, LINKEDIN, SLIDES, fake_complete


def post(li: str, cap: str = CAPTION, headline: str = "One pipeline") -> PostDraft:
    return PostDraft(linkedin=li, instagram_caption=cap, poster_headline=headline, slides=SLIDES)


def test_brand_introductions_fail():
    for li in ("Meet Tanyx.\n\nWe built an AI platform.",
               "Tanyx is an AI-powered platform that connects budgeting, designing and ordering.\n\nMore.",
               "Say hello to Tanyx: one layer for every project.",
               "Who we are: a team of builders at Tanyx."):
        assert intro_problems(post(li), "Tanyx"), li
    # A named NEW thing, or the brand inside a sentence, is fine.
    for li in ("Introducing Tanyx's renovation budget tool.\n\nWe turn PIPs into estimates.",
               "Freight adds 8-12% to hotel FF&E landed cost. At Tanyx, we price it upfront."):
        assert not intro_problems(post(li), "Tanyx"), li


def test_brand_in_third_person_fails_but_third_parties_keep_attribution():
    assert self_reference_problems(post("Tanyx says the industry needed intelligence that connects every step."), "Tanyx")
    assert self_reference_problems(post("Native's pricing page states the Max tier includes 3 brands."), "Native")
    assert not self_reference_problems(post("TechCrunch reported that we raised a round."), "Native")


def test_grounded_post_must_use_first_person(pack):
    fact = MinedFact(headline="Acme cut Globex deployment time by 40%", category="Customer story",
                     evidence_ids=["E1"], quote=pack.evidence[0].text[:60], why_it_matters="w")
    assert not check_post(post(LINKEDIN), fact, pack.evidence[:1], "Acme", [])
    outsider = LINKEDIN.replace("At Acme, we cut", "Acme cut")
    problems = check_post(post(outsider), fact, pack.evidence[:1], "Acme", [])
    assert any("not written as the brand" in p for p in problems)
    # Other languages are left to the prompt and critic (no English pronoun check).
    assert not any("not written as the brand" in p
                   for p in check_post(post(outsider), fact, pack.evidence[:1], "Acme", [], language="nb"))


def test_launch_needs_a_recent_dated_item():
    undated = {"E1": Evidence(id="E1", kind="site", url="https://tanyxai.com/", text=(
        "AI renovation budgets: AI-powered hotel renovation budget estimates in minutes."))}
    fact = MinedFact(headline="Tanyx launches AI renovation budgets", category="Launch", evidence_ids=["E1"],
                     quote="AI-powered hotel renovation budget estimates in minutes.", why_it_matters="w")
    assert any("is news" in p for p in check_fact(fact, undated, "Tanyx"))
    assert not check_fact(fact.model_copy(update={"category": "Feature how-to"}), undated, "Tanyx")
    recent = {"E1": undated["E1"].model_copy(update={"date": (date.today() - timedelta(days=30)).isoformat()})}
    assert not check_fact(fact, recent, "Tanyx")
    stale = {"E1": undated["E1"].model_copy(update={"date": "2022-01-01"})}
    assert check_fact(fact, stale, "Tanyx")


def test_same_topic_twice_is_one_topic():
    # Real duplicates from the native.no and salesforce.com runs.
    assert same_topic("Max plan provides 6,000 Native tokens monthly, four-times Pro's allocation",
                      "Max plan provides 6,000 tokens per month for AI-driven content generation")
    assert same_topic("Microsoft and Salesforce launch Copilotforce with 38+ prebuilt sales skills",
                      "Salesforce and Microsoft launch Copilotforce AI sales integration")
    assert not same_topic("Salesforce and Microsoft launch Copilotforce AI sales integration",
                          "Accenture rolls out Copilot to 740,000 people, including 55,000 Salesforce users")


def test_rank_spreads_post_types_drops_repeats_and_demotes_homepage_copy():
    ev = {"E1": Evidence(id="E1", kind="site", url="https://n.example/pricing", text="t"),
          "E2": Evidence(id="E2", kind="site", url="https://n.example/pricing", text="t"),
          "E3": Evidence(id="E3", kind="testimonial", url="https://n.example/customers/x", text="t"),
          "E4": Evidence(id="E4", kind="site", url="https://n.example", text="t")}
    f = lambda h, c, e, m=(): MinedFact(headline=h, category=c, evidence_ids=[e], quote=h + " (quote)", metrics=list(m),
                                        why_it_matters="w")
    a = f("Max plan provides 6,000 tokens monthly", "Proof point", "E1", ["6,000"])
    dup = f("Max plan includes 6,000 tokens per month", "Proof point", "E2", ["6,000"])
    b = f("World Taste Award publishes 42 posts with us", "Customer story", "E3", ["42"])
    hero = f("An AI social media manager for every brand", "Feature how-to", "E4")
    other = f("Canine Behavior Academy gets 24x more impressions", "Proof point", "E3", ["24x"])
    ordered = generate.rank([a, dup, b, hero, other], ev, 5, home_url="https://n.example/")
    heads = [x.headline for x in ordered]
    assert dup.headline not in heads  # same topic as `a`
    assert {ordered[0].category, ordered[1].category} == {"Proof point", "Customer story"}
    assert heads[-1] == hero.headline  # homepage hero copy goes last


def test_history_round_trip_and_rerun_skips_posted_topics(tmp_path, pack, cfg, monkeypatch):
    monkeypatch.setattr(LLM, "complete", fake_complete)
    first = generate.generate(pack, cfg.harness_dir, tmp_path / "r1", cfg)
    assert len(first.verified) == 2
    history.record(cfg, pack.brand.domain, pack.task_id, first.verified)
    posted = [p["headline"] for p in history.load(cfg, pack.brand.domain)]
    assert len(posted) == 2
    pack.already_posted = posted
    second = generate.generate(pack, cfg.harness_dir, tmp_path / "r2", cfg)
    assert second.verified == []  # the scripted model only knows these two facts: both already posted
    traj = (tmp_path / "r2" / "trajectory.md").read_text()
    assert "already posted in an earlier run" in traj


def test_history_can_be_disabled(cfg, monkeypatch):
    monkeypatch.setenv("ANCHOR_BRAND_HISTORY", "0")
    assert history.load(cfg, "acme.example") == []


def test_article_links_go_one_level_deeper():
    index = Page("https://acme.example/blog", (
        '<a href="/blog/how-we-cut-deploys-to-minutes">a</a><a href="/blog/page/2">next</a>'
        '<a href="/blog/tag/devops">tag</a><a href="https://other.example/blog/x-post">ext</a>'
        '<a href="/blog/why-release-notes-matter">b</a><a href="/blog/third-post-here">c</a>'), "Blog")
    pricing = Page("https://acme.example/pricing", '<a href="/pricing/enterprise-plan">e</a>', "Pricing")
    links = crawl.article_links([index, pricing], "https://acme.example/", set(), limit=4)
    assert links == ["https://acme.example/blog/how-we-cut-deploys-to-minutes",
                     "https://acme.example/blog/why-release-notes-matter"]  # 2 per index, no pagination/tags


def test_prompts_carry_brand_voice_post_types_and_history(tmp_path, pack, cfg, monkeypatch):
    seen = []

    def spy(self, system, user, **kw):
        seen.append((system, user))
        return fake_complete(self, system, user, **kw)

    monkeypatch.setattr(LLM, "complete", spy)
    pack.already_posted = ["Acme ships dark mode"]
    generate.generate(pack, cfg.harness_dir, tmp_path / "r", cfg)
    system, mine = next((s, u) for s, u in seen if "STAGE 1 OF 2" in u)
    write = next(u for _, u in seen if "STAGE 2 OF 2" in u)
    assert "Customer story" in mine and "ALREADY POSTED" in mine and "Acme ships dark mode" in mine
    assert "first person" in write and "you ARE Acme" in write and "Post type: Customer story" in write
    assert "no introductions" in system.lower() and '"we", "our", "us"' in system


def test_missing_brand_name_gets_a_sign_off_not_a_drop():
    from anchor.verify import normalize_post
    fact = MinedFact(headline="h", category="Customer story", evidence_ids=["E1"], quote="q", why_it_matters="w")
    p = normalize_post(post("We cut deploys to minutes.\n\nMore detail here.\n\n#devops #cicd", cap="We ship."),
                       fact, 2, "Acme")
    assert p.linkedin.endswith("— The Acme team\n\n#devops #cicd")
    named = normalize_post(post("At Acme, we cut deploys."), fact, 2, "Acme")
    assert "team" not in named.linkedin


def test_past_events_are_rejected_upcoming_ones_pass():
    from anchor.verify import dates_in
    assert dates_in("online on 12 November 2026 at 8:00 AM IST") == [date(2026, 11, 12)]
    assert dates_in("Join us Nov 3rd, 2027 or 2027-01-05") == [date(2027, 11, 3), date(2027, 1, 5)]
    ev = {"E1": Evidence(id="E1", kind="site", url="https://z.example/ai-summit", date="2026-09-10", text=(
        "Zendesk AI Summit 2026 takes place online in APAC on 12 November 2026 at 8:00 AM IST."))}
    fact = MinedFact(headline="Zendesk AI Summit 2026 showcases agentic AI", category="Event", evidence_ids=["E1"],
                     quote="Zendesk AI Summit 2026 takes place online in APAC on 12 November 2026 at 8:00 AM IST.",
                     why_it_matters="w")
    assert any("has passed" in p for p in check_fact(fact, ev, "Zendesk", today=date(2026, 11, 20)))
    assert not check_fact(fact, ev, "Zendesk", today=date(2026, 11, 1))
