"""Rendered-site crawl: one Playwright browser, bounded and concurrent.

Phase 1 renders the home page: design tokens, logo (element screenshot, so SVG/CSS logos
work), hero screenshot, imagery and same-origin links. Phase 2 renders up to `max_pages`
subpages, prioritised by the industry skill's crawl paths, then generic high-signal paths,
then the site's own navigation and sitemap.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from . import progress

log = logging.getLogger("anchor.crawl")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
GENERIC_PATHS = [
    "/about", "/about-us", "/press", "/news", "/newsroom", "/blog", "/customers",
    "/case-studies", "/pricing", "/awards",
]
_SKIP = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|mp4|xml|css|js)$|/(login|signin|signup|cart|account|privacy|terms|cookie)", re.I)

TOKENS_JS = r"""() => {
  const meta = (k) => { const el = document.querySelector(`meta[property="${k}"], meta[name="${k}"]`); return el ? el.getAttribute("content") : null; };
  const hex = (c) => { const m = (c || "").match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/); if (!m) return null;
    if (m[4] !== undefined && parseFloat(m[4]) < 0.5) return null;
    return "#" + [m[1], m[2], m[3]].map(v => parseInt(v).toString(16).padStart(2, "0")).join("").toUpperCase(); };
  const sat = (h) => { const r = parseInt(h.substr(1,2),16)/255, g = parseInt(h.substr(3,2),16)/255, b = parseInt(h.substr(5,2),16)/255;
    const mx = Math.max(r,g,b), mn = Math.min(r,g,b); return mx === 0 ? 0 : (mx - mn) / mx; };
  const weights = {};
  document.querySelectorAll('button, a[class*="btn"], a[class*="button"], [class*="cta"], [class*="primary"], [role="button"]').forEach(el => {
    const r = el.getBoundingClientRect(); if (r.width < 20 || r.height < 14) return;
    const cs = getComputedStyle(el);
    for (const c of [hex(cs.backgroundColor), hex(cs.borderColor)]) {
      if (c && sat(c) > 0.25) weights[c] = (weights[c] || 0) + r.width * r.height;
    }
  });
  document.querySelectorAll("a").forEach(el => { const c = hex(getComputedStyle(el).color); if (c && sat(c) > 0.35) weights[c] = (weights[c] || 0) + 400; });
  const root = getComputedStyle(document.documentElement);
  for (const sheet of Array.from(document.styleSheets)) { try { for (const rule of Array.from(sheet.cssRules)) {
    if (rule.selectorText === ":root" && rule.style) for (const prop of Array.from(rule.style)) {
      if (/(primary|brand|accent)/i.test(prop)) { const v = root.getPropertyValue(prop).trim(); const m = v.match(/^#([0-9a-f]{6})$/i);
        if (m && sat("#" + m[1].toUpperCase()) > 0.25) weights["#" + m[1].toUpperCase()] = (weights["#" + m[1].toUpperCase()] || 0) + 50000; } }
  } } catch (e) {} }
  const ranked = Object.entries(weights).sort((a, b) => b[1] - a[1]).map(e => e[0]);
  const fontFaces = [];
  for (const sheet of Array.from(document.styleSheets)) { try { for (const rule of Array.from(sheet.cssRules)) {
    if (rule.type === CSSRule.FONT_FACE_RULE) { const s = rule.style; const src = s.getPropertyValue("src");
      const urls = Array.from(src.matchAll(/url\(["']?([^"')]+)["']?\)/g)).map(m => new URL(m[1], sheet.href || location.href).href);
      if (urls.length) fontFaces.push({ family: s.getPropertyValue("font-family").replace(/["']/g, "").trim(),
        weight: s.getPropertyValue("font-weight") || "400", style: s.getPropertyValue("font-style") || "normal", urls }); } }
  } catch (e) {} }
  const fam = (el) => el ? getComputedStyle(el).fontFamily.split(",")[0].replace(/["']/g, "").trim() : null;
  let bg = hex(getComputedStyle(document.body).backgroundColor) || hex(getComputedStyle(document.documentElement).backgroundColor) || "#FFFFFF";
  const imgs = Array.from(document.images).filter(i => i.naturalWidth >= 600 && i.naturalHeight >= 400).map(i => i.currentSrc || i.src).slice(0, 12);
  const links = Array.from(new Set(Array.from(document.querySelectorAll("a[href]")).map(a => a.href))).slice(0, 400);
  return { title: document.title || "", description: meta("description") || meta("og:description") || "",
    site_name: meta("og:site_name") || "", og_image: meta("og:image") || "", ranked_colors: ranked.slice(0, 6),
    background: bg, text: hex(getComputedStyle(document.body).color) || "#111111",
    heading_font: fam(document.querySelector("h1, h2")), body_font: fam(document.querySelector("p") || document.body),
    font_faces: fontFaces.slice(0, 40), images: imgs, links,
    h1: (document.querySelector("h1") || {}).innerText || "" };
}"""

# Run just before page.content(): keep only what extract.py reads (text, headings, quotes, meta,
# JSON-LD, <time>, class names, img alt). Inline JS bundles, CSS, SVG and iframes are often
# megabytes per page; dropping them in the browser keeps both Chromium and the Python parse small.
SLIM_JS = r"""(maxChars) => {
  document.querySelectorAll('script:not([type="application/ld+json"]), style, link, noscript, svg, iframe, '
    + 'video, audio, canvas, template, object, embed, source, picture > source, map, dialog').forEach(e => e.remove());
  const keep = new Set(["class", "alt", "href", "src", "datetime", "content", "property", "name", "type", "id", "lang"]);
  document.querySelectorAll("*").forEach(el => {
    for (const a of Array.from(el.attributes)) if (!keep.has(a.name)) el.removeAttribute(a.name);
    if (el.tagName === "IMG" && (el.getAttribute("src") || "").startsWith("data:")) el.removeAttribute("src");
  });
  const html = document.documentElement.outerHTML;
  return html.length > maxChars ? html.slice(0, maxChars) : html;
}"""
# Enough for every evidence chunk a page can yield (extract keeps ~70 items across all pages).
_HTML_CAP = 600_000

# Third parties that add memory and network time but never carry brand content: analytics,
# ads, tag managers, chat widgets, session replay, embedded players.
_THIRD_PARTY = re.compile(
    r"(googletagmanager|google-analytics|googleadservices|doubleclick|googlesyndication|facebook\.net|"
    r"connect\.facebook|hotjar|clarity\.ms|segment\.(io|com)|mixpanel|amplitude|fullstory|heap(analytics)?\.|"
    r"intercom|drift\.com|zendesk|zdassets|hubspot|hs-scripts|hs-analytics|hsforms|crisp\.chat|tawk\.to|"
    r"livechat|olark|optimizely|newrelic|nr-data|sentry|datadoghq|bugsnag|linkedin\.com/(li|px)|snap\.licdn|"
    r"tiktok|pinterest|twitter\.com/i|ads-twitter|bing\.com/(bat|action)|youtube\.com/embed|ytimg|vimeo|"
    r"wistia|vidyard|cookiebot|onetrust|cookielaw|trustarc|recaptcha|hcaptcha|gstatic\.com/recaptcha)",
    re.I,
)
# Requests nothing in the crawl reads. Home keeps images/fonts/CSS (screenshot, logo, tokens).
_ALWAYS_SKIP = {"media", "websocket", "eventsource", "manifest", "texttrack", "ping", "beacon"}
# Subpages are only read for text.
_SUBPAGE_SKIP = _ALWAYS_SKIP | {"image", "font", "stylesheet"}


def _site(host: str) -> str:
    """Rough registrable domain (last two labels): enough to tell first party from third."""
    return ".".join(host.lower().removeprefix("www.").split(".")[-2:])


def _blocked(url: str, resource_type: str, site: str, skip_types: set[str]) -> bool:
    if resource_type in skip_types:
        return True
    host = urlparse(url).netloc.split(":")[0]
    # Never block the brand's own requests (crawling hubspot.com must still load hubspot.com).
    return _site(host) != site and bool(_THIRD_PARTY.search(url))


def _router(site_url: str, skip_types: set[str]):
    site = _site(urlparse(site_url).netloc.split(":")[0])

    async def route(r):
        req = r.request
        try:
            main_nav = req.is_navigation_request() and req.frame.parent_frame is None
        except Exception:
            main_nav = False
        if not main_nav and _blocked(req.url, req.resource_type, site, skip_types):
            await r.abort()
        else:
            await r.continue_()
    return route


async def _slim_html(page) -> str:
    try:
        return await page.evaluate(SLIM_JS, _HTML_CAP)
    except Exception:  # page navigated or crashed mid-evaluate: fall back to the raw DOM, capped
        return (await page.content())[:_HTML_CAP]


LOGO_SELECTORS = [
    'header a[href="/"] img', 'header a[href="/"] svg', 'nav a[href="/"] img', 'nav a[href="/"] svg',
    '[class*="logo" i] img', '[class*="logo" i] svg', 'img[alt*="logo" i]', 'img[src*="logo" i]',
    'a[aria-label*="home" i] svg', 'header svg',
]


class SiteBlocked(RuntimeError):
    """The site answered with a bot-protection page (Vercel, Cloudflare, Akamai...) instead of
    its content. Nothing to read; the site owner has to allow the crawler."""


# Bot-protection interstitials, matched on the page title or its first visible text.
_BLOCK_MARKERS = re.compile(
    r"vercel security checkpoint|security checkpoint|just a moment\.\.\.|attention required|"
    r"verify(ing)? (that )?you are (a )?human|we're verifying your browser|checking your browser|"
    r"enable javascript and cookies to continue|pardon our interruption|access denied|ddos-guard|"
    r"request unsuccessful\. incapsula|are you a robot",
    re.I,
)


def blocked_reason(title: str, text: str) -> str | None:
    """The block page's own wording when the page is a bot-protection interstitial, else None."""
    head = f"{title} {text[:600]}"
    m = _BLOCK_MARKERS.search(head)
    # A real page can mention "access denied" deep in its copy; interstitials are short.
    if m and (len(text) < 3000 or _BLOCK_MARKERS.search(title or "")):
        return m.group(0)
    return None


@dataclass
class Page:
    url: str
    html: str
    title: str = ""


@dataclass
class CrawlResult:
    url: str
    home: Page
    pages: list[Page] = field(default_factory=list)
    tokens: dict = field(default_factory=dict)
    logo_path: str | None = None
    screenshot_path: str | None = None


# Browsers installed inside the project dir survive from build to runtime on hosts like Render,
# where ~/.cache (Playwright's default) is not carried over. render-build.sh installs here.
_LOCAL_BROWSERS = Path(__file__).resolve().parent.parent / ".playwright"
if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and (_LOCAL_BROWSERS.is_dir() or sys.platform.startswith("linux")):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_LOCAL_BROWSERS)

_LINUX_ARGS = [
    "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
    # Memory: fewer renderer processes and no per-site process isolation. Measured on heavy home
    # pages, this caps Chromium's spikes around 350 MB instead of ~570 MB, which is what keeps
    # small (512 MB) instances from being OOM-killed mid-crawl.
    "--renderer-process-limit=1", "--disable-site-isolation-trials",
    "--disable-features=site-per-process,IsolateOrigins,Translate,MediaRouter",
    "--disable-extensions", "--disable-background-networking", "--disable-software-rasterizer",
    "--no-zygote",
]
_install_tried = False


def _missing_browser(err: Exception) -> bool:
    msg = str(err).lower()
    return "executable doesn't exist" in msg or "playwright install" in msg


async def _install_chromium() -> None:
    log.warning("Playwright chromium missing; installing into %s", os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "default path"))
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "playwright", "install", "chromium",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        log.error("playwright install chromium failed (%s): %s", proc.returncode, out.decode(errors="replace")[-2000:])


async def _launch(p):
    args = _LINUX_ARGS if sys.platform.startswith("linux") else []
    try:
        return await p.chromium.launch(headless=True, args=args)
    except Exception as err:
        if not _missing_browser(err):
            raise
    # Bundled chromium is missing (not installed at build time): install it once per process, retry.
    global _install_tried
    if not _install_tried:
        _install_tried = True
        await _install_chromium()
    try:
        return await p.chromium.launch(headless=True, args=args)
    except Exception as err:
        if sys.platform == "darwin":  # local dev: fall back to an installed Google Chrome
            try:
                return await p.chromium.launch(headless=True, channel="chrome")
            except Exception:
                pass
        raise RuntimeError(
            "Chromium is not available for Playwright. Run `python -m playwright install chromium` "
            "during the build (see render-build.sh)."
        ) from err


async def _goto(page, url: str) -> None:
    await _deadline(page.goto(url, wait_until="domcontentloaded", timeout=35000), 45,
                    f"{url}: the page did not load within 45s")
    await _bounded(page.wait_for_load_state("networkidle", timeout=6000), 8, "networkidle", quiet=True)
    await page.wait_for_timeout(800)


async def _deadline(coro, seconds: float, message: str):
    """Await `coro`; raise RuntimeError(message) if it overruns. Playwright's own timeouts live
    in the Node driver and can overrun (or never fire) when the renderer is wedged on a heavy
    page; an asyncio deadline always returns control to us."""
    try:
        return await asyncio.wait_for(coro, seconds)
    except asyncio.TimeoutError:
        raise RuntimeError(message) from None


async def _bounded(coro, seconds: float, label: str, default=None, quiet: bool = False):
    """Like _deadline, for optional steps: overruns and errors are logged and `default` returned."""
    try:
        return await asyncio.wait_for(coro, seconds)
    except asyncio.TimeoutError:
        if not quiet:
            log.warning("[crawl] %s took longer than %ss; skipped", label, seconds)
    except Exception as err:
        if not quiet:
            log.warning("[crawl] %s failed (%s); skipped", label, _first_line(err))
    return default


def _first_line(err: BaseException) -> str:
    return (str(err).splitlines() or [type(err).__name__])[0][:200]


async def _done(coro) -> bool:
    await coro
    return True


def _child_pids(pid: int) -> list[int]:
    """Direct children of `pid` (/proc on Linux, `ps` elsewhere). Empty if unknown."""
    try:
        if Path("/proc").is_dir() and sys.platform.startswith("linux"):
            out = []
            for d in Path("/proc").iterdir():
                if d.name.isdigit():
                    try:
                        if int((d / "stat").read_text().rsplit(")", 1)[1].split()[1]) == pid:
                            out.append(int(d.name))
                    except (OSError, ValueError, IndexError):
                        pass
            return out
        ps = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=5)
        return [int(a) for a, b in (l.split() for l in ps.stdout.splitlines() if l.strip()) if int(b) == pid]
    except Exception:
        return []


def _kill_driver(cm) -> None:
    """Last resort when Playwright will not shut down: SIGKILL the Node driver and the browsers it
    launched (each browser leads its own process group). Every in-flight Playwright call then fails
    with TargetClosedError instead of waiting forever, and Chromium's memory is freed."""
    proc = getattr(getattr(getattr(cm, "_client", None), "_transport", None), "_proc", None)
    pid = getattr(proc, "pid", None)
    if not pid:
        return
    for child in _child_pids(pid):
        for kill in (lambda c: os.killpg(c, signal.SIGKILL), lambda c: os.kill(c, signal.SIGKILL)):
            try:
                kill(child)
                break
            except (OSError, PermissionError):
                continue
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    log.warning("[crawl] browser did not shut down cleanly; killed the Playwright driver (pid %s)", pid)


@asynccontextmanager
async def _browser(label: str):
    """A Chromium browser whose startup and shutdown are both bounded. Leaving the block always
    releases the browser: close politely, and if the driver is wedged, kill it."""
    from playwright.async_api import async_playwright

    cm = async_playwright()
    try:
        pw = await _deadline(cm.start(), 60, f"{label}: the Playwright driver did not start within 60s")
    except BaseException:
        _kill_driver(cm)
        raise
    browser = None
    try:
        # Generous: the first launch on a fresh host may install Chromium (_launch).
        browser = await _deadline(_launch(pw), 240, f"{label}: Chromium did not start within 240s")
        yield browser
    finally:
        closed = browser is None or await _bounded(_done(browser.close()), 10, f"{label}: browser close", False)
        stopped = closed and await _bounded(_done(pw.stop()), 15, f"{label}: Playwright shutdown", False)
        if not stopped:
            _kill_driver(cm)
            await _bounded(_done(pw.stop()), 5, f"{label}: Playwright shutdown after kill", quiet=True)


async def crawl_home(url: str, assets_dir: Path) -> CrawlResult:
    assets_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    async with _browser("home") as browser:
        # 1x, not 2x: a 2x render of a heavy home page peaks around 750 MB and gets the process
        # OOM-killed on a 512 MB instance (1x: ~400 MB). Only the logo is rendered at 2x (_logo).
        ctx = await _deadline(browser.new_context(viewport={"width": 1440, "height": 900}, user_agent=UA,
                                                  device_scale_factor=1), 30, "home: could not open a browser context")
        # Video, trackers, chat widgets and embeds are never used (screenshot and tokens come
        # from the first frame anyway) and are the bulk of a heavy page's memory.
        await _deadline(ctx.route("**/*", _router(url, _ALWAYS_SKIP)), 15, "home: could not install the request filter")
        page = await _deadline(ctx.new_page(), 30, "home: could not open a page")
        await _goto(page, url)
        final_url = page.url
        log.info("[crawl] home loaded in %.1fs: %s", time.monotonic() - t0, final_url)
        # Essential reads: bounded so a wedged renderer fails the run with a clear error
        # instead of hanging the worker thread forever.
        stuck = f"{url}: the page stopped responding while being read"
        tokens = await _deadline(page.evaluate(TOKENS_JS), 30, stuck)
        body_text = await _deadline(page.evaluate("() => (document.body && document.body.innerText) || ''"), 15, stuck)
        reason = blocked_reason(tokens.get("title", ""), body_text)
        if reason:
            log.warning("[crawl] %s answered with a bot-protection page (%r); final url %s",
                        url, reason, final_url)
            raise SiteBlocked(f"{url} is behind bot protection ({reason!r}); the crawler was not let through")
        # Logo and screenshot before HTML: _slim_html strips SVGs, CSS and attributes from
        # the live DOM.
        logo = await _bounded(_logo(page, assets_dir / "logo.png"), 20, "logo capture")
        # The screenshot is only a fallback image (render.brand_images uses og:image and the
        # site's large images first). Skip it when those exist; it is the slowest, most
        # hang-prone step on heavy pages.
        shot = assets_dir / "screenshot.png"
        shot_ok = False
        if tokens.get("og_image") or tokens.get("images"):
            log.info("[crawl] site has its own imagery; skipping home screenshot")
        else:
            shot_ok = bool(await _bounded(_screenshot(page, shot), 20, "home screenshot", False))
        html = await _deadline(_slim_html(page), 45, stuck)
    log.info("[crawl] home %s: title=%r, %d chars of text (%.1fs)", final_url, tokens.get("title", "")[:80],
             len(body_text), time.monotonic() - t0)
    return CrawlResult(
        url=final_url, home=Page(final_url, html, tokens.get("title", "")), tokens=tokens,
        logo_path=logo, screenshot_path=str(shot) if shot_ok else None,
    )


async def _screenshot(page, out: Path) -> bool:
    """Viewport capture via raw CDP. Playwright's page.screenshot waits for web fonts and a stable
    frame, which can stall indefinitely on animated pages; CDP just grabs the current frame.
    The caller bounds this with a hard deadline."""
    import base64
    cdp = await page.context.new_cdp_session(page)
    res = await cdp.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
    out.write_bytes(base64.b64decode(res["data"]))
    return True


async def _logo(page, out: Path) -> str | None:
    """Find the header logo and re-render it ALONE on a transparent page, so whatever sits
    behind a transparent header (hero photos, gradients) is not captured with it."""
    for sel in LOGO_SELECTORS:
        try:
            for el in (await page.query_selector_all(sel))[:3]:
                box = await el.bounding_box()
                if not box or box["width"] < 24 or box["height"] < 10 or box["y"] > 300:
                    continue
                if box["width"] > 600 or box["height"] > 200:
                    continue
                markup = await el.evaluate("""e => {
                    const color = getComputedStyle(e).color;
                    if (e.tagName.toLowerCase() === 'img') return {color, html: `<img src="${e.currentSrc || e.src}">`};
                    return {color, html: e.outerHTML};
                }""")
                # A tiny separate 2x context keeps the logo crisp without rendering the page at 2x.
                iso_ctx = await page.context.browser.new_context(device_scale_factor=2)
                iso = await iso_ctx.new_page()
                try:
                    w, h = int(box["width"]) + 2, int(box["height"]) + 2
                    await iso.set_content(
                        f'<html><body style="margin:0;background:transparent">'
                        f'<div id="l" style="display:inline-block;width:{w}px;height:{h}px;color:{markup["color"]}">'
                        f'<style>#l > *{{width:100%;height:100%;object-fit:contain}}</style>{markup["html"]}</div></body></html>')
                    await iso.wait_for_timeout(500)
                    await (await iso.query_selector("#l")).screenshot(path=str(out), omit_background=True)
                finally:
                    await _bounded(iso_ctx.close(), 5, "logo context close", quiet=True)
                return str(out)
        except Exception:
            continue
    return None


def candidate_urls(result: CrawlResult, priority_paths: list[str], limit: int) -> list[str]:
    origin = "{0.scheme}://{0.netloc}".format(urlparse(result.url))
    host = urlparse(result.url).netloc.removeprefix("www.")
    ordered: list[str] = []

    def add(u: str) -> None:
        u = u.split("#")[0].split("?")[0].rstrip("/")
        pu = urlparse(u)
        if pu.netloc.removeprefix("www.") != host or not pu.path or pu.path == "/" or _SKIP.search(pu.path):
            return
        if u not in ordered and u.rstrip("/") != result.url.rstrip("/"):
            ordered.append(u)

    # Most important first, so the small page budget is spent on pages that exist: the playbook's
    # paths the home page links to, then other high-signal links from the home page, then the
    # playbook paths guessed blind (often 404), then the sitemap.
    links = [l for l in result.tokens.get("links", []) if isinstance(l, str)]
    by_stem: dict[str, str] = {}
    for l in links:
        by_stem.setdefault(urlparse(l).path.strip("/").lower(), l)
    paths = list(dict.fromkeys(list(priority_paths) + GENERIC_PATHS))
    for path in paths:
        if path.strip("/").lower() in by_stem:
            add(by_stem[path.strip("/").lower()])
    signal = re.compile(r"(about|press|news|blog|customer|case|award|story|stories|partner|pricing|feature|product|offer|dining|room|event|collection|review)", re.I)
    for l in links:
        if signal.search(urlparse(l).path):
            add(l)
    for path in paths:
        add(urljoin(origin, path))
    if len(ordered) < limit + 4:  # the sitemap is only fetched when the home page was not enough
        for l in _sitemap(origin):
            if signal.search(urlparse(l).path):
                add(l)
    return ordered


SITEMAP_SECONDS = 15  # wall clock: httpx's timeout is per read, so a trickling server never trips it


def _sitemap(origin: str) -> list[str]:
    """First 300 <loc> URLs. Streamed and capped: some sitemaps are tens of megabytes."""
    try:
        with httpx.stream("GET", f"{origin}/sitemap.xml", headers={"User-Agent": UA}, timeout=10,
                          follow_redirects=True) as r:
            if r.status_code != 200:
                return []
            buf = bytearray()
            stop_at = time.monotonic() + SITEMAP_SECONDS
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) >= 2_000_000 or time.monotonic() > stop_at:
                    break
        return re.findall(r"<loc>\s*([^<]+?)\s*</loc>", buf.decode("utf-8", errors="replace"))[:300]
    except httpx.HTTPError:
        pass
    return []


