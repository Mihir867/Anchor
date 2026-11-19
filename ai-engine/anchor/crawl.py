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
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

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
    await page.goto(url, wait_until="domcontentloaded", timeout=35000)
    try:
        await page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    await page.wait_for_timeout(800)


async def crawl_home(url: str, assets_dir: Path) -> CrawlResult:
    from playwright.async_api import async_playwright

    assets_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await _launch(p)
        # 1x, not 2x: a 2x render of a heavy home page peaks around 750 MB and gets the process
        # OOM-killed on a 512 MB instance (1x: ~400 MB). Only the logo is rendered at 2x (_logo).
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, user_agent=UA,
                                        device_scale_factor=1)
        # Video, trackers, chat widgets and embeds are never used (screenshot and tokens come
        # from the first frame anyway) and are the bulk of a heavy page's memory.
        await ctx.route("**/*", _router(url, _ALWAYS_SKIP))
        page = await ctx.new_page()
        await _goto(page, url)
        final_url = page.url
        tokens = await page.evaluate(TOKENS_JS)
        shot = assets_dir / "screenshot.png"
        body_text = await page.evaluate("() => (document.body && document.body.innerText) || ''")
        reason = blocked_reason(tokens.get("title", ""), body_text)
        if reason:
            await browser.close()
            log.warning("[crawl] %s answered with a bot-protection page (%r); final url %s",
                        url, reason, final_url)
            raise SiteBlocked(f"{url} is behind bot protection ({reason!r}); the crawler was not let through")
        shot_ok = await _screenshot(page, shot)
        logo = await _logo(page, assets_dir / "logo.png")
        html = await _slim_html(page)
        await browser.close()
    log.info("[crawl] home %s: title=%r, %d chars of text", final_url, tokens.get("title", "")[:80], len(body_text))
    return CrawlResult(
        url=final_url, home=Page(final_url, html, tokens.get("title", "")), tokens=tokens,
        logo_path=logo, screenshot_path=str(shot) if shot_ok else None,
    )


async def _screenshot(page, out: Path) -> bool:
    """Best-effort viewport screenshot. Playwright's screenshot waits for web fonts and a stable
    frame; heavy pages (endless animations, slow font CDNs) on small instances can stall that
    wait past its 30 s default and used to fail the whole run. The screenshot is optional
    downstream, so: one bounded normal attempt, then a raw CDP capture that skips those waits,
    then give up and continue without one."""
    try:
        await page.screenshot(path=str(out), timeout=15000, animations="disabled", caret="hide")
        return True
    except Exception as err:
        log.warning("[crawl] screenshot failed (%s); retrying via CDP", str(err).splitlines()[0][:200])
    try:
        import base64
        cdp = await page.context.new_cdp_session(page)
        res = await asyncio.wait_for(
            cdp.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}), 15)
        out.write_bytes(base64.b64decode(res["data"]))
        return True
    except Exception as err:
        log.warning("[crawl] CDP screenshot failed too (%s); continuing without a screenshot",
                    str(err).splitlines()[0][:200] if str(err) else type(err).__name__)
        return False


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
                    await iso_ctx.close()
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


def _sitemap(origin: str) -> list[str]:
    """First 300 <loc> URLs. Streamed and capped: some sitemaps are tens of megabytes."""
    try:
        with httpx.stream("GET", f"{origin}/sitemap.xml", headers={"User-Agent": UA}, timeout=10,
                          follow_redirects=True) as r:
            if r.status_code != 200:
                return []
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) >= 2_000_000:
                    break
        return re.findall(r"<loc>\s*([^<]+?)\s*</loc>", buf.decode("utf-8", errors="replace"))[:300]
    except httpx.HTTPError:
        pass
    return []


async def crawl_pages(urls: list[str], limit: int, concurrency: int | None = None) -> list[Page]:
    """Render subpages for their text only. One page at a time by default: on small instances a
    second concurrent page roughly doubles Chromium's heap (ANCHOR_CRAWL_CONCURRENCY raises it)."""
    from playwright.async_api import async_playwright

    pages: list[Page] = []
    concurrency = concurrency or max(1, int(os.environ.get("ANCHOR_CRAWL_CONCURRENCY", "1") or 1))
    sem = asyncio.Semaphore(concurrency)
    async with async_playwright() as p:
        browser = await _launch(p)
        ctx = await browser.new_context(viewport={"width": 1366, "height": 900}, user_agent=UA)
        await ctx.route("**/*", _router(urls[0] if urls else "", _SUBPAGE_SKIP))

        async def one(u: str) -> Page | None:
            async with sem:
                if len(pages) >= limit:  # enough pages already: skip the spare candidates
                    return None
                pg = await ctx.new_page()
                try:
                    resp = await pg.goto(u, wait_until="domcontentloaded", timeout=25000)
                    if not resp or resp.status >= 400:
                        return None
                    await pg.wait_for_timeout(900)
                    title = await pg.title()
                    text = await pg.evaluate("() => (document.body && document.body.innerText) || ''")
                    if blocked_reason(title, text):
                        log.info("skip %s: bot-protection page", u)
                        return None
                    got = Page(pg.url, await _slim_html(pg), title)
                    if len(pages) < limit and all(got.url != x.url for x in pages):
                        pages.append(got)
                    return got
                except Exception as exc:
                    log.debug("skip %s: %s", u, exc)
                    return None
                finally:
                    await pg.close()

        await asyncio.gather(*(one(u) for u in urls[: limit + 4]))
        await browser.close()
    log.info("Rendered %d subpages", len(pages))
    return pages