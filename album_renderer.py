#!/usr/bin/env python3
"""
Album Renderer - Python equivalent of the TypeScript image worker

Renders photobook pages with enhanced images instead of original images.
Integrates with the enhancement pipeline to use high-quality processed images.
"""

import json
import math
import os
import io
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass
import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter, ImageChops, ImageFile

# Allow PIL to load truncated/slightly corrupt images instead of raising an error.
# This prevents missing images on rendered pages when the source JPEG is only
# partially downloaded or has a few trailing bytes missing.
ImageFile.LOAD_TRUNCATED_IMAGES = True
import cv2
import numpy as np

from photobook_enhancer import PhotoBookEnhancer
from enhancement_specs import EnhancementSpec, SpecGenerator
from image_processor import ImageProcessor
from emoji_text_renderer import contains_emoji, draw_text_with_emoji, get_text_width_with_emoji

# =========================
# CONSTANTS
# =========================
DESIGN_REF_WIDTH = 800
DESIGN_REF_HEIGHT = 600
MAX_DPI = 300  # Maximum allowed DPI (capped since downsizing is not supported)
DEFAULT_DPI = 300  # Default DPI when no enhanced images are available
JPEG_QUALITY = 98  # Maximum quality JPEG for print (0-100)

# Default layouts path
LAYOUTS_PATH = Path(__file__).parent / "layouts.json"
FONTS_DIR = Path(__file__).parent / "fonts"
ASSETS_DIR = Path(__file__).parent / "assets"

# =========================
# FONT CONFIGURATION
# =========================

# Font family mapping
FONT_FAMILY_MAP = {
    # Google Fonts
    '"Playfair Display"': "Playfair Display",
    "Playfair Display": "Playfair Display",
    '"Montserrat"': "Montserrat",
    "Montserrat": "Montserrat",
    '"Roboto"': "Roboto",
    "Roboto": "Roboto",
    '"Open Sans"': "Open Sans",
    "Open Sans": "Open Sans",
    '"Lato"': "Lato",
    "Lato": "Lato",
    '"Merriweather"': "Merriweather",
    "Merriweather": "Merriweather",
    '"Raleway"': "Raleway",
    "Raleway": "Raleway",
    '"Dancing Script"': "Dancing Script",
    "Dancing Script": "Dancing Script",
    '"Architects Daughter"': "Architects Daughter",
    "Architects Daughter": "Architects Daughter",
    '"Caveat"': "Caveat",
    "Caveat": "Caveat",
    '"Amatic SC"': "Amatic SC",
    "Amatic SC": "Amatic SC",
    '"Swanky and Moo Moo"': "Swanky and Moo Moo",
    "Swanky and Moo Moo": "Swanky and Moo Moo",
    # New fonts
    '"Chetta Vissto"': "Chetta Vissto",
    "Chetta Vissto": "Chetta Vissto",
    "ChettaVissto": "Chetta Vissto",
    '"Classy Vogue"': "Classy Vogue",
    "Classy Vogue": "Classy Vogue",
    "ClassyVogue": "Classy Vogue",
    '"Hello"': "Hello",
    "Hello": "Hello",
    '"League Spartan"': "League Spartan",
    "League Spartan": "League Spartan",
    "LeagueSpartan": "League Spartan",
    '"New York"': "New York",
    "New York": "New York",
    "NewYork": "New York",
    '"Poppins"': "Poppins",
    "Poppins": "Poppins",
    '"Rammetto One"': "Rammetto One",
    "Rammetto One": "Rammetto One",
    "RammettoOne": "Rammetto One",
    '"Skynight"': "Skynight",
    "Skynight": "Skynight",
    # System fonts
    "Arial": "Arial",
    "Georgia": "Georgia",
    '"Times New Roman"': "Times New Roman",
    "Times New Roman": "Times New Roman",
    "Verdana": "Verdana",
    "Impact": "Impact",
}

# Font files configuration
FONT_FILES = {
    # Playfair Display
    "PlayfairDisplay-Regular": {"family": "Playfair Display", "weight": "normal", "style": "normal"},
    "PlayfairDisplay-Bold": {"family": "Playfair Display", "weight": "bold", "style": "normal"},
    "PlayfairDisplay-Italic": {"family": "Playfair Display", "weight": "normal", "style": "italic"},
    # Montserrat
    "Montserrat-Regular": {"family": "Montserrat", "weight": "normal", "style": "normal"},
    "Montserrat-Bold": {"family": "Montserrat", "weight": "bold", "style": "normal"},
    # Add more fonts as needed...
}

# =========================
# DATA STRUCTURES
# =========================

@dataclass
class AlbumImage:
    imageId: str
    image: Optional[Dict[str, Any]] = None
    # Direct URL field for new API structure
    imageUrl: Optional[str] = None

    def get_url(self) -> Optional[str]:
        """Get image URL from either nested image object or direct imageUrl field."""
        # Try nested image object first (old structure)
        if self.image:
            url = self.image.get("url") or self.image.get("storagePath")
            if url:
                return url
        # Fall back to direct imageUrl (new structure)
        return self.imageUrl

@dataclass
class AlbumPage:
    pageNumber: int
    pageType: Optional[str] = None
    isEditable: Optional[bool] = None
    layoutId: Optional[str] = None
    backgroundColor: Optional[str] = None
    backgroundImageUrl: Optional[str] = None
    backgroundImage: Optional[Dict[str, Any]] = None
    backgroundImageId: Optional[str] = None
    elements: Optional[List[Dict[str, Any]]] = None
    textElements: Optional[List[Dict[str, Any]]] = None
    backCoverLogoUrl: Optional[str] = None

@dataclass
class AlbumData:
    pages: List[AlbumPage]
    project_images: List[AlbumImage]

@dataclass
class LayoutZone:
    id: str
    position: Dict[str, float]  # {"x": float, "y": float}
    size: Dict[str, float]      # {"width": float, "height": float}

@dataclass
class LayoutDef:
    id: str
    zones: List[LayoutZone]

@dataclass
class RenderedPage:
    pageNumber: int
    pageType: Optional[str]
    buffer: bytes

# =========================
# HELPER FUNCTIONS
# =========================

def load_layouts_by_id(layouts_path: Optional[Path] = None) -> Dict[str, LayoutDef]:
    """Load layouts from JSON file and return as dictionary keyed by ID."""
    if layouts_path is None:
        layouts_path = LAYOUTS_PATH
    
    with open(layouts_path, 'r') as f:
        layouts_array = json.load(f)
    
    layouts_by_id = {}
    for layout_data in layouts_array:
        zones = [
            LayoutZone(
                id=zone["id"],
                position=zone["position"],
                size=zone["size"]
            )
            for zone in layout_data.get("zones", [])
        ]
        layout = LayoutDef(id=layout_data["id"], zones=zones)
        layouts_by_id[layout.id] = layout
    
    return layouts_by_id

