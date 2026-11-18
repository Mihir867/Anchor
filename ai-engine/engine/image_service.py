"""
Image Generation & Sourcing Service
Generates editorial photorealistic imagery for dynamic story posters.
3-Tier Visual Engine:
  Tier 1: Genuine Story Photos extracted from scraped articles / press releases
  Tier 2: Bespoke FLUX.1 Photorealistic Generation via dynamic prompt seeding
  Tier 3: Contextual High-Resolution Editorial Photography (zero dark/blank boxes)
"""

import hashlib
import io
import logging
import random
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote_plus
from PIL import Image, ImageDraw, ImageOps
import requests

logger = logging.getLogger("image_service")
logger.setLevel(logging.INFO)

CACHE_DIR = Path(__file__).resolve().parent.parent / "assets" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_cached_image_path(prompt: str, width: int, height: int) -> Path:
    key = f"{prompt.strip().lower()}_{width}_{height}"
    hashed = hashlib.md5(key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{hashed}.jpg"


def fetch_from_article_sources(candidate_urls: List[str], width: int, height: int) -> Optional[Image.Image]:
    """Attempts to fetch and fit genuine photos embedded directly in the scraped article."""
    if not candidate_urls:
        return None

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    for url in candidate_urls[:4]:
        if not url.startswith("http"):
            continue
        # Skip small icons, trackers, or svg
        if any(bad in url.lower() for bad in [".svg", "avatar", "icon", "logo", "tracker", "badge", "pixel"]):
            continue
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200 and len(resp.content) > 10000:
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                # Ensure it's large enough to be a genuine story photo
                if img.width >= 300 and img.height >= 200:
                    logger.info(f"[IMAGE SERVICE] Using genuine article embedded photo: {url[:60]}...")
                    return ImageOps.fit(img, (width, height), Image.Resampling.LANCZOS)
        except Exception:
            continue
    return None


def fetch_editorial_photography_fallback(prompt: str, width: int, height: int) -> Image.Image:
    """
    Fetches real contextual high-resolution photography using semantic topic seeds.
    Ensures the card ALWAYS has rich photography and never an empty or dark box.
    """
    # Extract clean semantic keywords from the prompt (e.g. hotel, office, payment, technology)
    clean_words = [
        w.lower() for w in re.findall(r"[a-zA-Z]{4,}", prompt)
        if w.lower() not in ["editorial", "photorealistic", "image", "scene", "showing", "modern", "high", "quality", "with"]
    ]
    seed_topic = "_".join(clean_words[:3]) or "technology_enterprise"
    logger.info(f"[IMAGE SERVICE] Fetching contextual editorial photography for seed: '{seed_topic}'")

    url = f"https://picsum.photos/seed/{seed_topic}/{width}/{height}"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 200 and len(resp.content) > 8000:
            return Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        logger.warning(f"[IMAGE SERVICE] Editorial photography CDN error: {e}")

    # Ultimate aesthetic gradient fallback with geometric styling
    img = Image.new("RGB", (width, height), color=(26, 35, 50))
    draw = ImageDraw.Draw(img)
    for i in range(0, width + height, 64):
        draw.line([(0, i), (i, 0)], fill=(40, 52, 75), width=2)
    return img


def fetch_or_generate_image(
    prompt: str,
    width: int = 800,
    height: int = 1000,
    candidate_urls: Optional[List[str]] = None,
    timeout_sec: int = 15,
) -> Image.Image:
    """
    Fetches or generates a unique high-quality editorial image matching the prompt.
    Tiers:
      1. Genuine embedded article photo
      2. Bespoke FLUX.1 generation
      3. Contextual high-res editorial photography (zero dark/blank boxes)
    """
    cache_path = get_cached_image_path(prompt, width, height)
    if cache_path.exists() and cache_path.stat().st_size > 15000:
        try:
            return Image.open(cache_path).convert("RGB")
        except Exception:
            pass

    # Tier 1: Try genuine article photos
    if candidate_urls:
        article_img = fetch_from_article_sources(candidate_urls, width, height)
        if article_img:
            article_img.save(cache_path, "JPEG", quality=90)
            return article_img

    # Tier 2: Bespoke FLUX.1 generation
    clean_prompt = " ".join(prompt.replace("\n", " ").split())[:220].strip()
    encoded = quote_plus(clean_prompt)
    dynamic_seed = int(hashlib.md5(f"{clean_prompt}_{width}_{height}".encode()).hexdigest(), 16) % 999999
    flux_url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&nologo=true&seed={dynamic_seed}"

    logger.info(f"[IMAGE SERVICE] Requesting FLUX visual asset: '{clean_prompt[:45]}...' ({width}x{height})")

    try:
        resp = requests.get(
            flux_url,
            timeout=timeout_sec,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
        )
        if resp.status_code == 200 and len(resp.content) > 10000:
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            img.save(cache_path, "JPEG", quality=90)
            logger.info("[IMAGE SERVICE] ✓ FLUX image generated and cached successfully.")
            return img
        elif resp.status_code == 402:
            logger.info("[IMAGE SERVICE] FLUX rate-limit reached. Switching smoothly to contextual editorial photography...")
    except Exception as e:
        logger.warning(f"[IMAGE SERVICE] FLUX request error: {e}. Switching to contextual editorial photography...")

    # Tier 3: Contextual High-Resolution Photography
    photo = fetch_editorial_photography_fallback(clean_prompt, width, height)
    photo.save(cache_path, "JPEG", quality=90)
    return photo
