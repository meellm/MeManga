#!/usr/bin/env python3
"""Generate MeManga's app icon files from the project artwork.

Produces the platform icon files used by PyInstaller specs and by
:func:`memanga.gui.app.MeMangaApp` at runtime. Run from the repo root:

    python scripts/generate_icon.py

Input:

    packaging/icon-source.png                    (square master artwork)

Outputs (overwritten in place — re-runnable):

    memanga/gui/assets/icon/icon-{16,32,48,64,128,256,512,1024}.png
    memanga/gui/assets/icon/icon.png            (alias of 256)
    packaging/icon.ico                           (Windows multi-res)
    packaging/icon.icns                          (macOS multi-res)

Every output is a resize of the whole artwork: nothing is cropped,
masked or redrawn.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image


PNG_SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
# Pixel sizes of the entries Pillow's ICNS writer stores (1x and @2x).
ICNS_SIZES = (32, 64, 128, 256, 512, 1024)


def _load_artwork(path: Path) -> Image.Image:
    """Return the master artwork as RGBA, refusing to distort it."""
    with Image.open(path) as source:
        art = source.convert("RGBA")
    if art.width != art.height:
        raise ValueError(
            f"{path} must be square, got {art.width}x{art.height}"
        )
    return art


def _render(art: Image.Image, size: int) -> Image.Image:
    """Return the whole artwork at ``size`` × ``size``."""
    if art.width == size:
        return art.copy()
    return art.resize((size, size), Image.Resampling.LANCZOS)


def _build_png_set(art: Image.Image, out_dir: Path) -> dict[int, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[int, Path] = {}
    for s in PNG_SIZES:
        p = out_dir / f"icon-{s}.png"
        _render(art, s).save(p, "PNG", optimize=True)
        paths[s] = p
    # Convenience alias used by runtime QIcon load.
    shutil.copyfile(paths[256], out_dir / "icon.png")
    return paths


def _build_ico(art: Image.Image, dest: Path):
    """Bundle a multi-resolution Windows .ico.

    PIL's ICO writer skips every size larger than the image it is called
    on, so it is called on the largest frame, with the others supplied
    pre-rendered.
    """
    frames = [_render(art, s) for s in sorted(ICO_SIZES, reverse=True)]
    frames[0].save(
        dest,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=frames[1:],
    )


def _build_icns(art: Image.Image, dest: Path):
    """Bundle a macOS .icns; Pillow writes it on every build host."""
    frames = [_render(art, s) for s in sorted(ICNS_SIZES, reverse=True)]
    frames[0].save(dest, format="ICNS", append_images=frames[1:])


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    runtime_dir = repo_root / "memanga" / "gui" / "assets" / "icon"
    packaging_dir = repo_root / "packaging"
    art = _load_artwork(packaging_dir / "icon-source.png")

    print("Generating PNG set…")
    png_paths = _build_png_set(art, runtime_dir)
    for s, p in sorted(png_paths.items()):
        print(f"  {s:>4}px → {p.relative_to(repo_root)}")

    print("Building Windows .ico…")
    ico_path = packaging_dir / "icon.ico"
    _build_ico(art, ico_path)
    print(f"  → {ico_path.relative_to(repo_root)}")

    print("Building macOS .icns…")
    icns_path = packaging_dir / "icon.icns"
    _build_icns(art, icns_path)
    print(f"  → {icns_path.relative_to(repo_root)}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
