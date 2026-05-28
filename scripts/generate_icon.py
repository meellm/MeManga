#!/usr/bin/env python3
"""Generate MeManga's app icon from code.

Produces the platform icon files used by PyInstaller specs and by
:func:`memanga.gui.app.MeMangaApp` at runtime. Run from the repo root:

    python scripts/generate_icon.py

Outputs (overwritten in place — re-runnable):

    memanga/gui/assets/icon/icon-{16,32,48,64,128,256,512,1024}.png
    memanga/gui/assets/icon/icon.png            (alias of 256)
    packaging/icon.ico                           (Windows multi-res)
    packaging/icon.icns                          (macOS, if iconutil available)

The icon is drawn from primitives (no source asset) so the project owns
its icon outright — no licence ambiguity. The visual is a bold geometric
"M" monogram in matcha green on a warm dark squircle. Colours come
from the GUI theme tokens (memanga/gui/theme/tokens.py).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw


# ---- Palette (pulled from memanga.gui.theme.tokens, dark variant) -------

SQUIRCLE_BG = "#211D17"            # warm dark surface (bg_1)
SQUIRCLE_RING = "#3F3930"          # subtle warm border (border_strong)
PAGE_FILL = "#F1ECDF"              # warm cream (text.t_1)
PAGE_LINE = "#BCB6A5"              # softer cream (text.t_2)
SPINE_COLOR = "#0E0B07"            # near-black (surfaces.root_bg)
ACCENT = "#A0C780"                 # matcha (accent.primary)
ACCENT_DEEP = "#80AB60"            # deeper matcha (accent.primary_2)


# ---- Geometry helpers ---------------------------------------------------


def _rounded_rect_mask(size: int, radius_ratio: float) -> Image.Image:
    """Return an L-mode mask for a rounded square of ``size`` with the
    given corner radius as a fraction of ``size``."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    r = int(size * radius_ratio)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=r, fill=255)
    return mask


