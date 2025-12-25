#!/bin/bash
# Activation script for the image enhancement environment
source venv/bin/activate
echo "✅ Virtual environment activated!"
echo "📦 Installed packages:"
pip list | grep -E "(opencv|Pillow|numpy|tqdm)"
echo ""
echo "🚀 Ready to use image enhancement tools!"
echo "💡 Run: python photobook_enhancer.py --help"