# print_enhancer_dynamic.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import csv
import os

import numpy as np
import cv2
from PIL import Image

Item = Dict[str, Any]
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


# ----------------------------- Config ---------------------------------

@dataclass
class EnhanceConfig:
    # Print targets
    primary_dpi: int = 300
    fallback_dpi: int = 240

    # Legacy compatibility field (used by enhance_one wrapper)
    print_inches_short_side: float = 9.0

    # Strict quality caps (your preference)
    max_upscale_300: float = 1.35   # set to 1.35 if you want even stricter
    max_upscale_240: float = 1.50

    # Warnings (does NOT block; only flags in report)
    warn_upscale_300: float = 1.25
    warn_upscale_240: float = 1.35

    # Standardization controls
    upscale_small: bool = True
    downscale_large: bool = True

    # Enhancements (kept close to OLD)
    denoise_h: int = 3
    denoise_h_color: int = 3

    enable_clahe: bool = False
    clahe_clip: float = 2.0
    clahe_grid: int = 8

    unsharp_amount_base: float = 0.55
    unsharp_sigma: float = 1.2

    # Output encoding
    jpeg_quality: int = 95
    set_dpi_metadata: bool = True

    # Layout mapping (short side inches)
    layout_to_short_in: Dict[str, float] = None

    def __post_init__(self):
        if self.layout_to_short_in is None:
            self.layout_to_short_in = {
                "9x9": 9.0,
                "8x12": 8.0,
                "12x18": 12.0,
                "10x10": 10.0,
            }


# ----------------------------- Helpers --------------------------------

def _sanitize_component(name: str) -> str:
    """Windows-safe path component."""
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad else c for c in (name or ""))
    out = out.strip().strip(".")
    return out or "NA"

def _norm_rel_path(p: str) -> str:
    p = (p or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if p.startswith("/"):
        p = p[1:]
    return p

def target_short_side_px(short_in: float, dpi: int) -> int:
    return int(round(float(short_in) * int(dpi)))

def compute_scale_to_target_short(w: int, h: int, target_short: int) -> Tuple[int, int, float]:
    short = min(w, h)
    if short <= 0 or target_short <= 0:
        return w, h, 1.0
    scale = float(target_short) / float(short)
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    return new_w, new_h, scale

def resize_keep_aspect(bgr: np.ndarray, new_w: int, new_h: int) -> np.ndarray:
    # INTER_AREA for downscale, INTER_CUBIC for upscale
    h, w = bgr.shape[:2]
    if new_w <= 0 or new_h <= 0:
        return bgr
    interp = cv2.INTER_CUBIC if (new_w > w or new_h > h) else cv2.INTER_AREA
    return cv2.resize(bgr, (new_w, new_h), interpolation=interp)

def mild_denoise(bgr: np.ndarray, h: int = 3, h_color: int = 3) -> np.ndarray:
    # Conservative denoise to avoid "plastic" look
    try:
        return cv2.fastNlMeansDenoisingColored(bgr, None, h, h_color, 7, 21)
    except Exception:
        return bgr

def apply_clahe_on_l_channel(bgr: np.ndarray, clip: float = 2.0, grid: int = 8) -> np.ndarray:
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=float(clip), tileGridSize=(int(grid), int(grid)))
    l2 = clahe.apply(l)
    merged = cv2.merge([l2, a, b])
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

def unsharp_mask(bgr: np.ndarray, amount: float = 0.55, sigma: float = 1.2) -> np.ndarray:
    if amount <= 0:
        return bgr
    blurred = cv2.GaussianBlur(bgr, (0, 0), float(sigma))
    # out = (1+amount)*orig - amount*blur
    out = cv2.addWeighted(bgr, 1.0 + float(amount), blurred, -float(amount), 0)
    return np.clip(out, 0, 255).astype(np.uint8)

