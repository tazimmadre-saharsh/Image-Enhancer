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

import os
import json
import tempfile
import shutil
import httpx
import asyncio
import boto3
from botocore.config import Config as BotoConfig
from pathlib import Path
from typing import Dict, Any, List, Union, Optional
from dataclasses import asdict
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from photobook_enhancer import PhotoBookEnhancer
from enhancement_specs import EnhancementSpec, validate_specs, SpecGenerator
from print_enhancer import EnhanceConfig
from album_renderer import AlbumRenderer

# Strapi API Configuration - Production (from environment variables)
STRAPI_API_TOKEN = os.getenv("STRAPI_API_TOKEN", "")
STRAPI_API_BASE_URL = os.getenv("STRAPI_API_BASE_URL", "http://localhost:1338")

# Strapi API Configuration - Staging/DEV (from environment variables)
STRAPI_API_TOKEN_STAGING = os.getenv("STRAPI_API_TOKEN_STAGING", "")
STRAPI_API_BASE_URL_STAGING = os.getenv("STRAPI_API_BASE_URL_STAGING", "http://localhost:1338")

# AWS S3 Configuration (from environment variables)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
AWS_BUCKET = os.getenv("AWS_BUCKET", "")
AWS_BUCKET_STAGING = os.getenv("AWS_BUCKET_STAGING", "")

# Initialize S3 client
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
    config=BotoConfig(signature_version='s3v4')
)


def get_env_config(env: Optional[str] = None) -> Dict[str, str]:
    """
    Return environment-specific config based on env parameter.

    Args:
        env: Optional environment string. If "staging", returns DEV config.

    Returns:
        Dict with strapi_token, strapi_base_url, and s3_bucket keys.
    """
    if env == "staging":
        return {
            "strapi_token": STRAPI_API_TOKEN_STAGING,
            "strapi_base_url": STRAPI_API_BASE_URL_STAGING,
            "s3_bucket": AWS_BUCKET_STAGING
        }
    return {
        "strapi_token": STRAPI_API_TOKEN,
        "strapi_base_url": STRAPI_API_BASE_URL,
        "s3_bucket": AWS_BUCKET
    }


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


# =========================
# ORDER PROCESSING HELPERS
# =========================

async def fetch_order_data(order_id: str, config: Dict[str, str]) -> Dict[str, Any]:
    """Fetch order data from Strapi API with bearer token auth.

    Args:
        order_id: The order documentId to fetch
        config: Environment config dict with strapi_base_url and strapi_token
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{config['strapi_base_url']}/api/orders/{order_id}/details",
            headers={"Authorization": f"Bearer {config['strapi_token']}"}
        )
        response.raise_for_status()
        return response.json()


def get_dimensions_from_order_item(item: Dict[str, Any]) -> Dict[str, float]:
    """Extract page dimensions from templateVariant options metadata."""
    options = item.get("templateVariant", {}).get("options", [])
    book_size = next(
        (opt for opt in options if opt.get("optionType", {}).get("slug") == "book-size"),
        None
    )

    if book_size and book_size.get("metadata"):
        meta = book_size["metadata"]
        inner_w = float(meta.get("width", 9))
        inner_h = float(meta.get("height", 9))
        # Use cover dimensions if defined, otherwise fallback to inner + 1 inch
        cover_w = float(meta.get("coverWidth", inner_w + 1))
        cover_h = float(meta.get("coverHeight", inner_h + 1))
        return {
            "inner_width": inner_w,
            "inner_height": inner_h,
            "cover_width": cover_w,
            "cover_height": cover_h
        }

    # Fallback defaults
    return {
        "inner_width": 9.0,
        "inner_height": 9.0,
        "cover_width": 10.0,
        "cover_height": 10.0
    }


def build_album_data_from_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert order item to album data format expected by renderer.

    New project_images structure:
    {
        "imageId": "uuid",
        "imageUrl": "https://...",
        ...
    }

    Width/height are no longer provided - they will be fetched from the image URL.
    """
    snapshot = item.get("designSnapshot", {})
    coverData = snapshot.get("coverData", {})
    project_images = coverData.get("projectImages", [])

    return {
        "data": {
            "pages": snapshot.get("pages", []),
            "project_images": [
                {
                    "imageId": img.get("imageId"),
                    "image": {
                        "url": img.get("imageUrl"),
                        "storagePath": img.get("imageUrl"),
                        # Width/height will be fetched dynamically
                        "width": None,
                        "height": None
                    }
                }
                for img in project_images
            ]
        }
    }


