#!/usr/bin/env python3
"""
enhancement_api.py

Clean API interface for image enhancement.
Ready for integration with FastAPI, Flask, or any web framework.

Example usage:
    from enhancement_api import ImageEnhancementAPI
    
    api = ImageEnhancementAPI()
    
    # Method 1: Full album processing
    result = api.enhance_album(
        album_data=album_json,
        layouts_data=layouts_json,
        page_size="9x9",
        image_files={"imageId1": "/path/to/image1.jpg", ...},
        output_dir="/path/to/output"
    )
    
    # Method 2: Process from enhancement specs
    result = api.enhance_from_specs(
        specs_data=[{"imageId": "...", "pageNo": 1, "print_inches_short_side": 9.0}, ...],
        image_files={"imageId1": "/path/to/image1.jpg", ...},
        output_dir="/path/to/output"
    )
"""

from __future__ import annotations

import json
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, List, Union, Optional
from dataclasses import asdict

from photobook_enhancer import PhotoBookEnhancer
from enhancement_specs import EnhancementSpec, validate_specs
from print_enhancer import EnhanceConfig


class ImageEnhancementAPI:
    """Clean API for image enhancement operations."""
    
    def __init__(self, config: Optional[EnhanceConfig] = None):
        self.enhancer = PhotoBookEnhancer(config)
    
    def enhance_album(
        self,
        album_data: Dict[str, Any],
        page_size: str,
        image_files: Dict[str, Union[str, Path]],  # {imageId: file_path}
        output_dir: str | Path,
        layouts_data: Optional[List[Dict[str, Any]]] = None,
        return_base64: bool = False
    ) -> Dict[str, Any]:
        """
        Enhance an entire album.
        
        Args:
            album_data: Album order data (JSON content)
            page_size: Page size like "9x9" or "12x14"  
            image_files: Mapping of imageId to file paths
            output_dir: Output directory
            layouts_data: Optional layouts definitions (uses ./layouts.json if not provided)
            return_base64: Include base64 encoded images in response
            
        Returns:
            Enhancement results and summary
        """
        try:
            # Create temporary file for album
            temp_dir = Path(tempfile.mkdtemp())
            album_file = temp_dir / "album_order.json"
            
            # Write album data to temp file
            with open(album_file, 'w') as f:
                json.dump(album_data, f)
            
            # Handle layouts
            layouts_file = None
            if layouts_data:
                layouts_file = temp_dir / "layouts.json"
                with open(layouts_file, 'w') as f:
                    json.dump(layouts_data, f)
            
            # Copy images to temp directory (if any provided)
            images_dir = None
            if image_files:
                images_dir = temp_dir / "images"
                images_dir.mkdir()
                for image_id, file_path in image_files.items():
                    src_path = Path(file_path)
                    if src_path.exists():
                        dst_path = images_dir / f"{image_id}{src_path.suffix}"
                        shutil.copy2(src_path, dst_path)
            
            # Process album
            result = self.enhancer.enhance_album(
                album_file=album_file,
                page_size=page_size,
                output_dir=output_dir,
                images_dir=images_dir,
                layouts_file=layouts_file
            )
            
            # Add base64 data if requested
            if return_base64:
                self._add_base64_data(result)
            
            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "total_jobs": 0,
                "successful_jobs": 0,
                "failed_jobs": 0
            }
        finally:
            # Cleanup
            if 'temp_dir' in locals() and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def enhance_from_specs(
        self,
        specs_data: List[Dict[str, Any]],
        image_files: Dict[str, Union[str, Path]],
        output_dir: str | Path,
        return_base64: bool = False
    ) -> Dict[str, Any]:
        """
        Enhance images from enhancement specifications.
        
        Args:
            specs_data: List of enhancement specifications
            image_files: Mapping of imageId to file paths
            output_dir: Output directory
            return_base64: Include base64 encoded images in response
            
        Returns:
            Enhancement results and summary
        """
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
            
            # Convert to specs and process
            specs = [EnhancementSpec(**spec) for spec in specs_data]
            results = self.enhancer.enhance_images_from_specs(specs, output_dir, images_dir)
            
            # Build response
            successful = sum(1 for r in results if r.success)
            response = {
                "success": True,
                "total_images": len(specs),
                "successful_enhancements": successful,
                "failed_enhancements": len(specs) - successful,
                "output_directory": str(output_dir),
                "results": [asdict(r) for r in results]
            }
            
            # Add base64 data if requested
            if return_base64:
                self._add_base64_data(response)
            
            return response
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "total_images": len(specs_data),
                "successful_enhancements": 0,
                "failed_enhancements": len(specs_data)
            }
        finally:
            # Cleanup
            if 'temp_dir' in locals() and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def enhance_single(
        self,
        image_id: str,
        image_file: Union[str, Path],
        print_inches_short_side: float,
        page_no: int = 0,
        output_dir: Optional[str | Path] = None,
        return_base64: bool = False
    ) -> Dict[str, Any]:
        """Enhance a single image."""
        spec_data = {
            "imageId": image_id,
            "pageNo": page_no,
            "print_inches_short_side": print_inches_short_side
        }
        
        return self.enhance_from_specs(
            [spec_data],
            {image_id: image_file},
            output_dir or tempfile.mkdtemp(),
            return_base64
        )
    
    def generate_specs_from_album(
        self,
        album_data: Dict[str, Any],
        page_size: str,
        layouts_data: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """Generate enhancement specs without processing images."""
        try:
            # Create temporary file for album
            temp_dir = Path(tempfile.mkdtemp())
            album_file = temp_dir / "album_order.json"
            
            with open(album_file, 'w') as f:
                json.dump(album_data, f)
            
            # Handle layouts
            layouts_file = None
            if layouts_data:
                layouts_file = temp_dir / "layouts.json"
                with open(layouts_file, 'w') as f:
                    json.dump(layouts_data, f)
            
            specs = self.enhancer.generate_enhancement_specs(album_file, page_size, layouts_file)
            return [asdict(spec) for spec in specs]
            
        finally:
            if 'temp_dir' in locals() and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def validate_specs(self, specs_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate enhancement specs data format."""
        return validate_specs(specs_data)
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration."""
        return asdict(self.enhancer.config)
    
    def update_config(self, **config_updates) -> Dict[str, Any]:
        """Update configuration."""
        current = asdict(self.enhancer.config)
        current.update(config_updates)
        self.enhancer.config = EnhanceConfig(**current)
        return self.get_config()
    
    def _add_base64_data(self, response: Dict[str, Any]) -> None:
        """Add base64 encoded image data to response."""
        import base64
        
        for result in response.get("results", []):
            if result.get("success") and result.get("output_path"):
                try:
                    with open(result["output_path"], 'rb') as f:
                        img_data = f.read()
                    result["base64_data"] = base64.b64encode(img_data).decode('utf-8')
                    result["mime_type"] = "image/jpeg"
                except Exception as e:
                    result["base64_error"] = str(e)


# FastAPI example integration
def create_fastapi_app():
    """
    Example FastAPI integration.
    
    To use:
        pip install fastapi uvicorn python-multipart
        python -c "from api import create_fastapi_app; app = create_fastapi_app()"
        uvicorn api:app --reload
    """
    try:
        from fastapi import FastAPI, UploadFile, File, Form, HTTPException
        from fastapi.responses import JSONResponse
        import tempfile
        import os
    except ImportError:
        raise ImportError("FastAPI not installed. Run: pip install fastapi python-multipart")
    
    app = FastAPI(title="Image Enhancement API")
    api = ImageEnhancementAPI()
    
    @app.post("/enhance/album")
    async def enhance_album(
        album_data: str = Form(...),
        layouts_data: str = Form(...), 
        page_size: str = Form(...),
        files: List[UploadFile] = File(...)
    ):
        try:
            album_json = json.loads(album_data)
            layouts_json = json.loads(layouts_data)
            
            # Save uploaded files
            temp_files = {}
            for file in files:
                temp_path = tempfile.mktemp(suffix=Path(file.filename).suffix)
                with open(temp_path, "wb") as f:
                    f.write(await file.read())
                # Extract imageId from filename or use mapping
                image_id = Path(file.filename).stem
                temp_files[image_id] = temp_path
            
            result = api.enhance_album(
                album_data=album_json,
                layouts_data=layouts_json,
                page_size=page_size,
                image_files=temp_files,
                output_dir=tempfile.mkdtemp(),
                return_base64=True
            )
            
            # Cleanup temp files
            for temp_path in temp_files.values():
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            
            return JSONResponse(result)
            
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @app.post("/enhance/specs")
    async def enhance_from_specs(
        specs_data: str = Form(...),
        files: List[UploadFile] = File(...)
    ):
        try:
            specs = json.loads(specs_data)
            
            temp_files = {}
            for file in files:
                temp_path = tempfile.mktemp(suffix=Path(file.filename).suffix)
                with open(temp_path, "wb") as f:
                    f.write(await file.read())
                image_id = Path(file.filename).stem
                temp_files[image_id] = temp_path
            
            result = api.enhance_from_specs(
                specs_data=specs,
                image_files=temp_files,
                output_dir=tempfile.mkdtemp(),
                return_base64=True
            )
            
            # Cleanup
            for temp_path in temp_files.values():
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            
            return JSONResponse(result)
            
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    @app.post("/generate-specs")
    async def generate_specs(
        album_data: str = Form(...),
        layouts_data: str = Form(...),
        page_size: str = Form(...)
    ):
        try:
            album_json = json.loads(album_data)
            layouts_json = json.loads(layouts_data)
            
            specs = api.generate_specs_from_album(album_json, layouts_json, page_size)
            return {"specs": specs, "count": len(specs)}
            
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    
    return app


if __name__ == "__main__":
    # Example usage
    api = ImageEnhancementAPI()
    print("✅ Image Enhancement API ready!")
    print("📋 Available methods:")
    print("  - enhance_album()")
    print("  - enhance_from_specs()")
    print("  - enhance_single()")
    print("  - generate_specs_from_album()")
    print("  - validate_specs())"