#!/usr/bin/env python3
"""Cut a contact sheet into named game assets.

The whole reason the generator asks for a GRID rather than for one image at a
time: a model will not honour an aspect ratio you asked for and will not hand
back N separate files, but a square canvas cut into N x N equal squares is
N x N equal squares whatever it decided to draw inside them -- and the cutting
is arithmetic, which cannot fail in an interesting way.

    cut.py sheet.png --out assets/sprites --grid 2 --size 256 \
           --names inf,light,tank,hq --prefix unit_blue --chroma auto
"""
import argparse
import collections
import os
import sys

from PIL import Image



def square(img: Image.Image) -> Image.Image:
    """Centre-crop to a square. The captured sheet is square in principle and
    off by a few pixels in practice; without this a lopsided export shears the
    grid a little further with every row."""
    s = min(img.size)
    return img.crop(((img.width - s) // 2, (img.height - s) // 2,
                     (img.width - s) // 2 + s, (img.height - s) // 2 + s))


def border_colour(tile: Image.Image, ring: int = 5):
    """The modal colour of a ring around the tile's edge.

    Asking for '#FF00FF' gets you *approximately* magenta: models add a
    vignette, a gradient, a hint of shadow, and JPEG-ish ringing. Keying on a
    hard-coded value therefore leaves a halo, so the key colour is measured
    from the picture instead. Sampling a RING rather than the corners means a
    subject that touches one edge does not poison the estimate."""
    px = tile.convert("RGB").load()
    w, h = tile.size
    seen = collections.Counter()
    for y in range(h):
        for x in range(w):
            if x < ring or y < ring or x >= w - ring or y >= h - ring:
                # quantise, or 40,000 near-identical magentas all count once
                r, g, b = px[x, y]
                seen[(r // 8, g // 8, b // 8)] += 1
    (r, g, b), _ = seen.most_common(1)[0]
    return (r * 8 + 4, g * 8 + 4, b * 8 + 4)


def key_out(tile: Image.Image, key, tol: int, feather: int) -> Image.Image:
    """Chroma-key `key` to transparency, with a feathered edge and un-mixing.

    Two bands: inside `tol` the pixel is fully transparent, and out to
    `tol + feather` the alpha ramps -- which is what stops a sprite having a
    hard jagged rim at the size the game draws it.

    The band pixels then have to be UN-MIXED, not merely darkened. An edge
    pixel is a blend of the subject and the key: observed = a*subject +
    (1-a)*key, so the subject is (observed - (1-a)*key) / a. Anything less
    principled -- nudging the channels down by a fudge factor, which is what
    this did first -- leaves a magenta fringe that is invisible at 100% and
    unmistakable at the 12% the game actually draws a sprite at."""
    tile = tile.convert("RGBA")
    px = tile.load()
    kr, kg, kb = key
    w, h = tile.size
    for y in range(h):
        for x in range(w):
            r, g, b, _ = px[x, y]
            d = abs(r - kr) + abs(g - kg) + abs(b - kb)
            if d <= tol:
                px[x, y] = (r, g, b, 0)
            elif d <= tol + feather:
                f = (d - tol) / feather                # 0 at the key, 1 at the subject
                a = f
                inv = 1.0 - a
                px[x, y] = (_unmix(r, kr, a, inv), _unmix(g, kg, a, inv),
                            _unmix(b, kb, a, inv), int(255 * a))
    return tile


def _unmix(v: int, k: int, a: float, inv: float) -> int:
    if a < 0.02:
        return 0
    return max(0, min(255, int((v - inv * k) / a)))


def fit_bbox(tile: Image.Image) -> Image.Image:
    """Crop to what is drawn and keep its natural proportions.

    The square version below is right for anything the game scales by a single
    size -- a tree, a haystack, a unit. It is wrong for anything the game
    stretches into a rectangle it already knows: a wide barn roof squared up
    inside its tile gains transparent margins top and bottom, and stretching
    THAT over a building's footprint leaves a border of paving all the way
    round it. Keeping the natural box means the roof reaches the eaves."""
    box = tile.getbbox()
    return tile if box is None else tile.crop(box)


def trim(tile: Image.Image, pad: float) -> Image.Image:
    """Crop to what is actually drawn, then pad back out to a square.

    A model given sixteen cells fills each one to a different extent, so
    without this a tree is 90% of its tile and the tree beside it is 40%, and
    the game -- which scales a sprite by its own metre size -- draws two trees
    of wildly different sizes from two assets that are nominally the same. The
    subject is normalised to its own bounding box so 'this asset is 4 metres
    across' means the same thing for all of them."""
    box = tile.getbbox()                                # alpha-aware
    if box is None:
        return tile
    tile = tile.crop(box)
    s = int(max(tile.size) * (1.0 + pad * 2.0))
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(tile, ((s - tile.width) // 2, (s - tile.height) // 2))
    return out


def seamless(tile: Image.Image) -> Image.Image:
    """Mirror a tile out to twice its size so its edges match by construction.

    A generated ground texture is not tileable: its left edge has nothing to do
    with its right, so drawing it repeatedly leaves a hard line at every repeat
    -- which at an eight-cell period is a visible grid of big squares across
    the whole map, and much more distracting than the per-cell chequerboard it
    replaced.

    A four-way mirror is seamless without any inpainting: the result is
    symmetric about its own middle, which on grass, stubble and earth is far
    less noticeable than a discontinuity. It is the wrong tool for anything
    with a direction or a repeating pattern of its own -- cobbles would come
    back as a mandala -- which is why it is a per-job flag and not the
    default."""
    w, h = tile.size
    out = Image.new(tile.mode, (w * 2, h * 2))
    out.paste(tile, (0, 0))
    out.paste(tile.transpose(Image.FLIP_LEFT_RIGHT), (w, 0))
    out.paste(tile.transpose(Image.FLIP_TOP_BOTTOM), (0, h))
    out.paste(tile.transpose(Image.FLIP_LEFT_RIGHT).transpose(Image.FLIP_TOP_BOTTOM), (w, h))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--grid", type=int, default=4)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--names", default="",
                    help="comma-separated tile names; falls back to 00,01,...")
    ap.add_argument("--chroma", default="",
                    help="'auto' to measure the key colour off each tile's own "
                         "border, or a hex like ff00ff; empty leaves the tile opaque")
    ap.add_argument("--tol", type=int, default=120)
    ap.add_argument("--feather", type=int, default=150)
    ap.add_argument("--pad", type=float, default=0.04)
    ap.add_argument("--fit", choices=["square", "bbox"], default="square",
                    help="square: normalise to a padded square, for anything the "
                         "game scales by one size. bbox: keep natural proportions, "
                         "for anything the game stretches to a known rectangle.")
    ap.add_argument("--inset", type=float, default=0.02,
                    help="fraction trimmed off each cell edge, to drop grid lines")
    ap.add_argument("--seamless", action="store_true",
                    help="mirror each tile out to 2x so it repeats without a seam")
    ap.add_argument("--edge", type=int, default=8,
                    help="pixels trimmed off the whole sheet first: it was captured "
                         "from a page that draws images in a rounded container, and "
                         "without this the four corner tiles each get a dark wedge")
    a = ap.parse_args()

    img = square(Image.open(a.sheet).convert("RGB"))
    if a.edge > 0:
        img = img.crop((a.edge, a.edge, img.width - a.edge, img.height - a.edge))
    s = img.width
    cell = s / a.grid
    pad = cell * a.inset

    names = [n for n in a.names.split(",") if n]
    os.makedirs(a.out, exist_ok=True)
    wrote = []
    for i in range(a.grid * a.grid):
        row, colm = divmod(i, a.grid)
        tile = img.crop((int(colm * cell + pad), int(row * cell + pad),
                         int((colm + 1) * cell - pad), int((row + 1) * cell - pad)))
        if a.chroma:
            key = border_colour(tile) if a.chroma == "auto" else (
                int(a.chroma[0:2], 16), int(a.chroma[2:4], 16), int(a.chroma[4:6], 16))
            tile = key_out(tile, key, a.tol, a.feather)
            tile = fit_bbox(tile) if a.fit == "bbox" else trim(tile, a.pad)
        if a.fit == "bbox":
            k = a.size / max(tile.size)
            tile = tile.resize((max(1, int(tile.width * k)), max(1, int(tile.height * k))),
                               Image.LANCZOS)
        else:
            tile = tile.resize((a.size, a.size), Image.LANCZOS)
        if a.seamless:
            tile = seamless(tile)
        name = names[i] if i < len(names) else f"{i:02d}"
        if name == "-":                                 # a cell we do not want
            continue
        path = os.path.join(a.out, f"{a.prefix}_{name}.png")
        tile.save(path)
        wrote.append(os.path.basename(path))
        if names and i + 1 >= len(names):
            break
    print(f"{len(wrote)} -> {a.out}/  {' '.join(wrote)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
