"""
Generate app_icon.ico for FLEx List Migrator.
Run once (on any platform with Pillow) and commit the result.

  pip install Pillow
  python make_icon.py
"""

from PIL import Image, ImageDraw, ImageFont

SIZES = [16, 24, 32, 48, 64, 128, 256]
BG    = (31, 78, 121)    # deep SIL blue
FG    = (255, 255, 255)  # white


def make_frame(size: int) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded rectangle background
    m = max(1, size // 10)
    r = max(3, size // 5)
    draw.rounded_rectangle([m, m, size - m - 1, size - m - 1],
                            radius=r, fill=BG)

    # "FL" label — scale font to frame
    font_size = max(6, int(size * 0.44))
    font = None
    for path in [
        "arialbd.ttf", "arial.ttf",           # Windows
        "/System/Library/Fonts/Helvetica.ttc", # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
    ]:
        try:
            font = ImageFont.truetype(path, font_size)
            break
        except OSError:
            pass
    if font is None:
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:
            font = ImageFont.load_default()

    text = "FL"
    # Skip text on very small frames where it's unreadable anyway
    if size >= 24:
        try:
            bb = draw.textbbox((0, 0), text, font=font)
            x  = (size - (bb[2] - bb[0])) / 2 - bb[0]
            y  = (size - (bb[3] - bb[1])) / 2 - bb[1] - max(0, size // 18)
            draw.text((x, y), text, fill=FG, font=font)
        except Exception:
            pass  # Fall back to blank-label icon for this size

    return img


if __name__ == "__main__":
    frames = [make_frame(s) for s in SIZES]
    out = "app_icon.ico"
    # Pillow's ICO save: pass all frames as a list via the 'icon_size' approach.
    # The most reliable method is to save the largest frame and append the rest.
    img = frames[-1]  # largest frame (256)
    img.save(
        out,
        format="ICO",
        append_images=frames[:-1],
    )
    import os
    print(f"Wrote {out}  ({os.path.getsize(out):,} bytes, {len(SIZES)} sizes: {SIZES})")
