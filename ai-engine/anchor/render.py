"""1080x1350 (4:5, native for Instagram and LinkedIn feeds) branded posters.

Imagery is REAL brand material only -- og:image, large site images, or the site's own hero
screenshot -- never an AI picture of an event that may not look like that. Brand fonts are
fetched from the site's @font-face rules (woff/woff2 converted to TTF), else Inter.
Text colours are chosen for WCAG contrast against whatever they sit on.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import ASSETS_DIR, Settings
from .crawl import UA
from .models import Card, TaskPack

log = logging.getLogger("anchor.render")
W, H, M = 1080, 1350, 80
INTER = {"bold": ASSETS_DIR / "fonts" / "inter_bold.ttf", "regular": ASSETS_DIR / "fonts" / "inter_regular.ttf"}


# ---- colour ---------------------------------------------------------------------------

def rgb(hex_str: str | None, default=(17, 24, 39)) -> tuple[int, int, int]:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", (hex_str or "").strip())
    return tuple(int(m.group(1)[i : i + 2], 16) for i in (0, 2, 4)) if m else default


def luminance(c: tuple[int, int, int]) -> float:
    def ch(v: int) -> float:
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable_on(bg, preferred) -> tuple[int, int, int]:
    if contrast(bg, preferred) >= 4.5:
        return preferred
    return (255, 255, 255) if contrast(bg, (255, 255, 255)) >= contrast(bg, (17, 17, 17)) else (17, 17, 17)


# ---- fonts ----------------------------------------------------------------------------

def _weight(face: dict) -> int:
    w = str(face.get("weight", "400")).split()[0].lower()
    return {"normal": 400, "bold": 700}.get(w, int(w) if w.isdigit() else 400)


NEEDED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 %$.,:'-&/")


def covers(path: Path) -> bool:
    """True only if every needed character is really in the font. Sites ship subsets two ways:
    unicode-range splits (Latin letters live in another file) and stripped outlines. A missing
    character renders as the font's box glyph, which still "draws pixels", so check the
    character map first, then that each mapped glyph actually draws."""
    try:
        cmap = TTFont(str(path)).getBestCmap() or {}
        if any(ord(c) not in cmap for c in NEEDED):
            return False
        f = ImageFont.truetype(str(path), 40)
    except Exception:
        return False
    return all(f.getmask(c).getbbox() is not None for c in NEEDED if not c.isspace())


def _save_font(data: bytes, path: Path) -> Path | None:
    """woff/woff2/ttf/otf bytes -> a TTF Pillow can use and that draws every needed glyph."""
    try:
        font = TTFont(io.BytesIO(data))
        font.flavor = None  # woff2 decoding needs the brotli package (in requirements.txt)
        path.parent.mkdir(parents=True, exist_ok=True)
        font.save(str(path))
    except Exception as exc:
        log.info("font not decodable (%s); trying the next source", type(exc).__name__)
        return None
    if covers(path):
        return path
    log.info("font %s lacks needed glyphs (site subset); trying the next source", path.name)
    return None


def _site_font(pack: TaskPack, family: str, target: int, cache: Path) -> Path | None:
    faces = [f for f in pack.brand.font_faces if f.get("family", "").lower() == family.lower()
             and f.get("style", "normal") == "normal"]
    for face in sorted(faces, key=lambda f: abs(_weight(f) - target)):
        for url in face.get("urls", []):
            path = cache / f"{hashlib.md5(url.encode()).hexdigest()}.ttf"
            if path.is_file():
                if covers(path):
                    return path
                continue
            try:
                r = httpx.get(url, headers={"User-Agent": UA, "Referer": pack.brand.url}, timeout=15,
                              follow_redirects=True)
            except httpx.HTTPError:
                continue
            if r.status_code == 200 and len(r.content) > 1000 and _save_font(r.content, path):
                return path
    return None


def _google_font(family: str, target: int, cache: Path) -> Path | None:
    """Same family from Google Fonts as plain TTF (served to non-browser clients); a full
    character set, so it also rescues sites whose own copy is a subset."""
    path = cache / f"gf-{re.sub(r'[^a-z0-9]+', '-', family.lower())}-{target}.ttf"
    if path.is_file():
        return path if covers(path) else None
    try:
        css = httpx.get("https://fonts.googleapis.com/css2", params={"family": f"{family}:wght@{target}"},
                        headers={"User-Agent": "anchor-engine/2.0"}, timeout=10)
        if css.status_code != 200:
            css = httpx.get("https://fonts.googleapis.com/css2", params={"family": family},
                            headers={"User-Agent": "anchor-engine/2.0"}, timeout=10)
        m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.ttf)\)", css.text) if css.status_code == 200 else None
        if not m:
            return None
        r = httpx.get(m.group(1), timeout=15)
        return _save_font(r.content, path) if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def brand_font_path(pack: TaskPack, heading: bool, cache: Path) -> Path:
    """Brand font from the site, else the same family from Google Fonts, else Inter."""
    families = [pack.brand.heading_font, pack.brand.body_font] if heading else [pack.brand.body_font, pack.brand.heading_font]
    target = 700 if heading else 400
    for family in [f for f in dict.fromkeys(families) if f]:
        if family.lower() in ("inter", "sans-serif", "serif", "system-ui", "-apple-system", "arial", "helvetica"):
            continue
        found = _site_font(pack, family, target, cache) or _google_font(family, target, cache)
        if found:
            log.info("[render] %s font: %s", "heading" if heading else "body", family)
            return found
    return INTER["bold" if heading else "regular"]


_CMAPS: dict[str, set[int]] = {}
_WEIGHTS: dict[str, int] = {}

# Per writing system: Google Fonts family (full TTF, includes Latin) and local system fonts,
# tried after the brand font and Inter. Pillow draws a whole string with one font, so the
# first font that covers EVERY character of the string wins.
_SCRIPT_FONTS: dict[str, tuple[str, list[str]]] = {
    "CJK": ("Noto Sans JP", ["/System/Library/Fonts/Hiragino Sans GB.ttc", "/System/Library/Fonts/PingFang.ttc",
                             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                             "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"]),
    "HANGUL": ("Noto Sans KR", ["/System/Library/Fonts/AppleSDGothicNeo.ttc",
                                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]),
    "DEVANAGARI": ("Noto Sans Devanagari", []),
    "THAI": ("Noto Sans Thai", []),
    "HEBREW": ("Noto Sans Hebrew", ["/System/Library/Fonts/ArialHB.ttc"]),
    "ARABIC": ("Noto Sans Arabic", []),
    "BENGALI": ("Noto Sans Bengali", []),
    "TAMIL": ("Noto Sans Tamil", []),
}
_UNIVERSAL = ["/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
FONT_CACHE: Path | None = None  # set by render_all; Google fallback fonts are cached here


def _cmap(path: Path) -> set[int]:
    key = str(path)
    if key not in _CMAPS:
        try:
            tt = TTFont(key, fontNumber=0, lazy=True)
            _CMAPS[key] = set((tt.getBestCmap() or {}).keys())
            _WEIGHTS[key] = int(getattr(tt.get("OS/2"), "usWeightClass", 400) or 400)
        except Exception:
            _CMAPS[key], _WEIGHTS[key] = set(), 400
    return _CMAPS[key]


def _is_bold(path: Path) -> bool:
    _cmap(path)
    return path == INTER["bold"] or _WEIGHTS.get(str(path), 400) >= 600


def _fallbacks(path: Path, text: str) -> list[Path]:
    from .verify import script_of

    bold = _is_bold(path)
    chain = [path, INTER["bold" if bold else "regular"]]
    scripts = list(dict.fromkeys(s for s in map(script_of, text) if s and s not in ("LATIN", "GREEK", "CYRILLIC")))
    for sc in scripts:
        family, local = _SCRIPT_FONTS.get(sc, ("", []))
        if family and FONT_CACHE is not None:
            g = _google_font(family, 700 if bold else 400, FONT_CACHE)
            if g:
                chain.append(g)
        chain += [Path(p) for p in local if Path(p).is_file()]
    chain += [Path(p) for p in _UNIVERSAL if Path(p).is_file()]
    return list(dict.fromkeys(chain))


def for_text(path: Path, text: str) -> Path:
    """The brand font if it has every character of `text`; else the first fallback that does
    (Inter, then a font for the text's script); else the one that covers the most."""
    need = {ord(c) for c in text if not c.isspace()}
    if need <= _cmap(path):
        return path
    best, best_n = path, -1
    for cand in _fallbacks(path, text):
        have = len(need & _cmap(cand))
        if have == len(need):
            return cand
        if have > best_n:
            best, best_n = cand, have
    return best


def drawable(path: Path, text: str) -> str:
    """`text` minus characters `path` cannot draw, so a box glyph never reaches a poster."""
    cmap = _cmap(path)
    out = "".join(c for c in text if c.isspace() or ord(c) in cmap)
    return re.sub(r"\s{2,}", " ", out).strip() if out != text else text


def prep(path: Path, text: str) -> tuple[Path, str]:
    chosen = for_text(path, text)
    return chosen, drawable(chosen, text)


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size, index=0)
    except OSError:
        return ImageFont.truetype(str(INTER["regular"]), size)


