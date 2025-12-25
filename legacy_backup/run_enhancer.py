# run_enhancer.py
import sys
from pathlib import Path

from print_enhancer import enhance_folder, EnhanceConfig


def main():
    # Folder where the EXE lives
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).parent
    else:
        base_dir = Path(__file__).parent

    input_dir = base_dir / "photos"
    output_dir = base_dir / "output"

    print("📂 Base directory:", base_dir)
    print("📥 Input folder :", input_dir)
    print("📤 Output folder:", output_dir)

    if not input_dir.exists():
        print("❌ 'photos' folder not found.")
        print("👉 Create a folder named 'photos' next to the exe and add images.")
        input("Press ENTER to exit...")
        return

    cfg = EnhanceConfig(
        enable_clahe=False  # stable colors by default
    )

    print("▶ Processing started...")
    report = enhance_folder(input_dir, output_dir, cfg)

    print("✅ Done")
    print("📄 Report:", report)
    input("Press ENTER to exit...")


if __name__ == "__main__":
    main()
