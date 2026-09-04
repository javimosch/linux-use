# sheetgen — generated image assets, no API key, no LLM in the loop

Ask a signed-in image model for **one contact sheet** and cut it into N named
files. Driven through [linux-use](https://github.com/javimosch/linux-use) on a
private X display, so the browser session you already have *is* the API.

```sh
./session.sh up                     # browser on its own display
./run.py jobs/*.json                # generate everything missing
./session.sh down                   # ALWAYS
```

```sh
./run.py --dry-run jobs/*.json      # what would be generated
./run.py --force   jobs/one.json    # regenerate even if it exists
./run.py --recut   jobs/*.json      # re-slice saved sheets, generate nothing
./run.py --root /path/to/repo jobs/*.json
```

Paths in a job's `out` resolve against `--root` / `$GEN_ROOT` / the current
directory; captured sheets go to `$GEN_SHEETS` (default `docs/sheets/`).

## A job is data

```json
{
  "name": "unit_blue",  "out": "assets/sprites",  "prefix": "unit_blue",
  "grid": 2,            "size": 256,              "chroma": "auto",
  "names": ["inf", "light", "tank", "wreck"],
  "prompt": "... a 2x2 grid of four tokens seen from DIRECTLY ABOVE ... Every cell is filled edge to edge with a FLAT PURE MAGENTA background, hex FF00FF ..."
}
```

Adding an asset is adding a file. `grid` × `grid` tiles are cut and written as
`<out>/<prefix>_<name>.png`; a name of `-` throws that cell away. Options:
`chroma` (`auto` or a hex — key the background to transparency), `seamless`
(mirror a texture so it tiles), `fit` (`square` or `bbox`), `tol`, `feather`,
`pad`, `inset`, `edge`, `timeout`.

Three example jobs are included: portraits (photographic, opaque), sprites
(flat art, chroma-keyed), textures (photographic, seamless).

## Why sheets

**One prompt, sixteen assets.** Not a quota trick — it is the only reliable
thing you can do to an image a model hands you. It will not honour an aspect
ratio and will not return sixteen files, but a square canvas cut into N×N
squares is N×N squares whatever it decided to draw inside them, and the cutting
is arithmetic, which cannot fail in an interesting way.

## Determinism, such as it is

The *model* is not deterministic and this does not pretend otherwise. What is
deterministic is everything after the pixels arrive, and that is where the
value is:

- **Resumable.** A job whose outputs all exist is skipped, so a queue stopped
  by a quota limit, a refusal or a closed laptop restarts with the same
  command. Failures are collected and the queue keeps going — one refusal must
  not cost the rest.
- **Sheets are kept.** `--recut` re-slices what is already in the sheet store.
  A bad *cut* therefore costs seconds instead of a generation, which means the
  cutter can be fixed and re-run for free. In practice this is the single most
  valuable property: it paid for itself twice in one afternoon.
- **Cutting, keying, trimming and tiling are pure functions** of the sheet.
  Same sheet in, same assets out, forever.

## What cut.py does after the cutting

**Chroma key with the key MEASURED, not assumed.** Asking for `#FF00FF` gets
you *approximately* magenta: a vignette, a gradient, a hint of shadow. So
`"chroma": "auto"` takes the modal colour of a ring around each tile's own
border and keys on that.

**Un-mix the feathered band, don't darken it.** An edge pixel is
`a·subject + (1−a)·key`, so the subject is `(observed − (1−a)·key) / a`.
Nudging the channels down by a fudge factor leaves a fringe that is invisible
at 100% and unmistakable at the 12% a game actually draws a sprite at.

**Normalise the subject to its own bounding box.** A model given sixteen cells
fills each to a different extent; without this one tree is 90% of its tile and
its neighbour 40%, and "this asset is 4 metres across" stops meaning anything.

**Two fits, and the choice matters.** `square` (crop to bbox, pad back to a
square) for anything scaled by one size — a tree, a unit. `bbox` (keep natural
proportions) for anything *stretched* to a rectangle the caller already knows —
a roof over a building footprint. Squaring a wide roof adds transparent margins,
and stretching that leaves a border all the way round it.

**`seamless` mirrors a tile out to 2×** so it repeats with no seam and no
inpainting. Per-job, never default: the result is symmetric about its middle,
which is invisible on grass and earth and turns cobbles into a mandala.

## Driving the page: the five that actually matter

**1. Never carry a `linux-use` ref between two calls.** The DOM restages on
every animation and a ref is a path of child indices, so a ref captured a second
ago is usually stale — and the tool refusing to act on it is the tool being
**correct**. Look up and act inside one call.

**2. The image's Download button cannot be fired synthetically.** `act` returns
`ok` and does nothing. `click` demonstrably lands — the tooltip appears in a
screenshot — and does nothing. Nor does the right-click menu, `Copy image` (the
clipboard keeps its previous contents), two clicks in a row, or hovering first.
The sheet is taken off the **screen**, cropped to the exact rectangle the
accessibility tree reports for the `image` element.

**3. Capture the browser's own window, never the root window.** `import -window
root` grabs whatever is stacked on top. Another program drawing on the same
display while a job captured once wrote a sheet of *its* pixels, which sliced
into perfectly clean unusable assets with no error anywhere. This captures the
browser by window id **and** runs on its own display (`:98`) — the first fixes
the symptom, the second the cause.

**4. Wheel events scroll a page that keys cannot.** `Page_Down` and `End` do
nothing because the chat's scroll container never takes keyboard focus, but
`click --button 5` works: a wheel event goes to whatever is under the pointer.
The sheet is taller than the viewport, so this is the only way to get it all
into one frame. `run.py` scrolls until `y + h < 900`, because the composer bar
floats over the bottom and otherwise eats the last row of tiles.

**5. Return in the composer silently fails**, often enough to matter — the text
just sits there and the job waits its whole timeout for an image nobody asked
for. `submit()` therefore verifies the send by looking for the prompt in the
**conversation** rather than trusting the keystroke, and retries, re-clicking
the composer each time (the paste re-renders the input and the click is what
restores focus).

There is a sixth, smaller one: the image's share/copy/download toolbar is drawn
**on hover** over the top-right tile, so the pointer is parked off the image
before the capture. Leave it there and one tile comes back with a download icon
baked into it.

## Session

`session.sh` runs Chrome on a private Xvfb display on its **default profile** —
a dedicated `--user-data-dir` starts logged out and there is no password to
type. Chrome must not already be running; one process owns the profile. Two
requirements are absolute: `--force-renderer-accessibility`, without which
Chromium exposes exactly one `frame` and zero web content and which cannot be
applied retroactively; and a **window manager** on that display, without which
X input focus is unset and no keystroke lands.

**`down` is not housekeeping.** Leaving it up means the next ordinary Chrome
launch surfaces the invisible instance and looks broken.

It matches its own browser by **pidfile**, falling back to
`google-chrome.*--force-renderer-accessibility`. Never match the flag alone —
other browsers on the machine may carry it for unrelated work, and a
`pkill -f force-renderer-accessibility` takes them down too. That mistake has
been made.

## Requirements

`linux-use`, Google Chrome (signed in), `Xvfb`, a window manager (`xfwm4`),
ImageMagick (`import`, `xwininfo`), Python 3 with Pillow.

## Limits, honestly

- The page renders any sheet at a fixed size (708px in the Gemini web app), so
  a 4×4 gives ~177px a tile and a 2×2 ~354px. Fine for anything drawn small;
  not a source of print-resolution art.
- Not CI-able and not meant to be. It needs a signed-in browser and a display.
  What it produces is meant to be committed.
- The model can refuse. `run.py` records the page's reply, marks the job
  failed, and keeps going.
