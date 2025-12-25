#!/usr/bin/env python3
"""
generate_jobs.py

Purpose:
  Read an album JSON (as exported in image-enhancer/album_order.json) and the design layouts
  (src/layouts.json), and compute per-image print_inches_short_side using the "short side" method,
  with crop-aware adjustments.

Inputs:
  - --album <path>   : Path to album_order.json
  - --layouts <path> : Path to src/layouts.json
  - --page <WxH>     : Page size in inches, e.g. 9x9 or 12x14
  - --dpi <int>      : Target DPI (optional, informational only; default 300)

Output:
  Prints a JSON array to stdout:
    [
      { "imageId": "<uuid>", "print_inches_short_side": <float> },
      ...
    ]

Notes:
  - If an image appears multiple times across pages/zones, we take the maximum required short-side inches.
  - Crop handling:
      If an element has transform.crop with width/height as percentages (0..100), we scale the required
      short-side inches by (fullShortPx / cropShortPx), so the cropped region receives enough upscaling.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, Tuple, Optional


def parse_page_inches(spec: str) -> Tuple[float, float]:
    """
    Parse page size like '9x9' or '12x14' into (widthIn, heightIn).
    """
    spec = spec.lower().replace(" ", "")
    if "x" not in spec:
        raise ValueError(f"Invalid page spec '{spec}', expected format WxH in inches (e.g., 9x9)")
    w_str, h_str = spec.split("x", 1)
    try:
        return float(w_str), float(h_str)
    except ValueError:
        raise ValueError(f"Invalid page numbers in '{spec}'")


def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_image_dimensions(album: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Build imageId -> {width:int, height:int, url:str|None} mapping
    from album['data']['project_images'].
    """
    mapping: Dict[str, Dict[str, Any]] = {}
    data = album.get("data") or {}
    for item in data.get("project_images", []) or []:
        image_id = item.get("imageId")
        img = item.get("image") or {}
        w = img.get("width")
        h = img.get("height")
        url: Optional[str] = img.get("url") or img.get("storagePath")
        if image_id and isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            mapping[image_id] = {"width": w, "height": h, "url": url}
    return mapping


def build_layouts_by_id(layouts: Any) -> Dict[str, Any]:
    """
    Build layoutId -> layout from layouts array in src/layouts.json.
    """
    layouts_by_id: Dict[str, Any] = {}
    if isinstance(layouts, list):
        for layout in layouts:
            lid = layout.get("id")
            if isinstance(lid, str):
                layouts_by_id[lid] = layout
    return layouts_by_id


def find_zone(layout: Dict[str, Any], zone_id: str) -> Dict[str, Any] | None:
    for z in layout.get("zones", []) or []:
        if z.get("id") == zone_id:
            return z
    return None


def compute_zone_short_inches(zone: Dict[str, Any], page_w_in: float, page_h_in: float) -> float:
    """
    Convert zone percentage size to inches and return the short side in inches.
    """
    size = zone.get("size") or {}
    w_pct = float(size.get("width", 0.0))
    h_pct = float(size.get("height", 0.0))
    zone_w_in = page_w_in * (w_pct / 100.0)
    zone_h_in = page_h_in * (h_pct / 100.0)
    return min(zone_w_in, zone_h_in)


def crop_short_side_pixels(crop: Dict[str, Any], img_w: int, img_h: int) -> float | None:
    """
    Compute the cropped region short side length (in pixels) given crop percentages and image size.
    Expects crop = { x, y, width, height } in percentages (0..100).
    Returns None if crop is invalid.
    """
    try:
        cw_pct = float(crop.get("width", 0.0))
        ch_pct = float(crop.get("height", 0.0))
        if cw_pct <= 0.0 or ch_pct <= 0.0:
            return None
        crop_w_px = max(1.0, img_w * (cw_pct / 100.0))
        crop_h_px = max(1.0, img_h * (ch_pct / 100.0))
        return min(crop_w_px, crop_h_px)
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate enhancement jobs from album and layouts.")
    parser.add_argument("--album", required=True, help="Path to album_order.json")
    parser.add_argument("--layouts", required=True, help="Path to src/layouts.json")
    parser.add_argument("--page", required=True, help="Page size in inches, e.g., 9x9 or 12x14")
    parser.add_argument("--dpi", type=int, default=300, help="Target DPI (informational)")
    args = parser.parse_args()

    album = load_json(Path(args.album))
    layouts = load_json(Path(args.layouts))
    page_w_in, page_h_in = parse_page_inches(args.page)

    layouts_by_id = build_layouts_by_id(layouts)
    image_dims = build_image_dimensions(album)

    # Accumulate max required short-side inches per imageId across all usages
    # Track max required inches and the pageNo where it occurred
    required_in_by_image: Dict[str, Tuple[float, int]] = {}

    data = album.get("data") or {}
    for page in data.get("pages", []) or []:
        layout_id = page.get("layoutId")
        if not layout_id:
            continue
        layout = layouts_by_id.get(layout_id)
        if not layout:
            continue

        elements = page.get("elements") or []
        page_no = int(page.get("pageNumber", -1))
        for elem in elements:
            image_id = elem.get("imageId")
            zone_id = elem.get("zoneId")
            if not image_id or not zone_id:
                continue
            zone = find_zone(layout, zone_id)
            if not zone:
                continue

            base_short_in = compute_zone_short_inches(zone, page_w_in, page_h_in)
            if base_short_in <= 0.0:
                continue

            # Crop-aware adjustment (if applicable)
            adjusted_short_in = base_short_in

            transform = elem.get("transform") or {}
            crop = transform.get("crop")
            img_info = image_dims.get(image_id)
            if crop and img_info:
                img_w = int(img_info["width"])
                img_h = int(img_info["height"])
                crop_short_px = crop_short_side_pixels(crop, img_w, img_h)
                if crop_short_px and crop_short_px > 0:
                    full_short_px = float(min(img_w, img_h))
                    # Scale inches so that the cropped region receives enough upscaling
                    factor = max(1.0, full_short_px / crop_short_px)
                    adjusted_short_in = base_short_in * factor

            prev = required_in_by_image.get(image_id, (0.0, -1))
            if adjusted_short_in > prev[0]:
                required_in_by_image[image_id] = (adjusted_short_in, page_no)

    # Emit array of jobs
    jobs = []
    for img_id in sorted(required_in_by_image.keys()):
        inches, page_no = required_in_by_image[img_id]
        img_info = image_dims.get(img_id) or {}
        jobs.append({
            "imageId": img_id,
            "pageNo": page_no,
            "print_inches_short_side": round(inches, 4),
            "imageUrl": img_info.get("url"),
        })
    json.dump(jobs, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()


