"""Thin evidence packs (1 post, no refine), the cross-run evidence pool, and DataForSEO retries (offline)."""

import json
from dataclasses import replace
from datetime import date, timedelta

import httpx

from anchor import history, market, pipeline, prepare
from anchor.models import Evidence


def _ev(n, kind="site"):
    return [Evidence(id=f"E{i}", kind=kind, url="https://acme.example", text=f"item {i}") for i in range(n)]


def test_thin_pack_threshold(cfg):
    assert prepare.thin_pack(_ev(5), cfg).startswith("5 evidence item(s) and no press")
    assert prepare.thin_pack(_ev(cfg.thin_evidence), cfg) == ""
    assert prepare.thin_pack(_ev(5) + _ev(1, "article"), cfg) == ""  # press coverage is not thin


def test_evidence_pool_round_trip_and_ageing(cfg):
    items = [{"kind": "site", "url": "https://acme.example/a", "title": "A", "date": None,
              "text": "We cut onboarding from 14 days to 3 for 40 design teams.", "_rank": 3.0}]
    history.record_evidence(cfg, "www.acme.example", items)
    pooled = history.load_evidence(cfg, "acme.example")
    assert [d["text"] for d in pooled] == [items[0]["text"]] and "_rank" not in pooled[0]

    # Items not re-crawled within the window drop out.
    f = history._pool_file(cfg, "acme.example")
    data = json.loads(f.read_text())
    data["items"][0]["seen"] = (date.today() - timedelta(days=cfg.evidence_pool_days + 1)).isoformat()
    f.write_text(json.dumps(data))
    assert history.load_evidence(cfg, "acme.example") == []
    assert history.load_evidence(replace(cfg, evidence_pool_days=0), "acme.example") == []


def test_pooled_evidence_skips_what_this_crawl_already_has(cfg):
    old = {"kind": "site", "url": "https://acme.example/a", "title": "", "date": None,
           "text": "We cut onboarding from 14 days to 3 for 40 design teams."}
    again = {"kind": "site", "url": "https://acme.example", "title": "", "date": None, "text": "Same text."}
    history.record_evidence(cfg, "acme.example", [old, again])
    pooled = prepare._pooled_evidence(cfg, "acme.example", [dict(again, _rank=1.0)])
    assert [d["text"] for d in pooled] == [old["text"]] and pooled[0]["_pooled"]


def test_thin_pack_skips_refine(cfg, pack, monkeypatch, tmp_path):
    pack.thin, pack.thin_reason, pack.max_posts = True, "2 evidence item(s) and no press", 1
    calls = []
    monkeypatch.setattr(pipeline, "refine_blocker", lambda c: "")
    monkeypatch.setattr(pipeline, "prepare", lambda *a, **k: (pack, tmp_path))
    monkeypatch.setattr(pipeline.generate, "generate", lambda *a, **k: calls.append("fast"))
    monkeypatch.setattr(pipeline, "finalize", lambda *a, **k: k)
    out = pipeline.run("https://acme.example", mode="refine", cfg=cfg)
    assert calls == ["fast"] and out["mode"] == "fast"
    assert out["stages_note"].startswith("Harness² refine skipped: thin evidence pack")


def test_transient_dataforseo_error_is_retried_once(cfg, monkeypatch):
    cfg = replace(cfg, dataforseo_login="l", dataforseo_password="p")
    monkeypatch.setattr(market.time, "sleep", lambda s: None)
    replies = [{"status_code": 40101, "status_message": "Internal SE Server Error."},
               {"status_code": 20000, "tasks": [{"status_code": 20000, "result": [{"items": [{"x": 1}]}]}]}]

    def post(url, **kw):
        status = 200
        body = replies.pop(0)
        if body["status_code"] == 40101:  # DataForSEO reports it as a task error
            body = {"status_code": 20000, "tasks": [{"status_code": 40101, "status_message": body["status_message"]}]}
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    market.reset_cost()
    assert market.post("serp/google/news/live/advanced", {"keyword": "acme"}, cfg) == [{"x": 1}]
    assert replies == []


def test_lasting_dataforseo_error_is_not_retried(cfg, monkeypatch):
    cfg = replace(cfg, dataforseo_login="l", dataforseo_password="p")
    calls = []

    def post(url, **kw):
        calls.append(url)
        return httpx.Response(200, json={"status_code": 20000, "tasks": [{"status_code": 40501, "status_message": "bad"}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    market.reset_cost()
    assert market.post("serp/google/news/live/advanced", {"keyword": "acme"}, cfg) == []
    assert len(calls) == 1