def wrap(draw: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        test = f"{cur} {word}".strip()
        if draw.textlength(test, font=f) <= width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def fit_text(draw, text: str, path: Path, width: int, max_lines: int, sizes=(76, 68, 60, 54, 48, 44)):
    path, text = prep(path, text)
    for size in sizes:
        f = font(path, size)
        lines = wrap(draw, text, f, width)
        if len(lines) <= max_lines:
            return f, lines, size
    f = font(path, sizes[-1])
    lines = wrap(draw, text, f, width)[:max_lines]
    lines[-1] = lines[-1].rstrip(".,;:") + "…"
    return f, lines, sizes[-1]


# ---- imagery --------------------------------------------------------------------------

def _download(url: str, cache: Path) -> Image.Image | None:
    path = cache / f"img-{hashlib.md5(url.encode()).hexdigest()}.png"
    try:
        if path.is_file():
            return Image.open(path).convert("RGB")
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=15, follow_redirects=True)
        if r.status_code != 200:
            return None
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        if img.width < 600 or img.height < 380:
            return None
        cache.mkdir(parents=True, exist_ok=True)
        img.save(path)
        return img
    except Exception:
        return None


def brand_images(pack: TaskPack, cache: Path) -> list[Image.Image]:
    imgs = [i for i in (_download(u, cache) for u in pack.brand.image_urls[:6]) if i is not None]
    if pack.brand.screenshot_path and Path(pack.brand.screenshot_path).is_file():
        imgs.append(Image.open(pack.brand.screenshot_path).convert("RGB"))
    return imgs