def auto_sharpen_amount(base: float, upscale_factor: float) -> float:
    """
    Old logic: reduce sharpening as upscale increases (avoid halos/over-sharpen).
    """
    if upscale_factor <= 1.2: return base
    if upscale_factor <= 1.6: return base * 0.85
    if upscale_factor <= 2.2: return base * 0.70
    if upscale_factor <= 3.0: return base * 0.55
    return base * 0.45


# ----------------------------- DPI choice ------------------------------

def choose_dpi_for_target(short_px: int, target_short_in: float, cfg: EnhanceConfig) -> Tuple[int, float, float, str, bool]:
    """
    Returns:
      chosen_dpi (300/240/0),
      scale_300, scale_240,
      reason,
      too_small (True if exceeds both caps)
    """
    if short_px <= 0 or target_short_in <= 0:
        return 0, float("inf"), float("inf"), "Invalid short_px/target_short_in", True

    need_300 = target_short_side_px(target_short_in, cfg.primary_dpi)
    need_240 = target_short_side_px(target_short_in, cfg.fallback_dpi)

    scale_300 = float(need_300) / float(short_px)
    scale_240 = float(need_240) / float(short_px)

    if scale_300 <= cfg.max_upscale_300:
        reason = f"300 OK (need {need_300}px short; scale={scale_300:.2f} <= {cfg.max_upscale_300})"
        return cfg.primary_dpi, scale_300, scale_240, reason, False

    if scale_240 <= cfg.max_upscale_240:
        reason = f"240 chosen (300 too much: {scale_300:.2f} > {cfg.max_upscale_300}; 240 scale={scale_240:.2f} <= {cfg.max_upscale_240})"
        return cfg.fallback_dpi, scale_300, scale_240, reason, False

    reason = f"TOO_SMALL (300 scale={scale_300:.2f} > {cfg.max_upscale_300}; 240 scale={scale_240:.2f} > {cfg.max_upscale_240})"
    return 0, scale_300, scale_240, reason, True


# ----------------------------- Enhance core ----------------------------

def enhance_one_for_target(
    pil_img: Image.Image,
    icc_profile: Optional[bytes],
    target_short_in: float,
    cfg: EnhanceConfig,
) -> Tuple[Image.Image, int, Dict[str, Any]]:
    """
    Enhances and resizes according to target_short_in and strict DPI caps.

    If TOO_SMALL:
      - still enhances
      - does NOT resize
      - chosen_dpi = 0 (so downstream knows dpi wasn't achieved)
    """
    rgb = pil_img.convert("RGB")
    arr = np.array(rgb)
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    h, w = bgr.shape[:2]
    short_px = min(w, h)

    chosen_dpi, scale_300, scale_240, dpi_reason, too_small = choose_dpi_for_target(short_px, float(target_short_in), cfg)

    # enhance first (as OLD)
    out = mild_denoise(bgr, h=cfg.denoise_h, h_color=cfg.denoise_h_color)
    if cfg.enable_clahe:
        out = apply_clahe_on_l_channel(out, clip=cfg.clahe_clip, grid=cfg.clahe_grid)

    did_upscale = False
    did_downscale = False
    scale_for_chosen = 1.0

    if not too_small:
        target_short_px = target_short_side_px(float(target_short_in), int(chosen_dpi))
        new_w, new_h, scale_for_chosen = compute_scale_to_target_short(w, h, target_short_px)

        # Standardize to target
        if cfg.downscale_large and short_px > target_short_px:
            out = resize_keep_aspect(out, new_w, new_h)
            did_downscale = True
        elif cfg.upscale_small and short_px < target_short_px:
            out = resize_keep_aspect(out, new_w, new_h)
            did_upscale = True
        # else already at target-ish size

    sharpen_amt = auto_sharpen_amount(cfg.unsharp_amount_base, scale_for_chosen if (did_upscale or did_downscale) else 1.0)
    out = unsharp_mask(out, amount=sharpen_amt, sigma=cfg.unsharp_sigma)

    out_rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
    out_pil = Image.fromarray(out_rgb)

    warn_300 = (scale_300 > cfg.warn_upscale_300)
    warn_240 = (scale_240 > cfg.warn_upscale_240)

    meta = {
        "src_w": w, "src_h": h, "src_short": short_px,
        "target_short_in": float(target_short_in),
        "chosen_dpi": int(chosen_dpi),
        "scale_300": scale_300,
        "scale_240": scale_240,
        "warn_300": warn_300,
        "warn_240": warn_240,
        "too_small": bool(too_small),
        "did_upscale": bool(did_upscale),
        "did_downscale": bool(did_downscale),
        "dst_w": out.shape[1],
        "dst_h": out.shape[0],
        "scale_for_chosen": scale_for_chosen,
        "sharpen_amount": float(sharpen_amt),
        "icc_preserved": icc_profile is not None,
        "dpi_reason": dpi_reason,
    }
    return out_pil, int(chosen_dpi), meta


