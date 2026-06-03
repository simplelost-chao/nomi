"""Build script for packaging Nomi backend with PyInstaller."""
import subprocess
import sys
from pathlib import Path


def main():
    desktop_dir = Path(__file__).parent
    spec_file = desktop_dir / "nomi-server.spec"

    print("Installing desktop dependencies...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "-r",
        str(desktop_dir.parent / "requirements-desktop.txt"),
    ])

    print("Installing PyInstaller...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "pyinstaller",
    ])

    print("Building nomi-server...")
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller",
        "--clean",
        str(spec_file),
    ], cwd=str(desktop_dir))

    output = desktop_dir / "dist" / "nomi-server"
    if output.exists():
        print(f"\nBuild successful: {output}")
        print(f"Size: {output.stat().st_size / 1024 / 1024:.1f} MB")
    else:
        print("\nBuild failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
