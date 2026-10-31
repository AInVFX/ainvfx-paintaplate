"""The page's icons, drawn from the Paint a plate logo in web/brand/title.png: its gold brush and its letter P, on the
dark ground of the Registry icon. Writes web/brand/favicon.png (64 px, the browser tab) and web/brand/touch-icon.png
(180 px, a phone's home screen). Run it again whenever the logo changes:

    python tools/brand_icons.py
"""
import os

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(ROOT, "web", "brand")
MASTER = 512  # drawn at this size, then reduced
GOLD, INK = 0.45, (0.08, 0.75)  # red channel: above GOLD is brush; from INK[0] (letter) to INK[1] (brush) is the letter's edge


def logo_parts(title):
    """The brush's two ends without letters, joined into one short stroke (RGB on black, alpha), and the letter P (alpha)."""
    red = title[..., 0]
    labels, n = ndimage.label(red > GOLD)
    brush = labels == 1 + int(np.argmax(ndimage.sum(np.ones_like(red), labels, range(1, n + 1))))  # the brush, not the n of AInVFX
    ys, xs = np.nonzero(brush)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    box = brush[y0:y1, x0:x1]
    letters, k = ndimage.label(ndimage.binary_fill_holes(box) & ~box)  # the letters are holes in the brush
    big = [i + 1 for i, a in enumerate(ndimage.sum(np.ones_like(box), letters, range(1, k + 1))) if a > 0.002 * box.size]
    spans = ndimage.find_objects(letters)
    first = min(big, key=lambda i: spans[i - 1][1].start)  # the P: the leftmost letter
    left, right = min(spans[i - 1][1].start for i in big), max(spans[i - 1][1].stop for i in big)
    h, w = box.shape
    crop = title[y0:y1, x0:x1]
    alpha = np.clip((crop[..., 0] - INK[0]) / (INK[1] - INK[0]), 0, 1)[..., None]
    head = slice(0, min(left - h // 16, int(0.8 * h)))  # the round end, before the letters
    tail = slice(max(right + h // 16, w - int(0.95 * h)), w)  # the bristles, after them
    over = h // 8  # the two ends blend over this many columns
    a, b = crop[:, head] * alpha[:, head], crop[:, tail] * alpha[:, tail]
    aa, ab = alpha[:, head], alpha[:, tail]
    ramp = np.linspace(0, 1, over)[None, :, None]
    rgb = np.concatenate([a[:, :-over], a[:, -over:] * (1 - ramp) + b[:, :over] * ramp, b[:, over:]], 1)
    alp = np.concatenate([aa[:, :-over], aa[:, -over:] * (1 - ramp) + ab[:, :over] * ramp, ab[:, over:]], 1)
    sy, sx = spans[first - 1]
    pad = h // 40
    py, px = slice(max(0, sy.start - pad), sy.stop + pad), slice(max(0, sx.start - pad), sx.stop + pad)
    shape = ndimage.binary_dilation(letters[py, px] == first, iterations=pad)
    letter = (1 - np.clip((crop[py, px, 0] - INK[0]) / (INK[1] - INK[0]), 0, 1)) * shape
    return rgb, alp, letter, h


def resized(img, w, h):
    return np.stack([np.asarray(Image.fromarray(img[..., c].astype(np.float32), "F").resize((w, h), Image.LANCZOS))
                     for c in range(img.shape[2])], -1)


def main():
    title = np.asarray(Image.open(os.path.join(BRAND, "title.png")).convert("RGB")).astype(np.float32) / 255.0
    rgb, alpha, letter, stroke_h = logo_parts(title)
    ground = np.median(title[title[..., 0] < 0.2], axis=0)  # the logo's dark ground
    yy, xx = np.mgrid[0:MASTER, 0:MASTER] / (MASTER - 1) - 0.5
    icon = ground * (1.0 + 0.6 * np.clip(1 - 2.2 * (xx**2 + yy**2), 0, 1))[..., None]  # a faint glow behind the brush
    sw = int(0.88 * MASTER)
    sh = int(round(sw * rgb.shape[0] / rgb.shape[1]))
    top, lft = (MASTER - sh) // 2, (MASTER - sw) // 2
    rgb_s, a_s = resized(rgb, sw, sh), resized(alpha, sw, sh)
    region = icon[top:top + sh, lft:lft + sw]
    icon[top:top + sh, lft:lft + sw] = region * (1 - a_s.clip(0, 1)) + rgb_s.clip(0, 1)
    lh = int(0.62 * sh)  # the letter, larger than in the logo, so it reads in a browser tab
    lw = int(round(lh * letter.shape[1] / letter.shape[0]))
    ink = resized(letter[..., None], lw, lh).clip(0, 1)
    ly, lx = top + (sh - lh) // 2, lft + int(0.42 * sw) - lw // 2  # the brush's body: its right end is bristles
    icon[ly:ly + lh, lx:lx + lw] = icon[ly:ly + lh, lx:lx + lw] * (1 - ink) + 0.03 * ink
    mask = Image.new("L", (4 * MASTER, 4 * MASTER), 0)  # a rounded square, smooth at its corners
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 4 * MASTER - 1, 4 * MASTER - 1), radius=int(0.88 * MASTER), fill=255)
    out = Image.fromarray((icon.clip(0, 1) * 255 + 0.5).astype(np.uint8), "RGB").convert("RGBA")
    out.putalpha(mask.resize((MASTER, MASTER), Image.LANCZOS))
    for name, size in (("favicon.png", 64), ("touch-icon.png", 180)):
        out.resize((size, size), Image.LANCZOS).save(os.path.join(BRAND, name), optimize=True)
        print(f"wrote web/brand/{name} ({size} px)")


if __name__ == "__main__":
    main()
