# print_enhancer.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, List
import csv

import numpy as np
import cv2
from PIL import Image
from tqdm import tqdm

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png"}

@dataclass
class EnhanceConfig:
    print_inches_short_side: float = 9.0
    primary_dpi: int = 300
    fallback_dpi: int = 240
    max_upscale_factor_primary: float = 2.5
    warn_upscale_factor_fallback: float = 3.5
    upscale_if_needed: bool = True
    jpeg_quality: int = 95
    set_dpi_metadata: bool = True
    denoise_h: int = 3
    denoise_h_color: int = 3
    unsharp_amount_base: float = 0.60
    unsharp_sigma: float = 1.10
    enable_clahe: bool = False
    clahe_clip: float = 1.3
    clahe_grid: Tuple[int, int] = (8, 8)
    report_csv_name: str = "print_enhance_report.csv"

def target_short_side_px(print_inches: float, dpi: int) -> int:
    return int(round(print_inches * dpi))

def mild_denoise(bgr: np.ndarray, h: int, h_color: int) -> np.ndarray:
    return cv2.fastNlMeansDenoisingColored(
        bgr, None, h=h, hColor=h_color, templateWindowSize=7, searchWindowSize=21
    )

def apply_clahe_on_l_channel(bgr: np.ndarray, clip: float, grid: Tuple[int, int]) -> np.ndarray:
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=grid)
    l2 = clahe.apply(l)
    lab2 = cv2.merge((l2, a, b))
    return cv2.cvtColor(lab2, cv2.COLOR_LAB2BGR)

def unsharp_mask(bgr: np.ndarray, amount: float, sigma: float) -> np.ndarray:
    blurred = cv2.GaussianBlur(bgr, (0, 0), sigmaX=sigma, sigmaY=sigma)
    sharp = cv2.addWeighted(bgr, 1.0 + amount, blurred, -amount, 0)
    return np.clip(sharp, 0, 255).astype(np.uint8)

def compute_scale_to_target_short(w: int, h: int, target_short: int) -> tuple[int, int, float]:
    short = min(w, h)
    if short <= 0:
        return w, h, float("inf")
    scale = target_short / float(short)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return new_w, new_h, scale

def resize_keep_aspect(bgr: np.ndarray, new_w: int, new_h: int) -> np.ndarray:
    h, w = bgr.shape[:2]
    interp = cv2.INTER_LANCZOS4 if (new_w >= w and new_h >= h) else cv2.INTER_AREA
    return cv2.resize(bgr, (new_w, new_h), interpolation=interp)

def choose_dpi(short_side_px: int, cfg: EnhanceConfig) -> tuple[int, float, bool, str]:
    primary_target = target_short_side_px(cfg.print_inches_short_side, cfg.primary_dpi)
    req_factor_primary = primary_target / float(short_side_px) if short_side_px > 0 else float("inf")

    if req_factor_primary > cfg.max_upscale_factor_primary:
        return (
            cfg.fallback_dpi,
            req_factor_primary,
            True,
            f"factor {req_factor_primary:.2f}x > {cfg.max_upscale_factor_primary:.2f}x => fallback {cfg.fallback_dpi}dpi",
        )
    return (cfg.primary_dpi, req_factor_primary, False, f"using {cfg.primary_dpi}dpi")

def compute_fallback_factor(short_side_px: int, cfg: EnhanceConfig) -> float:
    fallback_target = target_short_side_px(cfg.print_inches_short_side, cfg.fallback_dpi)
    return fallback_target / float(short_side_px) if short_side_px > 0 else float("inf")

def auto_sharpen_amount(base: float, upscale_factor: float) -> float:
    if upscale_factor <= 1.2: return base
    if upscale_factor <= 1.6: return base * 0.85
    if upscale_factor <= 2.2: return base * 0.70
    if upscale_factor <= 3.0: return base * 0.55
    return base * 0.45

