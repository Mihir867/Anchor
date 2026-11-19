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
  const links = Array.from(document.querySelectorAll("a[href]")).map(a => a.href);
  return { title: document.title || "", description: meta("description") || meta("og:description") || "",
    site_name: meta("og:site_name") || "", og_image: meta("og:image") || "", ranked_colors: ranked.slice(0, 6),
    background: bg, text: hex(getComputedStyle(document.body).color) || "#111111",
    heading_font: fam(document.querySelector("h1, h2")), body_font: fam(document.querySelector("p") || document.body),
    font_faces: fontFaces.slice(0, 40), images: imgs, links,
    h1: (document.querySelector("h1") || {}).innerText || "" };
}"""

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

_LINUX_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
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
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, user_agent=UA,
                                        device_scale_factor=2)
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
        await page.screenshot(path=str(shot))
        logo = await _logo(page, assets_dir / "logo.png")
        html = await page.content()
        await browser.close()
    log.info("[crawl] home %s: title=%r, %d chars of text", final_url, tokens.get("title", "")[:80], len(body_text))
    return CrawlResult(
        url=final_url, home=Page(final_url, html, tokens.get("title", "")), tokens=tokens,
        logo_path=logo, screenshot_path=str(shot),
    )


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
                iso = await page.context.new_page()
                try:
                    w, h = int(box["width"]) + 2, int(box["height"]) + 2
                    await iso.set_content(
                        f'<html><body style="margin:0;background:transparent">'
                        f'<div id="l" style="display:inline-block;width:{w}px;height:{h}px;color:{markup["color"]}">'
                        f'<style>#l > *{{width:100%;height:100%;object-fit:contain}}</style>{markup["html"]}</div></body></html>')
                    await iso.wait_for_timeout(500)
                    await (await iso.query_selector("#l")).screenshot(path=str(out), omit_background=True)
                finally:
                    await iso.close()
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

    links = [l for l in result.tokens.get("links", []) if isinstance(l, str)]
    for path in list(priority_paths) + GENERIC_PATHS:
        stem = path.strip("/").lower()
        match = next((l for l in links if urlparse(l).path.strip("/").lower() == stem), None)
        add(match or urljoin(origin, path))
    signal = re.compile(r"(about|press|news|blog|customer|case|award|story|stories|partner|pricing|feature|product|offer|dining|room|event|collection|review)", re.I)
    for l in links:
        if signal.search(urlparse(l).path):
            add(l)
    for l in _sitemap(origin):
        if signal.search(urlparse(l).path):
            add(l)
    return ordered


def _sitemap(origin: str) -> list[str]:
    try:
        r = httpx.get(f"{origin}/sitemap.xml", headers={"User-Agent": UA}, timeout=10, follow_redirects=True)
        if r.status_code == 200:
            return re.findall(r"<loc>\s*([^<]+?)\s*</loc>", r.text)[:300]
    except httpx.HTTPError:
        pass
    return []


async def crawl_pages(urls: list[str], limit: int, concurrency: int = 4) -> list[Page]:
    from playwright.async_api import async_playwright

    pages: list[Page] = []
    sem = asyncio.Semaphore(concurrency)
    async with async_playwright() as p:
        browser = await _launch(p)
        ctx = await browser.new_context(viewport={"width": 1366, "height": 900}, user_agent=UA)

        async def one(u: str) -> Page | None:
            async with sem:
                pg = await ctx.new_page()
                try:
                    resp = await pg.goto(u, wait_until="domcontentloaded", timeout=25000)
                    if not resp or resp.status >= 400:
                        return None
                    await pg.wait_for_timeout(1200)
                    title = await pg.title()
                    text = await pg.evaluate("() => (document.body && document.body.innerText) || ''")
                    if blocked_reason(title, text):
                        log.info("skip %s: bot-protection page", u)
                        return None
                    return Page(pg.url, await pg.content(), title)
                except Exception as exc:
                    log.debug("skip %s: %s", u, exc)
                    return None
                finally:
                    await pg.close()

        for got in await asyncio.gather(*(one(u) for u in urls[: limit + 4])):
            if got and len(pages) < limit and all(got.url != x.url for x in pages):
                pages.append(got)
        await browser.close()
    log.info("Rendered %d subpages", len(pages))
    return pages