def enhance_one(
    pil_img: Image.Image,
    icc_profile: Optional[bytes],
    cfg: EnhanceConfig
) -> Tuple[Image.Image, int, Dict[str, Any]]:
    """
    Backward-compatible wrapper for enhance_one_for_target.

    Uses print_inches_short_side from config if present, otherwise defaults to 9.0.
    This allows existing code that calls enhance_one(pil_img, icc_profile, cfg) to
    continue working with the new target-based enhancement logic.
    """
    target_short_in = getattr(cfg, 'print_inches_short_side', 9.0)
    return enhance_one_for_target(pil_img, icc_profile, target_short_in, cfg)


def save_with_metadata(img: Image.Image, dst_path: Path, chosen_dpi: int, cfg: EnhanceConfig, icc_profile: Optional[bytes]) -> None:
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs = dict(quality=int(cfg.jpeg_quality), optimize=True, subsampling=0)
    # Only write DPI metadata if chosen_dpi is valid (300/240)
    if cfg.set_dpi_metadata and int(chosen_dpi) in (cfg.primary_dpi, cfg.fallback_dpi):
        kwargs["dpi"] = (int(chosen_dpi), int(chosen_dpi))
    if icc_profile:
        kwargs["icc_profile"] = icc_profile
    img.save(dst_path, **kwargs)


# ----------------------------- Input parsing ---------------------------

def _target_short_in_from_row(row: Dict[str, str], cfg: EnhanceConfig) -> Tuple[float, str]:
    """
    Derive (target_short_in, layout_key) from a row.
    Priority:
      1) target_short_in column
      2) slot_w_in + slot_h_in  (uses min as short side)
      3) layout column mapped via cfg.layout_to_short_in
      4) fallback = 9.0
    """
    # 1) explicit
    tsi = (row.get("target_short_in") or "").strip()
    if tsi:
        try:
            v = float(tsi)
            return v, f"SHORTIN_{int(round(v))}"
        except Exception:
            pass

    # 2) slot inches
    sw = (row.get("slot_w_in") or "").strip()
    sh = (row.get("slot_h_in") or "").strip()
    if sw and sh:
        try:
            w_in = float(sw)
            h_in = float(sh)
            v = float(min(w_in, h_in))
            return v, f"SLOT_{w_in:g}x{h_in:g}"
        except Exception:
            pass

    # 3) layout mapping
    layout = (row.get("layout") or row.get("layout_key") or "").strip()
    if layout:
        # allow multi layouts separated by | ; ,
        # caller should split earlier; here just map first token
        tok = layout.split("|")[0].split(";")[0].split(",")[0].strip()
        if tok:
            v = cfg.layout_to_short_in.get(tok)
            if v:
                return float(v), tok

    # 4) fallback
    return 9.0, "9x9"


