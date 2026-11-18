"""
Brand Typography Engine
Downloads, decompresses (.woff2 -> .ttf), and resolves genuine brand fonts.
3-Tier Resolver:
  Tier 1: Direct CDN fonts from crawler @font-face extraction with weight awareness
  Tier 2: Google Fonts auto-resolver (Geist, Plus Jakarta Sans, Outfit, etc.)
  Tier 3: Fallback to high-grade local Inter
"""

import io
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from fontTools.ttLib import TTFont, woff2
from PIL import ImageFont
import requests

from .brand_profile import BrandMemory

logger = logging.getLogger("brand_font_loader")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    ch.setFormatter(formatter)
    logger.addHandler(ch)

FONTS_CACHE_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Google Fonts raw repository base URL
GOOGLE_FONTS_RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl"

# Known Google Fonts directory mappings
COMMON_GOOGLE_FONTS = {
    "geist": "https://raw.githubusercontent.com/google/fonts/main/ofl/geist/Geist%5Bwght%5D.ttf",
    "inter": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
    "roboto": "https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/Roboto%5Bwdth%2Cwght%5D.ttf",
    "poppins": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-SemiBold.ttf",
    "montserrat": "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
    "plus jakarta sans": "https://raw.githubusercontent.com/google/fonts/main/ofl/plusjakartasans/PlusJakartaSans%5Bwght%5D.ttf",
    "outfit": "https://raw.githubusercontent.com/google/fonts/main/ofl/outfit/Outfit%5Bwght%5D.ttf",
    "space grotesk": "https://raw.githubusercontent.com/google/fonts/main/ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf",
    "syne": "https://raw.githubusercontent.com/google/fonts/main/ofl/syne/Syne%5Bwght%5D.ttf",
}


def clean_font_name(name: str) -> str:
    """Strips quotes, fallbacks, and standardizes name."""
    if not name:
        return ""
    first = name.split(",")[0].replace('"', "").replace("'", "").strip()
    return first.lower()


def decompress_woff2_bytes(data: bytes, output_ttf_path: Path) -> bool:
    """Decompresses .woff2 binary bytes to .ttf using fontTools."""
    try:
        in_buf = io.BytesIO(data)
        out_buf = io.BytesIO()
        woff2.decompress(in_buf, out_buf)
        with open(output_ttf_path, "wb") as f:
            f.write(out_buf.getvalue())
        return True
    except Exception as e:
        logger.warning(f"  [FONT RESOLVER] Failed to decompress woff2: {e}")
        return False


def get_ttf_metadata(ttf_path: Path) -> Dict[str, str]:
    """Reads TTF name table to inspect Family and Subfamily."""
    try:
        tt = TTFont(str(ttf_path))
        names: Dict[int, str] = {}
        for r in tt["name"].names:
            if r.nameID in (1, 2, 4, 6):
                try:
                    names[r.nameID] = r.toUnicode()
                except Exception:
                    pass
        return {
            "family": names.get(1, "Unknown"),
            "subfamily": names.get(2, "Unknown"),
            "full_name": names.get(4, names.get(1, "Unknown")),
            "postscript": names.get(6, ""),
        }
    except Exception as e:
        return {"family": "Error", "subfamily": str(e), "full_name": "Error", "postscript": ""}


def score_font_face_candidate(
    candidate: Dict[str, Any],
    clean_target_family: str,
    target_is_bold: bool,
) -> int:
    """
    Ranks font face candidates with specificity scoring:
      - Exact family match: +100
      - Substring / containment match: +40
      - Length similarity / specificity: + (len(candidate) if matched)
      - Weight match (bold vs regular): +30
      - Penalize italic if not requested: -20
    """
    cand_family = clean_font_name(candidate.get("family", ""))
    cand_weight = str(candidate.get("weight", "400")).lower()
    cand_style = str(candidate.get("style", "normal")).lower()
    src_url = candidate.get("src_url", "")

    if not cand_family or not src_url.startswith("http"):
        return -100

    score = 0

    # Family match
    if cand_family == clean_target_family:
        score += 100
    elif clean_target_family in cand_family:
        score += 60 + len(cand_family)
    elif cand_family in clean_target_family:
        # Partial prefix match — award points proportional to length so longer matching prefixes win
        score += 30 + len(cand_family)
    else:
        return -50

    # Weight match
    is_cand_bold = (
        "bold" in cand_weight
        or cand_weight in ("600", "700", "800", "900")
        or "bold" in src_url.lower()
        or "-bold" in src_url.lower()
    )
    if target_is_bold and is_cand_bold:
        score += 35
    elif not target_is_bold and not is_cand_bold:
        score += 35
    elif target_is_bold and not is_cand_bold:
        score += 0  # Regular can be used if no bold exists, but bold gets priority
    else:
        score -= 10

    # Style match: prefer normal over italic unless requested
    if "italic" in cand_style or "italic" in src_url.lower():
        score -= 25

    return score


