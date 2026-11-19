"""Real-browser crawl tests against a local, deliberately hostile site.

These drive a fresh Chromium (Playwright contexts never reuse a profile or cache) through the
real crawl/prepare code, so they behave the same on a laptop, in CI and in the production image.
The fake brand site mixes good pages with the ways real sites hang a crawler:

    /changelog   accepts the connection and never answers
    /blog        spins JavaScript forever in <head> (wedges the renderer)
    /newsroom    a bot-protection interstitial
    /press       404
    /sitemap.xml trickles one byte at a time, forever

Run just these:          pytest -m browser
Skip them:               pytest -m "not browser"
Prod-like (512 MB, 0.5 CPU, Linux Chromium flags):  scripts/test_prod_like.sh
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from anchor import crawl, prepare, research

pytestmark = pytest.mark.browser

BRAND = "#E4572E"
LOGO_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="32" viewBox="0 0 120 32">'
            f'<rect width="120" height="32" rx="6" fill="{BRAND}"/></svg>')
PARA = ("Lumora is a workflow automation platform with an open API and SDK. Teams connect their "
        "dashboard, integrations and cloud data in one place, and the platform runs the automation. ")


def _page(title: str, body: str, head: str = "") -> str:
    return (f"<!doctype html><html lang='en-US'><head><title>{title}</title>{head}</head>"
            f"<body><main>{body}</main></body></html>")


HOME = _page(
    "Lumora | Workflow automation for support teams",
    f"""<header><a href="/" aria-label="home"><img alt="Lumora logo" src="/logo.svg" width="120" height="32"></a>
      <nav><a href="/customers">Customers</a> <a href="/changelog">Changelog</a> <a href="/blog">Blog</a>
      <a href="/newsroom">Newsroom</a> <a href="/press">Press</a> <a href="/integrations">Integrations</a>
      <a href="/pricing">Pricing</a> <a href="/about">About</a></nav></header>
      <h1>Automate every support workflow</h1>
      <p>{PARA * 3}</p>
      <a class="btn btn-primary" href="/pricing"
         style="display:inline-block;padding:14px 28px;background:{BRAND};color:#fff">Start a free trial</a>""",
    head=('<meta name="description" content="Lumora is the workflow automation platform for support teams.">'
          '<meta property="og:image" content="/hero.png">'
          '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization",'
          '"name":"Lumora","url":"/"}</script>'),
)
GOOD = {
    "/customers": _page("Customers | Lumora", "<h1>Customers</h1><blockquote>Lumora cut our first response "
                        "time by 38% across 14 support teams in the first quarter, said Dana Ortiz, VP Support "
                        "at Globex.</blockquote><p>" + PARA * 2 + "</p>"
                        '<a href="/customers/initech-moves-support-to-lumora">Read the Initech story</a>'
                        '<a href="/customers/page/2">More</a>'),
    # One level deeper than the index page: only reachable through the article-link pass.
    "/customers/initech-moves-support-to-lumora": _page(
        "How Initech answers 9,000 tickets a month | Lumora",
        '<article><time datetime="2026-10-14">October 14, 2026</time><h1>Initech moves support to Lumora</h1>'
        "<p>Initech now answers 9,000 support tickets a month with Lumora, and its median reply time "
        "fell from 6 hours to 41 minutes after the switch in September 2026.</p><p>" + PARA + "</p></article>"),
    "/integrations": _page("Integrations | Lumora", "<h1>Integrations</h1><p>Lumora integrates with Slack, "
                           "GitHub and Salesforce, with more than 120 integrations available today. "
                           + PARA + "</p>"),
    "/pricing": _page("Pricing | Lumora", "<h1>Pricing</h1><p>Plans start at $19 per seat per month, with a "
                      "14-day free trial and SOC 2 Type II compliance on every plan. " + PARA + "</p>"),
    "/about": _page("About | Lumora", "<h1>About Lumora</h1><p>Founded in 2019 in Lisbon, Lumora now serves "
                    "2,400 companies in 40 countries. " + PARA + "</p>"),
}
SPIN = _page("Blog | Lumora", "<p>never parsed</p>", head="<script>while (true) {}</script>")
BLOCKED = _page("Just a moment...", "<p>Checking your browser before accessing the site.</p>")


class _Site(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output readable
        pass

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0].rstrip("/") or "/"
        try:
            if path == "/":
                self._send(200, HOME.encode())
            elif path in GOOD:
                self._send(200, GOOD[path].encode())
            elif path == "/logo.svg":
                self._send(200, LOGO_SVG.encode(), "image/svg+xml")
            elif path == "/changelog":  # connection accepted, response never comes
                time.sleep(600)
            elif path == "/blog":
                self._send(200, SPIN.encode())
            elif path == "/newsroom":
                self._send(200, BLOCKED.encode())
            elif path == "/sitemap.xml":  # headers, then one byte every 0.2s forever
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.end_headers()
                while True:
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.2)
            else:
                self._send(404, b"not found")
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module", autouse=True)
def chromium():
    """Skip (not fail) when this machine has no usable Chromium/Chrome at all."""
    async def probe():
        async with crawl._browser("probe") as browser:
            page = await browser.new_page()
            await page.set_content("<h1>ok</h1>")
    try:
        asyncio.run(probe())
    except Exception as exc:
        pytest.skip(f"no usable Chromium for Playwright: {exc}")


@pytest.fixture
def fast(monkeypatch):
    """Short per-page timeouts so the hostile pages cost seconds, not minutes."""
    monkeypatch.setattr(crawl, "PAGE_TIMEOUT", 8)


def test_prepare_end_to_end_on_hostile_site(site, cfg, fast, monkeypatch, caplog):
    """The full prepare() step: brand kit, logo, and evidence from the good subpages, while the
    hanging / spinning / blocked / missing pages are skipped and logged, within a bounded time."""
    caplog.set_level(logging.INFO, logger="anchor")
    monkeypatch.setattr(research, "news_evidence", lambda *a, **k: [])  # no internet in this test
    cfg = replace(cfg, max_pages=4, subpage_budget=90)

    t0 = time.monotonic()
    pack, run_dir = prepare.prepare(site + "/", cfg, max_posts=2)
    elapsed = time.monotonic() - t0

    assert elapsed < 150, f"prepare took {elapsed:.0f}s"
    assert pack.brand.name == "Lumora"
    assert pack.industry == "saas"
    assert pack.brand.primary_color == BRAND
    assert pack.brand.logo_path and os.path.getsize(pack.brand.logo_path) > 0

    crawled = {u.removeprefix(site).rstrip("/") for u in pack.pages_crawled}
    assert {"/customers", "/integrations", "/pricing", "/about"} <= crawled, crawled
    assert not crawled & {"/changelog", "/blog", "/newsroom", "/press"}, crawled
    text = " ".join(e.text for e in pack.evidence)
    assert "38%" in text and "120 integrations" in text and "$19 per seat" in text
    # Second crawl level: the dated customer story linked from /customers.
    assert "/customers/initech-moves-support-to-lumora" in crawled
    story = [e for e in pack.evidence if "9,000 support tickets" in e.text]
    assert story and story[0].date == "2026-10-14"
    assert "/customers/page/2" not in crawled
    assert pack.language == "en" and pack.market_note.startswith("off:")
    assert (run_dir / "pack" / "pack.json").is_file()

    # Every subpage attempt is visible in the logs (the original bug was a silent hang).
    log = caplog.text
    for path, why in (("/changelog", "timed out"), ("/blog", "timed out"), ("/newsroom", "bot-protection"),
                      ("/press", "HTTP 404"), ("/customers", "chars")):
        assert any(path in line and why in line for line in log.splitlines()), (path, why)


def test_subpages_respect_wall_clock_budget(site, fast, caplog):
    """Every candidate hangs: crawl_pages gives up at its budget / stall limit and returns []."""
    caplog.set_level(logging.INFO, logger="anchor")
    urls = [f"{site}/changelog?{i}" for i in range(10)]
    t0 = time.monotonic()
    pages = asyncio.run(crawl.crawl_pages(urls, limit=8, budget=20))
    elapsed = time.monotonic() - t0
    assert pages == []
    assert elapsed < 20 + crawl.PAGE_TIMEOUT + 20, f"took {elapsed:.0f}s"
    assert "the browser looks stuck" in caplog.text or "budget" in caplog.text


def test_wedged_browser_is_killed_not_awaited_forever(monkeypatch):
    """If Chromium never acknowledges close(), leaving the session kills the driver instead of
    hanging the worker thread (the production symptom)."""
    seen = {}

    async def run():
        async with crawl._browser("wedge") as browser:
            page = await browser.new_page()
            await page.set_content("<p>hi</p>")
            cm_proc = browser._impl_obj._connection  # noqa: SLF001 (only to prove it is torn down)
            seen["conn"] = cm_proc

            async def never():
                await asyncio.sleep(3600)
            monkeypatch.setattr(browser, "close", never)

    t0 = time.monotonic()
    asyncio.run(run())
    assert time.monotonic() - t0 < 45
    assert seen["conn"]._closed_error is not None  # driver gone: in-flight calls are released


def test_sitemap_trickle_is_capped(site, monkeypatch):
    monkeypatch.setattr(crawl, "SITEMAP_SECONDS", 2)
    t0 = time.monotonic()
    assert crawl._sitemap(site) == []
    assert time.monotonic() - t0 < 8