def enhance_one(pil_img: Image.Image, icc_profile: bytes | None, cfg: EnhanceConfig) -> tuple[Image.Image, int, dict]:
    rgb = pil_img.convert("RGB")
    arr = np.array(rgb)
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    h, w = bgr.shape[:2]
    short = min(w, h)

    chosen_dpi, req_factor_primary, used_fallback, dpi_reason = choose_dpi(short, cfg)
    target_short = target_short_side_px(cfg.print_inches_short_side, chosen_dpi)

    fallback_factor = compute_fallback_factor(short, cfg)
    too_small_for_good_print = fallback_factor > cfg.warn_upscale_factor_fallback

    out = mild_denoise(bgr, h=cfg.denoise_h, h_color=cfg.denoise_h_color)

    if cfg.enable_clahe:
        out = apply_clahe_on_l_channel(out, clip=cfg.clahe_clip, grid=cfg.clahe_grid)

    new_w, new_h, scale_for_chosen = compute_scale_to_target_short(w, h, target_short)
    did_upscale = False
    if cfg.upscale_if_needed and short < target_short:
        out = resize_keep_aspect(out, new_w, new_h)
        did_upscale = True

    sharpen_amt = auto_sharpen_amount(cfg.unsharp_amount_base, scale_for_chosen if did_upscale else 1.0)
    out = unsharp_mask(out, amount=sharpen_amt, sigma=cfg.unsharp_sigma)

    out_rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
    out_pil = Image.fromarray(out_rgb)

    meta = {
        "src_w": w,
        "src_h": h,
        "src_short": short,
        "chosen_dpi": chosen_dpi,
        "used_fallback": used_fallback,
        "req_factor_for_300": req_factor_primary,
        "fallback_factor": fallback_factor,
        "too_small_for_good_print": too_small_for_good_print,
        "target_short": target_short,
        "did_upscale": did_upscale,
        "scale_for_chosen": scale_for_chosen if did_upscale else 1.0,
        "dst_w": out.shape[1],
        "dst_h": out.shape[0],
        "sharpen_amount": sharpen_amt,
        "dpi_reason": dpi_reason,
        "icc_preserved": icc_profile is not None,
    }
    return out_pil, chosen_dpi, meta

def save_with_metadata(img: Image.Image, dst_path: Path, chosen_dpi: int, cfg: EnhanceConfig, icc_profile: bytes | None) -> None:
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs = dict(quality=cfg.jpeg_quality, optimize=True, subsampling=0)
    if cfg.set_dpi_metadata:
        kwargs["dpi"] = (chosen_dpi, chosen_dpi)
    if icc_profile:
        kwargs["icc_profile"] = icc_profile
    img.save(dst_path, **kwargs)

def enhance_folder(input_dir: str | Path, output_dir: str | Path, cfg: EnhanceConfig | None = None) -> Path:
    """
    Ready-to-use function.
    Enhances all images under input_dir and writes jpg outputs under output_dir (same relative structure).
    Returns the path to the CSV report.
    """
    cfg = cfg or EnhanceConfig()
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    imgs: List[Path] = [
        p for p in input_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    ]
    if not imgs:
        raise FileNotFoundError("No supported images found (jpg/jpeg/png).")

    report_path = output_dir / cfg.report_csv_name
    rows = []

    for src in tqdm(imgs, desc="Enhancing"):
        try:
            with Image.open(src) as pil_img:
                icc = pil_img.info.get("icc_profile", None)
                out_pil, chosen_dpi, meta = enhance_one(pil_img, icc, cfg)

                rel = src.relative_to(input_dir)
                dst = (output_dir / rel).with_suffix(".jpg")
                save_with_metadata(out_pil, dst, chosen_dpi, cfg, icc)

                rows.append({
                    "relative_path": rel.as_posix(),
                    "output_file": dst.name,
                    "src_w": meta["src_w"],
                    "src_h": meta["src_h"],
                    "src_short": meta["src_short"],
                    "chosen_dpi": meta["chosen_dpi"],
                    "used_fallback": meta["used_fallback"],
                    "req_factor_for_300": f'{meta["req_factor_for_300"]:.2f}',
                    "fallback_factor": f'{meta["fallback_factor"]:.2f}',
                    "too_small_for_good_print": meta["too_small_for_good_print"],
                    "did_upscale": meta["did_upscale"],
                    "scale_for_chosen": f'{meta["scale_for_chosen"]:.2f}',
                    "dst_w": meta["dst_w"],
                    "dst_h": meta["dst_h"],
                    "sharpen_amount": f'{meta["sharpen_amount"]:.3f}',
                    "icc_preserved": meta["icc_preserved"],
                    "dpi_reason": meta["dpi_reason"],
                })
        except Exception as e:
            rows.append({
                "relative_path": src.relative_to(input_dir).as_posix(),
                "output_file": "",
                "src_w": "",
                "src_h": "",
                "src_short": "",
                "chosen_dpi": "",
                "used_fallback": "",
                "req_factor_for_300": "",
                "fallback_factor": "",
                "too_small_for_good_print": "",
                "did_upscale": "",
                "scale_for_chosen": "",
                "dst_w": "",
                "dst_h": "",
                "sharpen_amount": "",
                "icc_preserved": "",
                "dpi_reason": f"ERROR: {e}",
            })

    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    return report_path
