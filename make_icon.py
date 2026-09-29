"""
Generate the app and website icons from the SVG sources in icons/.

  icons/app_icon.svg        full design, used at 48 px and larger
  icons/app_icon_small.svg  bolder, simplified design for 16-32 px

Needs rsvg-convert (librsvg; on macOS `brew install librsvg`) and Pillow.
Run it after editing either SVG, then commit what it writes:

  app_icon.ico                 the .exe and window icon (16-256 px)
  docs/favicon.ico             website favicon (16-48 px)
  docs/favicon.svg             website icon for browsers that use SVG
  docs/180x180.png, docs/192x192.png, docs/512x512.png
                               Apple touch and web-app icons (docs/site.webmanifest)

  pip install Pillow
  python make_icon.py
"""

import io
import shutil
import subprocess
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
FULL = HERE / "icons" / "app_icon.svg"
SMALL = HERE / "icons" / "app_icon_small.svg"
SMALL_MAX = 32                     # sizes up to this use the simplified design

APP_ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
FAVICON_SIZES = [16, 32, 48]
PNG_SIZES = [180, 192, 512]


def render(svg: Path, size: int) -> Image.Image:
    png = subprocess.run(
        ["rsvg-convert", "-w", str(size), "-h", str(size), str(svg)],
        check=True, capture_output=True,
    ).stdout
    return Image.open(io.BytesIO(png)).convert("RGBA")


def frame(size: int) -> Image.Image:
    return render(SMALL if size <= SMALL_MAX else FULL, size)


def save_ico(path: Path, sizes) -> None:
    frames = [frame(s) for s in sizes]
    # Pillow stores a supplied image for each size rather than scaling one down,
    # so the small sizes get the simplified design.
    frames[-1].save(path, format="ICO", sizes=[(s, s) for s in sizes],
                    append_images=frames[:-1])


if __name__ == "__main__":
    if not shutil.which("rsvg-convert"):
        raise SystemExit("rsvg-convert not found: install librsvg "
                         "(macOS: brew install librsvg).")
    save_ico(HERE / "app_icon.ico", APP_ICO_SIZES)
    save_ico(HERE / "docs" / "favicon.ico", FAVICON_SIZES)
    # Browsers show the SVG favicon at tab size, so use the bold design.
    shutil.copyfile(SMALL, HERE / "docs" / "favicon.svg")
    for s in PNG_SIZES:
        frame(s).save(HERE / "docs" / f"{s}x{s}.png", optimize=True)
    print("Wrote app_icon.ico, docs/favicon.ico, docs/favicon.svg and "
          + ", ".join(f"docs/{s}x{s}.png" for s in PNG_SIZES))
