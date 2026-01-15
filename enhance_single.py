#!/usr/bin/env python3
"""
enhance_single.py

Purpose:
  Enhance a single image for print using the existing print_enhancer.py logic.
  Accepts an image URL and the desired print short-side in inches, constructs the
  EnhanceConfig, and returns a PIL Image object (via the callable function) along
  with metadata. The CLI can optionally write the enhanced image to disk.

CLI:
  python image-enhancer/enhance_single.py \
    --image-url https://.../image.jpg \
    --page 9x9 \
    --print-inches-short-side 5.4 \
    --primary-dpi 300 \
    --fallback-dpi 240 \
    --jpeg-quality 95 \
    --out enhanced.jpg

Batch mode (jobs.json):
  python image-enhancer/enhance_single.py \
    --jobs /path/to/jobs.json \
    --out-dir image-enhanced \
    --primary-dpi 300 \
    --fallback-dpi 240 \
    --jpeg-quality 95

Notes:
  - Page size is accepted for future use/logging; the core enhancer only needs
    print_inches_short_side to compute the short-side target in pixels at the chosen DPI.
  - The callable function `enhance_single_image` returns (PIL.Image, chosen_dpi:int, meta:dict).
"""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
from typing import Tuple, Dict, Any, List
from urllib.request import urlopen, Request

from PIL import Image

# Local import from the same folder
from print_enhancer import EnhanceConfig, enhance_one, save_with_metadata


def fetch_image_bytes(url: str, timeout: int = 20) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def enhance_single_image(
    image_url: str,
    print_inches_short_side: float,
    primary_dpi: int = 300,
    fallback_dpi: int = 240,
    jpeg_quality: int = 95,
    upscale_small: bool = True,
    downscale_large: bool = True,
    set_dpi_metadata: bool = True,
    denoise_h: int = 3,
    denoise_h_color: int = 3,
    unsharp_amount_base: float = 0.55,
    unsharp_sigma: float = 1.2,
    enable_clahe: bool = False,
    clahe_clip: float = 2.0,
    clahe_grid: int = 8,
) -> Tuple[Image.Image, int, Dict[str, Any]]:
    """
    Enhance a single image given its URL and the target print short side in inches.
    Returns:
      - enhanced PIL Image
      - chosen_dpi (int)
      - meta (dict) returned by enhance_one
    """
    raw = fetch_image_bytes(image_url)
    with Image.open(io.BytesIO(raw)) as pil_img:
        icc_profile = pil_img.info.get("icc_profile", None)
        cfg = EnhanceConfig(
            print_inches_short_side=float(print_inches_short_side),
            primary_dpi=int(primary_dpi),
            fallback_dpi=int(fallback_dpi),
            jpeg_quality=int(jpeg_quality),
            upscale_small=bool(upscale_small),
            downscale_large=bool(downscale_large),
            set_dpi_metadata=bool(set_dpi_metadata),
            denoise_h=int(denoise_h),
            denoise_h_color=int(denoise_h_color),
            unsharp_amount_base=float(unsharp_amount_base),
            unsharp_sigma=float(unsharp_sigma),
            enable_clahe=bool(enable_clahe),
            clahe_clip=float(clahe_clip),
            clahe_grid=int(clahe_grid),
        )
        out_pil, chosen_dpi, meta = enhance_one(pil_img, icc_profile, cfg)
        return out_pil, chosen_dpi, meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Enhance a single image for print.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image-url", help="Source image URL")
    group.add_argument("--jobs", help="Path to jobs.json for batch processing")
    parser.add_argument("--page", help="Page size in inches, e.g., 9x9 (kept for logging)")
    parser.add_argument("--print-inches-short-side", type=float, help="Target short side in inches (single mode)")
    parser.add_argument("--primary-dpi", type=int, default=300)
    parser.add_argument("--fallback-dpi", type=int, default=240)
    parser.add_argument("--jpeg-quality", type=int, default=95)
    parser.add_argument("--out", help="Output path to save enhanced image (single mode)")
    parser.add_argument("--out-dir", help="Directory to save enhanced images (batch mode)", default="enhanced_out")
    parser.add_argument("--meta-out", help="Optional path to write enhancement metadata JSON")
    args = parser.parse_args()

    # Single-image mode
    if args.image_url:
        if args.print_inches_short_side is None:
            raise SystemExit("--print-inches-short-side is required in single-image mode")
        img, chosen_dpi, meta = enhance_single_image(
            image_url=args.image_url,
            print_inches_short_side=args.print_inches_short_side,
            primary_dpi=args.primary_dpi,
            fallback_dpi=args.fallback_dpi,
            jpeg_quality=args.jpeg_quality,
        )

        if args.out:
            # Save with metadata similar to batch flow
            icc_profile = img.info.get("icc_profile", None)
            cfg = EnhanceConfig(
                print_inches_short_side=float(args.print_inches_short_side),
                primary_dpi=int(args.primary_dpi),
                fallback_dpi=int(args.fallback_dpi),
                jpeg_quality=int(args.jpeg_quality),
            )
            save_with_metadata(img, Path(args.out), chosen_dpi, cfg, icc_profile)
            print(args.out)
        else:
            # If no output path provided, at least dump meta to stdout
            print(json.dumps({"chosen_dpi": chosen_dpi, "meta": meta}, ensure_ascii=False))

        if args.meta_out:
            with open(args.meta_out, "w", encoding="utf-8") as f:
                json.dump({"chosen_dpi": chosen_dpi, "meta": meta}, f, ensure_ascii=False, indent=2)
        return

    # Batch mode from jobs.json
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.jobs, "r", encoding="utf-8") as f:
        jobs: List[Dict[str, Any]] = json.load(f)

    results_meta: List[Dict[str, Any]] = []
    for idx, job in enumerate(jobs, start=1):
        image_url = job.get("imageUrl")
        short_in = job.get("print_inches_short_side")
        image_id = job.get("imageId", f"job{idx}")
        page_no = job.get("pageNo", -1)

        if not image_url or not short_in:
            # Skip invalid entries
            continue

        img, chosen_dpi, meta = enhance_single_image(
            image_url=image_url,
            print_inches_short_side=float(short_in),
            primary_dpi=args.primary_dpi,
            fallback_dpi=args.fallback_dpi,
            jpeg_quality=args.jpeg_quality,
        )

        # Save a debug filename that includes index, page and imageId
        safe_id = "".join(c for c in image_id if c.isalnum() or c in ("-", "_"))
        fname = f"{idx:03d}_p{page_no}_{safe_id}.jpg"
        out_path = out_dir / fname

        icc_profile = img.info.get("icc_profile", None)
        cfg = EnhanceConfig(
            print_inches_short_side=float(short_in),
            primary_dpi=int(args.primary_dpi),
            fallback_dpi=int(args.fallback_dpi),
            jpeg_quality=int(args.jpeg_quality),
        )
        save_with_metadata(img, out_path, chosen_dpi, cfg, icc_profile)

        results_meta.append({
            "index": idx,
            "pageNo": page_no,
            "imageId": image_id,
            "imageUrl": image_url,
            "out": str(out_path),
            "chosen_dpi": chosen_dpi,
            "meta": meta,
        })

    # Print a small summary to stdout
    print(json.dumps({
        "saved": len(results_meta),
        "outDir": str(out_dir),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()