def read_inputs_csv(csv_path: str | Path, input_root: str | Path, cfg: EnhanceConfig) -> List[Item]:
    """
    Expected columns (minimum):
      - path OR rel_path OR file_path
    Optional:
      - layout (e.g., 9x9)
      - target_short_in
      - slot_w_in, slot_h_in
      - placement_id (used in filename)
    """
    csv_path = Path(csv_path)
    input_root = Path(input_root).resolve()

    items: List[Item] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            # handle stray commas causing None keys
            row = {k: v for k, v in raw.items() if k is not None}
            p = (row.get("path") or row.get("rel_path") or row.get("file_path") or "").strip()
            if not p:
                continue
            rel = _norm_rel_path(p)
            full = (input_root / rel).resolve()

            target_short_in, layout_key = _target_short_in_from_row(row, cfg)

            placement_id = (row.get("placement_id") or row.get("slot_id") or "").strip()
            items.append({
                "src_path": str(full),
                "rel_path": rel,
                "layout_key": layout_key,
                "target_short_in": float(target_short_in),
                "placement_id": placement_id,
            })
    return items


# ----------------------------- Batch runners ---------------------------

def enhance_inputs(
    inputs: List[Item],
    output_root: str | Path,
    cfg: EnhanceConfig | None = None,
    group_by_layout: bool = True,
) -> Path:
    """
    Process explicit list of inputs, each item requires:
      src_path, rel_path, layout_key, target_short_in, placement_id (optional)
    """
    cfg = cfg or EnhanceConfig()
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    report_rows: List[Dict[str, Any]] = []

    for it in inputs:
        src_path = Path(it["src_path"])
        rel_path = it.get("rel_path") or src_path.name
        layout_key = _sanitize_component(it.get("layout_key") or "NA")
        target_short_in = float(it.get("target_short_in") or 9.0)
        placement_id = _sanitize_component(it.get("placement_id") or "")

        try:
            pil_img = Image.open(src_path)
            icc = pil_img.info.get("icc_profile", None)

            out_img, chosen_dpi, meta = enhance_one_for_target(pil_img, icc, target_short_in, cfg)

            if meta["too_small"]:
                dpi_folder = "TOO_SMALL"
            else:
                dpi_folder = f"DPI_{chosen_dpi}"

            subdir = layout_key if group_by_layout else "ALL"
            dst_dir = output_root / subdir / dpi_folder

            base_name = Path(rel_path).stem
            if placement_id:
                base_name = f"{base_name}__{placement_id}"
            dst_path = dst_dir / f"{_sanitize_component(base_name)}.jpg"

            save_with_metadata(out_img, dst_path, chosen_dpi, cfg, icc)

            report_rows.append({
                "src_path": str(src_path),
                "rel_path": rel_path,
                "layout_key": layout_key,
                "target_short_in": f"{target_short_in:.3g}",
                "chosen_dpi": chosen_dpi,
                "output_file": str(dst_path),
                **{
                    "src_w": meta["src_w"], "src_h": meta["src_h"], "src_short": meta["src_short"],
                    "dst_w": meta["dst_w"], "dst_h": meta["dst_h"],
                    "scale_300": f'{meta["scale_300"]:.3f}',
                    "scale_240": f'{meta["scale_240"]:.3f}',
                    "warn_300": meta["warn_300"],
                    "warn_240": meta["warn_240"],
                    "too_small": meta["too_small"],
                    "did_upscale": meta["did_upscale"],
                    "did_downscale": meta["did_downscale"],
                    "scale_for_chosen": f'{meta["scale_for_chosen"]:.3f}',
                    "sharpen_amount": f'{meta["sharpen_amount"]:.3f}',
                    "icc_preserved": meta["icc_preserved"],
                    "dpi_reason": meta["dpi_reason"],
                }
            })

        except Exception as e:
            report_rows.append({
                "src_path": str(src_path),
                "rel_path": rel_path,
                "layout_key": layout_key,
                "target_short_in": f"{target_short_in:.3g}",
                "chosen_dpi": "",
                "output_file": "",
                "error": f"{type(e).__name__}: {e}",
            })

    report_path = output_root / "print_enhance_report.csv"
    # Write report
    cols = sorted({k for r in report_rows for k in r.keys()})
    with report_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in report_rows:
            w.writerow(r)

    return report_path