def rounded(img: Image.Image, radius: int = 28) -> Image.Image:
    mask = Image.new("L", (img.width * 2, img.height * 2), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width, mask.height), radius * 2, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask.resize(img.size, Image.Resampling.LANCZOS))
    return out


def logo_image(pack: TaskPack, max_w=300, max_h=60) -> Image.Image | None:
    p = pack.brand.logo_path
    if not p or not Path(p).is_file():
        return None
    img = Image.open(p).convert("RGBA")
    bbox = img.getbbox()
    img = img.crop(bbox) if bbox else img
    scale = min(max_w / img.width, max_h / img.height)
    return img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.Resampling.LANCZOS)


# ---- poster ---------------------------------------------------------------------------

def paste_logo(canvas: Image.Image, logo: Image.Image, xy: tuple[int, int], bg) -> None:
    """Logos are often white-on-transparent or dark-on-transparent; put a plate behind any logo
    that would vanish into this background."""
    if contrast(bg, _dominant(logo)) < 1.6:
        plate = Image.new("RGB", (logo.width + 28, logo.height + 20), readable_on(bg, (255, 255, 255)))
        r = rounded(plate, 12)
        canvas.paste(r, (xy[0] - 14, xy[1] - 10), r)
    canvas.paste(logo, xy, logo)


def _page_marker(d: ImageDraw.ImageDraw, page: int, total: int, path: Path, color) -> None:
    if total > 1:
        label = f"{page}/{total}" + ("  →" if page < total else "")
        path, label = prep(path, label)
        f = font(path, 26)
        d.text((W - M - d.textlength(label, font=f), M + 14), label, font=f, fill=color)


