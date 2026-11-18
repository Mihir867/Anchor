"""
Multi-Archetype Poster Composer (Dynamic Canvas Engine v3)
Dynamically renders 6 unique, story-driven visual layouts:
  1. cinematic_hero      - Full-bleed photo with glassmorphic dark gradient
  2. before_after         - Split-screen comparison with center metric badge
  3. quote_spotlight      - Editorial executive testimonial card with circular avatar
  4. contrarian_minimal  - High-impact Swiss typography poster (zero photos)
  5. step_flow           - 3-step numbered playbook card with supporting photo
  6. case_mosaic         - 3-photo asymmetrical grid case study
"""

import logging
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageOps
from .brand_profile import BrandMemory
from .campaign_story import DynamicStoryData
from .image_service import fetch_or_generate_image

logger = logging.getLogger("poster_composer")

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
POSTERS_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "posters"
POSTERS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def hex_to_rgb(hex_str: str, default: Tuple[int, int, int] = (31, 88, 105)) -> Tuple[int, int, int]:
    """Converts #RRGGBB to (r, g, b) tuple."""
    if not hex_str:
        return default
    clean = hex_str.lstrip("#")
    if len(clean) == 6:
        try:
            return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))
        except ValueError:
            pass
    return default


def get_inter_font(size: int) -> ImageFont.FreeTypeFont:
    """Loads Inter TTF font or falls back to system font."""
    font_path = FONTS_DIR / "Inter.ttf"
    if font_path.exists():
        try:
            return ImageFont.truetype(str(font_path), size)
        except Exception:
            pass
    mac_helv = Path("/System/Library/Fonts/Helvetica.ttc")
    if mac_helv.exists():
        try:
            return ImageFont.truetype(str(mac_helv), size)
        except Exception:
            pass
    return ImageFont.load_default()


def round_corners(image: Image.Image, radius: int = 16) -> Image.Image:
    """Rounds image corners using an anti-aliased alpha mask."""
    w, h = image.size
    mask = Image.new("L", (w * 2, h * 2), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (w * 2, h * 2)], radius=radius * 2, fill=255)
    mask = mask.resize((w, h), Image.Resampling.LANCZOS)
    
    rounded = image.copy().convert("RGBA")
    rounded.putalpha(mask)
    return rounded


