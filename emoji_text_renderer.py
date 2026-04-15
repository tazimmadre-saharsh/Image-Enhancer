"""Emoji Text Renderer - Handles text with emoji for print quality output.

Also handles per-character font fallback: when the primary font lacks a glyph
for a character (e.g. ClassyVogue doesn't have U+2022 bullet), we swap in a
fallback font (Arial) for just those characters rather than rendering a .notdef
tofu box. This keeps typographic punctuation like •, —, …, '' "" visible even
when the user's chosen decorative font doesn't carry those glyphs.
"""

import re
from functools import lru_cache
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji
from pilmoji.source import Twemoji
import pilmoji.helpers as _pilmoji_helpers

# Regex for quick emoji detection
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Symbols & Pictographs
    "\U0001F680-\U0001F6FF"  # Transport
    "\U0001F1E0-\U0001F1FF"  # Flags
    "\U0001F900-\U0001F9FF"  # Supplemental
    "\U0001FA00-\U0001FAFF"  # Extended-A
    "\u2600-\u26FF"          # Misc symbols
    "\u2700-\u27BF"          # Dingbats
    "\u200D"                 # Zero Width Joiner
    "\uFE0E\uFE0F"           # Variation selectors
    "]+"
)

# Patch pilmoji's emoji regex to include newer Unicode emoji ranges
# (e.g. Emoji 15.0+ like 🩵 U+1FA75) that the old emoji library doesn't cover,
# and also bare emoji codepoints (e.g. ❤ U+2764 without FE0F variation selector)
# that the old emoji library only recognizes with the variation selector attached.
_EXTENDED_EMOJI_PATTERN = (
    "["
    "\U0001FA70-\U0001FAFF"  # Extended-A (includes 🩵 U+1FA75 and other Emoji 15.0+)
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Symbols & Pictographs
    "\U0001F680-\U0001F6FF"  # Transport
    "\U0001F1E0-\U0001F1FF"  # Flags
    "\u2600-\u26FF"          # Misc symbols (❤ U+2764, ☀ U+2600, etc.)
    "\u2700-\u27BF"          # Dingbats (✂ U+2702, etc.)
    "]"
)
_original_pattern = _pilmoji_helpers.EMOJI_REGEX.pattern
_pilmoji_helpers.EMOJI_REGEX = re.compile(
    f'({_original_pattern[1:-1]}|{_EXTENDED_EMOJI_PATTERN})'
)

# Variation selectors (FE0E = text presentation, FE0F = emoji presentation)
# These are stripped only from characters that won't be rendered as emoji,
# to avoid broken box glyphs from fonts that lack these invisible glyphs.
# NOTE: We do NOT strip them before passing to pilmoji, since pilmoji needs
# FE0F to match emoji sequences like ❤️ (U+2764 + U+FE0F).
VARIATION_SELECTORS = re.compile("[\uFE0E\uFE0F]")


def contains_emoji(text: str) -> bool:
    """Check if text contains emoji characters."""
    return bool(EMOJI_PATTERN.search(text))


def get_text_width_with_emoji(text: str, font: ImageFont.FreeTypeFont, emoji_scale_factor: float = 1.0) -> int:
    """Get the rendered width of text that contains emoji.

    Uses pilmoji's getsize which accounts for both text glyphs and emoji images.
    """
    w, _ = _pilmoji_helpers.getsize(text, font, emoji_scale_factor=emoji_scale_factor)
    return w


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _get_emoji_y_offset(font: ImageFont.FreeTypeFont, emoji_scale_factor: float) -> int:
    """Calculate vertical offset to center emoji with the text's cap height.

    Pilmoji pastes emoji at the text origin y, but the visible text (capital
    letters) sits lower due to font metrics. This calculates how many pixels
    to shift the emoji down so it visually centers with the text.
    """
    from PIL import Image as _Img, ImageDraw as _IDraw
    _tmp = _Img.new("L", (1, 1))
    _draw = _IDraw.Draw(_tmp)
    bbox = _draw.textbbox((0, 0), "H", font=font)
    cap_top = bbox[1]
    cap_bottom = bbox[3]
    cap_height = cap_bottom - cap_top
    emoji_height = int(emoji_scale_factor * font.size)
    # Center the emoji vertically within the cap-height region
    return cap_top + (cap_height - emoji_height) // 2


