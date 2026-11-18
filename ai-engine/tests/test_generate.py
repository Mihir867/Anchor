"""A fast-mode rollout with a scripted model: verified post, markdown, trajectory."""

from anchor import generate
from anchor.config import ENGINE_DIR
from anchor.llm import LLM

from conftest import fake_complete


def test_rollout_publishes_only_verified_posts(tmp_path, pack, cfg, monkeypatch):
    monkeypatch.setattr(LLM, "complete", fake_complete)
    result = generate.generate(pack, ENGINE_DIR / "harness", tmp_path / "r", cfg)
    assert [c.status for c in result.cards] == ["verified", "verified"]
    md = (tmp_path / "r" / "posts.md").read_text()
    assert "### LinkedIn" in md and "### Instagram" in md and "[E1]" in md
    traj = (tmp_path / "r" / "trajectory.md").read_text()
    assert "VERIFIED" in traj and "skills loaded: ['saas']" in traj


def test_dropped_post_is_backfilled_from_next_fact(tmp_path, pack, cfg, monkeypatch):
    """The first fact's posts keep inventing a number; the rollout drops it and writes the next."""
    import json as _json

    import conftest

    def flaky(self, system, user, **kw):
        out = fake_complete(self, system, user, **kw)
        if "STAGE 2 OF 2" in user and '"E1"' in user.split("THE ONLY MATERIAL")[0]:
            d = _json.loads(out)
            d["linkedin"] += "\n\nIt now serves 9,999 stores."
            return _json.dumps(d)
        return out

    monkeypatch.setattr(LLM, "complete", flaky)
    pack.max_posts = 1
    result = generate.generate(pack, ENGINE_DIR / "harness", tmp_path / "r", cfg)
    assert [c.status for c in result.cards] == ["rejected", "verified"]
    assert result.verified[0].fact.evidence_ids == ["E2"]


def test_carousel_renders_cover_slides_and_pdf(tmp_path, pack, cfg, monkeypatch):
    from anchor import render
    from anchor.pipeline import finalize

    monkeypatch.setattr(LLM, "complete", fake_complete)
    monkeypatch.setattr(render, "_google_font", lambda *a, **k: None)  # offline
    run_dir = tmp_path / "run"
    generate.generate(pack, ENGINE_DIR / "harness", run_dir / "rollout", cfg)
    summary = finalize(pack, run_dir, run_dir / "rollout", ENGINE_DIR / "harness", cfg, mode="fast")
    assert summary["verified_posts"] == 2
    assert len(summary["posters"]) == 6 and len(summary["carousels"]) == 2
    md = (run_dir / "output" / "posts.md").read_text()
    assert "post_1_carousel.pdf" in md and "### Carousel" in md
