#!/usr/bin/env python3
"""
image_processor.py

Core image processing functionality for enhancement specifications.
Processes images directly from URLs (no local folder required).
"""

from __future__ import annotations

import tempfile
import shutil
import io
from pathlib import Path
from typing import Dict, Any, List, Union, Optional
from dataclasses import asdict
from urllib.request import urlopen, Request

from PIL import Image
from tqdm import tqdm

from print_enhancer import EnhanceConfig, enhance_one, save_with_metadata
from enhancement_specs import EnhancementSpec, EnhancementResult


def fetch_image_from_url(url: str, timeout: int = 20) -> Image.Image:
    """Fetch image directly from URL with EXIF orientation correction."""
    from PIL import ImageOps

    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as resp:
        image_data = resp.read()

    img = Image.open(io.BytesIO(image_data))

    # Apply EXIF orientation correction so enhanced images are correctly oriented
    try:
        img = ImageOps.exif_transpose(img)
    except (AttributeError, OSError, TypeError):
        # No EXIF data or orientation info
        pass

    return img


class ImageProcessor:
    """Processes images based on enhancement specifications."""
    
    def __init__(self, config: Optional[EnhanceConfig] = None):
        self.config = config or EnhanceConfig()
        self.temp_dir = Path(tempfile.gettempdir()) / "image_processor"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    def enhance_single_image(self, spec: EnhancementSpec, output_dir: Path, image_source: Union[str, Path] = None) -> EnhancementResult:
        """
        Enhance a single image based on enhancement specification.
        
        Args:
            spec: Enhancement specification with imageUrl or imageId
            output_dir: Directory to save enhanced image
            image_source: Optional local path (if not provided, uses spec.imageUrl)
        """
        try:
            # Create spec-specific config
            spec_config = EnhanceConfig(**{
                **asdict(self.config),
                'print_inches_short_side': spec.print_inches_short_side
            })
            
            # Get image - prefer local path, fallback to URL
            if image_source:
                pil_img = Image.open(image_source)
            elif spec.imageUrl:
                pil_img = fetch_image_from_url(spec.imageUrl)
            else:
                raise ValueError(f"No image source provided for {spec.imageId}")
            
            # Process image
            icc_profile = pil_img.info.get("icc_profile")
            enhanced_img, chosen_dpi, metadata = enhance_one(pil_img, icc_profile, spec_config)
            
            # Save enhanced image
            output_filename = f"{spec.imageId}_page{spec.pageNo:02d}.jpg"
            output_path = output_dir / output_filename
            output_dir.mkdir(parents=True, exist_ok=True)
            
            save_with_metadata(enhanced_img, output_path, chosen_dpi, spec_config, icc_profile)
            
            # Add spec metadata
            metadata.update({
                'imageId': spec.imageId,
                'pageNo': spec.pageNo,
                'requested_print_size': spec.print_inches_short_side,
                'output_filename': output_filename,
                'source': 'local_file' if image_source else 'url'
            })
            
            # Close image if we opened it
            if not image_source:
                pil_img.close()
            
            return EnhancementResult(
                imageId=spec.imageId,
                pageNo=spec.pageNo,
                success=True,
                output_path=str(output_path),
                chosen_dpi=chosen_dpi,
                metadata=metadata
            )
        except Exception as e:
            return EnhancementResult(
                imageId=spec.imageId,
                pageNo=spec.pageNo,
                success=False,
                error_message=str(e)
            )
    
    def enhance_images_from_specs(self, specs: List[EnhancementSpec], output_dir: str | Path, images_dir: Optional[str | Path] = None) -> List[EnhancementResult]:
        """
        Process multiple enhancement specifications.
        
        Args:
            specs: List of enhancement specifications
            output_dir: Directory to save enhanced images
            images_dir: Optional local images directory (if not provided, uses URLs from specs)
        """
        output_dir = Path(output_dir)
        results = []
        
        for spec in tqdm(specs, desc="Enhancing images"):
            image_source = None
            
            # Try to find local image if directory provided
            if images_dir:
                images_dir_path = Path(images_dir)
                for ext in ['.jpg', '.jpeg', '.png']:
                    candidate = images_dir_path / f"{spec.imageId}{ext}"
                    if candidate.exists():
                        image_source = candidate
                        break
            
            # Process image (will use URL if no local file found)
            result = self.enhance_single_image(spec, output_dir, image_source)
            results.append(result)
        
        return results
    
    def enhance_with_file_mapping(
        self, 
        specs: List[EnhancementSpec], 
        image_files: Dict[str, Union[str, Path]], 
        output_dir: str | Path
    ) -> List[EnhancementResult]:
        """Process specs with explicit file mapping."""
        try:
            # Create temporary images directory
            temp_dir = Path(tempfile.mkdtemp())
            images_dir = temp_dir / "images"
            images_dir.mkdir()
            
            # Copy images to temp directory  
            for image_id, file_path in image_files.items():
                src_path = Path(file_path)
                if src_path.exists():
                    dst_path = images_dir / f"{image_id}{src_path.suffix}"
                    shutil.copy2(src_path, dst_path)
            
            # Process using standard method
            results = self.enhance_images_from_specs(specs, images_dir, output_dir)
            
            return results
            
        finally:
            # Cleanup
            if 'temp_dir' in locals() and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def enhance_from_specs_file(self, specs_file: str | Path, output_dir: str | Path, images_dir: Optional[str | Path] = None) -> Dict[str, Any]:
        """
        Enhance images from existing enhancement_specs.json file.
        
        Args:
            specs_file: Path to enhancement_specs.json
            output_dir: Directory to save enhanced images
            images_dir: Optional local images directory (if not provided, uses URLs from specs)
        """
        from enhancement_specs import load_specs
        
        specs = load_specs(specs_file)
        results = self.enhance_images_from_specs(specs, output_dir, images_dir)
        
        successful = sum(1 for r in results if r.success)
        return {
            "success": True,
            "total_images": len(specs),
            "successful_enhancements": successful,
            "failed_enhancements": len(specs) - successful,
            "results": [asdict(r) for r in results]
        }
    
    def update_config(self, **config_updates) -> EnhanceConfig:
        """Update processor configuration."""
        current = asdict(self.config)
        current.update(config_updates)
        self.config = EnhanceConfig(**current)
        return self.config


if __name__ == "__main__":
    # Example usage
    import argparse
    import json
    from enhancement_specs import load_specs
    
    parser = argparse.ArgumentParser(description="Process enhancement specifications")
    parser.add_argument("--specs", required=True, help="Path to enhancement_specs.json")
    parser.add_argument("--images-dir", required=True, help="Directory with source images")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--primary-dpi", type=int, default=300)
    parser.add_argument("--fallback-dpi", type=int, default=240)
    parser.add_argument("--jpeg-quality", type=int, default=95)
    
    args = parser.parse_args()
    
    # Create processor with config
    config = EnhanceConfig(
        primary_dpi=args.primary_dpi,
        fallback_dpi=args.fallback_dpi,
        jpeg_quality=args.jpeg_quality
    )
    processor = ImageProcessor(config)
    
    # Process specifications
    result = processor.enhance_from_specs_file(args.specs, args.images_dir, args.output_dir)
    
    print(f"✅ Enhanced {result['successful_enhancements']}/{result['total_images']} images")
    print(f"📁 Output: {args.output_dir}")