def _footer(d: ImageDraw.ImageDraw, card: Card, pack: TaskPack, path: Path, color) -> None:
    src = card.sources[0] if card.sources else None
    host = urlparse(src.url).netloc.removeprefix("www.") if src else pack.brand.domain
    right = f"Source: {host}" + (f" · {src.date}" if src and src.date else "")
    path = for_text(path, pack.brand.domain + right)
    domain, right = drawable(path, pack.brand.domain), drawable(path, right)
    f = font(path, 24)
    d.line((M, H - 86, W - M, H - 86), fill=color, width=2)
    d.text((M, H - 62), domain, font=f, fill=color)
    d.text((W - M - d.textlength(right, font=f), H - 62), right, font=f, fill=color)


def slide(card: Card, pack: TaskPack, index: int, total: int, out: Path, cfg: Settings) -> Path:
    """An explainer slide: the brand frame, one title, 2-3 evidence-backed bullets."""
    cache = cfg.cache_dir / "fonts"
    head_path, body_path = brand_font_path(pack, True, cache), brand_font_path(pack, False, cache)
    bg = rgb(pack.brand.background_color, (255, 255, 255))
    accent = rgb(pack.brand.primary_color, (37, 99, 235))
    text_c = readable_on(bg, rgb(pack.brand.text_color, (17, 17, 17)))
    muted = tuple(int(t * 0.62 + b * 0.38) for t, b in zip(text_c, bg))
    mark = readable_on(bg, accent) if contrast(bg, accent) < 3 else accent
    canvas = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(canvas)
    sl = card.post.slides[index - 2]

    logo = logo_image(pack, max_w=200, max_h=40)
    if logo is not None:
        paste_logo(canvas, logo, (M, M + 8), bg)
    else:
        np, name = prep(head_path, pack.brand.name.upper())
        d.text((M, M + 8), name, font=font(np, 28), fill=text_c)
    _page_marker(d, index, total, body_path, muted)

    hf, lines, size = fit_text(d, sl.title, head_path, W - 2 * M - 36, 3, sizes=(76, 68, 60, 54, 48))
    lh = int(size * 1.18)
    bp = for_text(body_path, " ".join(sl.bullets))
    bf, bl = font(bp, 44), 60
    bullets = [wrap(d, drawable(bp, b), bf, W - 2 * M - 56) for b in sl.bullets[:3]]
    block = 56 + lh * len(lines) + 80 + sum(len(b) * bl + 40 for b in bullets)
    top, bottom = 220, H - 140
    y = max(top, top + (bottom - top - block) // 2)  # centre the content between header and footer

    d.text((M, y), f"{index - 1:02d}", font=font(head_path, 30), fill=mark)
    y += 56
    d.rectangle((M, y + 8, M + 10, y + lh * len(lines) - 12), fill=mark)
    for line in lines:
        d.text((M + 36, y), line, font=hf, fill=text_c)
        y += lh
    y += 80
    for blines in bullets:
        d.ellipse((M + 4, y + 20, M + 24, y + 40), fill=mark)
        for line in blines:
            d.text((M + 56, y), line, font=bf, fill=text_c)
            y += bl
        y += 40
    _footer(d, card, pack, body_path, muted)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "PNG", optimize=True)
    return out


