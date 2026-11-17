"""
Visual & Brand Asset Crawler (Crawler 1)
Extracts brand design tokens (HEX color palette, typography, logos, and hero snapshot)
using headless Playwright.
"""

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("visual_crawler")


class VisualTokens(BaseModel):
    url: str
    title: str = ""
    description: str = ""
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    background_color: Optional[str] = None
    text_color: Optional[str] = None
    accent_colors: List[str] = Field(default_factory=list)
    css_variables: Dict[str, str] = Field(default_factory=dict)
    heading_font: Optional[str] = None
    body_font: Optional[str] = None
    font_families: List[str] = Field(default_factory=list)
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
    # Ignore pure transparent or extreme outliers if alpha is 0
    return f"#{r:02x}{g:02x}{b:02x}".upper()


async def extract_visual_tokens(
    url: str,
    output_screenshot_path: Optional[str] = "hero_screenshot.png",
    timeout_ms: int = 30000,
) -> VisualTokens:
    """
    Crawls a target website using Playwright and extracts all brand design tokens.
    """
    from playwright.async_api import async_playwright

    logger.info(f"Starting Visual Crawler for: {url}")
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url

    async with async_playwright() as p:
        logger.info("Launching headless Chromium...")
        browser = await p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        try:
            logger.info(f"Navigating to {url} (timeout: {timeout_ms}ms)...")
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            logger.info("Page loaded and network settled.")
        except Exception as e:
            logger.warning(f"Networkidle wait timed out, falling back to domcontentloaded: {e}")
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        # Allow dynamic JS and animations to settle
        await page.wait_for_timeout(2000)

        # 1. Page Metadata
        title = await page.title()
        description = ""
        desc_el = await page.query_selector("meta[name='description'], meta[property='og:description']")
        if desc_el:
            description = (await desc_el.get_attribute("content")) or ""

        og_image_url = None
        og_img_el = await page.query_selector("meta[property='og:image']")
        if og_img_el:
            og_img_content = await og_img_el.get_attribute("content")
            if og_img_content:
                og_image_url = urljoin(url, og_img_content)

        favicon_url = None
        fav_el = await page.query_selector("link[rel~='icon'], link[rel='apple-touch-icon']")
        if fav_el:
            fav_href = await fav_el.get_attribute("href")
            if fav_href:
                favicon_url = urljoin(url, fav_href)

        # 2. Extract Hero Headline & Subheadline
        logger.info("Extracting Hero headline...")
        hero_headline = None
        h1_el = await page.query_selector("h1")
        if h1_el:
            hero_headline = (await h1_el.inner_text()).strip()

        hero_subheadline = None
        sub_el = await page.query_selector("h1 + p, h1 ~ p, .hero p, [class*='hero'] p")
        if sub_el:
            hero_subheadline = (await sub_el.inner_text()).strip()

        # 3. Extract In-DOM Logos (Header / Nav)
        logger.info("Searching for brand logos in header & navigation...")
        logo_urls = []
        logo_elements = await page.query_selector_all(
            "header img, nav img, a[href='/'] img, [class*='logo'] img, [id*='logo'] img"
        )
        for img in logo_elements:
            src = await img.get_attribute("src")
            if src and not src.startswith("data:"):
                abs_src = urljoin(url, src)
                if abs_src not in logo_urls:
                    logo_urls.append(abs_src)

        # If no <img> found, check for SVG links
        if not logo_urls:
            svg_parent = await page.query_selector("header a[href='/'], nav a[href='/'], [class*='logo']")
            if svg_parent:
                svg_el = await svg_parent.query_selector("svg")
                if svg_el:
                    logger.info("Found inline SVG logo in header anchor.")
                    logo_urls.append("inline:svg_header_logo")

        # 4. Computed Styles & Color Palette Extraction via In-Browser JS
        logger.info("Analyzing computed styles, colors, and typography...")
        style_data = await page.evaluate(r"""
        () => {
            // 1. Extract CSS variables from :root
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
                } catch (e) {
                    // Cross-origin stylesheet access might be blocked
                }
            }

            // 2. Sample computed styles from key semantic elements
            const bgCounts = {};
            const textCounts = {};
            const fontCounts = {};

            const sampleElements = document.querySelectorAll('body, header, nav, h1, h2, h3, p, button, a, [class*="btn"], footer');
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
                    if (cleanFont) {
                        fontCounts[cleanFont] = (fontCounts[cleanFont] || 0) + 1;
                    }
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
                bodyFont
            };
        }
        """)

        # Process Colors
        bg_counts = style_data.get("bgCounts", {})
        text_counts = style_data.get("textCounts", {})

        # Convert to HEX and tally frequencies
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

        # Filter out pure monochrome for accents/brand colors
        non_mono_colors = [
            color for color, _ in (sorted_bg + sorted_text)
            if color not in ("#FFFFFF", "#000000", "#111111", "#1A1A1A", "#F8F9FA", "#F5F5F5", "#E5E5E5")
        ]
        # Deduplicate while preserving rank
        unique_brand_colors = list(dict.fromkeys(non_mono_colors))

        primary_color = unique_brand_colors[0] if unique_brand_colors else (sorted_text[0][0] if sorted_text else "#000000")
        secondary_color = unique_brand_colors[1] if len(unique_brand_colors) > 1 else (sorted_text[1][0] if len(sorted_text) > 1 else None)
        background_color = sorted_bg[0][0] if sorted_bg else "#FFFFFF"
        text_color = sorted_text[0][0] if sorted_text else "#111111"

        # Typography
        heading_font_raw = style_data.get("headingFont") or ""
        body_font_raw = style_data.get("bodyFont") or ""
        heading_font = heading_font_raw.split(",")[0].replace("'", "").replace('"', "").strip() if heading_font_raw else None
        body_font = body_font_raw.split(",")[0].replace("'", "").replace('"', "").strip() if body_font_raw else None

        font_counts = style_data.get("fontCounts", {})
        sorted_fonts = [font for font, _ in sorted(font_counts.items(), key=lambda x: x[1], reverse=True)]

        # 5. Capture Hero Section / Viewport Screenshot
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
            accent_colors=unique_brand_colors[:5],
            css_variables=dict(list(style_data.get("cssVars", {}).items())[:20]),
            heading_font=heading_font,
            body_font=body_font,
            font_families=sorted_fonts[:5],
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

    data = asyncio.run(extract_visual_tokens(target_url, output_screenshot_path="hero_screenshot.png"))

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
    print(f"Heading Font:     {data.heading_font}")
    print(f"Body Font:        {data.body_font}")
    print(f"Logo URLs:        {data.logo_urls}")
    print(f"Hero Headline:    {data.hero_headline}")
    print(f"Screenshot Path:  {data.screenshot_path}")
    print("--------------------------------------\n")
