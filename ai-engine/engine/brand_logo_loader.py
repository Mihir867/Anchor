"""
Brand Logo Loader & Compositor
Downloads, caches, auto-trims, and prepares real brand logos for canvas rendering.
"""

import hashlib
import io
import logging
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse
from PIL import Image, ImageOps
import requests

from .brand_profile import BrandMemory

logger = logging.getLogger("brand_logo_loader")

LOGOS_CACHE_DIR = Path(__file__).resolve().parent.parent / "assets" / "logos"
LOGOS_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_cached_logo_path(url: str) -> Path:
    hashed = hashlib.md5(url.encode("utf-8")).hexdigest()
    ext = Path(urlparse(url).path).suffix or ".png"
    if ext.lower() not in [".png", ".jpg", ".jpeg", ".webp"]:
        ext = ".png"
    return LOGOS_CACHE_DIR / f"{hashed}{ext}"


def trim_transparent_padding(image: Image.Image) -> Image.Image:
    """Removes excess transparent padding around the logo."""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    bbox = image.getbbox()
    if bbox:
        return image.crop(bbox)
    return image


def download_image_asset(url: str, timeout: int = 10) -> Optional[Image.Image]:
    """Downloads an image asset with custom user-agent."""
    cache_path = get_cached_logo_path(url)
    if cache_path.exists():
        try:
            return Image.open(cache_path).convert("RGBA")
        except Exception:
            pass

    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"
            },
        )
        if resp.status_code == 200 and len(resp.content) > 200:
            # Check content type
            img = Image.open(io.BytesIO(resp.content))
            img = img.convert("RGBA")
            img.save(cache_path, "PNG")
            return img
    except Exception as e:
        logger.debug(f"Failed to download logo from {url}: {e}")
    return None


def load_brand_logo(
    brand: BrandMemory,
    max_width: int = 240,
    max_height: int = 56,
    invert_for_dark_bg: bool = False,
) -> Optional[Image.Image]:
    """
    Finds, downloads, trims, and scales the official brand logo.
    Returns a Pillow Image object ready to paste onto the poster canvas.
    """
    candidates = []

    # 1. Check extracted logo_urls
    for u in brand.logo_urls:
        if not u or u.startswith("inline:") or u.startswith("data:"):
            continue
        # Prioritize actual logo files
        if any(kw in u.lower() for kw in ["logo", "brand", "mark"]):
            candidates.insert(0, u)
        else:
            candidates.append(u)

    # 2. Check apple-touch-icon or favicon
    if brand.favicon_url:
        candidates.append(brand.favicon_url)

    # Try to download and load the best candidate
    logo_img: Optional[Image.Image] = None
    for cand_url in candidates:
        logo_img = download_image_asset(cand_url)
        if logo_img:
            logger.info(f"Loaded brand logo from: {cand_url}")
            break

    if not logo_img:
        logger.info("No downloadable image logo found. Will fall back to typographic wordmark.")
        return None

    # Auto-trim transparent borders
    logo_img = trim_transparent_padding(logo_img)

    # Scale proportionally within max_width and max_height
    w, h = logo_img.size
    ratio = min(max_width / max(w, 1), max_height / max(h, 1))
    new_w = max(int(w * ratio), 1)
    new_h = max(int(h * ratio), 1)

    scaled_logo = logo_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    return scaled_logo
