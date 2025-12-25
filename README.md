# Image Enhancement for Photo Books

Clean, modular API for enhancing images for high-quality printing in photo books.

## Overview

**Workflow**: `album_order.json` + `layouts.json` → `enhancement_specs.json` → enhanced images

## File Structure

### **Core Files** (Use these)
- **`enhancement_api.py`** - Main API for integration with web frameworks
- **`photobook_enhancer.py`** - High-level orchestrator 
- **`enhancement_specs.py`** - Enhancement specification management
- **`image_processor.py`** - Core image processing engine
- **`print_enhancer.py`** - Low-level image enhancement functions

### **Data Files**
- **`layouts.json`** - Layout definitions for calculating print sizes
- **`album_order.json`** - Album structure (generate from your API)

### **Legacy** (Backup only)
- **`legacy_backup/`** - Old files for reference (don't use)

## Installation

### Option 1: Virtual Environment (Recommended)
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Quick activation script (next time)
source activate.sh
```

### Option 2: System-wide Installation
```bash
pip install -r requirements.txt
```

## Quick Start

### Method 1: API Integration with URLs (Recommended)
```python
from enhancement_api import ImageEnhancementAPI

api = ImageEnhancementAPI()

# Process from enhancement specs (URLs in specs)
specs_data = [
    {"imageId": "abc", "pageNo": 1, "print_inches_short_side": 9.0, "imageUrl": "https://..."},
    {"imageId": "def", "pageNo": 2, "print_inches_short_side": 7.5, "imageUrl": "https://..."}
]

result = api.enhance_from_specs(
    specs_data=specs_data,
    image_files={},  # Empty - using URLs from specs
    output_dir="./output"
)

# OR with local file overrides
result = api.enhance_from_specs(
    specs_data=specs_data,
    image_files={"abc": "/local/override.jpg"},  # Override URL for abc
    output_dir="./output"
)
```

### Method 2: Direct Orchestrator (Optional local images)
```python
from photobook_enhancer import PhotoBookEnhancer

enhancer = PhotoBookEnhancer()

# URLs in specs - no images_dir needed
result = enhancer.enhance_album(
    album_file="album_order.json",
    layouts_file="layouts.json", 
    page_size="9x9",
    images_dir=None,  # Will use URLs from generated specs
    output_dir="./enhanced_output"
)

# OR with local images folder (optional)
result = enhancer.enhance_album(
    album_file="album_order.json",
    layouts_file="layouts.json",
    page_size="9x9", 
    images_dir="./local_images",  # Optional: local files take precedence
    output_dir="./enhanced_output"
)
```

### Method 3: Modular Processing
```python
from enhancement_specs import SpecGenerator
from image_processor import ImageProcessor

# Generate specs
generator = SpecGenerator()
specs = generator.generate_from_files("album_order.json", "layouts.json", "9x9")

# Process images
processor = ImageProcessor()
results = processor.enhance_images_from_specs(specs, "./images", "./output")
```

### Method 4: Command Line
```bash
# Clean, minimal command (uses URLs from specs, default layouts.json)
python photobook_enhancer.py \
  --album album_order.json \
  --page-size 9x9 \
  --output-dir ./enhanced_output

# With quality settings
python photobook_enhancer.py \
  --album album_order.json \
  --page-size 9x9 \
  --output-dir ./enhanced_output \
  --primary-dpi 300 \
  --jpeg-quality 95
```

## Module Breakdown

### `enhancement_specs.py`
- `EnhancementSpec` - Data structure for image requirements
- `SpecGenerator` - Creates specs from album + layouts
- `save_specs()` / `load_specs()` - File operations
- `validate_specs()` - Validation utilities

### `image_processor.py`
- `ImageProcessor` - Core processing engine
- `enhance_single_image()` - Process one image
- `enhance_images_from_specs()` - Batch processing
- `enhance_with_file_mapping()` - Process with explicit file mapping

### `photobook_enhancer.py`
- `PhotoBookEnhancer` - Main orchestrator
- `enhance_album()` - Complete workflow
- `enhance_album_simple()` - Simple function interface

### `enhancement_api.py`
- `ImageEnhancementAPI` - Web-ready API class
- Handles temporary files, validation, and response formatting
- Includes FastAPI integration example

## FastAPI Integration

```python
from enhancement_api import create_fastapi_app

app = create_fastapi_app()

# Endpoints available:
# POST /enhance/album
# POST /enhance/specs  
# POST /generate-specs
```

## Configuration

```python
from print_enhancer import EnhanceConfig

config = EnhanceConfig(
    primary_dpi=300,
    fallback_dpi=240,
    jpeg_quality=95,
    max_upscale_factor_primary=2.5,
    denoise_h=3,
    unsharp_amount_base=0.60
)

api = ImageEnhancementAPI(config)
```

## What It Does

**Smart Print Optimization**:
- Automatically determines optimal DPI (300 or 240 fallback)
- Intelligent upscaling with quality preservation  
- Crop-aware sizing adjustments
- Adaptive sharpening based on upscale factor

**Image Enhancement Pipeline**:
- Noise reduction using advanced denoising
- Optional contrast enhancement (CLAHE)
- Unsharp masking for crisp printing
- ICC color profile preservation

**Print-Ready Output**:
- JPEG optimization for print quality
- DPI metadata embedding
- Structured output with detailed reports

## Album Rendering with Enhanced Images

### `album_renderer.py`
Renders complete photobook pages using enhanced images instead of original images.

```python
from album_renderer import AlbumRenderer

renderer = AlbumRenderer()

# Auto-generate enhanced images and render album
result = await renderer.render_album_from_files(
    album_file="album_order.json",
    page_size="9x9",
    output_dir="./rendered_album",
    auto_enhance=True  # Automatically enhances images first
)

# Or use existing enhanced images
result = await renderer.render_album_from_files(
    album_file="album_order.json", 
    page_size="9x9",
    output_dir="./rendered_album",
    enhanced_dir="./enhanced_output"
)
```

### Command Line Album Rendering
```bash
# Generate enhanced images and render album
python album_renderer.py \
  --album album_order.json \
  --page-size 9x9 \
  --output-dir ./rendered_album \
  --auto-enhance

# Use existing enhanced images
python album_renderer.py \
  --album album_order.json \
  --page-size 9x9 \
  --output-dir ./rendered_album \
  --enhanced-dir ./enhanced_output

# Skip enhancement, use original images only
python album_renderer.py \
  --album album_order.json \
  --page-size 9x9 \
  --output-dir ./rendered_album \
  --no-enhance
```

### Key Features
- **Enhanced Image Integration**: Automatically uses enhanced images when available, falls back to originals
- **Font Support**: Handles multiple font families with system font fallbacks
- **Transform Support**: Crops, scales, rotations, margins, and fit modes
- **High Quality Output**: 300 DPI JPEG with optimized print quality
- **Background Images**: Supports page backgrounds with enhanced images
- **Text Elements**: Renders text with proper font scaling and positioning

## Migration from Legacy

If you were using the old files:
- `jobs.json` → `enhancement_specs.json`
- `generate_jobs.py` → use `SpecGenerator` from `enhancement_specs.py`
- `process_jobs.py` → use `ImageProcessor` from `image_processor.py`
- `job_enhancer.py` → use `ImageEnhancementAPI` from `enhancement_api.py`

All old functionality is preserved but organized into focused modules.