def sanitize_display_text(text: str) -> str:
    """Normalizes non-breaking hyphens, smart quotes, and dashes to standard ASCII glyphs."""
    if not text:
        return ""
    replacements = {
        "\u2011": "-",  # non-breaking hyphen
        "\u2010": "-",  # hyphen
        "\u2012": "-",  # figure dash
        "\u2013": "-",  # en-dash
        "\u2014": "--", # em-dash
        "\u2212": "-",  # minus sign
        "\u2018": "'",  # left single quote
        "\u2019": "'",  # right single quote
        "\u201c": '"',  # left double quote
        "\u201d": '"',  # right double quote
        "\u2026": "...", # ellipsis
        "\u00a0": " ",  # non-breaking space
    }
    for orig, rep in replacements.items():
        text = text.replace(orig, rep)
    return text


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Wraps text into lines that fit within max_width, sanitizing unicode glyphs."""
    clean_str = sanitize_display_text(text)
    words = clean_str.split(" ")
    lines = []
    current_line = []
    
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return lines


def get_brand_prompt(brand: BrandMemory, custom_prompt: Optional[str], role: str = "primary") -> str:
    """
    Constructs a completely dynamic image prompt grounded in the brand's verified identity.
    NO hardcoded hotels or templates!
    """
    if custom_prompt and len(custom_prompt.strip()) > 10:
        return custom_prompt.strip()

    name = brand.business_name
    tagline = brand.tagline or brand.hero_headline or "industry innovation"
    core = brand.core_offerings[0] if brand.core_offerings else tagline

    if role == "primary":
        return f"editorial modern commercial photography representing {name}, {core}, aesthetic lighting, cinematic composition"
    elif role == "before":
        return f"conceptual photography of complex manual chaos, overwhelmed professional facing fragmented {core} workflows"
    elif role == "after":
        return f"sleek modern technological simplicity and clarity, team succeeding with {name} {core}"
    elif role == "portrait":
        return f"professional editorial studio headshot portrait of an innovative business executive, neutral clean background"
    elif role == "detail":
        return f"close-up modern technological details of {name} system, high aesthetic, clean minimal composition"
    
    return f"photorealistic commercial photography of {name} {tagline}"


# =========================================================================
# LAYOUT 1: CINEMATIC HERO (Full-bleed photo + dark bottom gradient)
# =========================================================================
def render_cinematic_hero(story: DynamicStoryData, brand: BrandMemory, accent_rgb: Tuple[int, int, int], width: int, height: int) -> Image.Image:
    prompt = get_brand_prompt(brand, story.image_prompt_primary, role="primary")
    hero_img = fetch_or_generate_image(prompt, width=width, height=height)
    hero_img = ImageOps.fit(hero_img, (width, height), Image.Resampling.LANCZOS).convert("RGBA")

    # Dark gradient overlay on bottom 50%
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    grad_start = int(height * 0.45)
    for y in range(grad_start, height):
        alpha = int(240 * ((y - grad_start) / (height - grad_start)))
        draw_ov.line([(0, y), (width, y)], fill=(10, 15, 26, alpha))

    canvas = Image.alpha_composite(hero_img, overlay)
    draw = ImageDraw.Draw(canvas)

    # Top brand badge
    font_badge = get_inter_font(24)
    draw.rounded_rectangle([(64, 64), (64 + 220, 64 + 48)], radius=24, fill=(0, 0, 0, 160))
    draw.text((84, 76), brand.business_name.upper()[:16], font=font_badge, fill=(255, 255, 255))

    # Bottom Content
    text_y = int(height * 0.65)
    
    # Category tag
    if story.badge_label:
        font_tag = get_inter_font(22)
        draw.rounded_rectangle([(64, text_y), (64 + 180, text_y + 40)], radius=8, fill=accent_rgb)
        draw.text((78, text_y + 8), story.badge_label.upper(), font=font_tag, fill=(255, 255, 255))
        text_y += 64

    # Headline
    font_head = get_inter_font(56)
    lines = wrap_text(story.headline, font_head, width - 128, draw)
    for line in lines[:3]:
        draw.text((64, text_y), line, font=font_head, fill=(255, 255, 255))
        text_y += 68

    # Subheadline / Body
    sub = story.subheadline or story.body_text
    if sub:
        text_y += 12
        font_sub = get_inter_font(28)
        sub_lines = wrap_text(sub, font_sub, width - 128, draw)
        for line in sub_lines[:2]:
            draw.text((64, text_y), line, font=font_sub, fill=(209, 213, 219))
            text_y += 38

    return canvas.convert("RGB")


# =========================================================================
# LAYOUT 2: BEFORE / AFTER (Split Screen + Center Floating Metric Badge)
# =========================================================================
def render_before_after(story: DynamicStoryData, brand: BrandMemory, accent_rgb: Tuple[int, int, int], width: int, height: int) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    half_h = (height - 180) // 2
    img_w = width - 128

    # Dynamic prompts for Before & After
    prompt_before = get_brand_prompt(brand, story.image_prompt_secondary, role="before")
    prompt_after = get_brand_prompt(brand, story.image_prompt_primary, role="after")

    img_before = fetch_or_generate_image(prompt_before, width=img_w, height=half_h)
    img_before = ImageOps.fit(img_before, (img_w, half_h), Image.Resampling.LANCZOS)
    img_before_r = round_corners(img_before, radius=16)

    img_after = fetch_or_generate_image(prompt_after, width=img_w, height=half_h)
    img_after = ImageOps.fit(img_after, (img_w, half_h), Image.Resampling.LANCZOS)
    img_after_r = round_corners(img_after, radius=16)

    # Top Headline Bar
    font_head = get_inter_font(44)
    draw.text((64, 48), story.headline, font=font_head, fill=(17, 24, 39))

    # Paste Before
    canvas.paste(img_before_r, (64, 130), img_before_r)
    font_pill = get_inter_font(24)
    draw.rounded_rectangle([(84, 150), (84 + 220, 150 + 44)], radius=8, fill=(17, 24, 39, 210))
    draw.text((98, 158), (story.before_label or "BEFORE").upper(), font=font_pill, fill=(255, 255, 255))

    # Paste After
    bottom_y = 130 + half_h + 20
    canvas.paste(img_after_r, (64, bottom_y), img_after_r)
    draw.rounded_rectangle([(84, bottom_y + 20), (84 + 240, bottom_y + 20 + 44)], radius=8, fill=accent_rgb)
    draw.text((98, bottom_y + 28), (story.after_label or f"WITH {brand.business_name}").upper()[:22], font=font_pill, fill=(255, 255, 255))

    # Center Floating Metric Badge
    badge_label = story.metric_badge or "SPEED & PRECISION"
    font_metric = get_inter_font(30)
    badge_w = 340
    badge_h = 60
    center_x = (width - badge_w) // 2
    center_y = 130 + half_h - (badge_h // 2) + 10
    draw.rounded_rectangle([(center_x, center_y), (center_x + badge_w, center_y + badge_h)], radius=30, fill=(10, 15, 26))
    draw.rounded_rectangle([(center_x + 2, center_y + 2), (center_x + badge_w - 2, center_y + badge_h - 2)], radius=28, outline=accent_rgb, width=2)
    draw.text((center_x + 36, center_y + 14), badge_label.upper(), font=font_metric, fill=(255, 255, 255))

    return canvas.convert("RGB")


# =========================================================================
# LAYOUT 3: QUOTE SPOTLIGHT (Editorial Magazine Card + Customer Headshot)
# =========================================================================
def render_quote_spotlight(story: DynamicStoryData, brand: BrandMemory, accent_rgb: Tuple[int, int, int], width: int, height: int) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), (249, 250, 251))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=(229, 231, 235), width=2)

    # Top Brand Header
    font_badge = get_inter_font(26)
    draw.text((72, 64), brand.business_name.upper(), font=font_badge, fill=accent_rgb)

    # Giant Decorative Quotation Mark “
    font_quote_mark = get_inter_font(180)
    draw.text((64, 110), "“", font=font_quote_mark, fill=(accent_rgb[0], accent_rgb[1], accent_rgb[2], 50))

    # Quote Body Text
    quote_body = story.body_text or story.headline
    font_quote = get_inter_font(42)
    lines = wrap_text(f'"{quote_body}"', font_quote, width - 144, draw)
    text_y = 280
    for line in lines[:7]:
        draw.text((72, text_y), line, font=font_quote, fill=(17, 24, 39))
        text_y += 58

    # Bottom Author Section with Circular Headshot Avatar
    author_y = height - 240
    avatar_size = 130

    prompt_avatar = get_brand_prompt(brand, story.image_prompt_primary, role="portrait")
    avatar_img = fetch_or_generate_image(prompt_avatar, width=avatar_size * 2, height=avatar_size * 2)
    avatar_img = ImageOps.fit(avatar_img, (avatar_size, avatar_size), Image.Resampling.LANCZOS)

    # Circular mask
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse([(0, 0), (avatar_size, avatar_size)], fill=255)
    avatar_round = avatar_img.convert("RGBA")
    avatar_round.putalpha(mask)

    canvas.paste(avatar_round, (72, author_y), avatar_round)

    # Author details
    font_name = get_inter_font(34)
    font_role = get_inter_font(26)
    author_name = story.author_name or "Verified Customer"
    author_role = story.author_role or f"Client of {brand.business_name}"

    draw.text((72 + avatar_size + 28, author_y + 24), author_name, font=font_name, fill=(17, 24, 39))
    draw.text((72 + avatar_size + 28, author_y + 72), author_role, font=font_role, fill=(107, 114, 128))

    return canvas.convert("RGB")


# =========================================================================
# LAYOUT 4: CONTRARIAN MINIMAL (Swiss Typography Poster — Zero Photo Clutter)
# =========================================================================
def render_contrarian_minimal(story: DynamicStoryData, brand: BrandMemory, accent_rgb: Tuple[int, int, int], width: int, height: int) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), (10, 15, 26))
    draw = ImageDraw.Draw(canvas)

    # Top Brand Kicker
    font_brand = get_inter_font(28)
    draw.text((72, 72), f"// {brand.business_name.upper()} PERSPECTIVE", font=font_brand, fill=accent_rgb)

    # Category Tag
    tag = story.badge_label or "UNPOPULAR OPINION"
    font_tag = get_inter_font(24)
    draw.rounded_rectangle([(72, 130), (72 + 280, 130 + 44)], radius=8, fill=(26, 32, 44))
    draw.text((92, 138), tag.upper(), font=font_tag, fill=(209, 213, 219))

    # Giant Statement Headline
    font_headline = get_inter_font(68)
    lines = wrap_text(story.headline, font_headline, width - 144, draw)
    text_y = 260
    for line in lines[:4]:
        draw.text((72, text_y), line, font=font_headline, fill=(255, 255, 255))
        text_y += 86

    # Horizontal Accent Rule
    text_y += 20
    draw.rectangle([(72, text_y), (72 + 160, text_y + 6)], fill=accent_rgb)
    text_y += 40

    # Body Explanation
    body = story.body_text or story.subheadline
    if body:
        font_body = get_inter_font(34)
        body_lines = wrap_text(body, font_body, width - 144, draw)
        for line in body_lines[:5]:
            draw.text((72, text_y), line, font=font_body, fill=(156, 163, 175))
            text_y += 50

    return canvas.convert("RGB")


# =========================================================================
# LAYOUT 5: STEP FLOW (Numbered Playbook Card + Supporting Photo)
# =========================================================================
def render_step_flow(story: DynamicStoryData, brand: BrandMemory, accent_rgb: Tuple[int, int, int], width: int, height: int) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=(229, 231, 235), width=2)

    # Dynamic Top Photo
    photo_h = 440
    photo_w = width - 128
    prompt = get_brand_prompt(brand, story.image_prompt_primary, role="primary")
    img = fetch_or_generate_image(prompt, width=photo_w, height=photo_h)
    img = ImageOps.fit(img, (photo_w, photo_h), Image.Resampling.LANCZOS)
    img_r = round_corners(img, radius=16)
    canvas.paste(img_r, (64, 64), img_r)

    # Headline
    text_y = 64 + photo_h + 40
    font_head = get_inter_font(46)
    lines = wrap_text(story.headline, font_head, width - 128, draw)
    for line in lines[:2]:
        draw.text((64, text_y), line, font=font_head, fill=(17, 24, 39))
        text_y += 56

    text_y += 20

    # 3 Numbered Steps (01, 02, 03)
    steps = [
        ("01", story.step_1 or f"Connect live data and initiate {brand.business_name} workflow"),
        ("02", story.step_2 or "AI runs real-time analysis and cross-functional coordination"),
        ("03", story.step_3 or "Deploy results with measurable efficiency and accuracy"),
    ]

    font_num = get_inter_font(26)
    font_step = get_inter_font(27)

    for num, step_text in steps:
        draw.rounded_rectangle([(64, text_y), (64 + 56, text_y + 44)], radius=8, fill=accent_rgb)
        draw.text((76, text_y + 7), num, font=font_num, fill=(255, 255, 255))

        step_lines = wrap_text(step_text, font_step, width - 260, draw)
        for s_line in step_lines[:2]:
            draw.text((140, text_y + 4), s_line, font=font_step, fill=(55, 65, 81))
            text_y += 34
        text_y += 24

    return canvas.convert("RGB")


# =========================================================================
# LAYOUT 6: CASE MOSAIC (The Asymmetrical 3-Photo Grid)
# =========================================================================
def render_case_mosaic(story: DynamicStoryData, brand: BrandMemory, accent_rgb: Tuple[int, int, int], width: int, height: int) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=(229, 231, 235), width=2)

    padding_x = 72
    curr_y = 68

    # Badge & Client
    font_header = get_inter_font(28)
    draw.rectangle([(padding_x, curr_y), (padding_x + 8, curr_y + 36)], fill=accent_rgb)
    draw.text((padding_x + 24, curr_y + 4), (story.badge_label or brand.business_name).upper(), font=font_header, fill=(17, 24, 39))
    curr_y += 72

    # Headline
    font_head = get_inter_font(52)
    lines = wrap_text(story.headline, font_head, width - 144, draw)
    for line in lines[:2]:
        draw.text((padding_x, curr_y), line, font=font_head, fill=(17, 24, 39))
        curr_y += 62

    # Subheadline
    if story.subheadline:
        draw.text((padding_x, curr_y), story.subheadline, font=get_inter_font(26), fill=(107, 114, 128))
        curr_y += 44

    # 3-Photo Grid Area
    grid_w = width - (padding_x * 2)
    grid_h = height - curr_y - 68
    grid_gap = 18

    left_w = int((grid_w - grid_gap) * 0.58)
    right_w = grid_w - grid_gap - left_w
    half_h = int((grid_h - grid_gap) / 2)

    p1 = get_brand_prompt(brand, story.image_prompt_primary, role="primary")
    p2 = get_brand_prompt(brand, story.image_prompt_secondary, role="detail")
    p3 = get_brand_prompt(brand, story.image_prompt_tertiary, role="portrait")

    img_left = fetch_or_generate_image(p1, width=left_w * 2, height=grid_h * 2)
    img_top_r = fetch_or_generate_image(p2, width=right_w * 2, height=half_h * 2)
    img_bot_r = fetch_or_generate_image(p3, width=right_w * 2, height=half_h * 2)

    img_l = round_corners(ImageOps.fit(img_left, (left_w, grid_h), Image.Resampling.LANCZOS), radius=12)
    img_tr = round_corners(ImageOps.fit(img_top_r, (right_w, half_h), Image.Resampling.LANCZOS), radius=12)
    img_br = round_corners(ImageOps.fit(img_bot_r, (right_w, half_h), Image.Resampling.LANCZOS), radius=12)

    canvas.paste(img_l, (padding_x, curr_y), img_l)
    canvas.paste(img_tr, (padding_x + left_w + grid_gap, curr_y), img_tr)
    canvas.paste(img_br, (padding_x + left_w + grid_gap, curr_y + half_h + grid_gap), img_br)

    return canvas.convert("RGB")


# =========================================================================
# MASTER DISPATCHER: Renders the appropriate archetype
# =========================================================================
def render_dynamic_poster(
    story: DynamicStoryData,
    brand: BrandMemory,
    card_index: int = 1,
    width: int = 1080,
    height: int = 1350,
) -> Path:
    layout = story.visual_layout.lower().strip()
    logger.info(f"Rendering Dynamic Poster for Card {card_index} using archetype: '{layout}'...")

    accent_rgb = hex_to_rgb(brand.primary_color, default=(31, 88, 105))
    if brand.accent_colors and len(brand.accent_colors) > 0:
        accent_rgb = hex_to_rgb(brand.accent_colors[0], default=accent_rgb)

    if layout == "cinematic_hero":
        final_img = render_cinematic_hero(story, brand, accent_rgb, width, height)
    elif layout == "before_after":
        final_img = render_before_after(story, brand, accent_rgb, width, height)
    elif layout == "quote_spotlight":
        final_img = render_quote_spotlight(story, brand, accent_rgb, width, height)
    elif layout == "contrarian_minimal":
        final_img = render_contrarian_minimal(story, brand, accent_rgb, width, height)
    elif layout == "step_flow":
        final_img = render_step_flow(story, brand, accent_rgb, width, height)
    else:
        final_img = render_case_mosaic(story, brand, accent_rgb, width, height)

    output_path = POSTERS_OUTPUT_DIR / f"card_{card_index}_poster.png"
    final_img.save(output_path, "PNG", quality=95)
    logger.info(f"Dynamic Poster successfully saved to: {output_path.resolve()}")
    return output_path