def resolve_font_path(brand: BrandMemory, is_heading: bool = True) -> Path:
    """
    Resolves the real font file path for the brand, with extensive diagnostic logging.
    """
    raw_font_name = brand.heading_font if is_heading else brand.body_font
    clean_name = clean_font_name(raw_font_name or "")
    target_weight_label = "bold" if is_heading else "regular"
    default_font_path = FONTS_CACHE_DIR / "Inter.ttf"

    logger.info(f"[FONT RESOLVER] Requesting font: '{clean_name or 'None'}' | is_heading={is_heading} ({target_weight_label})")

    if not clean_name:
        logger.info(f"  [FONT RESOLVER] No brand font declared. Using default: {default_font_path.name}")
        return default_font_path

    # Cache file name accounts for weight so bold and regular fonts don't overwrite each other
    cache_key = f"{clean_name.replace(' ', '_')}_{target_weight_label}.ttf"
    cached_ttf = FONTS_CACHE_DIR / cache_key

    # Check if a validated TTF already exists in cache
    if cached_ttf.exists() and cached_ttf.stat().st_size > 2000:
        meta = get_ttf_metadata(cached_ttf)
        # Sanity check: Ensure it's not a mis-cached generic font
        if clean_name.split()[0] in meta.get("family", "").lower():
            logger.info(f"  [FONT RESOLVER] Cache HIT: {cached_ttf.name} (Family: '{meta['family']}', Subfamily: '{meta['subfamily']}')")
            return cached_ttf
        else:
            logger.warning(f"  [FONT RESOLVER] Cache invalid (expected '{clean_name}', found '{meta['family']}'). Evicting.")
            cached_ttf.unlink(missing_ok=True)

    # -------------------------------------------------------------
    # Tier 1: Direct CDN @font-face from Brand Website
    # -------------------------------------------------------------
    if brand.font_faces:
        logger.info(f"  [FONT RESOLVER] Evaluating {len(brand.font_faces)} @font-face rules from brand website...")
        
        # Score and rank all candidate font faces
        ranked_candidates: List[Tuple[int, Dict[str, Any]]] = []
        for ff in brand.font_faces:
            cand_score = score_font_face_candidate(ff, clean_name, target_is_bold=is_heading)
            if cand_score > 0:
                ranked_candidates.append((cand_score, ff))

        ranked_candidates.sort(key=lambda x: x[0], reverse=True)

        for score, best_ff in ranked_candidates:
            src_url = best_ff.get("src_url", "")
            ff_family = best_ff.get("family", "")
            ff_weight = best_ff.get("weight", "400")
            logger.info(f"  [FONT RESOLVER] Trying candidate [Score {score}]: '{ff_family}' (weight={ff_weight}) -> {src_url}")

            try:
                resp = requests.get(src_url, timeout=12)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    success = False
                    if src_url.endswith(".woff2") or "woff2" in src_url:
                        success = decompress_woff2_bytes(resp.content, cached_ttf)
                    else:
                        with open(cached_ttf, "wb") as f:
                            f.write(resp.content)
                        success = True

                    if success and cached_ttf.exists():
                        meta = get_ttf_metadata(cached_ttf)
                        logger.info(f"  [FONT RESOLVER] SUCCESS! Loaded brand typography: '{meta['full_name']}' ({cached_ttf.name})")
                        return cached_ttf
            except Exception as e:
                logger.warning(f"  [FONT RESOLVER] Failed to download CDN font from {src_url}: {e}")

    # -------------------------------------------------------------
    # Tier 2: Check Google Fonts Repository
    # -------------------------------------------------------------
    logger.info(f"  [FONT RESOLVER] Checking Google Fonts catalog for '{clean_name}'...")
    if clean_name in COMMON_GOOGLE_FONTS:
        url = COMMON_GOOGLE_FONTS[clean_name]
        try:
            logger.info(f"  [FONT RESOLVER] Downloading known Google Font: {url}")
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 2000:
                with open(cached_ttf, "wb") as f:
                    f.write(resp.content)
                meta = get_ttf_metadata(cached_ttf)
                logger.info(f"  [FONT RESOLVER] SUCCESS! Cached Google Font: '{meta['full_name']}'")
                return cached_ttf
        except Exception as e:
            logger.warning(f"  [FONT RESOLVER] Google Font download failed: {e}")

    # Generic Google Fonts lookup
    try:
        font_slug = clean_name.replace(" ", "")
        weight_suffix = "Bold" if is_heading else "Regular"
        direct_url = f"{GOOGLE_FONTS_RAW}/{font_slug}/{clean_name.title().replace(' ', '')}-{weight_suffix}.ttf"
        logger.info(f"  [FONT RESOLVER] Probing generic Google Fonts repo: {direct_url}")
        resp = requests.get(direct_url, timeout=8)
        if resp.status_code == 200 and len(resp.content) > 2000:
            with open(cached_ttf, "wb") as f:
                f.write(resp.content)
            meta = get_ttf_metadata(cached_ttf)
            logger.info(f"  [FONT RESOLVER] SUCCESS! Loaded from Google Fonts repo: '{meta['full_name']}'")
            return cached_ttf
    except Exception:
        pass

    # -------------------------------------------------------------
    # Tier 3: Default High-Grade Typography Fallback
    # -------------------------------------------------------------
    logger.info(f"  [FONT RESOLVER] Fallback: using default high-grade typography ({default_font_path.name})")
    return default_font_path


def get_brand_font(
    brand: BrandMemory,
    size: int,
    is_heading: bool = True,
) -> ImageFont.FreeTypeFont:
    """
    Returns a Pillow FreeTypeFont loaded with the brand's genuine typography.
    Logs font identity and loaded size.
    """
    font_path = resolve_font_path(brand, is_heading=is_heading)
    try:
        font = ImageFont.truetype(str(font_path), size)
        role = "HEADLINE" if is_heading else "BODY/KICKER"
        logger.info(f"[FONT LOADED] {role} font active: '{font_path.name}' at {size}pt")
        return font
    except Exception as e:
        logger.warning(f"[FONT ERROR] Failed to load font from {font_path}: {e}. Trying system Helvetica...")
        mac_helv = Path("/System/Library/Fonts/Helvetica.ttc")
        if mac_helv.exists():
            try:
                return ImageFont.truetype(str(mac_helv), size)
            except Exception:
                pass
        return ImageFont.load_default()
