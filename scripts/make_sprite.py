#!/usr/bin/env python3
"""Prepare the pet sprite for rendering.

The user provides their OWN reference image WITH an alpha channel in assets/.
We do NOT chroma-key anymore — we simply:
  1. Load the newest alpha-bearing PNG in assets/ (excluding our own output name
     only if a distinct source exists),
  2. Crop to the non-transparent bounding box,
  3. Square-pad with transparency,
  4. Resize to 120x120,
  5. Save back as assets/pet_sprite.png (the name ui_component.py loads).

If the source has NO real alpha, we fall back to a background chroma-key.
"""
import glob
import os
from PIL import Image, ImageFilter

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
DST = os.path.join(ASSETS, "pet_sprite.png")
SIZE = 120


def has_real_alpha(im):
    if im.mode not in ("RGBA", "LA") and "transparency" not in im.info:
        return False
    a = im.convert("RGBA").getchannel("A")
    lo, hi = a.getextrema()
    return lo < 200  # something is actually transparent


def pick_source():
    # Explicit priority: the preserved full-res alpha source wins so we never
    # downsample our own 120px output as if it were the source.
    preferred = os.path.join(ASSETS, "pet_reference_alpha.png")
    if os.path.isfile(preferred):
        return preferred
    cands = []
    for p in glob.glob(os.path.join(ASSETS, "*")):
        if not os.path.isfile(p):
            continue
        if p.lower().endswith((".png", ".webp", ".gif")):
            cands.append(p)
    if not cands:
        raise FileNotFoundError(f"No image found in {ASSETS}")
    # Prefer a source that isn't already 120x120 (our processed output).
    def score(p):
        try:
            w, h = Image.open(p).size
        except Exception:
            return (0, 0)
        already_processed = (w == SIZE and h == SIZE)
        return (0 if already_processed else 1, os.path.getmtime(p))
    cands.sort(key=score, reverse=True)
    return cands[0]


def chroma_key(im):
    """Fallback only: remove near-white/gray background via border flood-ish
    brightness+saturation test (used when the source has no alpha)."""
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            mx, mn = max(r, g, b), min(r, g, b)
            if mx > 215 and (mx - mn) < 24:
                px[x, y] = (r, g, b, 0)
    alpha = im.split()[3].filter(ImageFilter.GaussianBlur(1.0))
    im.putalpha(alpha)
    return im


def main():
    src = pick_source()
    im = Image.open(src)
    print(f"source: {src} size={im.size} mode={im.mode}")

    if has_real_alpha(im):
        im = im.convert("RGBA")
        print("source has real alpha -> using it directly (no chroma-key)")
    else:
        print("source has NO alpha -> chroma-keying background")
        im = chroma_key(im)

    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
        print(f"cropped to content bbox {bbox} -> {im.size}")

    cw, ch = im.size
    side = max(cw, ch)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - cw) // 2, (side - ch) // 2), im)
    canvas = canvas.resize((SIZE, SIZE), Image.LANCZOS)
    canvas.save(DST)

    a = canvas.getchannel("A")
    opaque = sum(1 for v in a.getdata() if v > 200)
    semi = sum(1 for v in a.getdata() if 20 < v <= 200)
    print(f"saved {DST} size={canvas.size} mode={canvas.mode}")
    print(f"alpha extrema: {a.getextrema()}  opaque={opaque} semi={semi} / {SIZE*SIZE}")
    for name, (x, y) in {"TL": (2, 2), "TR": (SIZE - 3, 2), "BL": (2, SIZE - 3),
                         "BR": (SIZE - 3, SIZE - 3), "C": (SIZE // 2, SIZE // 2)}.items():
        print(name, canvas.getpixel((x, y)))


if __name__ == "__main__":
    main()
