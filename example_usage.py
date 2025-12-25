#!/usr/bin/env python3
"""
example_usage.py

Examples showing correct usage with URL-based processing.
"""

from enhancement_api import ImageEnhancementAPI
from enhancement_specs import EnhancementSpec
from image_processor import ImageProcessor

# Example enhancement specifications with URLs
example_specs = [
    {
        "imageId": "img001",
        "pageNo": 1,
        "print_inches_short_side": 9.0,
        "imageUrl": "https://example.com/photo1.jpg"
    },
    {
        "imageId": "img002", 
        "pageNo": 2,
        "print_inches_short_side": 7.5,
        "imageUrl": "https://example.com/photo2.jpg"
    }
]

def example_1_api_with_specs():
    """Example 1: Using API with enhancement specs (URLs in specs)"""
    print("🔥 Method 1: API with specs containing URLs")
    
    api = ImageEnhancementAPI()
    
    # No need for image_files mapping - URLs are in the specs!
    result = api.enhance_from_specs(
        specs_data=example_specs,
        image_files={},  # Empty because using URLs
        output_dir="./output_method1"
    )
    
    print(f"✅ Enhanced {result['successful_enhancements']}/{result['total_images']} images")


def example_2_direct_processor():
    """Example 2: Direct processor usage with URLs"""
    print("🔥 Method 2: Direct processor with URL fetching")
    
    processor = ImageProcessor()
    specs = [EnhancementSpec(**spec) for spec in example_specs]
    
    # Process directly - no images_dir needed
    results = processor.enhance_images_from_specs(
        specs=specs,
        output_dir="./output_method2"
        # images_dir=None  (will use URLs from specs)
    )
    
    successful = sum(1 for r in results if r.success)
    print(f"✅ Enhanced {successful}/{len(specs)} images")


def example_3_single_image():
    """Example 3: Single image from URL"""
    print("🔥 Method 3: Single image enhancement")
    
    api = ImageEnhancementAPI()
    
    result = api.enhance_single(
        image_id="single_test",
        image_file="https://example.com/test.jpg",  # Can be URL now!
        print_inches_short_side=8.0,
        output_dir="./output_method3"
    )
    
    print(f"✅ Result: {result}")


def example_4_mixed_sources():
    """Example 4: Mixed local files + URLs"""
    print("🔥 Method 4: Mixed local and URL sources")
    
    api = ImageEnhancementAPI()
    
    # Some images from files, some from URLs
    result = api.enhance_from_specs(
        specs_data=example_specs,
        image_files={
            "img001": "./local_photo1.jpg",  # Local override for img001
            # img002 will use URL from spec
        },
        output_dir="./output_method4"
    )
    
    print(f"✅ Enhanced {result['successful_enhancements']}/{result['total_images']} images")


if __name__ == "__main__":
    print("🚀 Image Enhancement Examples")
    print("=" * 50)
    
    # Note: These examples won't actually run without real URLs/files
    # They demonstrate the correct API usage patterns
    
    print("\n📋 Key Points:")
    print("✅ URLs are in enhancement_specs.json (imageUrl field)")
    print("✅ No source_images folder required")
    print("✅ layouts.json is static in source code")
    print("✅ Can mix local files + URLs")
    print("✅ Automatically fetches from URLs when no local file")
    
    print("\n🔧 Usage Patterns:")
    print("1. Pure URL processing - specs contain imageUrl")
    print("2. Local file override - provide image_files mapping") 
    print("3. Mixed sources - local files take precedence")
    print("4. Single image - can pass URL directly")