def _draw_m_monogram(draw: ImageDraw.ImageDraw, size: int):
    """Render a bold geometric "M" monogram centred in ``size`` × ``size``.

    Built as a single 8-point polygon (outer rect minus the V-shaped
    notch on top + two valleys on the bottom of the bowls). Stroke
    weights chosen so the negative space reads as the letter M at
    every output size from 16 px up.
    """
    cx = size // 2
    cy = size // 2

    # M bounding box: ~58 % of canvas width, ~58 % of canvas height,
    # centred. The geometric centre is shifted up by ~3 % so the
    # letter sits visually balanced — humans read M as bottom-heavy
    # because of the legs.
    m_w = int(size * 0.58)
    m_h = int(size * 0.58)
    left = cx - m_w // 2
    right = cx + m_w // 2
    top = cy - m_h // 2 - int(size * 0.02)
    bottom = top + m_h

    # Stroke width (the outer legs) and how deep the central V notch
    # goes. The V stops a third of the way down so the bowls feel
    # bold and chunky, not spindly.
    stroke = int(m_w * 0.22)
    v_depth = int(m_h * 0.55)
    inner_left = left + stroke
    inner_right = right - stroke
    # Inner-V tip — slightly above the geometric midline gives the M
    # more visual weight at the bottom.
    v_tip_y = top + v_depth

    # 8-point M outline, clockwise from top-left.
    poly = [
        (left, top),                                 # top-left outer
        (inner_left, top),                           # top-left inner (start of left peak)
        (cx, v_tip_y),                               # bottom of inner V
        (inner_right, top),                          # top-right inner
        (right, top),                                # top-right outer
        (right, bottom),                             # bottom-right outer
        (inner_right, bottom),                       # bottom-right inner (right leg foot)
        # Up the inside of the right leg to where it meets the right
        # bowl's inner slope — the inner edge curves back up to follow
        # the leg, then over to the V tip.
        (inner_right, top + int(v_depth * 0.55)),
        (cx, bottom),                                # bottom of central V on baseline
        (inner_left, top + int(v_depth * 0.55)),     # mirror on the left
        (inner_left, bottom),                        # left leg foot inner
        (left, bottom),                              # bottom-left outer
    ]
    draw.polygon(poly, fill=ACCENT)

    # Subtle deeper-matcha edge bevel on the right side, only at
    # larger renders — gives the flat M a hint of dimensionality.
    if size >= 128:
        bevel_w = max(1, size // 180)
        # Right leg outer edge
        draw.line(
            [(right, top), (right, bottom)],
            fill=ACCENT_DEEP, width=bevel_w,
        )
        # Bottom edge of both legs
        draw.line(
            [(left, bottom), (inner_left, bottom)],
            fill=ACCENT_DEEP, width=bevel_w,
        )
        draw.line(
            [(inner_right, bottom), (right, bottom)],
            fill=ACCENT_DEEP, width=bevel_w,
        )



def _draw_icon(size: int) -> Image.Image:
    """Return a fully-rendered RGBA icon at ``size`` × ``size``."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background squircle (rounded square) — corner radius ~22 %.
    r = int(size * 0.22)
    draw.rounded_rectangle(
        (0, 0, size - 1, size - 1),
        radius=r,
        fill=SQUIRCLE_BG,
    )
    # Inner ring stroke for depth on larger renders.
    if size >= 64:
        stroke = max(1, size // 256)
        draw.rounded_rectangle(
            (stroke, stroke, size - 1 - stroke, size - 1 - stroke),
            radius=r - stroke,
            outline=SQUIRCLE_RING,
            width=stroke,
        )

    _draw_m_monogram(draw, size)
    return img


# ---- Driver -------------------------------------------------------------


PNG_SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 32, 48, 64, 128, 256)
ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def _build_png_set(out_dir: Path) -> dict[int, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[int, Path] = {}
    for s in PNG_SIZES:
        # 1024 is the master; smaller sizes are direct renders, NOT
        # downsamples of the master — the line widths and text-hint
        # threshold need to be size-aware to read cleanly at 16/32.
        img = _draw_icon(s)
        p = out_dir / f"icon-{s}.png"
        img.save(p, "PNG")
        paths[s] = p
    # Convenience alias used by runtime QIcon load.
    shutil.copyfile(paths[256], out_dir / "icon.png")
    return paths


def _build_ico(png_paths: dict[int, Path], dest: Path):
    """Bundle a multi-resolution Windows .ico from the PNG set.

    PIL's ICO writer wants the LARGEST source image and a `sizes` kwarg
    listing the section sizes to downscale into. Passing the 16×16 PNG
    and a list of larger sizes silently drops every section but the
    16×16 one, leaving a 199-byte stub that Windows Explorer falls
    back to the default exe glyph for.
    """
    master = max(s for s in ICO_SIZES if s in png_paths)
    img = Image.open(png_paths[master]).convert("RGBA")
    img.save(dest, format="ICO", sizes=[(s, s) for s in ICO_SIZES])


def _build_icns(png_paths: dict[int, Path], dest: Path) -> bool:
    """Build a macOS .icns via `iconutil` if available.

    Returns True on success, False if iconutil isn't present (Linux /
    Windows build hosts). PyInstaller's macOS spec falls back to the
    PNG if .icns is missing.
    """
    if not shutil.which("iconutil"):
        return False
    # iconutil expects an .iconset directory with a strict naming scheme.
    iconset = dest.with_suffix(".iconset")
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    # Apple's required entries: (size, scale).
    mapping = [
        (16, 1, "icon_16x16.png"),
        (16, 2, "icon_16x16@2x.png"),
        (32, 1, "icon_32x32.png"),
        (32, 2, "icon_32x32@2x.png"),
        (128, 1, "icon_128x128.png"),
        (128, 2, "icon_128x128@2x.png"),
        (256, 1, "icon_256x256.png"),
        (256, 2, "icon_256x256@2x.png"),
        (512, 1, "icon_512x512.png"),
        (512, 2, "icon_512x512@2x.png"),
    ]
    for base, scale, name in mapping:
        px = base * scale
        if px in png_paths:
            shutil.copyfile(png_paths[px], iconset / name)
        else:
            # Resample from the next-larger if missing.
            larger = max(p for p in png_paths if p >= px)
            Image.open(png_paths[larger]).resize(
                (px, px), Image.LANCZOS,
            ).save(iconset / name, "PNG")
    try:
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(dest)],
            check=True,
        )
        return True
    finally:
        shutil.rmtree(iconset, ignore_errors=True)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    runtime_dir = repo_root / "memanga" / "gui" / "assets" / "icon"
    packaging_dir = repo_root / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)

    print("Generating PNG set…")
    png_paths = _build_png_set(runtime_dir)
    for s, p in sorted(png_paths.items()):
        print(f"  {s:>4}px → {p.relative_to(repo_root)}")

    print("Building Windows .ico…")
    ico_path = packaging_dir / "icon.ico"
    _build_ico(png_paths, ico_path)
    print(f"  → {ico_path.relative_to(repo_root)}")

    print("Building macOS .icns…")
    icns_path = packaging_dir / "icon.icns"
    if _build_icns(png_paths, icns_path):
        print(f"  → {icns_path.relative_to(repo_root)}")
    else:
        print("  iconutil not available — skipping (Windows/Linux host)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
