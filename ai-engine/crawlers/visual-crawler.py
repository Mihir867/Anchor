"""
Visual & Brand Asset Crawler (Crawler 1) — v2
Extracts brand design tokens (HEX color palette, typography, font files,
logos, and hero snapshot) using headless Playwright.

v2 improvements:
  - Smarter page-load strategy (selector-based waits, no double-navigate)
  - @font-face extraction → actual font file URLs (.woff2/.woff/.ttf)
  - Deeper logo detection (SVG, <picture>, background-image, favicon, touch-icon)
  - Dark-site-aware color extraction (no longer filters all darks)
  - Accent color extraction from buttons, links, and CTA elements
  - Hero subheadline fallback chain
"""

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("visual_crawler")


class FontFace(BaseModel):
    family: str
    src_url: Optional[str] = None
    weight: Optional[str] = None
    style: Optional[str] = None
    format: Optional[str] = None


class VisualTokens(BaseModel):
    url: str
    title: str = ""
    description: str = ""
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    background_color: Optional[str] = None
    text_color: Optional[str] = None
    accent_colors: List[str] = Field(default_factory=list)
    all_brand_colors: List[str] = Field(default_factory=list)
    css_variables: Dict[str, str] = Field(default_factory=dict)
    heading_font: Optional[str] = None
    body_font: Optional[str] = None
    font_families: List[str] = Field(default_factory=list)
    font_faces: List[Dict[str, Any]] = Field(default_factory=list)
    favicon_url: Optional[str] = None
    og_image_url: Optional[str] = None
    logo_urls: List[str] = Field(default_factory=list)
    hero_headline: Optional[str] = None
    hero_subheadline: Optional[str] = None
    screenshot_path: Optional[str] = None


def rgb_to_hex(rgb_str: str) -> Optional[str]:
    """Converts rgb(r, g, b) or rgba(r, g, b, a) to #RRGGBB."""
    match = re.match(
        r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*[\d.]+)?\)", rgb_str.strip()
    )
    if not match:
        return None
    r, g, b = map(int, match.groups()[:3])
    return f"#{r:02x}{g:02x}{b:02x}".upper()


def is_near_monochrome(hex_color: str) -> bool:
    """Checks if a color is essentially black, white, or grey."""
    hex_color = hex_color.upper().lstrip("#")
    if len(hex_color) != 6:
        return False
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    # Check if all channels are very close (grey range)
    spread = max(r, g, b) - min(r, g, b)
    return spread < 25