def draw_text_with_emoji(
    canvas: Image.Image,
    position: Tuple[int, int],
    text: str,
    fill: str,
    font: ImageFont.FreeTypeFont,
    emoji_scale_factor: float = 1.0,
    fallback_font: Optional[ImageFont.FreeTypeFont] = None,
) -> None:
    """Draw text with color emoji support.

    Args:
        canvas: PIL Image to draw on
        position: (x, y) position for text
        text: Text content (may include emoji)
        fill: Text color (hex string like "#000000")
        font: PIL ImageFont to use for text
        emoji_scale_factor: Scale factor for emoji size (default 1.0)
        fallback_font: Optional font used for characters the primary font
            lacks. Required to render typographic punctuation (•, —, …, etc.)
            when the primary font is a decorative face missing those glyphs.
    """
    oy = _get_emoji_y_offset(font, emoji_scale_factor)
    if fallback_font is None:
        with Pilmoji(canvas, source=Twemoji) as pilmoji:
            pilmoji.text(
                position,
                text,
                fill=hex_to_rgb(fill),
                font=font,
                emoji_scale_factor=emoji_scale_factor,
                emoji_position_offset=(0, oy)
            )
        return

    # Split text into runs using the primary font where possible, fallback
    # font for characters the primary font doesn't carry a glyph for.
    runs = _split_text_for_fallback(text, font, fallback_font)
    fill_rgb = hex_to_rgb(fill)
    x, y = position
    draw = ImageDraw.Draw(canvas)

    # Align the fallback font's baseline to the primary font's baseline so
    # mixed-font lines don't look staggered.
    primary_ascent, _ = font.getmetrics()
    fallback_ascent, _ = fallback_font.getmetrics()
    fallback_y_adjust = primary_ascent - fallback_ascent

    current_x = float(x)
    for run_text, uses_primary in runs:
        run_font = font if uses_primary else fallback_font
        run_y = y if uses_primary else y + fallback_y_adjust
        if uses_primary and contains_emoji(run_text):
            with Pilmoji(canvas, source=Twemoji) as pilmoji:
                pilmoji.text(
                    (int(current_x), int(run_y)),
                    run_text,
                    fill=fill_rgb,
                    font=run_font,
                    emoji_scale_factor=emoji_scale_factor,
                    emoji_position_offset=(0, oy),
                )
            run_w, _ = _pilmoji_helpers.getsize(
                run_text, run_font, emoji_scale_factor=emoji_scale_factor
            )
        else:
            draw.text(
                (int(current_x), int(run_y)),
                run_text,
                fill=fill_rgb,
                font=run_font,
            )
            try:
                run_w = draw.textlength(run_text, font=run_font)
            except AttributeError:
                bbox = draw.textbbox((0, 0), run_text, font=run_font)
                run_w = bbox[2] - bbox[0]
        current_x += run_w


# =========================
# FONT FALLBACK SUPPORT
# =========================

# Characters we should never split a run on — whitespace and invisible control
# codepoints that every font handles the same way (width-wise they're uniform
# and they won't render a tofu box).
_NEVER_FALLBACK_CODEPOINTS = frozenset({
    0x00A0,  # non-breaking space
    0x200B, 0x200C, 0x200D,  # ZWSP, ZWNJ, ZWJ
    0xFE0E, 0xFE0F,          # variation selectors
})


@lru_cache(maxsize=64)
def _get_font_cmap(font_path: str) -> frozenset:
    """Return the set of codepoints a font file supports (cached).

    Returns an empty frozenset if the cmap can't be read — callers should
    treat that as "assume supported" so we don't force fallback on every
    character.
    """
    if not font_path:
        return frozenset()
    try:
        from fontTools.ttLib import TTFont
        tt = TTFont(font_path, fontNumber=0, lazy=True)
        codepoints = set()
        for table in tt["cmap"].tables:
            codepoints.update(table.cmap.keys())
        tt.close()
        return frozenset(codepoints)
    except Exception:
        return frozenset()


