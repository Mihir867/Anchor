"""A run never ends with zero posts, and the crawl keeps only what matters."""

import json

from anchor import crawl, generate
from anchor.config import ENGINE_DIR
from anchor.llm import LLM, LLMError
from anchor.pipeline import finalize

from conftest import fake_complete


def _finalize(tmp_path, pack, cfg, monkeypatch):
    from anchor import render

    monkeypatch.setattr(render, "_google_font", lambda *a, **k: None)  # offline
    run_dir = tmp_path / "run"
    generate.generate(pack, ENGINE_DIR / "harness", run_dir / "rollout", cfg)
    return run_dir, finalize(pack, run_dir, run_dir / "rollout", ENGINE_DIR / "harness", cfg, mode="fast")


def test_best_rejected_draft_is_delivered_as_flagged_fallback(tmp_path, pack, cfg, monkeypatch):
    def always_invents(self, system, user, **kw):
        out = fake_complete(self, system, user, **kw)
        if "STAGE 2 OF 2" in user:
            d = json.loads(out)
            d["linkedin"] += "\n\nIt now serves 9,999 stores."
            return json.dumps(d)
        return out

    monkeypatch.setattr(LLM, "complete", always_invents)
    run_dir, summary = _finalize(tmp_path, pack, cfg, monkeypatch)
    assert summary["verified_posts"] == 1 and summary["fallback_posts"] == 1
    assert "marked for review" in summary["note"]
    deck = json.loads((run_dir / "output" / "deck.json").read_text())
    delivered = [c for c in deck["cards"] if c["status"] == "verified"]
    assert len(delivered) == 1 and delivered[0]["fallback"] is True
    assert delivered[0]["notes"][0].startswith("Fallback post:")
    assert "Not fully verified" in (run_dir / "output" / "posts.md").read_text()
    assert len(summary["posters"]) >= 1


def test_template_post_when_model_cannot_write(tmp_path, pack, cfg, monkeypatch):
    def down(self, system, user, **kw):
        raise LLMError("provider unavailable")

    monkeypatch.setattr(LLM, "complete", down)
    run_dir, summary = _finalize(tmp_path, pack, cfg, monkeypatch)
    assert summary["verified_posts"] == 1 and summary["fallback_posts"] == 1
    card = json.loads((run_dir / "output" / "deck.json").read_text())["cards"][-1]
    assert card["fallback"] and pack.brand.name in card["post"]["linkedin"]
    assert card["fact"]["category"] == "Spotlight"
    assert "meet " not in card["post"]["linkedin"].lower()  # never an introduction


def test_verified_runs_are_untouched(tmp_path, pack, cfg, monkeypatch):
    monkeypatch.setattr(LLM, "complete", fake_complete)
    _, summary = _finalize(tmp_path, pack, cfg, monkeypatch)
    assert summary["verified_posts"] == 2 and summary["fallback_posts"] == 0 and summary["note"] == ""


def test_trackers_blocked_but_first_party_never():
    site = crawl._site("www.hubspot.com")
    assert not crawl._blocked("https://js.hubspot.com/app.js", "script", site, crawl._ALWAYS_SKIP)
    other = crawl._site("acme.com")
    assert crawl._blocked("https://js.hs-scripts.com/1.js", "script", other, crawl._ALWAYS_SKIP)
    assert crawl._blocked("https://www.googletagmanager.com/gtm.js", "script", other, crawl._ALWAYS_SKIP)
    assert crawl._blocked("https://acme.com/hero.mp4", "media", other, crawl._ALWAYS_SKIP)
    assert not crawl._blocked("https://cdn.acme-assets.net/app.js", "script", other, crawl._ALWAYS_SKIP)
    assert crawl._blocked("https://acme.com/a.png", "image", other, crawl._SUBPAGE_SKIP)


def test_linked_pages_come_before_guessed_paths(monkeypatch):
    monkeypatch.setattr(crawl, "_sitemap", lambda origin: [])
    home = crawl.CrawlResult(url="https://acme.com", home=crawl.Page("https://acme.com", ""),
                             tokens={"links": ["https://acme.com/customers", "https://acme.com/product/x",
                                               "https://acme.com/login"]})
    urls = crawl.candidate_urls(home, ["/integrations"], 8)
    assert urls[:2] == ["https://acme.com/customers", "https://acme.com/product/x"]
    assert "https://acme.com/integrations" in urls and "https://acme.com/login" not in urls


def test_hanging_model_is_skipped_after_two_timeouts(cfg, monkeypatch):
    import httpx
    from dataclasses import replace

    from anchor import llm

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm, "_tripped", {})
    calls = []

    def post(url, json=None, **kw):
        calls.append(json["model"])
        if json["model"] == "hangs":
            raise httpx.ReadTimeout("timed out")
        body = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    cfg = replace(cfg, fallback_models=[])
    assert LLM("gemini:hangs,gemini:works", cfg=cfg).complete("s", "u") == "ok"
    assert calls == ["hangs", "hangs", "works"]
    # Later calls in the same process skip the hanging model straight away.
    assert LLM("gemini:hangs,gemini:works", cfg=cfg).complete("s", "u") == "ok"
    assert calls[3:] == ["works"]
