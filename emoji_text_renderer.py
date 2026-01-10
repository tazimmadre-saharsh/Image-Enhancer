"""Emoji Text Renderer - Handles text with emoji for print quality output."""

import re
from typing import Tuple
from PIL import Image, ImageFont
from pilmoji import Pilmoji
from pilmoji.source import Twemoji

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
    "]+"
)


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
    with Pilmoji(canvas, source=Twemoji) as pilmoji:
        pilmoji.text(
            position,
            text,
            fill=hex_to_rgb(fill),
            font=font,
            emoji_scale_factor=emoji_scale_factor
        )