def enhance_folder_fixed_target(
    input_dir: str | Path,
    output_root: str | Path,
    target_short_in: float = 9.0,
    layout_key: str = "9x9",
    cfg: EnhanceConfig | None = None,
) -> Path:
    """
    Backward-compatible behavior with ONE target for everything, but output is still grouped by layout/dpi.
    """
    cfg = cfg or EnhanceConfig()
    input_dir = Path(input_dir).resolve()

    inputs: List[Item] = []
    for p in input_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            rel = p.relative_to(input_dir).as_posix()
            inputs.append({
                "src_path": str(p),
                "rel_path": rel,
                "layout_key": layout_key,
                "target_short_in": float(target_short_in),
                "placement_id": "",
            })

    return enhance_inputs(inputs, output_root, cfg=cfg, group_by_layout=True)


def enhance_folder(
    input_dir: str | Path,
    output_dir: str | Path,
    cfg: EnhanceConfig | None = None,
) -> Path:
    """
    Backward-compatible wrapper expected by older callers.
    Uses ONE target for the whole folder:
      - cfg.print_inches_short_side if present, else 9.0
      - cfg.layout_key if present, else "9x9"
    """
    cfg = cfg or EnhanceConfig()

    target_short_in = float(getattr(cfg, "print_inches_short_side", 9.0))
    layout_key = str(getattr(cfg, "layout_key", "9x9"))

    return enhance_folder_fixed_target(
        input_dir=input_dir,
        output_root=output_dir,
        target_short_in=target_short_in,
        layout_key=layout_key,
        cfg=cfg,
    )

# ----------------------------- CLI ------------------------------------

def _build_arg_parser():
    import argparse
    ap = argparse.ArgumentParser(description="Print enhancer with per-image size + strict DPI caps.")
    ap.add_argument("--input-root", type=str, required=True, help="Root folder of images.")
    ap.add_argument("--output-root", type=str, required=True, help="Output root folder.")
    ap.add_argument("--csv", type=str, default="", help="Optional CSV listing files + dimensions. If omitted, uses folder mode.")

    # Folder-mode target
    ap.add_argument("--target-short-in", type=float, default=9.0, help="Folder-mode: target short side inches.")
    ap.add_argument("--layout-key", type=str, default="9x9", help="Folder-mode: layout key label for output grouping.")

    # Strict caps
    ap.add_argument("--max-300", type=float, default=1.40, help="Max upscale allowed to use 300 DPI.")
    ap.add_argument("--max-240", type=float, default=1.50, help="Max upscale allowed to use 240 DPI.")

    # Standardization
    ap.add_argument("--no-downscale", action="store_true", help="Disable downscaling large images to target pixels.")
    ap.add_argument("--no-upscale", action="store_true", help="Disable upscaling small images (still picks DPI; may mark TOO_SMALL).")

    # Enhancements
    ap.add_argument("--clahe", action="store_true", help="Enable CLAHE.")
    ap.add_argument("--jpeg-quality", type=int, default=95, help="JPEG quality (1-100).")

    return ap

def main():
    ap = _build_arg_parser()
    args = ap.parse_args()

    cfg = EnhanceConfig()
    cfg.max_upscale_300 = float(args.max_300)
    cfg.max_upscale_240 = float(args.max_240)
    cfg.downscale_large = not bool(args.no_downscale)
    cfg.upscale_small = not bool(args.no_upscale)
    cfg.enable_clahe = bool(args.clahe)
    cfg.jpeg_quality = int(args.jpeg_quality)

    input_root = Path(args.input_root).resolve()

    if args.csv:
        items = read_inputs_csv(args.csv, input_root, cfg)
        if not items:
            raise SystemExit("No valid rows found in CSV (need a path/rel_path/file_path column).")
        report = enhance_inputs(items, args.output_root, cfg=cfg, group_by_layout=True)
    else:
        report = enhance_folder_fixed_target(
            input_root,
            args.output_root,
            target_short_in=float(args.target_short_in),
            layout_key=str(args.layout_key),
            cfg=cfg,
        )

    print(f"Report written: {report}")

if __name__ == "__main__":
    main()