# =========================
# ORDER ITEM STATUS UPDATES
# =========================

async def update_order_item_in_progress(item_id: str, config: Dict[str, str]) -> bool:
    """
    Update order item status to 'in_progress' before processing.

    Args:
        item_id: The order item documentId
        config: Environment config dict with strapi_base_url and strapi_token

    Returns:
        True if update succeeded, False otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(
                f"{config['strapi_base_url']}/api/order-items/{item_id}",
                headers={
                    "Authorization": f"Bearer {config['strapi_token']}",
                    "Content-Type": "application/json"
                },
                json={
                    "data": {
                        "photoExportStatus": "in_progress",
                        "photoExportUpdatedAt": datetime.utcnow().isoformat() + "Z",
                        "photoExportError": None
                    }
                }
            )
            response.raise_for_status()
            print(f"📝 Order item {item_id} status: in_progress")
            return True
    except Exception as e:
        print(f"⚠️ Failed to update order item {item_id} to in_progress: {e}")
        return False


async def update_order_item_completed(item_id: str, exported_pages: List[Dict[str, Any]], config: Dict[str, str]) -> bool:
    """
    Update order item status to 'completed' after successful processing.

    Args:
        item_id: The order item documentId
        exported_pages: List of page info dicts with pageNumber, filename, url etc.
        config: Environment config dict with strapi_base_url and strapi_token

    Returns:
        True if update succeeded, False otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(
                f"{config['strapi_base_url']}/api/order-items/{item_id}",
                headers={
                    "Authorization": f"Bearer {config['strapi_token']}",
                    "Content-Type": "application/json"
                },
                json={
                    "data": {
                        "photoExportStatus": "completed",
                        "photoExportUrls": exported_pages,
                        "photoExportUpdatedAt": datetime.utcnow().isoformat() + "Z",
                        "photoExportError": None
                    }
                }
            )
            response.raise_for_status()
            print(f"✅ Order item {item_id} status: completed ({len(exported_pages)} pages)")
            return True
    except Exception as e:
        print(f"⚠️ Failed to update order item {item_id} to completed: {e}")
        return False


