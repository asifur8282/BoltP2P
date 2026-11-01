"""
CrossDrop Desktop Daemon - Packaging Script
Builds standalone, windowless Windows 11 executable: dist/CrossDrop.exe
"""

import os
import sys
import subprocess
import shutil
from PIL import Image, ImageDraw

DESKTOP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(DESKTOP_DIR, "assets")
ICON_PATH = os.path.join(ASSETS_DIR, "app_icon.ico")
SPEC_PATH = os.path.join(DESKTOP_DIR, "crossdrop.spec")
DIST_DIR = os.path.join(DESKTOP_DIR, "dist")
BUILD_DIR = os.path.join(DESKTOP_DIR, "build")
OUTPUT_EXE = os.path.join(DIST_DIR, "CrossDrop.exe")


def ensure_icon():
    """Ensure multi-resolution slate monochrome icon is present."""
    os.makedirs(ASSETS_DIR, exist_ok=True)
    if os.path.exists(ICON_PATH):
        return

    print("[1/4] Generating application icon (assets/app_icon.ico)...")
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    images = []

    for size in sizes:
        w, h = size
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Carbon dark circle with crisp 1px border
        draw.ellipse((2, 2, w - 3, h - 3), fill="#161B22", outline="#30363D", width=max(1, w // 32))
        # Blue accent signal dot in center (#2F81F7)
        pad = w // 3
        draw.ellipse((pad, pad, w - pad, h - pad), fill="#2F81F7")
        images.append(img)

    images[0].save(ICON_PATH, format="ICO", sizes=[(img.width, img.height) for img in images])
    print("      Done.")


def clean_previous_builds():
    """Terminate running instances and remove stale build artifacts."""
    print("[2/4] Checking for running instances and cleaning previous build artifacts...")
    # Terminate running instances on Windows so the executable file is not locked
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/F", "/IM", "CrossDrop.exe"], capture_output=True)
            import time
            time.sleep(1.0)
        except Exception:
            pass

    for directory in [BUILD_DIR, DIST_DIR]:
        if os.path.exists(directory):
            try:
                shutil.rmtree(directory)
            except Exception as e:
                # If file lock remains
                exe_candidate = os.path.join(directory, "CrossDrop.exe")
                if os.path.exists(exe_candidate):
                    print(f"\n[WARNING] Could not delete '{exe_candidate}'.")
                    print("          CrossDrop.exe is currently running in your system tray.")
                    print("          Please right-click the CrossDrop tray icon and click 'Exit CrossDrop', then re-run.\n")
                    sys.exit(1)
                shutil.rmtree(directory, ignore_errors=True)
    print("      Done.")


def run_pyinstaller():
    """Invoke PyInstaller to compile crossdrop.spec."""
    print("[3/4] Compiling standalone executable via PyInstaller...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        SPEC_PATH
    ]
    result = subprocess.run(cmd, cwd=DESKTOP_DIR)
    if result.returncode != 0:
        print("\n[ERROR] PyInstaller compilation failed with code:", result.returncode)
        sys.exit(result.returncode)


def verify_executable():
    """Verify final standalone executable output."""
    print("[4/4] Verifying generated binary...")
    if not os.path.exists(OUTPUT_EXE):
        print(f"\n[ERROR] Expected binary not found at: {OUTPUT_EXE}")
        sys.exit(1)

    size_mb = os.path.getsize(OUTPUT_EXE) / (1024 * 1024)
    print(f"\n" + "=" * 60)
    print("SUCCESS: Standalone executable compiled successfully!")
    print(f"Path: {OUTPUT_EXE}")
    print(f"Size: {size_mb:.2f} MB")
    print(f"Mode: Windowless/Headless System Tray Daemon")
    print("=" * 60)


if __name__ == "__main__":
    ensure_icon()
    clean_previous_builds()
    run_pyinstaller()
    verify_executable()
