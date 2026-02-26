"""Emoji Text Renderer - Handles text with emoji for print quality output."""

import re
from typing import Tuple
from PIL import Image, ImageFont
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
# (e.g. Emoji 15.0+ like 🩵 U+1FA75) that the old emoji library doesn't cover.
# Build a combined regex: original pilmoji patterns OR our extended ranges.
# Use a non-capturing group with alternation to avoid matching single ASCII chars.
_EXTENDED_EMOJI_PATTERN = (
    "["
    "\U0001FA70-\U0001FAFF"  # Extended-A (includes 🩵 U+1FA75 and other Emoji 15.0+)
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols (catch any gaps)
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Symbols & Pictographs
    "\U0001F680-\U0001F6FF"  # Transport
    "\U0001F1E0-\U0001F1FF"  # Flags
    "]"
)
_original_pattern = _pilmoji_helpers.EMOJI_REGEX.pattern
_pilmoji_helpers.EMOJI_REGEX = re.compile(
    f'({_original_pattern[1:-1]}|{_EXTENDED_EMOJI_PATTERN})'
)

# Characters that should be stripped before rendering to avoid broken glyphs
# Variation selectors (FE0E = text presentation, FE0F = emoji presentation)
# These are invisible modifiers that fonts often lack glyphs for
INVISIBLE_CHARS_TO_STRIP = re.compile("[\uFE0E\uFE0F]")


def contains_emoji(text: str) -> bool:
    """Check if text contains emoji characters."""
    return bool(EMOJI_PATTERN.search(text))


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def draw_text_with_emoji(
    canvas: Image.Image,
    position: Tuple[int, int],
    text: str,
    fill: str,
    font: ImageFont.FreeTypeFont,
    emoji_scale_factor: float = 1.0
) -> None:
    """Draw text with color emoji support.

    Args:
        canvas: PIL Image to draw on
        position: (x, y) position for text
        text: Text content (may include emoji)
        fill: Text color (hex string like "#000000")
        font: PIL ImageFont to use for text
        emoji_scale_factor: Scale factor for emoji size (default 1.0)
    """
    # Strip variation selectors that pilmoji doesn't consume,
    # which would otherwise render as broken box glyphs
    cleaned_text = INVISIBLE_CHARS_TO_STRIP.sub("", text)
    with Pilmoji(canvas, source=Twemoji) as pilmoji:
        pilmoji.text(
            position,
            cleaned_text,
            fill=hex_to_rgb(fill),
            font=font,
            emoji_scale_factor=emoji_scale_factor
        )