async def extract_visual_tokens(
    url: str,
    output_screenshot_path: Optional[str] = "hero_screenshot.png",
    timeout_ms: int = 45000,
) -> VisualTokens:
    """
    Crawls a target website using Playwright and extracts all brand design tokens.
    """
    from playwright.async_api import async_playwright

    logger.info(f"Starting Visual Crawler for: {url}")

    # Normalize URL
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        # Handle case like "devrev.ai" parsed as path
        url = "https://" + url.lstrip("/")

    async with async_playwright() as p:
        logger.info("Launching headless Chrome...")
        browser = await p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # ----- SMART PAGE LOADING -----
        # Strategy: Navigate once with domcontentloaded (fast),
        # then wait for key content selectors to appear.
        try:
            logger.info(f"Navigating to {url} (timeout: {timeout_ms}ms)...")
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            logger.info("DOM loaded. Waiting for content to render...")

            # Wait for hero content (h1 or main heading) — most sites have one
            try:
                await page.wait_for_selector(
                    "h1, h2, [class*='hero'], [class*='headline'], main",
                    timeout=10000,
                )
                logger.info("Hero content detected.")
            except Exception:
                logger.info("No hero selector found within 10s, continuing anyway...")

            # Let JS/CSS/fonts settle
            await page.wait_for_timeout(3000)

        except Exception as e:
            logger.error(f"Navigation failed: {e}")
            await browser.close()
            return VisualTokens(url=url)

        # ----- 1. PAGE METADATA -----
        title = await page.title()
        description = ""
        desc_el = await page.query_selector(
            "meta[name='description'], meta[property='og:description']"
        )
        if desc_el:
            description = (await desc_el.get_attribute("content")) or ""

        og_image_url = None
        og_img_el = await page.query_selector("meta[property='og:image']")
        if og_img_el:
            og_img_content = await og_img_el.get_attribute("content")
            if og_img_content:
                og_image_url = urljoin(url, og_img_content)

        # Favicon (check multiple rel values)
        favicon_url = None
        for fav_selector in [
            "link[rel='icon']",
            "link[rel='shortcut icon']",
            "link[rel='apple-touch-icon']",
            "link[rel='apple-touch-icon-precomposed']",
        ]:
            fav_el = await page.query_selector(fav_selector)
            if fav_el:
                fav_href = await fav_el.get_attribute("href")
                if fav_href:
                    favicon_url = urljoin(url, fav_href)
                    break
        if not favicon_url:
            favicon_url = urljoin(url, "/favicon.ico")

        # ----- 2. HERO HEADLINE & SUBHEADLINE -----
        logger.info("Extracting hero headline...")
        hero_headline = None
        h1_el = await page.query_selector("h1")
        if h1_el:
            hero_headline = (await h1_el.inner_text()).strip()

        hero_subheadline = None
        # Try multiple fallback selectors for subheadline
        sub_selectors = [
            "h1 + p",
            "h1 ~ p",
            ".hero p",
            "[class*='hero'] p",
            "[class*='hero'] h2",
            "[class*='headline'] + p",
            "[class*='subtitle']",
            "[class*='subhead']",
            "[class*='sub-head']",
            "main > section:first-child p",
            "header + section p",
        ]
        for sel in sub_selectors:
            sub_el = await page.query_selector(sel)
            if sub_el:
                text = (await sub_el.inner_text()).strip()
                if 10 < len(text) < 300:
                    hero_subheadline = text
                    break

        # ----- 3. LOGO DETECTION (Deep) -----
        logger.info("Searching for brand logos...")
        logo_urls: List[str] = []
        seen_logo_srcs: Set[str] = set()

        # 3a. <img> in header/nav/logo containers
        logo_img_selectors = [
            "header img",
            "nav img",
            "a[href='/'] img",
            "[class*='logo'] img",
            "[id*='logo'] img",
            "[class*='brand'] img",
            "[class*='navbar'] img",
            "[aria-label*='logo' i] img",
            "[aria-label*='home' i] img",
        ]
        for sel in logo_img_selectors:
            elements = await page.query_selector_all(sel)
            for img in elements:
                src = await img.get_attribute("src")
                srcset = await img.get_attribute("srcset")
                if src and not src.startswith("data:"):
                    abs_src = urljoin(url, src)
                    if abs_src not in seen_logo_srcs:
                        seen_logo_srcs.add(abs_src)
                        logo_urls.append(abs_src)
                if srcset:
                    # Extract the highest resolution from srcset
                    parts = srcset.split(",")
                    for part in parts:
                        part_src = part.strip().split(" ")[0]
                        if part_src and not part_src.startswith("data:"):
                            abs_src = urljoin(url, part_src)
                            if abs_src not in seen_logo_srcs:
                                seen_logo_srcs.add(abs_src)
                                logo_urls.append(abs_src)

        # 3b. Inline SVG logos in header
        if not logo_urls:
            svg_containers = [
                "header a[href='/']",
                "nav a[href='/']",
                "[class*='logo']",
                "[class*='brand']",
                "header svg",
            ]
            for sel in svg_containers:
                parent = await page.query_selector(sel)
                if parent:
                    svg_el = await parent.query_selector("svg")
                    if svg_el:
                        # Extract the SVG markup so it can be used later
                        svg_html = await svg_el.evaluate("el => el.outerHTML")
                        if svg_html and len(svg_html) > 20:
                            logger.info(f"Found inline SVG logo via '{sel}'")
                            logo_urls.append(f"inline:svg_logo ({sel})")
                            break

        # 3c. Apple touch icon or large favicon as fallback logo
        touch_icon_el = await page.query_selector("link[rel='apple-touch-icon']")
        if touch_icon_el:
            href = await touch_icon_el.get_attribute("href")
            if href:
                abs_href = urljoin(url, href)
                if abs_href not in seen_logo_srcs:
                    logo_urls.append(abs_href)

        # ----- 4. FONT-FACE EXTRACTION (the big new feature) -----
        logger.info("Extracting @font-face declarations and font file URLs...")
        font_data = await page.evaluate(r"""
        () => {
            const fontFaces = [];
            const seenFamilies = new Set();

            // Method 1: document.fonts API (reliable, includes dynamically loaded fonts)
            if (document.fonts) {
                for (const ff of document.fonts) {
                    const entry = {
                        family: ff.family.replace(/['"]/g, ''),
                        weight: ff.weight || 'normal',
                        style: ff.style || 'normal',
                        status: ff.status,
                    };
                    // Try to get src from the CSS rule
                    const key = `${entry.family}-${entry.weight}-${entry.style}`;
                    if (!seenFamilies.has(key)) {
                        seenFamilies.add(key);
                        fontFaces.push(entry);
                    }
                }
            }

            // Method 2: Parse @font-face rules from stylesheets
            const fontFaceRules = [];
            for (let i = 0; i < document.styleSheets.length; i++) {
                try {
                    const sheet = document.styleSheets[i];
                    for (let j = 0; j < sheet.cssRules.length; j++) {
                        const rule = sheet.cssRules[j];
                        if (rule instanceof CSSFontFaceRule) {
                            const family = rule.style.getPropertyValue('font-family').replace(/['"]/g, '').trim();
                            const srcRaw = rule.style.getPropertyValue('src');
                            const weight = rule.style.getPropertyValue('font-weight') || 'normal';
                            const style = rule.style.getPropertyValue('font-style') || 'normal';

                            // Parse URL(s) from src
                            const urlMatches = [...srcRaw.matchAll(/url\(['"]?([^'")\s]+)['"]?\)/g)];
                            const urls = urlMatches.map(m => m[1]);

                            // Parse format hints
                            const formatMatches = [...srcRaw.matchAll(/format\(['"]?([^'")\s]+)['"]?\)/g)];
                            const formats = formatMatches.map(m => m[1]);

                            fontFaceRules.push({
                                family,
                                urls,
                                formats,
                                weight,
                                style,
                            });
                        }
                    }
                } catch (e) {
                    // Cross-origin stylesheets → skip
                }
            }

            // Method 3: Look for <link> preload hints for fonts
            const preloadFonts = [];
            document.querySelectorAll('link[rel="preload"][as="font"], link[rel="prefetch"][as="font"]').forEach(link => {
                const href = link.getAttribute('href');
                const type = link.getAttribute('type') || '';
                if (href) {
                    preloadFonts.push({ href, type });
                }
            });

            return { fontFaces, fontFaceRules, preloadFonts };
        }
        """)

        # Build font face list
        all_font_faces: List[Dict[str, Any]] = []
        seen_font_urls: Set[str] = set()

        for rule in font_data.get("fontFaceRules", []):
            family = rule["family"]
            for i, font_url in enumerate(rule.get("urls", [])):
                abs_url = urljoin(url, font_url)
                if abs_url not in seen_font_urls:
                    seen_font_urls.add(abs_url)
                    fmt = rule["formats"][i] if i < len(rule.get("formats", [])) else None
                    all_font_faces.append({
                        "family": family,
                        "src_url": abs_url,
                        "weight": rule.get("weight", "normal"),
                        "style": rule.get("style", "normal"),
                        "format": fmt,
                    })

        # Add preloaded font URLs
        for preload in font_data.get("preloadFonts", []):
            abs_url = urljoin(url, preload["href"])
            if abs_url not in seen_font_urls:
                seen_font_urls.add(abs_url)
                all_font_faces.append({
                    "family": "preloaded_unknown",
                    "src_url": abs_url,
                    "weight": "normal",
                    "style": "normal",
                    "format": preload.get("type", "").replace("font/", ""),
                })

        logger.info(f"Found {len(all_font_faces)} font file references.")

        # ----- 5. COMPUTED STYLES & COLOR PALETTE -----
        logger.info("Analyzing computed styles, colors, and typography...")
        style_data = await page.evaluate(r"""
        () => {
            // 1. CSS variables from :root
            const cssVars = {};
            const rootStyles = getComputedStyle(document.documentElement);
            for (let i = 0; i < document.styleSheets.length; i++) {
                try {
                    const sheet = document.styleSheets[i];
                    for (let j = 0; j < sheet.cssRules.length; j++) {
                        const rule = sheet.cssRules[j];
                        if (rule.selectorText === ':root' || rule.selectorText === ':root, :host') {
                            const style = rule.style;
                            for (let k = 0; k < style.length; k++) {
                                const prop = style[k];
                                if (prop.startsWith('--')) {
                                    const val = rootStyles.getPropertyValue(prop).trim();
                                    if (val) cssVars[prop] = val;
                                }
                            }
                        }
                    }
                } catch (e) {}
            }

            // 2. Sample colors from key elements (wider net)
            const bgCounts = {};
            const textCounts = {};
            const fontCounts = {};
            const accentColors = new Set();

            const sampleSelectors = 'body, header, nav, main, section, h1, h2, h3, h4, p, span, button, a, [class*="btn"], [class*="cta"], [class*="card"], footer, [class*="feature"], [class*="hero"]';
            const sampleElements = document.querySelectorAll(sampleSelectors);

            sampleElements.forEach(el => {
                const style = window.getComputedStyle(el);

                // Background color
                const bg = style.backgroundColor;
                if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                    bgCounts[bg] = (bgCounts[bg] || 0) + 1;
                }

                // Text color
                const color = style.color;
                if (color && color !== 'rgba(0, 0, 0, 0)' && color !== 'transparent') {
                    textCounts[color] = (textCounts[color] || 0) + 1;
                }

                // Fonts
                const font = style.fontFamily;
                if (font) {
                    const cleanFont = font.split(',')[0].replace(/['"]/g, '').trim();
                    if (cleanFont) fontCounts[cleanFont] = (fontCounts[cleanFont] || 0) + 1;
                }
            });

            // 3. Extract accent colors from interactive elements (buttons, CTAs, links)
            const interactiveEls = document.querySelectorAll('button, a[class*="btn"], a[class*="cta"], [class*="btn"], [class*="button"], [class*="cta"], [role="button"]');
            interactiveEls.forEach(el => {
                const style = window.getComputedStyle(el);
                const bg = style.backgroundColor;
                const borderColor = style.borderColor;
                if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                    accentColors.add(bg);
                }
                if (borderColor && borderColor !== 'rgba(0, 0, 0, 0)' && borderColor !== 'transparent' && borderColor !== bg) {
                    accentColors.add(borderColor);
                }
            });

            // Heading & Body fonts
            const h1 = document.querySelector('h1');
            const headingFont = h1 ? window.getComputedStyle(h1).fontFamily : null;
            const bodyFont = window.getComputedStyle(document.body).fontFamily;

            return {
                cssVars,
                bgCounts,
                textCounts,
                fontCounts,
                headingFont,
                bodyFont,
                accentColors: [...accentColors],
            };
        }
        """)

        # Process Colors
        bg_counts = style_data.get("bgCounts", {})
        text_counts = style_data.get("textCounts", {})

        hex_bg_freq: Dict[str, int] = {}
        for rgb_str, count in bg_counts.items():
            hex_val = rgb_to_hex(rgb_str)
            if hex_val:
                hex_bg_freq[hex_val] = hex_bg_freq.get(hex_val, 0) + count

        hex_text_freq: Dict[str, int] = {}
        for rgb_str, count in text_counts.items():
            hex_val = rgb_to_hex(rgb_str)
            if hex_val:
                hex_text_freq[hex_val] = hex_text_freq.get(hex_val, 0) + count

        sorted_bg = sorted(hex_bg_freq.items(), key=lambda x: x[1], reverse=True)
        sorted_text = sorted(hex_text_freq.items(), key=lambda x: x[1], reverse=True)

        # Accent colors from buttons/CTAs
        accent_hex: List[str] = []
        for rgb_str in style_data.get("accentColors", []):
            hex_val = rgb_to_hex(rgb_str)
            if hex_val and not is_near_monochrome(hex_val):
                if hex_val not in accent_hex:
                    accent_hex.append(hex_val)

        # Build full brand palette — separate chromatic from monochrome
        all_colors_ranked = [(c, f) for c, f in (sorted_bg + sorted_text)]
        chromatic_colors = [c for c, _ in all_colors_ranked if not is_near_monochrome(c)]
        # Deduplicate preserving order
        chromatic_colors = list(dict.fromkeys(chromatic_colors))

        # Combine accent colors (from buttons) with chromatic colors (from bg/text)
        all_brand_colors = list(dict.fromkeys(accent_hex + chromatic_colors))

        # Assign semantic roles
        background_color = sorted_bg[0][0] if sorted_bg else "#FFFFFF"
        text_color = sorted_text[0][0] if sorted_text else "#111111"

        if all_brand_colors:
            primary_color = all_brand_colors[0]
            secondary_color = all_brand_colors[1] if len(all_brand_colors) > 1 else None
        else:
            # Fallback: use the most common non-dominant bg/text color
            primary_color = text_color
            secondary_color = background_color

        # Typography
        heading_font_raw = style_data.get("headingFont") or ""
        body_font_raw = style_data.get("bodyFont") or ""
        heading_font = (
            heading_font_raw.split(",")[0].replace("'", "").replace('"', "").strip()
            if heading_font_raw
            else None
        )
        body_font = (
            body_font_raw.split(",")[0].replace("'", "").replace('"', "").strip()
            if body_font_raw
            else None
        )

        font_counts = style_data.get("fontCounts", {})
        sorted_fonts = [
            font
            for font, _ in sorted(font_counts.items(), key=lambda x: x[1], reverse=True)
        ]

        # Filter out CSS variable references from css_variables (keep only color/spacing/brand ones)
        raw_vars = style_data.get("cssVars", {})
        # Prioritize brand-relevant variables
        brand_var_patterns = re.compile(
            r"(color|brand|primary|secondary|accent|bg|background|text|font|heading|body|radius|spacing|shadow)",
            re.I,
        )
        brand_vars = {k: v for k, v in raw_vars.items() if brand_var_patterns.search(k)}
        # If too few brand vars, include all (up to 30)
        if len(brand_vars) < 5:
            brand_vars = dict(list(raw_vars.items())[:30])
        else:
            brand_vars = dict(list(brand_vars.items())[:30])

        # ----- 6. SCREENSHOT -----
        screenshot_file = None
        if output_screenshot_path:
            logger.info(f"Capturing hero viewport screenshot to: {output_screenshot_path}")
            await page.screenshot(path=output_screenshot_path, full_page=False)
            screenshot_file = str(Path(output_screenshot_path).resolve())

        await browser.close()
        logger.info("Browser closed successfully.")

        result = VisualTokens(
            url=url,
            title=title,
            description=description,
            primary_color=primary_color,
            secondary_color=secondary_color,
            background_color=background_color,
            text_color=text_color,
            accent_colors=accent_hex[:6],
            all_brand_colors=all_brand_colors[:10],
            css_variables=brand_vars,
            heading_font=heading_font,
            body_font=body_font,
            font_families=sorted_fonts[:8],
            font_faces=all_font_faces,
            favicon_url=favicon_url,
            og_image_url=og_image_url,
            logo_urls=logo_urls,
            hero_headline=hero_headline,
            hero_subheadline=hero_subheadline,
            screenshot_path=screenshot_file,
        )

        logger.info(f"Visual Extraction Complete for {url}!")
        return result


