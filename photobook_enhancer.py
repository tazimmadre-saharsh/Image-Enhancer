#!/usr/bin/env python3
"""
photobook_enhancer.py

Main photobook enhancement orchestrator using focused modules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from dataclasses import asdict

from print_enhancer import EnhanceConfig
from enhancement_specs import EnhancementSpec, SpecGenerator, save_specs
from image_processor import ImageProcessor


class PhotoBookEnhancer:
    """Main orchestrator for photobook image enhancement."""
    
    def __init__(self, config: Optional[EnhanceConfig] = None):
        self.config = config or EnhanceConfig()
        self.spec_generator = SpecGenerator()
        self.image_processor = ImageProcessor(self.config)
    
    def generate_enhancement_specs(self, album_file: str | Path, page_size: str, layouts_file: Optional[str | Path] = None) -> List[EnhancementSpec]:
        """Generate enhancement specifications from album and layouts."""
        return self.spec_generator.generate_from_files(album_file, page_size, layouts_file)
    
    def enhance_images_from_specs(self, specs: List[EnhancementSpec], output_dir: str | Path, images_dir: Optional[str | Path] = None):
        """Process multiple enhancement specifications."""
        return self.image_processor.enhance_images_from_specs(specs, output_dir, images_dir)
    
    def enhance_single_image(self, spec: EnhancementSpec, output_dir: Path, image_source: Union[str, Path] = None):
        """Enhance a single image based on enhancement specification."""
        return self.image_processor.enhance_single_image(spec, output_dir, image_source)
    
    def enhance_album(
        self, 
        album_file: str | Path, 
        page_size: str,
        output_dir: str | Path,
        images_dir: Optional[str | Path] = None,
        layouts_file: Optional[str | Path] = None,
        save_specs_file: bool = True
    ) -> Dict[str, Any]:
        """
        Complete album enhancement workflow.
        
        Args:
            album_file: Path to album_order.json
            page_size: Page size like "9x9" or "12x14"
            output_dir: Directory for enhanced images
            images_dir: Optional directory with source images (if not provided, uses URLs)
            layouts_file: Optional path to layouts.json (defaults to ./layouts.json)
            save_specs_file: Whether to save enhancement_specs.json file
        
        Returns:
            Dictionary with results and summary
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate enhancement specs
        specs = self.generate_enhancement_specs(album_file, page_size, layouts_file)
        
        # Save specs file if requested
        if save_specs_file:
            specs_file = output_dir / "enhancement_specs.json"
            save_specs(specs, specs_file)
        
        # Process enhancement specs
        results = self.enhance_images_from_specs(specs, output_dir, images_dir)
        
        # Generate summary
        successful = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        
        summary = {
            "success": True,
            "total_images": len(specs),
            "successful_enhancements": successful,
            "failed_enhancements": failed,
            "output_directory": str(output_dir),
            "page_size": page_size,
            "config": asdict(self.config),
            "results": [asdict(r) for r in results]
        }
        
        # Save report
        report_file = output_dir / "enhancement_report.json"
        with open(report_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        return summary
    
    def enhance_from_specs_file(self, specs_file: str | Path, output_dir: str | Path, images_dir: Optional[str | Path] = None) -> Dict[str, Any]:
        """Enhance images from existing enhancement_specs.json file."""
        return self.image_processor.enhance_from_specs_file(specs_file, output_dir, images_dir)
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration."""
        return asdict(self.config)
    
    def update_config(self, **config_updates) -> Dict[str, Any]:
        """Update configuration."""
        current = asdict(self.config)
        current.update(config_updates)
        self.config = EnhanceConfig(**current)
        self.image_processor.config = self.config
        return self.get_config()


def enhance_album_simple(
    album_file: str,
    page_size: str,
    output_dir: str,
    images_dir: Optional[str] = None,
    layouts_file: Optional[str] = None,
    **config_overrides
) -> Dict[str, Any]:
    """
    Simple function interface for album enhancement.
    
    Example:
        result = enhance_album_simple(
            album_file="album_order.json",
            page_size="9x9",
            output_dir="./enhanced_output",
            # images_dir="./source_images",  # Optional: local images
            # layouts_file="./layouts.json",  # Optional: custom layouts
            primary_dpi=300,
            jpeg_quality=95
        )
    """
    config = EnhanceConfig()
    if config_overrides:
        config_dict = asdict(config)
        config_dict.update(config_overrides)
        config = EnhanceConfig(**config_dict)
    
    enhancer = PhotoBookEnhancer(config)
    return enhancer.enhance_album(album_file, page_size, output_dir, images_dir, layouts_file)


if __name__ == "__main__":
    # Command line interface
    import argparse
    
    parser = argparse.ArgumentParser(description="Photobook image enhancement")
    parser.add_argument("--album", required=True, help="Path to album_order.json")
    parser.add_argument("--page-size", required=True, help="Page size like 9x9 or 12x14")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--primary-dpi", type=int, default=300)
    parser.add_argument("--fallback-dpi", type=int, default=240) 
    parser.add_argument("--jpeg-quality", type=int, default=95)
    
    args = parser.parse_args()
    
    result = enhance_album_simple(
        album_file=args.album,
        page_size=args.page_size,
        output_dir=args.output_dir,
        primary_dpi=args.primary_dpi,
        fallback_dpi=args.fallback_dpi,
        jpeg_quality=args.jpeg_quality
    )
    
    print(f"✅ Enhanced {result['successful_enhancements']}/{result['total_images']} images")
    print(f"📁 Output: {result['output_directory']}")