PAGE_TIMEOUT = 40  # seconds for one subpage, end to end
_MAX_STALLS = 3   # consecutive subpage timeouts = the renderer is wedged; stop early


async def crawl_pages(urls: list[str], limit: int, concurrency: int | None = None,
                      budget: float | None = None) -> list[Page]:
    """Render subpages for their text only, within a wall-clock `budget` (seconds).

    Subpages are an enhancement: whatever is collected when the budget runs out (or the browser
    wedges) is returned, never an error. One page at a time by default: on small instances a
    second concurrent page roughly doubles Chromium's heap (ANCHOR_CRAWL_CONCURRENCY raises it)."""
    queue = list(dict.fromkeys(urls))[: limit + 4]
    if not queue or limit <= 0:
        return []
    concurrency = concurrency or max(1, int(os.environ.get("ANCHOR_CRAWL_CONCURRENCY", "1") or 1))
    budget = budget or float(os.environ.get("ANCHOR_SUBPAGE_BUDGET", "150") or 150)
    total = len(queue)
    pages: list[Page] = []
    state = {"tried": 0, "stalls": 0}
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    deadline = t0 + budget
    log.info("[crawl] rendering up to %d subpages from %d candidates (budget %.0fs)", limit, total, budget)

    try:
        async with _browser("subpages") as browser:
            ctx = await _deadline(browser.new_context(viewport={"width": 1366, "height": 900}, user_agent=UA),
                                  30, "subpages: could not open a browser context")
            await _deadline(ctx.route("**/*", _router(queue[0], _SUBPAGE_SKIP)), 15,
                            "subpages: could not install the request filter")

            async def read(pg, u: str) -> tuple[Page | None, str]:
                resp = await pg.goto(u, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT * 1000)
                if not resp or resp.status >= 400:
                    return None, f"HTTP {resp.status if resp else 'no response'}"
                await pg.wait_for_timeout(900)
                title = await pg.title()
                text = await pg.evaluate("() => (document.body && document.body.innerText) || ''")
                if blocked_reason(title, text):
                    return None, "bot-protection page"
                return Page(pg.url, await _slim_html(pg), title), f"{len(text)} chars"

            async def one(u: str) -> None:
                state["tried"] += 1
                n, started = state["tried"], loop.time()
                window = min(PAGE_TIMEOUT + 10, deadline - started)
                pg, got, stalled = None, None, False
                try:
                    pg = await asyncio.wait_for(ctx.new_page(), min(15, window))
                    got, note = await asyncio.wait_for(read(pg, u), max(1, window - (loop.time() - started)))
                except asyncio.TimeoutError:
                    note, stalled = "timed out", True
                except Exception as exc:
                    # Playwright's own TimeoutError (goto timeout) is a stall too.
                    stalled = type(exc).__name__ == "TimeoutError"
                    note = "timed out" if stalled else _first_line(exc)
                finally:
                    if pg is not None:
                        await _bounded(pg.close(), 5, f"close {u}", quiet=True)
                state["stalls"] = state["stalls"] + 1 if stalled else 0
                kept = bool(got and len(pages) < limit and all(got.url != x.url for x in pages))
                if kept:
                    pages.append(got)
                log.info("[crawl] subpage %d/%d %s %s (%s, %.1fs)", n, total, "ok  " if kept else "skip",
                         u, note if got is None or kept else "duplicate", loop.time() - started)
                # Live progress for the client; raises progress.Cancelled when the job is stopped.
                progress.report("crawling", subpages=len(pages))

            async def worker() -> None:
                while queue and len(pages) < limit:
                    if deadline - loop.time() < 5:
                        log.warning("[crawl] subpage budget of %.0fs used up; continuing with %d page(s)",
                                    budget, len(pages))
                        return
                    if state["stalls"] >= _MAX_STALLS:
                        log.warning("[crawl] %d subpages in a row timed out; the browser looks stuck, "
                                    "continuing with %d page(s)", state["stalls"], len(pages))
                        return
                    await one(queue.pop(0))

            # asyncio.wait, not gather/wait_for: it returns at the deadline even if a task is stuck
            # in a Playwright call that ignores cancellation. Leaving _browser() then kills the
            # driver, which fails those calls and lets the tasks finish.
            tasks = [asyncio.create_task(worker()) for _ in range(concurrency)]
            done, pending = await asyncio.wait(tasks, timeout=budget + PAGE_TIMEOUT)
            for t in pending:
                t.cancel()
            if pending:
                log.warning("[crawl] subpage rendering overran its budget; stopping it")
                await asyncio.wait(pending, timeout=5)
            for t in done:
                if not t.cancelled() and isinstance(t.exception(), progress.Cancelled):
                    raise t.exception()
                if not t.cancelled() and t.exception():
                    log.warning("[crawl] subpage worker failed: %s", _first_line(t.exception()))
    except progress.Cancelled:
        raise
    except Exception as exc:  # browser could not start, or died: subpages are optional
        log.warning("[crawl] subpage rendering stopped early (%s); continuing with %d page(s)",
                    _first_line(exc), len(pages))
    log.info("Rendered %d subpages in %.1fs", len(pages), loop.time() - t0)
    return pages