def font_supports_char(font: ImageFont.FreeTypeFont, ch: str) -> bool:
    """True if the loaded font has a glyph for this character."""
    path = getattr(font, "path", None)
    if not path:
        return True
    cmap = _get_font_cmap(path)
    if not cmap:
        return True  # couldn't inspect — assume supported
    return ord(ch) in cmap


def text_has_unsupported_chars(text: str, font: ImageFont.FreeTypeFont) -> bool:
    """True if any non-whitespace, non-emoji character is missing from the font."""
    path = getattr(font, "path", None)
    if not path:
        return False
    cmap = _get_font_cmap(path)
    if not cmap:
        return False
    for ch in text:
        cp = ord(ch)
        if ch.isspace() or cp < 0x20 or cp in _NEVER_FALLBACK_CODEPOINTS:
            continue
        if EMOJI_PATTERN.match(ch):
            continue
        if cp not in cmap:
            return True
    return False


def _split_text_for_fallback(
    text: str,
    primary_font: ImageFont.FreeTypeFont,
    fallback_font: ImageFont.FreeTypeFont,
) -> List[Tuple[str, bool]]:
    """Split text into runs of (run_text, uses_primary_font).

    Characters that exist in the primary font's cmap stay in primary runs.
    Characters missing from the primary but present in the fallback are
    split into fallback runs. Emoji, whitespace, and control characters
    always stay in the primary run so pilmoji can still pick up emoji.
    """
    primary_path = getattr(primary_font, "path", None)
    fallback_path = getattr(fallback_font, "path", None)
    primary_cmap = _get_font_cmap(primary_path) if primary_path else frozenset()
    fallback_cmap = _get_font_cmap(fallback_path) if fallback_path else frozenset()

    if not primary_cmap:
        return [(text, True)]

    runs: List[Tuple[str, bool]] = []
    buf = ""
    buf_primary = True

    def flush():
        nonlocal buf
        if buf:
            runs.append((buf, buf_primary))
            buf = ""

    for ch in text:
        cp = ord(ch)
        if (
            ch.isspace()
            or cp < 0x20
            or cp in _NEVER_FALLBACK_CODEPOINTS
            or EMOJI_PATTERN.match(ch)
            or cp in primary_cmap
        ):
            uses_primary = True
        elif fallback_cmap and cp not in fallback_cmap:
            # Neither font has it — stick with primary (will render as tofu,
            # but so would the fallback).
            uses_primary = True
        else:
            uses_primary = False

        if not buf:
            buf = ch
            buf_primary = uses_primary
        elif uses_primary == buf_primary:
            buf += ch
        else:
            flush()
            buf = ch
            buf_primary = uses_primary
    flush()
    return runs


def get_text_width_with_fallback(
    text: str,
    primary_font: ImageFont.FreeTypeFont,
    fallback_font: Optional[ImageFont.FreeTypeFont],
    emoji_scale_factor: float = 1.0,
) -> int:
    """Measure rendered width of text, accounting for emoji and font fallback.

    Mirrors the layout draw_text_with_emoji uses so centering/wrapping stays
    consistent with what actually gets drawn.
    """
    if fallback_font is None:
        return get_text_width_with_emoji(text, primary_font, emoji_scale_factor)

    runs = _split_text_for_fallback(text, primary_font, fallback_font)
    tmp = Image.new("L", (1, 1))
    draw = ImageDraw.Draw(tmp)
    total = 0.0
    for run_text, uses_primary in runs:
        run_font = primary_font if uses_primary else fallback_font
        if uses_primary and contains_emoji(run_text):
            w, _ = _pilmoji_helpers.getsize(
                run_text, run_font, emoji_scale_factor=emoji_scale_factor
            )
            total += w
        else:
            try:
                total += draw.textlength(run_text, font=run_font)
            except AttributeError:
                bbox = draw.textbbox((0, 0), run_text, font=run_font)
                total += bbox[2] - bbox[0]
    return int(round(total))
