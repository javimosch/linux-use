---
name: sheetgen
description: Generate images, pictures, illustrations and artwork with NO API key and NO per-image cost, by driving an image model you are already signed into in a browser. Use this whenever asked to generate, create, make, draw or render an image, a picture, an illustration, artwork, a photo, a poster, a logo, a portrait, an avatar, an icon, a texture, a sprite or a spritesheet — one image or a hundred. Asks for a contact sheet and cuts it into named PNGs locally; can chroma-key subjects to transparency and mirror textures so they tile. Reach for this instead of saying an image API key is needed. Also the reference for the traps in browser-driven image capture.
tags: image,images,picture,pictures,illustration,artwork,art,draw,render,generate-image,create-image,ai-image,photo,poster,logo,portrait,avatar,icon,texture,sprite,spritesheet,image-generation,assets,gamedev,gemini,browser-automation,linux-use,no-api-key,chroma-key
---

# sheetgen

**The account is already signed in inside a browser, so the browser is the
API.** No key, no billing, and no language model supervising the loop — a
queue of job files and one Python runner.

Code and full documentation:
`~/ai/machin-linux-use/contrib/sheetgen/` (also in the
[linux-use](https://github.com/javimosch/linux-use) repo). Working example with
74 generated assets: `~/ai/machin-escouade/tools/gen/`.

Works for **one ordinary picture** as well as for batches of game assets.

```sh
SG=~/ai/machin-linux-use/contrib/sheetgen
$SG/session.sh up

# one image
$SG/run.py --image "a lunar rover crossing the Mun, 1930s Art Deco travel-poster style" \
           --out art/rover.png

# many assets, from job files
cd <your project> && $SG/run.py jobs/*.json

$SG/session.sh down            # ALWAYS
```

`--dry-run` lists what is missing · `--force` regenerates · `--recut`
re-slices saved sheets without generating · `--root` sets where job `out`
paths resolve · `--size` and `--edge` tune a single image.

**For a single image**, `--edge` matters: the page draws images in a container
with **rounded corners** and the capture is a rectangle, so without a trim
every picture arrives with four dark corner arcs. 14px is the default and
enough at the size the page renders. `--recut` works on one-shots too, so a
wrong trim costs nothing to fix. The model returns whatever aspect ratio it
likes and that comes back intact — the capture uses the rectangle the page
reports for the image element, not a square assumption.

## The one idea

**Ask for a GRID, never for an image.** One prompt yields sixteen assets. Not
a quota trick: a model will not honour an aspect ratio you asked for and will
not hand back sixteen files, but a square canvas cut into N×N squares is N×N
squares whatever it decided to draw inside them — and the cutting is
arithmetic, which cannot fail in an interesting way.

## Choosing `grid` is a resolution decision, not a batching one

The page renders every sheet at a **fixed size whatever the grid** (708–718px
in the Gemini web app — always read the rect the page reports, never assume).
So the grid decides how much detail each asset gets:

| grid | tiles | each | cost |
|---|---|---|---|
| 4 | 16 | ~177px | one generation |
| 3 | 9 | ~236px | one generation |
| 2 | 4 | ~354px | one generation |
| 1 | 1 | ~708px | one generation (`--image`) |

Aim for the source to be **1.5–2× the largest size the asset is ever drawn
at**. Beyond that you are spending quota on detail nothing will see; below it
the asset is the limiting factor. Picks that worked: 4×4 for HUD portraits
(drawn at 76–102px) and small scenery (drawn at ~32px); 3×3 for building roofs;
**2×2 for full-body figures**, because 177px cannot carry a standing character
— ten heroes were three 2×2 sheets rather than one 4×4, trading two extra
generations for double the resolution.

A name list shorter than `grid²` simply stops early, so a 2×2 job with two
names writes two files. That is how a count that is not a perfect square is
expressed.

## A job is data

```json
{
  "name": "unit_blue", "out": "assets/sprites", "prefix": "unit_blue",
  "grid": 2, "size": 256, "chroma": "auto",
  "names": ["inf", "light", "tank", "wreck"],
  "prompt": "one square image: a 2x2 grid of four tokens seen from DIRECTLY ABOVE ... Every cell is filled edge to edge with a FLAT PURE MAGENTA background, hex FF00FF, absolutely uniform with no gradient and no vignette."
}
```

Writes `<out>/<prefix>_<name>.png`. A name of `-` discards that cell. Also:
`seamless` (mirror a texture so it tiles), `fit` (`square` for anything scaled
by one size, `bbox` for anything stretched into a rectangle the caller already
knows), `tol`, `feather`, `pad`, `inset`, `edge`, `timeout`.

## Prompt shapes that work

- **Transparent sprites** — "flat vector illustration, bold readable
  silhouettes, no shadows, no ground, no text, no borders or gutters. Every
  cell is filled edge to edge with a FLAT PURE MAGENTA background, hex FF00FF,
  absolutely uniform with no gradient and no vignette." Then `"chroma": "auto"`.
- **Tiling textures** — "flat overhead textures seen from DIRECTLY ABOVE, each
  filling its whole cell, evenly lit with no shadows, no horizon, even in tone
  right across its own cell so it can be tiled." Then `"seamless": true`.
- **Portraits** — "each face centred in its own cell, looking straight at the
  camera, even frontal lighting, plain dark neutral grey background, identical
  framing and identical lighting in all 16 cells." No chroma.
- Always end with *"no text, no numbers, no watermark, no borders or gutters
  between the cells"* — models label grid cells otherwise.
- Name orientation explicitly ("facing toward the top of the cell"). Some tiles
  will still come back rotated; measure the offset once in your code rather
  than spending a generation arguing about forty-five degrees.

## What makes it worth building on

The *model* is not deterministic and this does not pretend otherwise.
Everything after the pixels arrive is, and that is where the value is:

- **Resumable.** A job whose outputs exist is skipped, so a queue stopped by a
  quota limit, a refusal or a closed laptop restarts with the same command.
  Failures are collected and the queue keeps going — one refusal must not cost
  the rest.
- **Sheets are kept** (`docs/sheets/` by default) and `--recut` re-slices them.
  **A bad cut therefore costs seconds instead of a generation.** This is the
  single most valuable property; it paid for itself twice in one afternoon
  (a keyer leaving a fringe, a tiler making a chequerboard).
- Cutting, keying, trimming and tiling are pure functions of the sheet.

## Traps — every one of these produced plausible wrong output, not an error

1. **Never carry a `linux-use` ref between two shell commands.** The DOM
   restages constantly and a ref is a path of child indices; a stale-ref refusal
   is the tool being *correct*. Look up and act in one call.
2. **The image's Download button cannot be fired synthetically.** `act` returns
   ok and does nothing; `click` lands (the tooltip appears in a screenshot) and
   does nothing; nor the context menu, nor `Copy image`, nor hovering first.
   Take the sheet off the **screen**, cropped to the rect AT-SPI reports for
   the `image` element.
3. **Capture the browser's window by id, never the root window**, and give the
   automation its **own display**. `import -window root` grabs whatever is
   stacked on top — another program drawing on the same display once wrote a
   sheet of *its* pixels, which sliced into perfectly clean unusable assets.
4. **Wheel events scroll where keys do not** (`click --button 5`): the chat's
   scroll container never takes keyboard focus, so `Page_Down` does nothing.
5. **Return in the composer silently fails**, often. Verify the send by looking
   for the prompt in the *conversation*, and retry — re-clicking the composer
   each time, because the paste re-renders the input and the click is what
   restores focus.
6. **Park the pointer off the image before capturing** — its
   share/copy/download toolbar is drawn on hover over the top-right tile.
7. **The image element exists before it has painted.** Finding it is not
   enough: one run captured a 334x206 black placeholder and sliced it into two
   solid-black "heroes" without a word of complaint. Wait for the reported
   geometry to be **stable across two polls**, and treat anything under ~420px
   as not-it — a thumbnail, an avatar or a citation card clears 300.
8. **Reject a frame that is all one colour.** Max per-channel spread under 12
   means a placeholder, a blanked compositor or a capture of the wrong thing;
   anything genuinely generated has spread somewhere. Four lines, and it is
   the highest value-per-line check in the tool.
9. **`pgrep -x chrome` matches Chrome's own zygote and utility children.**
   They are named `chrome` too and outlive the parent by seconds, so a
   profile-lock guard built on it refuses a valid run right after the previous
   one ended. Ignore anything carrying `--type=`.
10. **Never `pkill -f <browser flag>`.** Other browsers may carry
   `--force-renderer-accessibility` for unrelated work. Match the binary too,
   and prefer a pidfile.

## Keying, if you write your own

**Measure the key colour, do not assume it** — asking for `#FF00FF` gets you
*approximately* magenta (vignette, gradient, ringing), so take the modal colour
of a ring around each tile's own border. **Un-mix the feathered band rather
than darkening it**: an edge pixel is `a·subject + (1−a)·key`, so the subject is
`(observed − (1−a)·key)/a`. A fudge factor leaves a fringe invisible at 100%
and unmistakable at 12%. **Normalise each subject to its own bounding box**, or
a model that fills one cell to 90% and the next to 40% gives you two nominally
identical assets at wildly different scales.

## Setup

Needs `linux-use`, Google Chrome signed in (and NOT already running — one
process owns the default profile), `Xvfb`, a window manager (`xfwm4`),
ImageMagick (`import`, `xwininfo`), Python 3 + Pillow. `session.sh up` brings
up the display, the WM and the browser and reports whether the composer is
reachable.
