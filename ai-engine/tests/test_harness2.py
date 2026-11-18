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


def test_full_harness2_step_through_anchor_adapter(tmp_path, pack, cfg, monkeypatch):
    """Propose-Probe-Compose at k=1: 4 rollouts, edited harness adopted, library entry written."""
    monkeypatch.setattr(LLM, "complete", fake_complete)
    from anchor.h2.refine import refine

    run_dir = tmp_path / "run"
    write_pack(pack, run_dir / "pack", [])
    outcome = refine(pack, run_dir, cfg, k=1)

    rollouts = list((run_dir / "h2" / "rollouts").glob("**/cards.json"))
    assert len(rollouts) == 4  # base1 + inv1 + dom1 + agg1
    assert outcome.chosen_label == "agg1" and not outcome.fell_back_to_base
    cards = json.loads((outcome.chosen_run_dir / "cards.json").read_text())
    assert cards["cards"][0]["status"] == "verified"
    assert "whole sentences" in (outcome.harness_dir / "guardrails.md").read_text()
    lib = cfg.library_dir / "agg" / "saas"
    assert (lib / "INDEX.md").is_file() and list(lib.rglob("EXPERIENCE.md"))
    assert "[ACTION]" in (outcome.chosen_run_dir / "trajectory.md").read_text()