def load_remote_image(url: str, timeout: int = 20) -> Image.Image:
    """Load image from URL with EXIF orientation correction."""
    if not url or not isinstance(url, str):
        raise ValueError("Missing image url for remote load")

    headers = {"User-Agent": "Mozilla/5.0 (compatible; AlbumRenderer/1.0)"}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()

    img = Image.open(io.BytesIO(response.content))

    # Apply EXIF orientation correction (browsers/Canvas do this automatically)
    # This is needed because images may be stored in landscape with EXIF rotation data
    try:
        img = ImageOps.exif_transpose(img)
    except (AttributeError, OSError, TypeError):
        # No EXIF data or orientation info
        pass

    return img

def pct_x(width: float, value: float) -> float:
    """Convert percentage to pixel value for width."""
    return (value / 100.0) * width

def pct_y(height: float, value: float) -> float:
    """Convert percentage to pixel value for height."""
    return (value / 100.0) * height

def get_fitted_rect(img_w: int, img_h: int, box_w: int, box_h: int, mode: str = "cover") -> Dict[str, float]:
    """Calculate fitted rectangle for image in container."""
    if mode == "fill":
        return {"x": 0, "y": 0, "width": box_w, "height": box_h}
    
    img_ratio = img_w / img_h
    box_ratio = box_w / box_h
    
    if mode == "cover":
        scale = box_w / img_w if box_ratio > img_ratio else box_h / img_h
    else:  # "contain" or "smart"
        scale = box_h / img_h if box_ratio > img_ratio else box_w / img_w
    
    w = img_w * scale
    h = img_h * scale
    
    return {
        "x": (box_w - w) / 2,
        "y": (box_h - h) / 2,
        "width": w,
        "height": h
    }

def resolve_font_family(css_font_family: str) -> str:
    """Parse CSS font-family string and return best matching font."""
    if not css_font_family:
        return "Arial"
    
    fonts = [f.strip() for f in css_font_family.split(",")]
    
    for font in fonts:
        clean_font = font.replace('"', '').replace("'", "").strip()
        
        # Check direct mapping
        if font in FONT_FAMILY_MAP:
            return FONT_FAMILY_MAP[font]
        if clean_font in FONT_FAMILY_MAP:
            return FONT_FAMILY_MAP[clean_font]
        
        # Skip generic families
        if clean_font in ["sans-serif", "serif", "monospace", "cursive", "fantasy"]:
            continue
        
        return clean_font
    
    return "Arial"

