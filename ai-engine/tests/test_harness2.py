"""The base harness satisfies Harness²'s own validators, and the full method runs end to end."""

import json
from pathlib import Path

import pytest
from harness2.core import tree as htree
from harness2.substrate.opencode import OPENCODE_SURFACE

from anchor import harness
from anchor.config import ENGINE_DIR
from anchor.h2.adapter import AnchorAdapter
from anchor.h2.proposer import apply_edits, pack_context
from anchor.llm import LLM
from anchor.prepare import write_pack

from conftest import fake_complete

BASE = ENGINE_DIR / "harness"


def test_base_harness_passes_harness2_validation():
    tree = htree.read_tree(OPENCODE_SURFACE, BASE)
    census = htree.validate(OPENCODE_SURFACE, tree)
    assert census["skills"] >= 4
    assert harness.problems(BASE) == []


def test_every_industry_skill_has_routing_metadata():
    h = harness.load(BASE)
    for name in ("saas", "hospitality", "ecommerce", "general"):
        skill = h.skills[name]
        assert skill.meta["industry"] is True
        assert skill.list_meta("crawl_paths") and skill.list_meta("news_queries")
        assert isinstance(skill.meta.get("banned_phrases"), list)


def test_adapter_rejects_unexecutable_components(tmp_path, pack, cfg):
    write_pack(pack, tmp_path / "pack", [])
    adapter = AnchorAdapter(tmp_path, pack, cfg, BASE)
    tree = htree.read_tree(OPENCODE_SURFACE, BASE)
    adapter.validate_tree(tree)  # base is fine
    with pytest.raises(ValueError, match="scripts/"):
        adapter.validate_tree({**tree, "scripts/check.py": "print(1)\n"})
    with pytest.raises(ValueError, match="industry skill"):
        adapter.validate_tree({k: v for k, v in tree.items() if not k.startswith("skills/saas/")})


def test_apply_edits_stays_inside_harness(tmp_path):
    (tmp_path / "guardrails.md").write_text("old")
    ignored = apply_edits('<file path="context/harness/guardrails.md">new</file>'
                          '<file path="context/source/evidence.md">x</file>'
                          '<file path="context/harness/../escape.md">x</file>', tmp_path)
    assert (tmp_path / "guardrails.md").read_text() == "new\n"
    assert len(ignored) == 2 and not (tmp_path.parent / "escape.md").exists()


def test_pack_context_respects_budget(tmp_path):
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness" / "systemprompt.md").write_text("S" * 5000)
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "evidence.md").write_text("E" * 200000)
    packed = pack_context(tmp_path, 20000)
    assert len(packed) < 26000 and "renderer truncated" in packed and "S" * 5000 in packed


def _refine(tmp_path, pack, cfg, monkeypatch, boost: float = 0.0):
    """Run Propose-Probe-Compose at k=1 with the scripted model. `boost` is added to the quality
    score of every non-base rollout, to simulate an edit that really helps."""
    monkeypatch.setattr(LLM, "complete", fake_complete)
    from anchor import score
    from anchor.h2 import refine as refine_mod

    real = score.score_rollout

    def scored(run_dir, *a, **k):
        out = dict(real(run_dir, *a, **k))
        if not Path(run_dir).name.startswith("base"):
            out["score"] = out["score"] + boost
        return out

    monkeypatch.setattr(refine_mod, "score_rollout", scored)
    run_dir = tmp_path / "run"
    write_pack(pack, run_dir / "pack", [])
    return run_dir, refine_mod.refine(pack, run_dir, cfg, k=1)


def test_harness2_keeps_base_when_edit_does_not_score_higher(tmp_path, pack, cfg, monkeypatch):
    """The old behaviour adopted the single composed final blindly at k=1 and stored it in the
    library even when it changed nothing. Now an edit must beat the base on the quality score."""
    run_dir, outcome = _refine(tmp_path, pack, cfg, monkeypatch, boost=0.0)
    assert len(list((run_dir / "h2" / "rollouts").glob("**/cards.json"))) == 4  # base1 + inv1 + dom1 + agg1
    assert not outcome.adopted and outcome.chosen_label == "base1"
    assert outcome.harness_dir == BASE
    assert "kept base" in outcome.notes
    assert not list((cfg.library_dir / "agg" / "saas").rglob("EXPERIENCE.md"))  # nothing stored
    assert (outcome.chosen_run_dir / "score.json").is_file()
    from anchor.pipeline import learned_harness
    assert learned_harness(cfg, "saas") == cfg.harness_dir


def test_harness2_promotes_an_edit_that_scores_higher(tmp_path, pack, cfg, monkeypatch):
    run_dir, outcome = _refine(tmp_path, pack, cfg, monkeypatch, boost=1.0)
    assert outcome.adopted and outcome.chosen_label == "agg1" and not outcome.fell_back_to_base
    cards = json.loads((outcome.chosen_run_dir / "cards.json").read_text())
    assert cards["cards"][0]["status"] == "verified"
    assert "whole sentences" in (outcome.harness_dir / "guardrails.md").read_text()
    lib = cfg.library_dir / "agg" / "saas"
    assert (lib / "INDEX.md").is_file() and list(lib.rglob("EXPERIENCE.md"))
    promoted = json.loads(next(lib.rglob("PROMOTED.json")).read_text())
    assert promoted["gain"] >= 0.25 and promoted["label"] == "agg1"
    # Later fast runs for this industry use the promoted harness.
    from anchor.pipeline import learned_harness
    assert "whole sentences" in (learned_harness(cfg, "saas") / "guardrails.md").read_text()
    assert "[ACTION]" in (outcome.chosen_run_dir / "trajectory.md").read_text()


def test_unpromoted_legacy_library_entries_are_ignored(cfg):
    legacy = cfg.library_dir / "agg" / "general" / "harnesses" / "old-task" / "harness"
    legacy.parent.mkdir(parents=True)
    import shutil
    shutil.copytree(BASE, legacy)
    from anchor.pipeline import learned_harness
    assert learned_harness(cfg, "general") == cfg.harness_dir  # no PROMOTED.json: never used


def test_infra_failures_are_marked_for_the_improver(tmp_path, pack, cfg):
    write_pack(pack, tmp_path / "pack", [])
    adapter = AnchorAdapter(tmp_path, pack, cfg, BASE)
    d = tmp_path / "r"
    d.mkdir()
    (d / "trajectory.md").write_text(
        "[ERROR] post 1: writer failed: PostDraft: could not obtain valid JSON (no JSON object found)\n"
        "[OBSERVATION] post 2: deterministic checks failed: linkedin length is 300 chars\n")
    out = adapter.trajectory(d, obs_trunc=2000).splitlines()
    assert out[0].startswith("[INFRA]") and "do NOT edit the harness" in out[0]
    assert out[1].startswith("[OBSERVATION]")
