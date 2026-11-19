"""Cost controls (per-role chains, fail-fast on truncated replies, learned-harness reuse) and fonts."""

import shutil
from pathlib import Path

import httpx
from fontTools.subset import Subsetter
from fontTools.ttLib import TTFont

from anchor import llm, render
from anchor.config import ENGINE_DIR
from anchor.pipeline import learned_harness


def test_role_chain_is_tried_in_order(cfg, monkeypatch):
    monkeypatch.setenv("GROQ_KEY", "g")
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from dataclasses import replace
    c = replace(cfg, fallback_models=[])
    m = llm.LLM("groq:openai/gpt-oss-120b,openrouter:x/y,cerebras:qwen-3.8-27b", cfg=c)
    assert [e.spec for e in m.endpoints] == ["groq:openai/gpt-oss-120b", "cerebras:qwen-3.8-27b"]  # no key -> skipped


def test_truncated_empty_reply_moves_to_next_model_without_retrying(cfg, monkeypatch):
    from dataclasses import replace
    monkeypatch.setenv("GROQ_KEY", "g")
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json["model"])
        if json["model"] == "qwen-3.8-27b":  # reasoning ate the budget
            body = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}], "usage": {}}
        else:
            body = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}}
        return httpx.Response(200, json=body)

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    m = llm.LLM("cerebras:qwen-3.8-27b,groq:openai/gpt-oss-120b", cfg=replace(cfg, fallback_models=[]))
    assert m.complete("s", "u") == "ok"
    assert calls == ["qwen-3.8-27b", "openai/gpt-oss-120b"]  # one paid attempt, not six


def test_fast_runs_reuse_the_learned_industry_harness(cfg):
    assert learned_harness(cfg, "saas") == cfg.harness_dir  # empty library -> base
    adopted = cfg.library_dir / "agg" / "saas" / "harnesses" / "brand-1" / "harness"
    shutil.copytree(ENGINE_DIR / "harness", adopted)
    assert learned_harness(cfg, "saas") == cfg.harness_dir  # stored but never promoted -> base
    (adopted.parent / "PROMOTED.json").write_text('{"promoted_at": "2026-11-20T00:00:00+00:00", "gain": 0.5}')
    assert learned_harness(cfg, "saas") == adopted
    (adopted / "scripts").mkdir()
    (adopted / "scripts" / "x.py").write_text("print(1)")  # invalid for this executor -> skipped
    assert learned_harness(cfg, "saas") == cfg.harness_dir


def test_unicode_range_subset_font_is_rejected(tmp_path):
    """A Cyrillic-only subset draws every Latin letter as a box; it must never be used."""
    font = TTFont(str(render.INTER["regular"]))
    sub = Subsetter()
    sub.populate(unicodes=range(0x0400, 0x0450))
    sub.subset(font)
    path = tmp_path / "subset.ttf"
    font.save(str(path))
    assert render.covers(render.INTER["regular"]) and not render.covers(path)
    assert render.for_text(path, "Hello") == render.INTER["regular"]


def test_text_no_font_can_draw_is_stripped_not_boxed():
    assert render.drawable(render.INTER["regular"], "PwC本格 and JDSC") == "PwC and JDSC"
    assert render.drawable(render.INTER["regular"], "Plain text") == "Plain text"
