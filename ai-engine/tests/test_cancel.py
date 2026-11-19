"""Stopping a job: the pipeline exits at its next progress report and the job ends cancelled."""
import importlib
import threading
import time

import pytest

from anchor import progress


def test_report_raises_once_stopped():
    flag = {"stop": False}
    seen = []
    with progress.reporting(lambda s, i: seen.append(s), lambda: flag["stop"]):
        progress.report("crawling")
        flag["stop"] = True
        with pytest.raises(progress.Cancelled):
            progress.report("writing")
    assert seen == ["crawling"]
    progress.report("writing")  # no reporter installed: no-op, never raises


def test_cancel_endpoint_stops_running_job(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "")  # never touch a real database from tests
    monkeypatch.setenv("ANCHOR_RUNS_DIR", str(tmp_path))
    main = importlib.import_module("main")
    from fastapi.testclient import TestClient

    started, finished = threading.Event(), {}

    def fake_run(url, **kw):
        started.set()
        try:
            for _ in range(200):
                progress.report("writing", post=1)
                time.sleep(0.02)
        except BaseException as exc:
            finished["exc"] = type(exc).__name__
            raise
        return {"task_id": "x"}

    monkeypatch.setattr(main, "run", fake_run)
    client = TestClient(main.app)
    job_id = client.post("/runs", json={"url": "https://acme.example"}).json()["job_id"]
    assert started.wait(5)
    assert client.post(f"/runs/{job_id}/cancel").json()["status"] == "cancelled"
    for _ in range(100):
        if "exc" in finished:
            break
        time.sleep(0.02)
    assert finished.get("exc") == "Cancelled"
    assert main._jobs[job_id]["status"] == "cancelled"
