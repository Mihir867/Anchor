from anchor.models import MinedFact, PostDraft
from anchor.verify import GLOBAL_BANNED, check_fact, check_post, numbers, quote_found

from anchor.models import Slide

from conftest import CAPTION, E1, LINKEDIN, SLIDES


def test_numbers_canonicalise_units():
    assert numbers("$27M raised") == numbers("27 million dollars raised") == {(27e6, False)}
    assert numbers("30% faster") == numbers("30 percent faster") == {(30.0, True)}
    assert numbers("3 reasons to care") == set()  # structure, not a claim
    assert numbers("#top10 list") == set()  # hashtags ignored


def test_quote_must_be_verbatim():
    assert quote_found("Acme cut deployment time by 40% for Globex", [E1])
    assert quote_found("Acme cut deployment time ... ships updates to 12,000 stores", [E1])
    assert not quote_found("Acme reduced deployment time by 40% for Globex", [E1])


def test_fact_with_invented_metric_is_rejected(pack):
    fact = MinedFact(headline="Acme saved Globex 60%", category="Outcome", evidence_ids=["E1"],
                     quote="Acme cut deployment time by 40% for Globex, the company said on Tuesday.",
                     metrics=["60%"], named_entities=["Initech"], why_it_matters="x")
    problems = " | ".join(check_fact(fact, pack.evidence_by_id()))
    assert "60%" in problems and "Initech" in problems and "headline" in problems


def test_fact_citing_unknown_id_is_rejected(pack):
    fact = MinedFact(headline="x", category="y", evidence_ids=["E99"], quote="z" * 30, why_it_matters="w")
    assert any("do not exist" in p for p in check_fact(fact, pack.evidence_by_id()))


def _post(**kw):
    base = dict(linkedin=LINKEDIN, instagram_caption=CAPTION, hashtags=["#devops"],
                poster_headline="Globex deploys to 12,000 stores", poster_kicker="Customer outcome",
                poster_stat="40%", slides=[Slide(**x) for x in SLIDES])
    base.update(kw)
    return PostDraft(**base)


def test_grounded_post_passes(pack):
    ev = pack.evidence_by_id()
    fact = MinedFact(headline="h", category="c", evidence_ids=["E1"], quote="q", why_it_matters="w")
    assert check_post(_post(), fact, [ev["E1"]], "Acme", GLOBAL_BANNED) == []


def test_post_with_unsupported_number_and_cliche_fails(pack):
    ev = pack.evidence_by_id()
    fact = MinedFact(headline="h", category="c", evidence_ids=["E1"], quote="q", why_it_matters="w")
    bad = _post(linkedin=LINKEDIN + "\n\nThis game-changer now serves 3.5 million users.", poster_stat="99%")
    problems = " | ".join(check_post(bad, fact, [ev["E1"]], "Acme", GLOBAL_BANNED))
    assert "3.5e+06" in problems or "3500000" in problems
    assert "game-changer" in problems and "poster_stat" in problems


def test_fact_about_another_product_is_rejected(pack):
    fact = MinedFact(headline="Globex ships to 12,000 stores", category="Outcome", evidence_ids=["E1"],  # E1 = article
                     quote="Globex now ships updates to 12,000 stores from a single pipeline.",
                     why_it_matters="x")
    assert any("not about Acme" in p for p in check_fact(fact, pack.evidence_by_id(), "Acme"))


def test_on_site_fact_need_not_repeat_brand_name(pack):
    fact = MinedFact(headline="Slack and GitHub integrations", category="Integration", evidence_ids=["E2"],
                     quote="integrates with Slack and GitHub so release notes reach every team", why_it_matters="x")
    assert check_fact(fact, pack.evidence_by_id(), "Acme") == []


def test_normalize_post_fixes_layout_limits_only():
    from anchor.verify import normalize_post
    fact = MinedFact(headline="Acme cut Globex deploy time by 40%", category="Outcome", evidence_ids=["E1"],
                     quote="q", why_it_matters="w")
    fixed = normalize_post(_post(poster_stat="40% faster deploys", poster_headline="x" * 120), fact)
    assert fixed.poster_stat == "" and fixed.poster_headline == fact.headline and fixed.linkedin == LINKEDIN


def test_slides_are_held_to_the_same_grounding(pack):
    ev = pack.evidence_by_id()
    fact = MinedFact(headline="h", category="c", evidence_ids=["E1"], quote="q", why_it_matters="w")
    bad = _post(slides=[Slide(title="Results", bullets=["Revenue up 25%"]), Slide(**SLIDES[1])])
    assert any("slide 2" in p and "25%" in p for p in check_post(bad, fact, [ev["E1"]], "Acme", GLOBAL_BANNED))
    short = _post(slides=[Slide(**SLIDES[0])])
    assert any("carousel needs 2 slides" in p for p in check_post(short, fact, [ev["E1"]], "Acme", GLOBAL_BANNED))