if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://native.no/"
    logger.info(f"Running standalone visual crawler on target: {target_url}")

    data = asyncio.run(
        extract_visual_tokens(target_url, output_screenshot_path="hero_screenshot.png")
    )

    output_path = Path("output_visuals.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data.model_dump(), f, indent=2)

    logger.info(f"Results successfully saved to {output_path.resolve()}")
    print("\n--- VISUAL BRAND TOKENS EXTRACTED ---")
    print(f"Title:            {data.title}")
    print(f"Primary Color:    {data.primary_color}")
    print(f"Secondary Color:  {data.secondary_color}")
    print(f"Background Color: {data.background_color}")
    print(f"Text Color:       {data.text_color}")
    print(f"Accent Colors:    {data.accent_colors}")
    print(f"Heading Font:     {data.heading_font}")
    print(f"Body Font:        {data.body_font}")
    print(f"Font Files Found: {len(data.font_faces)}")
    for ff in data.font_faces[:5]:
        print(f"  → {ff['family']} ({ff.get('weight','?')}) : {ff.get('src_url','inline')}")
    print(f"Logo URLs:        {data.logo_urls}")
    print(f"Hero Headline:    {data.hero_headline}")
    print(f"Hero Subheadline: {data.hero_subheadline}")
    print(f"Screenshot Path:  {data.screenshot_path}")
    print("--------------------------------------\n")