async def update_order_item_failed(item_id: str, error_message: str, config: Dict[str, str]) -> bool:
    """
    Update order item status to 'failed' when processing fails.

    Args:
        item_id: The order item documentId
        error_message: Description of what went wrong
        config: Environment config dict with strapi_base_url and strapi_token

    Returns:
        True if update succeeded, False otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(
                f"{config['strapi_base_url']}/api/order-items/{item_id}",
                headers={
                    "Authorization": f"Bearer {config['strapi_token']}",
                    "Content-Type": "application/json"
                },
                json={
                    "data": {
                        "photoExportStatus": "failed",
                        "photoExportUpdatedAt": datetime.utcnow().isoformat() + "Z",
                        "photoExportError": error_message
                    }
                }
            )
            response.raise_for_status()
            print(f"❌ Order item {item_id} status: failed - {error_message}")
            return True
    except Exception as e:
        print(f"⚠️ Failed to update order item {item_id} to failed: {e}")
        return False


# =========================
# S3 UPLOAD FUNCTIONS
# =========================

def upload_page_to_s3(
    local_file_path: str,
    order_id: str,
    item_id: str,
    page_number: int,
    page_type: str,
    s3_bucket: str
) -> Dict[str, Any]:
    """
    Upload a rendered page to S3 and return the URL info.

    Args:
        local_file_path: Path to the local rendered page file
        order_id: The order documentId
        item_id: The order item documentId
        page_number: The page number (0-indexed)
        page_type: The page type (cover-front, cover-back, content, etc.)
        s3_bucket: The S3 bucket name to upload to

    Returns:
        Dict with url, filename, pageType, pageNumber, orderItemId
    """
    filename = f"{order_id}-page-{page_number:02d}.jpg"
    s3_key = f"orders/{order_id}/{item_id}/{filename}"

    # Upload to S3
    s3_client.upload_file(
        local_file_path,
        s3_bucket,
        s3_key,
        ExtraArgs={
            'ContentType': 'image/jpeg'
        }
    )

    # Construct the S3 URL
    s3_url = f"https://{s3_bucket}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"

    return {
        "url": s3_url,
        "filename": filename,
        "pageType": page_type,
        "pageNumber": page_number,
        "orderItemId": item_id
    }


async def upload_pages_to_s3(
    pages: List[Dict[str, Any]],
    output_dir: Path,
    order_id: str,
    item_id: str,
    s3_bucket: str
) -> List[Dict[str, Any]]:
    """
    Upload all rendered pages to S3.

    Args:
        pages: List of page info dicts from renderer (with filename, pageNumber, pageType)
        output_dir: Directory containing the rendered page files
        order_id: The order documentId
        item_id: The order item documentId
        s3_bucket: The S3 bucket name to upload to

    Returns:
        List of dicts with S3 URLs in the expected format
    """
    uploaded_pages = []

    for page in pages:
        local_path = str(output_dir / page.get("filename"))
        page_number = page.get("pageNumber", 0)
        page_type = page.get("pageType", "content")

        try:
            # Run S3 upload in thread pool to not block async loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                upload_page_to_s3,
                local_path,
                order_id,
                item_id,
                page_number,
                page_type,
                s3_bucket
            )
            uploaded_pages.append(result)
            print(f"📤 Uploaded page {page_number} to S3: {result['url']}")
        except Exception as e:
            print(f"⚠️ Failed to upload page {page_number}: {e}")
            # Include error info but continue with other pages
            uploaded_pages.append({
                "url": None,
                "filename": page.get("filename"),
                "pageType": page_type,
                "pageNumber": page_number,
                "orderItemId": item_id,
                "error": str(e)
            })

    return uploaded_pages


# =========================
# BACKGROUND TASK PROCESSING
# =========================

# Track currently processing orders to prevent duplicate task creation
# Key: (order_id, env) tuple to handle different environments separately
_processing_orders: set[tuple[str, Optional[str]]] = set()


async def process_order_background(order_id: str, env: Optional[str] = None):
    """
    Background task to process an order - fetch data, enhance images, render pages, upload to S3.

    This function is designed to run as a background task and will:
    1. Fetch order data from Strapi API
    2. For each order item:
       - Update status to 'in_progress'
       - Enhance images and render pages
       - Upload pages to S3
       - Update status to 'completed' with S3 URLs on success
       - Update status to 'failed' with error message on failure

    Args:
        order_id: The order documentId to process
        env: Optional environment string. If "staging", uses DEV config.
    """
    # Get environment-specific config
    config = get_env_config(env)
    env_label = "staging" if env == "staging" else "production"
    print(f"🚀 Starting background processing for order: {order_id} (env: {env_label})")

    try:
        # Fetch order data from Strapi
        order_data = await fetch_order_data(order_id, config)
        print(f"📦 Fetched order data with {len(order_data.get('items', []))} items")

        for item in order_data.get("items", []):
            item_id = item.get("documentId") or str(item.get("id"))
            print(f"\n📋 Processing order item: {item_id}")

            # Update status to in_progress before starting
            # await update_order_item_in_progress(item_id, config)

            # Get dimensions from templateVariant
            dims = get_dimensions_from_order_item(item)
            print(f"📐 Dimensions: inner={dims['inner_width']}x{dims['inner_height']}, cover={dims['cover_width']}x{dims['cover_height']}")

            # Build album data from order item
            album_data = build_album_data_from_item(item)

            if not album_data["data"]["pages"]:
                error_msg = "No pages found in designSnapshot"
                await update_order_item_failed(item_id, error_msg, config)
                print(f"❌ {error_msg}")
                continue

            # Create output directory
            output_dir = Path(f"./output/{item_id}")
            output_dir.mkdir(parents=True, exist_ok=True)

            try:
                # Create renderer and process with dimensions
                renderer = AlbumRenderer()
                result = await renderer.render_album_with_dimensions(
                    album_data=album_data,
                    dimensions=dims,
                    output_dir=output_dir,
                    auto_enhance=True
                )

                pages = result.get("pages", [])
                print(f"✅ Rendered {len(pages)} pages locally")

                # Upload all pages to S3
                print(f"📤 Uploading pages to S3 bucket: {config['s3_bucket']}...")
                # uploaded_pages = await upload_pages_to_s3(
                #     pages=pages,
                #     output_dir=output_dir,
                #     order_id=order_id,
                #     item_id=item_id,
                #     s3_bucket=config['s3_bucket']
                # )

                # # # Sort by page number
                # uploaded_pages.sort(key=lambda x: x.get("pageNumber", 0))

                # # Update status to completed with S3 URLs
                # await update_order_item_completed(item_id, uploaded_pages, config)
                # print(f"✅ Order item {item_id} completed with {len(uploaded_pages)} pages uploaded to S3")

                # Clean up local output folder after successful upload
                try:
                    # shutil.rmtree(output_dir)
                    print(f"🗑️ Cleaned up local output folder: {output_dir}")
                except Exception as cleanup_error:
                    print(f"⚠️ Failed to clean up output folder: {cleanup_error}")

            except Exception as item_error:
                error_msg = str(item_error)
                # await update_order_item_failed(item_id, error_msg, config)
                print(f"❌ Order item {item_id} failed: {error_msg}")

        print(f"\n🎉 Background processing completed for order: {order_id}")

    except Exception as e:
        print(f"❌ Background processing failed for order {order_id}: {e}")

    finally:
        # Always remove from tracking set when done (success or failure)
        _processing_orders.discard((order_id, env))


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

    @app.post("/render/album")
    async def render_album(
        album_data: str = Form(...),
        page_size: str = Form(...),
        output_dir: str = Form(None),
        auto_enhance: bool = Form(True),
        enhanced_dir: str = Form(None),
        layouts_path: str = Form(None)
    ):
        """
        Render album pages with optional auto-enhancement.

        Args:
            album_data: Album order JSON data
            page_size: Page size like "9x9" or "12x14"
            output_dir: Output directory for rendered pages (optional, uses temp dir if not provided)
            auto_enhance: Whether to auto-generate enhanced images (default: True)
            enhanced_dir: Directory with pre-generated enhanced images (optional)
            layouts_path: Path to layouts.json file (optional)
        """
        try:
            album_json = json.loads(album_data)

            # Use temp directory if output_dir not provided
            if not output_dir:
                output_dir = tempfile.mkdtemp(prefix="rendered_album_")

            # Create temp file for album data
            temp_dir = Path(tempfile.mkdtemp())
            album_file = temp_dir / "album_order.json"
            with open(album_file, 'w') as f:
                json.dump(album_json, f)

            # Create renderer
            renderer = AlbumRenderer(
                layouts_path=Path(layouts_path) if layouts_path else None
            )

            # Render album
            result = await renderer.render_album_from_files(
                album_file=album_file,
                page_size=page_size,
                output_dir=output_dir,
                enhanced_dir=enhanced_dir,
                auto_enhance=auto_enhance
            )

            # Cleanup temp album file
            shutil.rmtree(temp_dir, ignore_errors=True)

            return JSONResponse(result)

        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/render/album-file")
    async def render_album_from_file(
        album_file: UploadFile = File(...),
        page_size: str = Form(...),
        output_dir: str = Form(None),
        auto_enhance: bool = Form(True),
        enhanced_dir: str = Form(None),
        layouts_path: str = Form(None)
    ):
        """
        Render album pages from uploaded album_order.json file.

        Args:
            album_file: The album_order.json file
            page_size: Page size like "9x9" or "12x14"
            output_dir: Output directory for rendered pages (optional)
            auto_enhance: Whether to auto-generate enhanced images (default: True)
            enhanced_dir: Directory with pre-generated enhanced images (optional)
            layouts_path: Path to layouts.json file (optional)
        """
        try:
            # Use temp directory if output_dir not provided
            if not output_dir:
                output_dir = tempfile.mkdtemp(prefix="rendered_album_")

            # Save uploaded album file
            temp_dir = Path(tempfile.mkdtemp())
            temp_album_file = temp_dir / "album_order.json"
            content = await album_file.read()
            with open(temp_album_file, 'wb') as f:
                f.write(content)

            # Create renderer
            renderer = AlbumRenderer(
                layouts_path=Path(layouts_path) if layouts_path else None
            )

            # Render album
            result = await renderer.render_album_from_files(
                album_file=temp_album_file,
                page_size=page_size,
                output_dir=output_dir,
                enhanced_dir=enhanced_dir,
                auto_enhance=auto_enhance
            )

            # Cleanup temp files
            shutil.rmtree(temp_dir, ignore_errors=True)

            return JSONResponse(result)

        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/process/order")
    async def process_order(
        order_id: str = Form(...),
        env: Optional[str] = Form(None)
    ):
        """
        Process an order by ID - runs in background and returns immediately.

        This endpoint:
        1. Validates the order_id and starts background processing
        2. Returns immediately with a "processing started" response
        3. In background: fetches order data, enhances images, renders pages, uploads to S3
        4. Updates order item status in Strapi (in_progress -> completed/failed)

        The background task will:
        - Fetch order data from Strapi API
        - For each order item:
          - Update status to 'in_progress'
          - Enhance images and render pages (cover at cover dimensions, content at inner)
          - Upload rendered pages to S3
          - Update status to 'completed' with S3 URLs on success
          - Update status to 'failed' with error message on failure

        Check order item status in DB to monitor progress.

        Args:
            order_id: The order documentId to process
            env: Optional environment string. If "staging", uses DEV config
                 (AWS_BUCKET_STAGING, STRAPI_API_TOKEN_STAGING, STRAPI_API_BASE_URL_STAGING).
                 Otherwise uses production config.
        """
        if not order_id or not order_id.strip():
            raise HTTPException(status_code=400, detail="order_id is required")

        env_label = "staging" if env == "staging" else "production"

        # Check if this order is already being processed (skip redundant tasks)
        order_key = (order_id, env)
        if order_key in _processing_orders:
            return JSONResponse({
                "success": True,
                "message": "Order is already being processed",
                "order_id": order_id,
                "env": env_label,
                "status": "already_processing",
                "note": "Skipped redundant task creation. Check order item photoExportStatus in database to monitor progress"
            })

        # Mark order as processing before starting task
        _processing_orders.add(order_key)

        # Start background task using asyncio with environment config
        asyncio.create_task(process_order_background(order_id, env))

        return JSONResponse({
            "success": True,
            "message": "Order processing started in background",
            "order_id": order_id,
            "env": env_label,
            "status": "processing_started",
            "note": "Check order item photoExportStatus in database to monitor progress"
        })

    @app.post("/process/order-sync")
    async def process_order_sync(order_id: str = Form(...)):
        """
        Process an order by ID synchronously - waits for completion before returning.

        This is the synchronous version that waits for all processing to complete.
        Use /process/order for async background processing instead.

        Args:
            order_id: The order documentId to process
        """
        try:
            # Fetch order data from Strapi
            order_data = await fetch_order_data(order_id)

            results = []
            for item in order_data.get("items", []):
                item_id = item.get("documentId") or str(item.get("id"))

                # Update status to in_progress before starting
                await update_order_item_in_progress(item_id)

                # Get dimensions from templateVariant
                dims = get_dimensions_from_order_item(item)

                # Build album data from order item
                album_data = build_album_data_from_item(item)

                if not album_data["data"]["pages"]:
                    error_msg = "No pages found in designSnapshot"
                    await update_order_item_failed(item_id, error_msg)
                    results.append({
                        "item_id": item_id,
                        "status": "failed",
                        "error": error_msg
                    })
                    continue

                # Create output directory
                output_dir = Path(f"./output/{item_id}")
                output_dir.mkdir(parents=True, exist_ok=True)

                try:
                    # Create renderer and process with dimensions
                    renderer = AlbumRenderer()
                    result = await renderer.render_album_with_dimensions(
                        album_data=album_data,
                        dimensions=dims,
                        output_dir=output_dir,
                        auto_enhance=True
                    )

                    pages = result.get("pages", [])

                    # Upload all pages to S3
                    uploaded_pages = await upload_pages_to_s3(
                        pages=pages,
                        output_dir=output_dir,
                        order_id=order_id,
                        item_id=item_id
                    )

                    # Sort by page number
                    uploaded_pages.sort(key=lambda x: x.get("pageNumber", 0))

                    # Update status to completed with S3 URLs
                    await update_order_item_completed(item_id, uploaded_pages)

                    # Clean up local output folder after successful upload
                    try:
                        shutil.rmtree(output_dir)
                    except Exception:
                        pass  # Ignore cleanup errors in sync mode

                    results.append({
                        "item_id": item_id,
                        "status": "completed",
                        "dimensions": dims,
                        "pages": uploaded_pages
                    })

                except Exception as item_error:
                    error_msg = str(item_error)
                    # Update status to failed with error message
                    await update_order_item_failed(item_id, error_msg)
                    results.append({
                        "item_id": item_id,
                        "status": "failed",
                        "error": error_msg
                    })

            # Determine aggregate status
            failed_count = sum(1 for r in results if r.get("status") == "failed")
            if failed_count == len(results):
                aggregate_status = "failed"
            elif failed_count > 0:
                aggregate_status = "completed_with_errors"
            else:
                aggregate_status = "completed"

            return JSONResponse({
                "success": aggregate_status != "failed",
                "status": aggregate_status,
                "order_id": order_id,
                "items_processed": len(results),
                "items_succeeded": len(results) - failed_count,
                "items_failed": failed_count,
                "results": results
            })

        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Failed to fetch order: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    return app


# Create app instance for uvicorn
app = create_fastapi_app()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        # Run FastAPI server
        import uvicorn
        app = create_fastapi_app()
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
        print(f"Starting API server on http://localhost:{port}")
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        # Example usage
        api = ImageEnhancementAPI()
        print("Image Enhancement API ready!")
        print("")
        print("Available methods:")
        print("  - enhance_album()")
        print("  - enhance_from_specs()")
        print("  - enhance_single()")
        print("  - generate_specs_from_album()")
        print("  - validate_specs()")
        print("")
        print("FastAPI Endpoints (run with 'python enhancement_api.py serve'):")
        print("  POST /enhance/album      - Enhance album images")
        print("  POST /enhance/specs      - Enhance from specs")
        print("  POST /generate-specs     - Generate enhancement specs")
        print("  POST /render/album       - Render album pages (JSON data)")
        print("  POST /render/album-file  - Render album pages (file upload)")
        print("  POST /process/order      - Process order (async, returns immediately)")
        print("  POST /process/order-sync - Process order (sync, waits for completion)")
        print("")
        print("S3 Configuration:")
        print(f"  Bucket: {AWS_BUCKET}")
        print(f"  Region: {AWS_REGION}")
        print("")
        print("To start the server:")
        print("  python enhancement_api.py serve [port]")
        print("  # or")
        print("  uvicorn enhancement_api:app --reload")