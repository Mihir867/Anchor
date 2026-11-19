"""Storage: Cloudinary signing/config offline; Postgres round-trip when TEST_DATABASE_URL is set."""

import json
import os

import pytest

from anchor import storage


def test_cloudinary_signature_matches_documented_example():
    # https://cloudinary.com/documentation/authentication_signatures
    params = {"eager": "w_400,h_300,c_pad|w_260,h_200,c_crop", "public_id": "sample_image",
              "timestamp": "1315060510"}
    assert storage.signature(params, "abcd") == "bfd09f95f331f558cbd1320e67aa8d488770583e"


def test_cloudinary_credentials_from_url_or_parts(monkeypatch):
    for k in ("CLOUDINARY_URL", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    assert storage.cloudinary_creds() is None
    monkeypatch.setenv("CLOUDINARY_URL", "cloudinary://123:s%2Fecret@demo")
    assert storage.cloudinary_creds() == ("demo", "123", "s/ecret")
    monkeypatch.delenv("CLOUDINARY_URL")
    monkeypatch.setenv("CLOUDINARY_CLOUD_NAME", "c")
    monkeypatch.setenv("CLOUDINARY_API_KEY", "k")
    monkeypatch.setenv("CLOUDINARY_API_SECRET", "s")
    assert storage.cloudinary_creds() == ("c", "k", "s")


def test_storage_is_a_no_op_without_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert not storage.enabled()
    storage.record_job("x", {"url": "https://a.b"}, "queued")  # must not raise


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="set TEST_DATABASE_URL to run")
def test_finished_run_round_trips_through_postgres(tmp_path, pack, cfg, monkeypatch):
    from anchor import generate, render
    from anchor.config import ENGINE_DIR
    from anchor.llm import LLM
    from anchor.pipeline import finalize

    from conftest import fake_complete

    import psycopg

    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("CLOUDINARY_URL", "cloudinary://k:s@demo")
    monkeypatch.setattr(storage, "_initialised", False)
    uploads = []

    def fake_upload(path, public_id, raw=False):
        uploads.append((public_id, raw))
        kind = "raw" if raw else "image"
        return {"secure_url": f"https://res.cloudinary.com/demo/{kind}/upload/{public_id}",
                "public_id": public_id, "width": 1080, "height": 1350, "bytes": 1}

    monkeypatch.setattr(storage, "upload", fake_upload)
    monkeypatch.setattr(LLM, "complete", fake_complete)
    monkeypatch.setattr(render, "_google_font", lambda *a, **k: None)
    run_dir = tmp_path / "acme-com-20260101-120000"
    generate.generate(pack, ENGINE_DIR / "harness", run_dir / "rollout", cfg)
    finalize(pack, run_dir, run_dir / "rollout", ENGINE_DIR / "harness", cfg, mode="fast")

    storage.record_job("job-test-1", {"url": pack.url, "mode": "fast"}, "running")
    out = storage.save_run("job-test-1", run_dir, {"url": pack.url, "mode": "fast"})
    storage.save_run("job-test-1", run_dir, {"url": pack.url, "mode": "fast"})  # idempotent
    assert len(out["slide_urls"]["post_1"]) == 3
    assert ("anchor/acme-com-20260101-120000/post_1_carousel.pdf", True) in uploads
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as conn:
        run = conn.execute("SELECT status, verified_posts, brand FROM runs WHERE id = 'job-test-1'").fetchone()
        posts = conn.execute("SELECT status, slide_urls, pdf_url FROM posts WHERE run_id = 'job-test-1' "
                             "ORDER BY position").fetchall()
        n_assets = conn.execute("SELECT count(*) FROM assets WHERE run_id = 'job-test-1'").fetchone()[0]
        conn.execute("DELETE FROM runs WHERE id = 'job-test-1'")
    assert run == ("done", 2, "Acme")
    assert [p[0] for p in posts] == ["verified", "verified"]
    assert posts[0][1][0].startswith("https://res.cloudinary.com/demo/image/upload/anchor/")
    assert n_assets == 8  # 2 posts x (3 slides + 1 pdf)


def test_progress_reporter_accumulates_info_and_is_scoped_to_the_job():
    from anchor import progress

    seen = []
    progress.report("crawling", url="https://a.b")  # no reporter installed: no-op
    with progress.reporting(lambda stage, info: seen.append((stage, info))):
        progress.report("crawling", url="https://a.b")
        progress.report("mining", evidence=12, brand=None)
    progress.report("writing", post=1)
    assert seen == [("crawling", {"url": "https://a.b"}),
                    ("mining", {"url": "https://a.b", "evidence": 12})]


def test_progress_reporter_errors_never_reach_the_pipeline():
    from anchor import progress

    def boom(stage, info):
        raise RuntimeError("db down")

    with progress.reporting(boom):
        progress.report("crawling", url="x")  # must not raise