def poster(card: Card, pack: TaskPack, image: Image.Image | None, out: Path, cfg: Settings,
           total: int = 1) -> Path:
    cache = cfg.cache_dir / "fonts"
    head_path, body_path = brand_font_path(pack, True, cache), brand_font_path(pack, False, cache)
    bg = rgb(pack.brand.background_color, (255, 255, 255))
    accent = rgb(pack.brand.primary_color, (37, 99, 235))
    text_c = readable_on(bg, rgb(pack.brand.text_color, (17, 17, 17)))
    muted = tuple(int(t * 0.62 + b * 0.38) for t, b in zip(text_c, bg))
    canvas = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(canvas)
    p = card.post

    y = M
    logo = logo_image(pack)
    if logo is not None:
        paste_logo(canvas, logo, (M, y), bg)
        y += logo.height + 56
    else:
        np, name = prep(head_path, pack.brand.name.upper())
        d.text((M, y), name, font=font(np, 34), fill=text_c)
        y += 90

    kp, kicker = prep(body_path, (p.poster_kicker or card.fact.category).upper())
    kf = font(kp, 26)
    kw = int(d.textlength(kicker, font=kf)) + 40
    d.rounded_rectangle((M, y, M + kw, y + 50), 25, fill=accent)
    d.text((M + 20, y + 11), kicker, font=kf, fill=readable_on(accent, (255, 255, 255)))
    y += 86

    hf, lines, size = fit_text(d, p.poster_headline, head_path, W - 2 * M, 4)
    for line in lines:
        d.text((M, y), line, font=hf, fill=text_c)
        y += int(size * 1.18)
    y += 36

    footer_h = 110
    area = (M, y, W - M, H - footer_h)
    stat_path, stat = prep(head_path, p.poster_stat) if p.poster_stat else (head_path, "")
    if image is not None and area[3] - area[1] > 260:
        size = (area[2] - area[0], area[3] - area[1])
        if image.width / image.height > size[0] / size[1] * 1.15:
            # Landscape (site screenshot, og:image card): show it whole on a tinted panel.
            panel = tuple(min(255, max(0, c + (18 if luminance(bg) < 0.5 else -12))) for c in bg)
            photo = ImageOps.pad(image, size, Image.Resampling.LANCZOS, color=panel)
        else:
            photo = ImageOps.fit(image, size, Image.Resampling.LANCZOS)
        r = rounded(photo)
        canvas.paste(r, area[:2], r)
        if stat:
            sf = font(stat_path, 96)
            sw = int(d.textlength(stat, font=sf))
            box = (area[0] + 28, area[3] - 160, area[0] + 28 + sw + 56, area[3] - 28)
            shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            ImageDraw.Draw(shadow).rounded_rectangle(box, 24, fill=(0, 0, 0, 90))
            canvas.paste(shadow.filter(ImageFilter.GaussianBlur(12)), (0, 6), shadow.filter(ImageFilter.GaussianBlur(12)))
            d.rounded_rectangle(box, 24, fill=accent)
            d.text((box[0] + 28, box[1] + 8), stat, font=sf, fill=readable_on(accent, (255, 255, 255)))
    elif stat:
        sf = font(stat_path, 200)
        d.text((M, y + 20), stat, font=sf, fill=readable_on(bg, accent))

    _page_marker(d, 1, total, body_path, muted)
    _footer(d, card, pack, body_path, muted)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "PNG", optimize=True)
    return out


def _dominant(img: Image.Image) -> tuple[int, int, int]:
    small = img.convert("RGBA").resize((24, 24))
    px = [p[:3] for p in small.getdata() if p[3] > 128]
    if not px:
        return (128, 128, 128)
    return tuple(sum(c[i] for c in px) // len(px) for i in range(3))


def render_all(cards: list[Card], pack: TaskPack, out_dir: Path, cfg: Settings) -> dict[str, list[str]]:
    """Per post: cover (logo, title, image) + explainer slides as PNGs, plus one PDF of the whole
    carousel (LinkedIn's document format). Returns card id -> file names, cover first."""
    global FONT_CACHE
    FONT_CACHE = cfg.cache_dir / "fonts"
    images = brand_images(pack, cfg.cache_dir / "images")
    files: dict[str, list[str]] = {}
    for i, card in enumerate(cards):
        total = 1 + len(card.post.slides)
        img = images[i % len(images)] if images else None
        pages = [poster(card, pack, img, out_dir / f"{card.id}_1.png", cfg, total)]
        pages += [slide(card, pack, n, total, out_dir / f"{card.id}_{n}.png", cfg) for n in range(2, total + 1)]
        pdf = out_dir / f"{card.id}_carousel.pdf"
        frames = [Image.open(p).convert("RGB") for p in pages]
        frames[0].save(pdf, "PDF", save_all=True, append_images=frames[1:], resolution=150)
        files[card.id] = [p.name for p in pages] + [pdf.name]
        log.info("[render] %s: %d slides + %s", card.id, len(pages), pdf.name)
    return files
