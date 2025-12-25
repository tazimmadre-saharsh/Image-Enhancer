#!/usr/bin/env python3
"""
process_jobs.py

Purpose:
  Read a jobs.json produced by generate_jobs.py and process the jobs in batches,
  calling the single-image enhancement logic for each entry.

Usage:
  python image-enhancer/process_jobs.py \
    --jobs jobs.json \
    --batch-size 4 \
    --debug true \
    --out-dir output \
    --primary-dpi 300 \
    --fallback-dpi 240 \
    --jpeg-quality 95

Behavior:
  - In debug mode (default true), writes enhanced images into --out-dir and prints a summary.
  - If debug is false, it runs enhancements but does not upload to S3 (upload step to be added later).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image

from print_enhancer import EnhanceConfig, save_with_metadata
from enhance_single import enhance_single_image


def chunk(items: List[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
    size = max(1, int(size))
    return [items[i : i + size] for i in range(0, len(items), size)]


def process_batch(
    batch: List[Dict[str, Any]],
    out_dir: Path,
    primary_dpi: int,
    fallback_dpi: int,
    jpeg_quality: int,
    debug: bool,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for idx, job in enumerate(batch, start=1):
        image_url = job.get("imageUrl")
        short_in = job.get("print_inches_short_side")
        image_id = job.get("imageId") or f"job{idx}"
        page_no = job.get("pageNo", -1)

        if not image_url or not short_in:
            continue

        img, chosen_dpi, meta = enhance_single_image(
            image_url=image_url,
            print_inches_short_side=float(short_in),
            primary_dpi=primary_dpi,
            fallback_dpi=fallback_dpi,
            jpeg_quality=jpeg_quality,
        )

        out_path: str | None = None
        if debug:
            safe_id = "".join(c for c in image_id if c.isalnum() or c in ("-", "_"))
            filename = f"p{page_no}_{safe_id}.jpg"
            out_file = out_dir / filename

            icc_profile = img.info.get("icc_profile", None)
            cfg = EnhanceConfig(
                print_inches_short_side=float(short_in),
                primary_dpi=int(primary_dpi),
                fallback_dpi=int(fallback_dpi),
                jpeg_quality=int(jpeg_quality),
            )
            save_with_metadata(img, out_file, chosen_dpi, cfg, icc_profile)
            out_path = str(out_file)

        results.append({
            "imageId": image_id,
            "pageNo": page_no,
            "imageUrl": image_url,
            "chosen_dpi": chosen_dpi,
            "meta": meta,
            "out": out_path,
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Process enhancement jobs in batches.")
    parser.add_argument("--jobs", required=True, help="Path to jobs.json")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size")
    parser.add_argument("--debug", type=lambda v: str(v).lower() in ("1", "true", "yes"), default=True, help="If true, write outputs to folder instead of uploading")
    parser.add_argument("--out-dir", default="output", help="Output directory used in debug mode")
    parser.add_argument("--primary-dpi", type=int, default=300)
    parser.add_argument("--fallback-dpi", type=int, default=240)
    parser.add_argument("--jpeg-quality", type=int, default=95)
    args = parser.parse_args()

    jobs_path = Path(args.jobs)
    if not jobs_path.exists():
        raise FileNotFoundError(f"Jobs file not found: {jobs_path}")

    with jobs_path.open("r", encoding="utf-8") as f:
        jobs: List[Dict[str, Any]] = json.load(f)

    batches = chunk(jobs, args.batch_size)
    out_dir = Path(args.out_dir)
    all_results: List[Dict[str, Any]] = []
    for b in batches:
        results = process_batch(
            b,
            out_dir=out_dir,
            primary_dpi=args.primary_dpi,
            fallback_dpi=args.fallback_dpi,
            jpeg_quality=args.jpeg_quality,
            debug=args.debug,
        )
        all_results.extend(results)

    summary = {
        "totalJobs": len(jobs),
        "processed": len(all_results),
        "debug": args.debug,
        "outDir": str(out_dir) if args.debug else None,
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()