def load_font(family: str, size: int, style: str = "normal", weight: str = "normal") -> tuple:
    """Load font with fallback to system fonts if not found.

    Returns:
        tuple: (ImageFont.FreeTypeFont, bool) - The font and whether bold was requested but not found
    """
    # List of font paths to try
    font_attempts = []
    bold_requested_but_not_found = False

    # Normalize weight to boolean
    is_bold = weight in ("bold", "700", "800", "900") or (isinstance(weight, int) and weight >= 700)
    is_italic = style == "italic"

    # Build suffix patterns to match (in priority order)
    if is_bold and is_italic:
        suffix_patterns = ["bolditalic", "bold-italic", "bold_italic", "bi", "bold", "italic", "regular", ""]
    elif is_bold:
        suffix_patterns = ["bold", "regular", ""]
    elif is_italic:
        suffix_patterns = ["italic", "regular", ""]
    else:
        suffix_patterns = ["regular", ""]

    # Normalize family name for matching
    family_normalized = family.lower().replace(" ", "").replace("-", "")

    # Track which suffix was actually matched
    matched_suffix = None

    # 1. Try fonts directory if it exists
    if FONTS_DIR.exists():
        # Collect all matching font files for this family
        matching_fonts = []
        for font_file in FONTS_DIR.glob("*.ttf"):
            stem_normalized = font_file.stem.lower().replace("-", "").replace("_", "")
            if family_normalized in stem_normalized:
                matching_fonts.append(font_file)

        # Try to find best match based on suffix patterns
        for suffix in suffix_patterns:
            for font_file in matching_fonts:
                stem_normalized = font_file.stem.lower().replace("-", "").replace("_", "")
                # Check if this font matches the desired suffix
                if suffix == "":
                    # Empty suffix matches any font (fallback)
                    font_attempts.append(str(font_file))
                    matched_suffix = suffix
                    break
                elif suffix in stem_normalized:
                    font_attempts.append(str(font_file))
                    matched_suffix = suffix
                    break
            if font_attempts:
                break

        # If no match found but we have matching fonts, use the first one
        if not font_attempts and matching_fonts:
            font_attempts.append(str(matching_fonts[0]))
            matched_suffix = ""

    # Check if bold was requested but we fell back to non-bold
    if is_bold and matched_suffix not in ["bold", "bolditalic", "bold-italic", "bold_italic", "bi"]:
        bold_requested_but_not_found = True
        print(f"[DEBUG] Bold requested for '{family}' but no bold variant found, will simulate bold")

    # 2. Try common system font locations
    system_font_paths = [
        f"/System/Library/Fonts/{family}.ttc",  # macOS
        f"/System/Library/Fonts/Supplemental/{family}.ttf",  # macOS
        f"/Library/Fonts/{family}.ttf",  # macOS user fonts
        f"/usr/share/fonts/truetype/{family.lower()}/{family}.ttf",  # Linux
        f"C:\\Windows\\Fonts\\{family}.ttf",  # Windows
    ]
    font_attempts.extend(system_font_paths)

    # 3. Try generic font names as fallback from system
    fallback_fonts = ["Arial", "Helvetica", "DejaVuSans", "FreeSans"]
    for fb_font in fallback_fonts:
        font_attempts.extend([
            f"/System/Library/Fonts/{fb_font}.ttc",
            f"/System/Library/Fonts/{fb_font}.ttf",
            f"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ])

    # Try each font path
    for font_path in font_attempts:
        try:
            return (ImageFont.truetype(font_path, size), bold_requested_but_not_found)
        except (OSError, IOError):
            continue

    # 4. Last resort: use bundled fallback fonts from our fonts directory
    # These are guaranteed to exist and are scalable TrueType fonts
    # Arial is first as it's the client's default font
    bundled_fallbacks = ["Arial", "Roboto", "OpenSans", "Lato", "Montserrat"]
    if FONTS_DIR.exists():
        for fallback_name in bundled_fallbacks:
            # Try with style suffix
            if is_bold and is_italic:
                suffixes = ["-BoldItalic", "-Bold", "-Regular", ""]
            elif is_bold:
                suffixes = ["-Bold", "-Regular", ""]
            elif is_italic:
                suffixes = ["-Italic", "-Regular", ""]
            else:
                suffixes = ["-Regular", ""]

            for suffix in suffixes:
                fallback_path = FONTS_DIR / f"{fallback_name}{suffix}.ttf"
                if fallback_path.exists():
                    try:
                        print(f"[DEBUG] Using bundled fallback font: {fallback_path}")
                        return (ImageFont.truetype(str(fallback_path), size), bold_requested_but_not_found)
                    except (OSError, IOError):
                        continue

    # Absolute last resort: PIL's default (bitmap font - not ideal)
    print(f"[WARNING] No scalable font found, using PIL default bitmap font")
    try:
        return (ImageFont.load_default(), bold_requested_but_not_found)
    except:
        return (ImageFont.load_default(), bold_requested_but_not_found)

def draw_text(
    draw: ImageDraw.ImageDraw,
    text_elem: Dict[str, Any],
    page_w: int,
    page_h: int,
    override_x: Optional[float] = None,
    override_y: Optional[float] = None
):
    """Draw text element on the image."""
    content = text_elem.get("content", "")
    if not content:
        return

    y = override_y if override_y is not None else pct_y(page_h, text_elem.get("position", {}).get("y", 0))

    # Scale font size from design resolution to print resolution
    scale_y = page_h / DESIGN_REF_HEIGHT
    font_px = int((text_elem.get("fontSize", 12)) * scale_y)

    print(f"[DEBUG] Text: '{content}', fontSize: {text_elem.get('fontSize', 12)}, scaled: {font_px}px, page_h: {page_h}, scale_y: {scale_y:.2f}")

    # Resolve font family
    css_font_family = text_elem.get("fontFamily", "Arial")
    font_family = resolve_font_family(css_font_family)
    font_style = text_elem.get("fontStyle", "normal")
    font_weight = text_elem.get("fontWeight", "normal")

    print(f"[DEBUG] Font family: '{css_font_family}' -> '{font_family}'")

    # Load font (returns tuple: font, simulate_bold)
    font, simulate_bold = load_font(font_family, font_px, font_style, font_weight)

    # Calculate stroke width for simulated bold (proportional to font size)
    stroke_width = max(1, font_px // 50) if simulate_bold else 0

    # Check text width and adjust if needed
    has_emoji = contains_emoji(content)
    emoji_scale = 0.85  # Scale emojis slightly smaller than font height to match preview appearance

    if has_emoji:
        # Use emoji-aware width calculation that accounts for emoji image sizes
        text_width = get_text_width_with_emoji(content, font, emoji_scale)
    else:
        try:
            text_bbox = draw.textbbox((0, 0), content, font=font)
            text_width = text_bbox[2] - text_bbox[0]
        except:
            # Fallback for older PIL versions
            text_width = font.getsize(content)[0] if hasattr(font, 'getsize') else len(content) * font_px * 0.6

    # Safe area is 10% from left and right edges
    safe_left = page_w * 0.10
    safe_right = page_w * 0.90
    safe_area_width = safe_right - safe_left  # 80% of page width

    # Calculate intended X position first (before any scaling)
    centered_x = (page_w - text_width) / 2
    intended_x = override_x if override_x is not None else centered_x

    # Calculate where text would end up
    text_left = intended_x
    text_right = intended_x + text_width

    # Only scale down if text actually overflows the safe area
    if text_left < safe_left or text_right > safe_right:
        print(f"[DEBUG] Text overflows safe area: left={text_left:.0f} (safe={safe_left:.0f}), right={text_right:.0f} (safe={safe_right:.0f})")

        # Calculate scale factor to fit text within safe area
        # For centered text, max width is safe_area_width
        # For non-centered text, calculate based on available space
        if override_x is None:
            # Centered text - scale to fit within safe area width
            scale_factor = safe_area_width / text_width
        else:
            # Non-centered text - calculate available space from position to safe boundary
            available_width = safe_right - intended_x
            if intended_x < safe_left:
                # Text starts before safe area, need to fit entirely in safe area
                available_width = safe_area_width
            scale_factor = available_width / text_width

        font_px = int(font_px * scale_factor)
        font, simulate_bold = load_font(font_family, font_px, font_style, font_weight)
        stroke_width = max(1, font_px // 50) if simulate_bold else 0

        if has_emoji:
            text_width = get_text_width_with_emoji(content, font, emoji_scale)
        else:
            try:
                text_bbox = draw.textbbox((0, 0), content, font=font)
                text_width = text_bbox[2] - text_bbox[0]
            except:
                text_width = font.getsize(content)[0] if hasattr(font, 'getsize') else len(content) * font_px * 0.6

        # Recalculate centered position with new text width
        centered_x = (page_w - text_width) / 2
    else:
        print(f"[DEBUG] Text fits in safe area: left={text_left:.0f} (safe={safe_left:.0f}), right={text_right:.0f} (safe={safe_right:.0f})")

    # Calculate final X position
    x = override_x if override_x is not None else centered_x

    print(f"[DEBUG] Drawing text at ({x:.0f}, {y:.0f}), width: {text_width:.0f}px")

    color = text_elem.get("color", "#000000")

    # Draw text (with emoji support if text contains emoji)
    if has_emoji:
        canvas = draw._image
        draw_text_with_emoji(canvas, (int(x), int(y)), content, color, font, emoji_scale)
    else:
        # Use stroke to simulate bold if bold font variant wasn't available
        if stroke_width > 0:
            draw.text((x, y), content, fill=color, font=font, stroke_width=stroke_width, stroke_fill=color)
        else:
            draw.text((x, y), content, fill=color, font=font)

# =========================
# ENHANCED IMAGE INTEGRATION
# =========================

class EnhancedImageManager:
    """Manages enhanced images and provides fallback to original images."""

    def __init__(self, enhanced_dir: Optional[Path] = None):
        self.enhanced_dir = enhanced_dir
        self.enhanced_images_cache: Dict[str, str] = {}
        self._min_dpi: Optional[int] = None  # Track minimum DPI across enhanced images
        self._per_image_dpi: Dict[str, Optional[int]] = {}  # Track DPI per image
        self._icc_profile: Optional[bytes] = None  # Store ICC profile from enhanced images

        if enhanced_dir and enhanced_dir.exists():
            self._build_enhanced_cache()

    def _build_enhanced_cache(self):
        """Build cache of enhanced image paths by imageId and determine minimum DPI."""
        if not self.enhanced_dir or not self.enhanced_dir.exists():
            return

        dpi_values = []
        for img_file in self.enhanced_dir.glob("*.jpg"):
            # Enhanced images are named as: {imageId}_page{pageNo:02d}.jpg
            if "_page" in img_file.stem:
                image_id = img_file.stem.split("_page")[0]
                self.enhanced_images_cache[image_id] = str(img_file)

                # Read DPI and ICC profile from image metadata
                try:
                    with Image.open(img_file) as img:
                        dpi = img.info.get("dpi")
                        if dpi:
                            # DPI is a tuple (x_dpi, y_dpi), take the first value
                            img_dpi = int(dpi[0]) if isinstance(dpi, tuple) else int(dpi)
                            dpi_values.append(img_dpi)
                            self._per_image_dpi[image_id] = img_dpi
                        else:
                            # TOO_SMALL images have no DPI metadata - skip for DPI calculation
                            # (they're still usable, just at lower quality)
                            self._per_image_dpi[image_id] = None
                            print(f"Info: {img_file.name} has no DPI metadata (likely TOO_SMALL)")

                        # Extract ICC profile from first image that has one
                        if self._icc_profile is None:
                            icc = img.info.get("icc_profile")
                            if icc:
                                self._icc_profile = icc
                except Exception as e:
                    self._per_image_dpi[image_id] = None
                    print(f"Warning: Could not read metadata from {img_file}: {e}")

        # Set minimum DPI (capped at MAX_DPI)
        if dpi_values:
            self._min_dpi = min(min(dpi_values), MAX_DPI)

    def get_dpi(self) -> int:
        """Get the DPI to use for rendering, based on enhanced images (capped at MAX_DPI)."""
        if self._min_dpi is not None:
            return self._min_dpi
        return DEFAULT_DPI

    def get_image_dpi(self, image_id: str) -> Optional[int]:
        """Get DPI for a specific image, or None if TOO_SMALL/unknown."""
        return self._per_image_dpi.get(image_id)

    def get_page_dpi(self, image_ids: List[str]) -> int:
        """
        Get the DPI to use for a specific page based on images on that page.

        Returns the minimum DPI among the provided image IDs (capped at MAX_DPI).
        If no valid DPIs found, returns DEFAULT_DPI.
        """
        page_dpis = []
        for image_id in image_ids:
            img_dpi = self._per_image_dpi.get(image_id)
            if img_dpi is not None:  # Skip TOO_SMALL images (None)
                page_dpis.append(img_dpi)

        if page_dpis:
            return min(min(page_dpis), MAX_DPI)
        return DEFAULT_DPI

    def get_icc_profile(self) -> Optional[bytes]:
        """Get the ICC profile extracted from enhanced images."""
        return self._icc_profile

    def get_image(self, image_id: str, original_url: Optional[str] = None) -> Image.Image:
        """Get enhanced image if available, fallback to original."""
        # Try enhanced image first
        if image_id in self.enhanced_images_cache:
            try:
                enhanced_path = self.enhanced_images_cache[image_id]
                img = Image.open(enhanced_path)
                # Enhanced images are already processed and correctly oriented
                # NO EXIF rotation needed
                return img
            except Exception as e:
                print(f"Failed to load enhanced image for {image_id}: {e}")

        # Fallback to original image with EXIF orientation correction
        if original_url:
            return load_remote_image(original_url)

        raise ValueError(f"No image available for imageId: {image_id}")

# =========================
# RENDER PAGE
# =========================

def get_page_image_ids(page: AlbumPage, layouts_by_id: Dict[str, LayoutDef]) -> List[str]:
    """Extract all image IDs used on a page (background + layout elements)."""
    image_ids = []

    # Background image ID
    bg_image_id = page.backgroundImageId or (page.backgroundImage and page.backgroundImage.get("imageId"))
    if bg_image_id:
        image_ids.append(bg_image_id)

    # Layout element image IDs
    if page.layoutId and page.layoutId in layouts_by_id:
        layout = layouts_by_id[page.layoutId]
        elements = page.elements or []
        for zone in layout.zones:
            elem = next((e for e in elements if e.get("zoneId") == zone.id), None)
            if elem and elem.get("imageId"):
                image_ids.append(elem["imageId"])

    return image_ids


async def render_page(
    page: AlbumPage,
    page_width: int,
    page_height: int,
    layouts_by_id: Dict[str, LayoutDef],
    album: AlbumData,
    enhanced_manager: Optional[EnhancedImageManager] = None,
    icc_profile: Optional[bytes] = None,
    dpi: int = DEFAULT_DPI
) -> bytes:
    """Render a single page to JPEG buffer."""
    
    # Create canvas
    canvas = Image.new("RGB", (page_width, page_height), color=page.backgroundColor or "#ffffff")
    
    # 1) Background image
    bg_url = None
    if page.backgroundImageUrl:
        bg_url = page.backgroundImageUrl
    elif page.backgroundImage and page.backgroundImage.get("url"):
        bg_url = page.backgroundImage["url"]
    elif page.backgroundImage and page.backgroundImage.get("storagePath"):
        bg_url = page.backgroundImage["storagePath"]
    elif page.backgroundImageId or (page.backgroundImage and page.backgroundImage.get("imageId")):
        bg_image_id = page.backgroundImageId or page.backgroundImage.get("imageId")
        bg_image_obj = next((p for p in album.project_images if p.imageId == bg_image_id), None)
        if bg_image_obj:
            # Get URL using helper method (supports both old and new structures)
            bg_url = bg_image_obj.get_url()
    
    if bg_url:
        try:
            bg_image_id = page.backgroundImageId or (page.backgroundImage and page.backgroundImage.get("imageId"))
            if enhanced_manager and bg_image_id:
                bg_img = enhanced_manager.get_image(bg_image_id, bg_url)
                bg_dpi = enhanced_manager.get_image_dpi(bg_image_id)
                is_enhanced = bg_image_id in enhanced_manager.enhanced_images_cache
                if is_enhanced:
                    dpi_str = f"{bg_dpi} DPI" if bg_dpi else "TOO_SMALL (no DPI)"
                    print(f"  🖼️ Background {bg_image_id}: Enhanced, {dpi_str}")
                else:
                    print(f"  🖼️ Background {bg_image_id}: Original (no enhanced version)")
            else:
                bg_img = load_remote_image(bg_url)
                if bg_image_id:
                    print(f"  🖼️ Background {bg_image_id}: Original (enhancement disabled)")
                else:
                    print(f"  🖼️ Background: Original (URL only)")

            # Apply background image with transforms (matching TypeScript lines 403-435)
            bg_transform = page.backgroundImage.get("transform", {}) if page.backgroundImage else {}
            fit_mode = bg_transform.get("fitMode", "cover")
            rotation = bg_transform.get("rotation", 0)
            flip_x = bg_transform.get("flipX", False)
            flip_y = bg_transform.get("flipY", False)
            scale = bg_transform.get("scale", 1.0)
            offset_x = bg_transform.get("offsetX", 0)
            offset_y = bg_transform.get("offsetY", 0)
            opacity = bg_transform.get("opacity", 1.0)

            # Calculate fitted dimensions
            fitted_bg_base = get_fitted_rect(bg_img.width, bg_img.height, page_width, page_height, fit_mode)

            # Apply scale
            draw_bw = fitted_bg_base["width"] * scale
            draw_bh = fitted_bg_base["height"] * scale
            draw_bx = fitted_bg_base["x"] + offset_x
            draw_by = fitted_bg_base["y"] + offset_y

            # Resize background image
            bg_resized = bg_img.resize((int(draw_bw), int(draw_bh)), Image.Resampling.LANCZOS)

            # Apply sharpening after resize
            bg_resized = bg_resized.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))

            # Apply transforms (Canvas context style)
            bg_transformed = bg_resized.convert("RGBA")

            # Apply flips
            if flip_x:
                bg_transformed = bg_transformed.transpose(Image.FLIP_LEFT_RIGHT)
            if flip_y:
                bg_transformed = bg_transformed.transpose(Image.FLIP_TOP_BOTTOM)

            # Apply rotation (Canvas rotates CLOCKWISE with positive angles)
            if rotation != 0:
                # Calculate center for rotation
                bcx = draw_bx + draw_bw / 2
                bcy = draw_by + draw_bh / 2

                # Rotate (negate for PIL counterclockwise)
                bg_transformed = bg_transformed.rotate(-rotation, expand=True, fillcolor=(0, 0, 0, 0))

                # Recalculate position after rotation
                draw_bx = bcx - bg_transformed.width / 2
                draw_by = bcy - bg_transformed.height / 2

            # Apply opacity
            if opacity < 1.0:
                alpha = int(255 * max(0, min(1, opacity)))
                # Adjust alpha channel
                alpha_channel = bg_transformed.split()[3]
                alpha_channel = alpha_channel.point(lambda p: int(p * opacity))
                bg_transformed.putalpha(alpha_channel)

            # Composite onto canvas
            canvas_rgba = canvas.convert("RGBA")
            canvas_rgba.paste(bg_transformed, (int(draw_bx), int(draw_by)), bg_transformed)
            canvas = canvas_rgba.convert("RGB")
            
        except Exception as e:
            print(f"⚠️ WARNING: Failed to load background image for page {page.pageNumber} "
                  f"(type={page.pageType}): {e}")
    
    # 2) Layout zones with enhanced images
    layout = layouts_by_id.get(page.layoutId) if page.layoutId else None
    
    if layout and layout.zones:
        for zone in layout.zones:
            if not page.elements:
                continue
                
            elem = next((e for e in page.elements if e.get("zoneId") == zone.id), None)
            if not elem or not elem.get("imageId"):
                continue
            
            image_obj = next((p for p in album.project_images if p.imageId == elem["imageId"]), None)
            if not image_obj:
                continue

            # Get URL using helper method (supports both old and new structures)
            original_url = image_obj.get_url()
            if not original_url:
                continue
            
            try:
                # Use enhanced image if available, fallback to original
                image_id = elem["imageId"]
                if enhanced_manager:
                    img = enhanced_manager.get_image(image_id, original_url)
                    img_dpi = enhanced_manager.get_image_dpi(image_id)
                    is_enhanced = image_id in enhanced_manager.enhanced_images_cache
                    if is_enhanced:
                        dpi_str = f"{img_dpi} DPI" if img_dpi else "TOO_SMALL (no DPI)"
                        print(f"  📷 Image {image_id}: Enhanced, {dpi_str}")
                    else:
                        print(f"  📷 Image {image_id}: Original (no enhanced version)")
                else:
                    img = load_remote_image(original_url) if original_url else None
                    print(f"  📷 Image {image_id}: Original (enhancement disabled)")

                if not img:
                    continue

                # Calculate zone positions
                zone_x = pct_x(page_width, zone.position["x"])
                zone_y = pct_y(page_height, zone.position["y"])
                zone_w = pct_x(page_width, zone.size["width"])
                zone_h = pct_y(page_height, zone.size["height"])
                
                # Apply transforms
                transform = elem.get("transform", {})
                fit_mode = transform.get("fitMode", "cover")
                layout_mode = transform.get("layoutMode", None)
                scale = transform.get("scale", 1.0)
                offset_x = transform.get("offsetX", 0)
                offset_y = transform.get("offsetY", 0)
                margin = transform.get("margin", 0)
                rotation = transform.get("rotation", 0)
                flip_x = transform.get("flipX", False)
                flip_y = transform.get("flipY", False)
                crop = transform.get("crop")

                # Apply margin only for 'smart' fitMode (matches frontend behavior)
                if fit_mode == "smart":
                    margin_px_x = (margin / 100.0) * zone_w
                    margin_px_y = (margin / 100.0) * zone_h
                    effective_zone_w = zone_w - (margin_px_x * 2)
                    effective_zone_h = zone_h - (margin_px_y * 2)
                    effective_zone_x = zone_x + margin_px_x
                    effective_zone_y = zone_y + margin_px_y
                else:
                    effective_zone_w = zone_w
                    effective_zone_h = zone_h
                    effective_zone_x = zone_x
                    effective_zone_y = zone_y

                # Check if we have valid crop data
                # Crop represents scale/offset transforms, not extraction coordinates
                has_crop = crop and crop.get("width", 0) > 0 and crop.get("height", 0) > 0

                if has_crop:
                    # Frontend crop logic: crop values define scale and offset
                    # scaleX = 100 / crop.width, scaleY = 100 / crop.height
                    # Image is scaled to (zone_size * scale) and positioned with offset
                    crop_width = crop.get("width", 100)
                    crop_height = crop.get("height", 100)
                    crop_x = crop.get("x", 0)
                    crop_y = crop.get("y", 0)

                    # Swap crop dimensions for 90° or 270° rotations
                    # Frontend calculates crop values for POST-rotation state,
                    # but backend applies crop before rotation, so we need to swap
                    rotation_mod = rotation % 360
                    if rotation_mod == 90 or rotation_mod == 270:
                        crop_width, crop_height = crop_height, crop_width
                        crop_x, crop_y = crop_y, crop_x

                    scale_x = 100.0 / crop_width
                    scale_y = 100.0 / crop_height

                    # Calculate image dimensions relative to zone
                    # The image is scaled so that crop_width% of image = 100% of zone
                    draw_w = effective_zone_w * scale_x
                    draw_h = effective_zone_h * scale_y

                    # Calculate offset position
                    # Frontend: offsetX = -crop.x * scaleX, offsetY = -crop.y * scaleY
                    crop_offset_x = -crop_x * scale_x
                    crop_offset_y = -crop_y * scale_y

                    # Position image within zone (as percentage converted to pixels)
                    draw_x = effective_zone_x + (crop_offset_x / 100.0) * effective_zone_w
                    draw_y = effective_zone_y + (crop_offset_y / 100.0) * effective_zone_h

                    # Use the full image (no extraction crop)
                    img_to_draw = img

                else:
                    # No crop data - use original fitMode logic
                    # When layoutMode is "original", use contain to show full image
                    if layout_mode == "original":
                        fit_mode = "contain"

                    # Calculate fitted size
                    fitted = get_fitted_rect(img.width, img.height, effective_zone_w, effective_zone_h, fit_mode)

                    # Apply scale
                    draw_w = fitted["width"] * scale
                    draw_h = fitted["height"] * scale

                    # Calculate draw position with offset
                    draw_x = effective_zone_x + fitted["x"] + offset_x
                    draw_y = effective_zone_y + fitted["y"] + offset_y

                    # Use full image
                    img_to_draw = img

                # Calculate center point for rotation
                cx = draw_x + draw_w / 2
                cy = draw_y + draw_h / 2

                # Resize to draw dimensions
                img_resized = img_to_draw.resize((int(draw_w), int(draw_h)), Image.Resampling.LANCZOS)

                # Apply sharpening after resize to compensate for quality loss
                # This is important because we're resizing already-enhanced images
                img_resized = img_resized.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))

                # Create a temporary canvas for transforms
                # This simulates Canvas context save/clip/transform/draw/restore
                temp_layer = Image.new("RGBA", (page_width, page_height), (0, 0, 0, 0))

                # Apply transforms matching Canvas order: translate -> rotate -> scale(flip)
                img_transformed = img_resized.convert("RGBA")

                # Apply flips (Canvas scale with negative values)
                if flip_x:
                    img_transformed = img_transformed.transpose(Image.FLIP_LEFT_RIGHT)
                if flip_y:
                    img_transformed = img_transformed.transpose(Image.FLIP_TOP_BOTTOM)

                # Apply rotation if needed (Canvas rotates CLOCKWISE, PIL rotates COUNTERCLOCKWISE)
                if rotation != 0:
                    # Negate rotation to match Canvas clockwise behavior
                    img_transformed = img_transformed.rotate(-rotation, expand=True, fillcolor=(0, 0, 0, 0))

                # Calculate position after rotation (image size may have changed)
                paste_x = int(cx - img_transformed.width / 2)
                paste_y = int(cy - img_transformed.height / 2)

                # Paste transformed image to temp layer
                temp_layer.paste(img_transformed, (paste_x, paste_y), img_transformed)

                # Create clipping mask for the zone
                mask = Image.new("L", (page_width, page_height), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.rectangle([int(zone_x), int(zone_y), int(zone_x + zone_w), int(zone_y + zone_h)], fill=255)

                # Apply zone mask to temp_layer's alpha channel to clip outside the zone
                # This preserves transparency within the zone (for contain/letterbox areas)
                temp_alpha = temp_layer.split()[3]  # Get alpha channel
                clipped_alpha = ImageChops.multiply(temp_alpha, mask)  # Combine with zone mask
                temp_layer.putalpha(clipped_alpha)

                # Alpha composite onto canvas - transparent areas show canvas background
                canvas = canvas.convert("RGBA")
                canvas = Image.alpha_composite(canvas, temp_layer)
                canvas = canvas.convert("RGB")
                
            except Exception as e:
                print(f"⚠️ WARNING: Failed to process image {elem['imageId']} on page {page.pageNumber} "
                      f"(type={page.pageType}, zone={zone.id}): {e}")
                continue
    
    # 3) Text elements
    # Create new draw object on the final canvas after all image processing
    if page.textElements:
        draw = ImageDraw.Draw(canvas)
        for text_elem in page.textElements:
            draw_text(draw, text_elem, page_width, page_height)

    # 4) Back cover logo (only if no background image on back cover)
    has_back_cover_bg = page.pageType == "cover-back" and (page.backgroundImageUrl or page.backgroundImage or page.backgroundImageId)
    if page.pageType == "cover-back" and page.backCoverLogoUrl and not has_back_cover_bg:
        try:
            # Resolve logo: load from local assets based on the relative URL path
            logo_filename = Path(page.backCoverLogoUrl).name  # e.g. "light-back-cover-logo.png"
            local_logo_path = ASSETS_DIR / "back-cover-logo" / logo_filename
            if local_logo_path.exists():
                logo_img = Image.open(local_logo_path)
            else:
                logo_img = load_remote_image(page.backCoverLogoUrl)

            # Size logo to full page (logo is full-page with transparent background)
            fitted = get_fitted_rect(logo_img.width, logo_img.height, page_width, page_height, "contain")
            logo_resized = logo_img.resize(
                (int(fitted["width"]), int(fitted["height"])),
                Image.Resampling.LANCZOS
            )

            # Center on page
            logo_x = int((page_width - fitted["width"]) / 2)
            logo_y = int((page_height - fitted["height"]) / 2)

            # Alpha-composite for transparent PNG logos
            canvas_rgba = canvas.convert("RGBA")
            logo_rgba = logo_resized.convert("RGBA")
            canvas_rgba.paste(logo_rgba, (logo_x, logo_y), logo_rgba)
            canvas = canvas_rgba.convert("RGB")

            print(f"  🏷️ Back cover logo rendered: {logo_filename}")
        except Exception as e:
            print(f"  ⚠️ Failed to render back cover logo: {e}")

    # Convert to JPEG with metadata
    output_buffer = io.BytesIO()

    # Build save kwargs with DPI and ICC profile
    save_kwargs = {
        "format": "JPEG",
        "quality": JPEG_QUALITY,
        "dpi": (dpi, dpi),
        "optimize": True
    }

    # Include ICC profile to preserve color vibrancy
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile

    canvas.save(output_buffer, **save_kwargs)

    return output_buffer.getvalue()

# =========================
# ALBUM RENDERER CLASS
# =========================

class AlbumRenderer:
    """Main album renderer with enhanced image integration."""
    
    def __init__(self, layouts_path: Optional[Path] = None, enhanced_dir: Optional[Path] = None):
        self.layouts_by_id = load_layouts_by_id(layouts_path)
        self.enhanced_manager = EnhancedImageManager(enhanced_dir) if enhanced_dir else None
        self.enhancer = PhotoBookEnhancer()
    
    def generate_and_use_enhanced_images(
        self,
        album_file: Union[str, Path],
        page_size: str,
        enhanced_output_dir: Union[str, Path]
    ) -> Path:
        """Generate enhanced images and return the enhanced directory path."""
        result = self.enhancer.enhance_album(
            album_file=album_file,
            page_size=page_size,
            output_dir=enhanced_output_dir,
            images_dir=None  # Use URLs from specs
        )
        
        enhanced_dir = Path(enhanced_output_dir)
        self.enhanced_manager = EnhancedImageManager(enhanced_dir)
        
        return enhanced_dir
    
    async def render_album_pages(
        self,
        album_data: Dict[str, Any],
        page_size: str,
        output_dir: Union[str, Path],
        use_enhanced: bool = True
    ) -> List[RenderedPage]:
        """Render all pages of an album."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Parse page size (dimensions calculated per-page based on image DPIs)
        page_w_in, page_h_in = [float(x) for x in page_size.lower().split("x")]

        # Convert data to structured format (supports both old and new API structures)
        album_images = [
            AlbumImage(
                imageId=img.get("imageId", ""),
                image=img.get("image"),
                imageUrl=img.get("imageUrl")  # New structure has direct imageUrl
            )
            for img in album_data.get("data", {}).get("project_images", [])
        ]
        
        album_pages = [
            AlbumPage(
                pageNumber=page.get("pageNumber", 0),
                pageType=page.get("pageType"),
                layoutId=page.get("layoutId"),
                backgroundColor=page.get("backgroundColor"),
                backgroundImageUrl=page.get("backgroundImageUrl"),
                backgroundImage=page.get("backgroundImage"),
                backgroundImageId=page.get("backgroundImageId"),
                elements=page.get("elements"),
                textElements=page.get("textElements"),
                backCoverLogoUrl=page.get("backCoverLogoUrl")
            )
            for page in album_data.get("data", {}).get("pages", [])
        ]

        album = AlbumData(pages=album_pages, project_images=album_images)

        rendered_pages = []

        # Get ICC profile from enhanced images to preserve color vibrancy
        icc_profile = self.enhanced_manager.get_icc_profile() if self.enhanced_manager else None

        for page in album.pages:
            try:
                # Calculate per-page DPI based on images on this page
                if self.enhanced_manager and use_enhanced:
                    page_image_ids = get_page_image_ids(page, self.layouts_by_id)
                    page_dpi = self.enhanced_manager.get_page_dpi(page_image_ids)
                else:
                    page_dpi = DEFAULT_DPI

                # Calculate page dimensions based on this page's DPI
                page_width = int(page_w_in * page_dpi)
                page_height = int(page_h_in * page_dpi)
                print(f"📐 Page {page.pageNumber}: Using {page_dpi} DPI ({page_width}x{page_height} px)")

                buffer = await render_page(
                    page,
                    page_width,
                    page_height,
                    self.layouts_by_id,
                    album,
                    self.enhanced_manager if use_enhanced else None,
                    icc_profile=icc_profile,
                    dpi=page_dpi
                )

                # Save rendered page
                page_filename = f"page_{page.pageNumber:02d}.jpg"
                page_path = output_path / page_filename

                with open(page_path, "wb") as f:
                    f.write(buffer)

                rendered_pages.append(RenderedPage(
                    pageNumber=page.pageNumber,
                    pageType=page.pageType,
                    buffer=buffer
                ))

                print(f"✅ Rendered page {page.pageNumber}")

            except Exception as e:
                print(f"❌ Failed to render page {page.pageNumber}: {e}")
                continue

        return rendered_pages
    
    async def render_album_from_files(
        self,
        album_file: Union[str, Path],
        page_size: str,
        output_dir: Union[str, Path],
        enhanced_dir: Optional[Union[str, Path]] = None,
        auto_enhance: bool = True
    ) -> Dict[str, Any]:
        """Render album from album_order.json file."""
        
        # Load album data
        with open(album_file, 'r') as f:
            album_data = json.load(f)
        
        # Auto-generate enhanced images if requested and not provided
        if auto_enhance and not enhanced_dir:
            print("🔄 Generating enhanced images...")
            enhanced_dir = self.generate_and_use_enhanced_images(
                album_file=album_file,
                page_size=page_size,
                enhanced_output_dir=Path(output_dir) / "enhanced"
            )
            print(f"✅ Enhanced images generated in: {enhanced_dir}")
        elif enhanced_dir:
            self.enhanced_manager = EnhancedImageManager(Path(enhanced_dir))
        
        # Render pages
        print("🎨 Rendering album pages...")
        rendered_pages = await self.render_album_pages(
            album_data=album_data,
            page_size=page_size,
            output_dir=output_dir,
            use_enhanced=bool(enhanced_dir)
        )
        
        return {
            "success": True,
            "total_pages": len(rendered_pages),
            "output_dir": str(output_dir),
            "enhanced_dir": str(enhanced_dir) if enhanced_dir else None,
            "pages": [
                {
                    "pageNumber": p.pageNumber,
                    "pageType": p.pageType,
                    "filename": f"page_{p.pageNumber:02d}.jpg"
                }
                for p in rendered_pages
            ]
        }

    async def render_album_with_dimensions(
        self,
        album_data: Dict[str, Any],
        dimensions: Dict[str, float],
        output_dir: Union[str, Path],
        auto_enhance: bool = True
    ) -> Dict[str, Any]:
        """
        Render album with different dimensions for cover vs content pages.

        Args:
            album_data: Album data dict with pages and project_images
            dimensions: Dict with inner_width, inner_height, cover_width, cover_height (in inches)
            output_dir: Output directory for rendered pages
            auto_enhance: Whether to auto-generate enhanced images

        Returns:
            Dict with success status, page count, and page details
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Auto-enhance if requested (do this first to build DPI cache)
        if auto_enhance:
            print("🔄 Generating enhanced images...")
            enhanced_dir = await self._enhance_with_dimensions(
                album_data, dimensions, output_path / "enhanced"
            )
            self.enhanced_manager = EnhancedImageManager(enhanced_dir)
            print(f"✅ Enhanced images generated in: {enhanced_dir}")

        # Store dimension inches for per-page DPI calculation
        inner_w_in = dimensions.get("inner_width", 9.0)
        inner_h_in = dimensions.get("inner_height", 9.0)
        cover_w_in = dimensions.get("cover_width", 10.0)
        cover_h_in = dimensions.get("cover_height", 10.0)

        # Convert data to structured format (supports both old and new API structures)
        data = album_data.get("data", album_data)
        album_images = [
            AlbumImage(
                imageId=img.get("imageId", ""),
                image=img.get("image"),
                imageUrl=img.get("imageUrl")  # New structure has direct imageUrl
            )
            for img in data.get("project_images", [])
        ]

        album_pages = [
            AlbumPage(
                pageNumber=page.get("pageNumber", 0),
                pageType=page.get("pageType"),
                layoutId=page.get("layoutId"),
                backgroundColor=page.get("backgroundColor"),
                backgroundImageUrl=page.get("backgroundImageUrl"),
                backgroundImage=page.get("backgroundImage"),
                backgroundImageId=page.get("backgroundImageId"),
                elements=page.get("elements"),
                textElements=page.get("textElements"),
                backCoverLogoUrl=page.get("backCoverLogoUrl")
            )
            for page in data.get("pages", [])
        ]

        album = AlbumData(pages=album_pages, project_images=album_images)

        rendered_pages = []
        print("🎨 Rendering album pages...")

        # Get ICC profile from enhanced images to preserve color vibrancy
        icc_profile = self.enhanced_manager.get_icc_profile() if self.enhanced_manager else None

        for page in album.pages:
            try:
                # Calculate per-page DPI based on images on this page
                if self.enhanced_manager:
                    page_image_ids = get_page_image_ids(page, self.layouts_by_id)
                    page_dpi = self.enhanced_manager.get_page_dpi(page_image_ids)
                else:
                    page_dpi = DEFAULT_DPI

                # Determine dimensions based on page type, using per-page DPI
                if page.pageType in ("cover-front", "cover-back"):
                    page_width = int(cover_w_in * page_dpi)
                    page_height = int(cover_h_in * page_dpi)
                    page_type_label = "cover"
                else:
                    page_width = int(inner_w_in * page_dpi)
                    page_height = int(inner_h_in * page_dpi)
                    page_type_label = "inner"

                print(f"📐 Page {page.pageNumber}: Using {page_dpi} DPI ({page_width}x{page_height} px, {page_type_label})")

                # Render page
                buffer = await render_page(
                    page,
                    page_width,
                    page_height,
                    self.layouts_by_id,
                    album,
                    self.enhanced_manager,
                    icc_profile=icc_profile,
                    dpi=page_dpi
                )

                # Save rendered page
                page_filename = f"page_{page.pageNumber:02d}.jpg"
                page_path = output_path / page_filename

                with open(page_path, "wb") as f:
                    f.write(buffer)

                rendered_pages.append({
                    "pageNumber": page.pageNumber,
                    "pageType": page.pageType,
                    "filename": page_filename,
                    "width_px": page_width,
                    "height_px": page_height,
                    "size_type": page_type_label,
                    "dpi": page_dpi
                })

                print(f"✅ Rendered page {page.pageNumber} ({page_type_label}: {page_width}x{page_height})")

            except Exception as e:
                print(f"❌ Failed to render page {page.pageNumber}: {e}")
                continue

        return {
            "success": True,
            "total_pages": len(rendered_pages),
            "output_dir": str(output_path),
            "enhanced_dir": str(output_path / "enhanced") if auto_enhance else None,
            "dimensions": dimensions,
            "pages": rendered_pages
        }

    async def _enhance_with_dimensions(
        self,
        album_data: Dict[str, Any],
        dimensions: Dict[str, float],
        enhanced_output_dir: Union[str, Path]
    ) -> Path:
        """
        Generate enhanced images using dimension-aware specs.

        Args:
            album_data: Album data dict
            dimensions: Dict with inner/cover width/height
            enhanced_output_dir: Output directory for enhanced images

        Returns:
            Path to enhanced images directory
        """
        enhanced_dir = Path(enhanced_output_dir)
        enhanced_dir.mkdir(parents=True, exist_ok=True)

        # Load layouts
        layouts_file = Path(__file__).parent / "layouts.json"
        with open(layouts_file, 'r') as f:
            layouts_data = json.load(f)

        # Generate specs with dimension awareness
        spec_generator = SpecGenerator()
        specs = spec_generator.generate_from_album_data_with_dimensions(
            album_data, dimensions, layouts_data
        )

        if not specs:
            print("⚠️ No enhancement specs generated")
            return enhanced_dir

        print(f"📋 Generated {len(specs)} enhancement specs")

        # Process images using ImageProcessor
        processor = ImageProcessor()
        results = processor.enhance_images_from_specs(specs, enhanced_dir, images_dir=None)

        successful = sum(1 for r in results if r.success)
        print(f"✅ Enhanced {successful}/{len(specs)} images")

        return enhanced_dir


# =========================
# COMMAND LINE INTERFACE
# =========================

if __name__ == "__main__":
    import argparse
    import asyncio
    
    parser = argparse.ArgumentParser(description="Render photobook album with enhanced images")
    parser.add_argument("--album", required=True, help="Path to album_order.json")
    parser.add_argument("--page-size", required=True, help="Page size like 9x9 or 12x14")
    parser.add_argument("--output-dir", required=True, help="Output directory for rendered pages")
    parser.add_argument("--enhanced-dir", help="Directory with enhanced images (optional)")
    parser.add_argument("--layouts", help="Path to layouts.json (optional)")
    parser.add_argument("--auto-enhance", action="store_true", default=True, help="Auto-generate enhanced images")
    parser.add_argument("--no-enhance", action="store_true", help="Skip enhancement, use original images")
    
    args = parser.parse_args()
    
    async def main():
        renderer = AlbumRenderer(
            layouts_path=Path(args.layouts) if args.layouts else None
        )
        
        result = await renderer.render_album_from_files(
            album_file=args.album,
            page_size=args.page_size,
            output_dir=args.output_dir,
            enhanced_dir=args.enhanced_dir,
            auto_enhance=args.auto_enhance and not args.no_enhance
        )
        
        print(f"\n🎉 Album rendering complete!")
        print(f"📁 Output: {result['output_dir']}")
        print(f"📄 Rendered: {result['total_pages']} pages")
        if result.get('enhanced_dir'):
            print(f"✨ Enhanced images: {result['enhanced_dir']}")
    
    asyncio.run(main())