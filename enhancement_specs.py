#!/usr/bin/env python3
"""
enhancement_specs.py

Data structures and utilities for managing image enhancement specifications.
"""

from __future__ import annotations

import io
import json
import tempfile
import requests
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, asdict
from PIL import Image, ImageOps


@dataclass
class EnhancementSpec:
    """Specification for enhancing a single image."""
    imageId: str
    pageNo: int
    print_inches_short_side: float
    imageUrl: Optional[str] = None


@dataclass
class EnhancementResult:
    """Result of processing an enhancement specification."""
    imageId: str
    pageNo: int
    success: bool
    output_path: Optional[str] = None
    error_message: Optional[str] = None
    chosen_dpi: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


def fetch_image_dimensions(url: str, timeout: int = 20) -> Tuple[int, int]:
    """
    Fetch image dimensions from URL by loading the image.

    Args:
        url: Image URL to fetch
        timeout: Request timeout in seconds

    Returns:
        Tuple of (width, height) in pixels

    Raises:
        ValueError: If URL is invalid or image cannot be loaded
    """
    if not url or not isinstance(url, str):
        raise ValueError("Missing image URL for dimension fetch")

    headers = {"User-Agent": "Mozilla/5.0 (compatible; AlbumRenderer/1.0)"}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()

    img = Image.open(io.BytesIO(response.content))

    # Apply EXIF orientation correction to get correct dimensions
    try:
        img = ImageOps.exif_transpose(img)
    except (AttributeError, OSError, TypeError):
        pass

    return img.width, img.height


class SpecGenerator:
    """Generates enhancement specifications from album and layout data."""

    def __init__(self):
        # Cache for fetched image dimensions to avoid repeated requests
        self._dimension_cache: Dict[str, Tuple[int, int]] = {}

    def _get_cached_dimensions(self, url: str) -> Optional[Tuple[int, int]]:
        """Get dimensions from cache or fetch and cache them."""
        if url in self._dimension_cache:
            return self._dimension_cache[url]

        try:
            dims = fetch_image_dimensions(url)
            self._dimension_cache[url] = dims
            return dims
        except Exception as e:
            print(f"⚠️ Failed to fetch dimensions for {url}: {e}")
            return None

    def parse_page_size(self, spec: str) -> Tuple[float, float]:
        """Parse page size like '9x9' or '12x14' into (width, height)."""
        spec = spec.lower().replace(" ", "")
        if "x" not in spec:
            raise ValueError(f"Invalid page spec '{spec}', expected format WxH (e.g., 9x9)")
        w_str, h_str = spec.split("x", 1)
        try:
            return float(w_str), float(h_str)
        except ValueError:
            raise ValueError(f"Invalid page numbers in '{spec}'")
    
    def build_image_dimensions(self, album: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Extract image dimensions from album data.

        Handles both old structure (with image.width/height) and new structure
        (where dimensions need to be fetched from imageUrl).
        """
        mapping = {}
        data = album.get("data", {})
        for item in data.get("project_images", []):
            image_id = item.get("imageId")

            # Try old structure first (nested image object)
            img = item.get("image", {})
            w, h = img.get("width"), img.get("height")
            url = img.get("url") or img.get("storagePath")

            # Try new structure (direct imageUrl field)
            if not url:
                url = item.get("imageUrl")

            if not image_id or not url:
                continue

            # If we have valid dimensions, use them
            if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
                mapping[image_id] = {"width": w, "height": h, "url": url}
            else:
                # Fetch dimensions from URL
                dims = self._get_cached_dimensions(url)
                if dims:
                    w, h = dims
                    mapping[image_id] = {"width": w, "height": h, "url": url}
                    print(f"📐 Fetched dimensions for {image_id}: {w}x{h}")
                else:
                    # Still add the URL so we can try to process the image
                    mapping[image_id] = {"width": None, "height": None, "url": url}

        return mapping
    
    def build_layouts_by_id(self, layouts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Build layout lookup by ID."""
        return {layout["id"]: layout for layout in layouts if "id" in layout}
    
    def find_zone(self, layout: Dict[str, Any], zone_id: str) -> Optional[Dict[str, Any]]:
        """Find zone in layout by ID."""
        for zone in layout.get("zones", []):
            if zone.get("id") == zone_id:
                return zone
        return None
    
    def compute_zone_short_inches(self, zone: Dict[str, Any], page_w: float, page_h: float) -> float:
        """Calculate zone short side in inches."""
        size = zone.get("size", {})
        w_pct = float(size.get("width", 0))
        h_pct = float(size.get("height", 0))
        zone_w_in = page_w * (w_pct / 100.0)
        zone_h_in = page_h * (h_pct / 100.0)
        return min(zone_w_in, zone_h_in)
    
    def apply_crop_adjustment(self, base_inches: float, crop: Dict[str, Any], img_w: int, img_h: int) -> float:
        """Apply crop-aware adjustment to required inches."""
        try:
            cw_pct = float(crop.get("width", 0))
            ch_pct = float(crop.get("height", 0))
            if cw_pct <= 0 or ch_pct <= 0:
                return base_inches
            
            crop_w_px = max(1, img_w * (cw_pct / 100.0))
            crop_h_px = max(1, img_h * (ch_pct / 100.0))
            crop_short_px = min(crop_w_px, crop_h_px)
            full_short_px = min(img_w, img_h)
            
            factor = max(1.0, full_short_px / crop_short_px)
            return base_inches * factor
        except Exception:
            return base_inches
    
    def generate_from_album_data(
        self, 
        album_data: Dict[str, Any], 
        layouts_data: List[Dict[str, Any]], 
        page_size: str
    ) -> List[EnhancementSpec]:
        """Generate enhancement specs from album and layout data."""
        page_w, page_h = self.parse_page_size(page_size)
        layouts_by_id = self.build_layouts_by_id(layouts_data)
        image_dims = self.build_image_dimensions(album_data)
        
        # Track max required inches per image
        required_by_image: Dict[str, Tuple[float, int, str]] = {}  # imageId -> (inches, pageNo, url)
        
        data = album_data.get("data", {})
        for page in data.get("pages", []):
            layout_id = page.get("layoutId")
            if not layout_id or layout_id not in layouts_by_id:
                continue
            
            layout = layouts_by_id[layout_id]
            page_no = int(page.get("pageNumber", -1))
            
            for elem in page.get("elements", []):
                image_id = elem.get("imageId")
                zone_id = elem.get("zoneId")
                if not image_id or not zone_id:
                    continue
                
                zone = self.find_zone(layout, zone_id)
                if not zone:
                    continue
                
                base_short_in = self.compute_zone_short_inches(zone, page_w, page_h)
                if base_short_in <= 0:
                    continue
                
                # Apply crop adjustment if needed
                adjusted_short_in = base_short_in
                transform = elem.get("transform", {})
                crop = transform.get("crop")
                img_info = image_dims.get(image_id)

                # Only apply crop adjustment if we have valid dimensions
                if crop and img_info and img_info.get("width") and img_info.get("height"):
                    adjusted_short_in = self.apply_crop_adjustment(
                        base_short_in, crop, img_info["width"], img_info["height"]
                    )

                # Track maximum requirement
                current = required_by_image.get(image_id, (0.0, -1, None))
                if adjusted_short_in > current[0]:
                    url = img_info.get("url") if img_info else None
                    required_by_image[image_id] = (adjusted_short_in, page_no, url)
        
        # Convert to specs
        specs = []
        for img_id in sorted(required_by_image.keys()):
            inches, page_no, url = required_by_image[img_id]
            specs.append(EnhancementSpec(
                imageId=img_id,
                pageNo=page_no,
                print_inches_short_side=round(inches, 4),
                imageUrl=url
            ))
        
        return specs
    
    def generate_from_album_data_with_dimensions(
        self,
        album_data: Dict[str, Any],
        dimensions: Dict[str, float],
        layouts_data: List[Dict[str, Any]]
    ) -> List[EnhancementSpec]:
        """
        Generate enhancement specs using different dimensions for cover vs content pages.

        Args:
            album_data: Album data dict
            dimensions: Dict with inner_width, inner_height, cover_width, cover_height
            layouts_data: List of layout definitions

        Returns:
            List of EnhancementSpec with proper print_inches_short_side per page type
        """
        layouts_by_id = self.build_layouts_by_id(layouts_data)
        image_dims = self.build_image_dimensions(album_data)

        # Track max required inches per image
        required_by_image: Dict[str, Tuple[float, int, str]] = {}

        data = album_data.get("data", {})
        for page in data.get("pages", []):
            layout_id = page.get("layoutId")
            if not layout_id or layout_id not in layouts_by_id:
                continue

            layout = layouts_by_id[layout_id]
            page_no = int(page.get("pageNumber", -1))
            page_type = page.get("pageType", "content")

            # Determine page dimensions based on type
            if page_type in ("cover-front", "cover-back"):
                page_w = dimensions.get("cover_width", 10.0)
                page_h = dimensions.get("cover_height", 10.0)
            else:
                page_w = dimensions.get("inner_width", 9.0)
                page_h = dimensions.get("inner_height", 9.0)

            for elem in page.get("elements", []):
                image_id = elem.get("imageId")
                zone_id = elem.get("zoneId")
                if not image_id or not zone_id:
                    continue

                zone = self.find_zone(layout, zone_id)
                if not zone:
                    continue

                base_short_in = self.compute_zone_short_inches(zone, page_w, page_h)
                if base_short_in <= 0:
                    continue

                # Apply crop adjustment if needed
                adjusted_short_in = base_short_in
                transform = elem.get("transform", {})
                crop = transform.get("crop")
                img_info = image_dims.get(image_id)

                # Only apply crop adjustment if we have valid dimensions
                if crop and img_info and img_info.get("width") and img_info.get("height"):
                    adjusted_short_in = self.apply_crop_adjustment(
                        base_short_in, crop, img_info["width"], img_info["height"]
                    )

                # Track maximum requirement
                current = required_by_image.get(image_id, (0.0, -1, None))
                if adjusted_short_in > current[0]:
                    url = img_info.get("url") if img_info else None
                    required_by_image[image_id] = (adjusted_short_in, page_no, url)

        # Convert to specs
        specs = []
        for img_id in sorted(required_by_image.keys()):
            inches, page_no, url = required_by_image[img_id]
            specs.append(EnhancementSpec(
                imageId=img_id,
                pageNo=page_no,
                print_inches_short_side=round(inches, 4),
                imageUrl=url
            ))

        return specs

    def generate_from_files(self, album_file: str | Path, page_size: str, layouts_file: Optional[str | Path] = None) -> List[EnhancementSpec]:
        """Generate enhancement specs from files."""
        with open(album_file, 'r') as f:
            album_data = json.load(f)
        
        # Use provided layouts file or default to layouts.json in same directory
        if layouts_file is None:
            layouts_file = Path(__file__).parent / "layouts.json"
        
        with open(layouts_file, 'r') as f:
            layouts_data = json.load(f)
        
        return self.generate_from_album_data(album_data, layouts_data, page_size)


def save_specs(specs: List[EnhancementSpec], file_path: str | Path) -> None:
    """Save enhancement specs to JSON file."""
    with open(file_path, 'w') as f:
        json.dump([asdict(spec) for spec in specs], f, indent=2)


def load_specs(file_path: str | Path) -> List[EnhancementSpec]:
    """Load enhancement specs from JSON file."""
    with open(file_path, 'r') as f:
        specs_data = json.load(f)
    return [EnhancementSpec(**spec) for spec in specs_data]


def validate_specs(specs_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate enhancement specs data format."""
    try:
        specs = [EnhancementSpec(**spec) for spec in specs_data]
        return {
            "valid": True,
            "spec_count": len(specs),
            "message": f"Successfully validated {len(specs)} enhancement specs"
        }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
            "message": "Enhancement spec validation failed"
        }


if __name__ == "__main__":
    # Example usage
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate enhancement specs from album")
    parser.add_argument("--album", required=True, help="Path to album_order.json")
    parser.add_argument("--page-size", required=True, help="Page size like 9x9 or 12x14")
    parser.add_argument("--output", default="enhancement_specs.json", help="Output file")
    parser.add_argument("--layouts", help="Optional path to layouts.json (defaults to ./layouts.json)")
    
    args = parser.parse_args()
    
    generator = SpecGenerator()
    specs = generator.generate_from_files(args.album, args.page_size, args.layouts)
    save_specs(specs, args.output)
    
    print(f"✅ Generated {len(specs)} enhancement specs")
    print(f"📄 Saved to: {args.output}")
    print(f"📐 Using layouts: {args.layouts or 'layouts.json (default)'}")