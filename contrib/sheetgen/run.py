#!/usr/bin/env python3
"""run.py -- generate images through a signed-in browser, unattended.

One image:

    tools/gen/session.sh up
    tools/gen/run.py --image "a lunar rover, 1930s poster style" --out art/rover.png

A queue of asset jobs:

    tools/gen/run.py tools/gen/jobs/*.json
    tools/gen/run.py --force tools/gen/jobs/unit_blue.json
    tools/gen/run.py --dry-run tools/gen/jobs/*.json
    tools/gen/session.sh down

A job is DATA, not a script: prompt, grid, tile names, how to cut. That is the
whole point -- adding an asset means adding a file, and running the queue costs
nothing but wall-clock. Nothing in here needs a language model to supervise it.

Resumable by construction: a job whose outputs all exist is skipped, so a run
interrupted by a quota limit, a refusal or a closed laptop is restarted with
the same command and picks up where it stopped.

Everything about driving the page that is load-bearing is documented in
tools/gen/README.md. The three that will bite anyone editing this file:
  * never reuse a linux-use ref across two calls -- the DOM restages constantly
  * the image's Download button cannot be fired synthetically; the sheet is
    captured off the screen at the rect AT-SPI reports for the image element
  * wheel events scroll a page that Page_Down cannot
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cut  # noqa: E402  (same directory, deliberately)

from PIL import Image  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
# Where a job's `out` and the sheet store are resolved from. Defaults to the
# current working directory so the tool is not tied to any one repo's layout;
# --root or GEN_ROOT overrides it.
ROOT = os.environ.get("GEN_ROOT") or os.getcwd()
SHEETS = os.environ.get("GEN_SHEETS") or os.path.join("docs", "sheets")
# The generator gets its OWN display. It used to share :99 with the game's
# headless screenshots, and `import -window root` grabs whatever is on top --
# so a build that rendered a frame while a job was capturing wrote a sheet of
# GAME PIXELS, which sliced cleanly into nine unusable "roofs". Capturing the
# browser window by id (below) fixes the symptom; not sharing a display with
# anything else fixes the cause.
DISPLAY = os.environ.get("GEN_DISPLAY", ":98")
APP = "Google Chrome"
# The composer bar floats over the bottom of the viewport. A sheet whose bottom
# edge is below this line comes back with its last row of tiles eaten.
SAFE_BOTTOM = 900


def lu(*args, check=False):
    env = dict(os.environ, DISPLAY=DISPLAY)
    r = subprocess.run(["linux-use", *args], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"linux-use {args[0]}: {r.stdout.strip() or r.stderr.strip()}")
    return r


def find_act(verb, query, role=None):
    """Look the element up and act on it inside ONE call.

    Gemini restages its DOM on every animation and a linux-use ref is a path of
    child indices, so a ref captured even a second ago is usually stale -- and
    the tool refusing to act on a stale ref is the tool being CORRECT, not
    broken. Carrying refs between calls is the single biggest source of
    flakiness in driving this page."""
    els = state()
    q = query.lower()
    for e in els:
        if q in (e.get("name") or "").lower() and (role is None or e.get("role") == role):
            return lu(verb, e["ref"])
    return None


def state():
    r = lu("state", "--app", APP, "--all", "--depth", "50")
    try:
        return json.loads(r.stdout).get("elements", [])
    except (ValueError, TypeError):
        return []


# Anything narrower than this is a thumbnail, an avatar, a citation card or a
# placeholder that has not painted yet -- not the generated image.
MIN_IMAGE = 420


def image_geometry(els=None):
    """The rect of the generated image, as the page reports it."""
    for e in els if els is not None else state():
        if e.get("role") == "image" and (e.get("w") or 0) >= MIN_IMAGE:
            return e["x"], e["y"], e["w"], e["h"]
    return None


def page_text(els, limit=6):
    out = []
    for e in els:
        if e.get("role") == "static" and (e.get("x") or 0) > 500 and (e.get("y") or 0) > 300:
            t = (e.get("name") or "").strip()
            if len(t) > 24:
                out.append(t)
    return " / ".join(out[:limit])


def wheel(x, y, up=False):
    lu("click", "--x", str(x), "--y", str(y), "--button", "4" if up else "5")


def sent(prompt):
    """Has the prompt actually left the composer?

    Pressing Return in the composer submits -- except when it does not, which
    happens often enough to matter and silently: the text simply sits there and
    the job then waits five minutes for an image that was never asked for. The
    only trustworthy evidence is the prompt appearing in the CONVERSATION, at
    the top of the page rather than down in the composer, so that is what is
    checked."""
    head = prompt[:40].lower()
    for e in state():
        if e.get("role") in ("static", "paragraph") and (e.get("y") or 9999) < 380:
            if head in (e.get("name") or "").lower():
                return True
    return False


def submit(prompt, tries=3):
    find_act("act", "new chat")
    time.sleep(4)
    if find_act("click", "enter a prompt") is None:
        raise RuntimeError("composer not found -- is the session up and signed in?")
    time.sleep(1)
    lu("paste", prompt, check=True)
    time.sleep(2)
    for attempt in range(tries):
        # Re-click the composer before every Return. The paste re-renders the
        # input and the click is what puts keyboard focus back into it; without
        # it the Return lands nowhere and reports success.
        find_act("click", "enter a prompt")
        time.sleep(1)
        lu("key", "Return", check=True)
        for _ in range(8):
            time.sleep(2)
            if sent(prompt):
                return
        print(f"   submit did not take, retrying ({attempt + 1}/{tries})", file=sys.stderr)
    raise RuntimeError("the prompt would not submit -- it is still in the composer")


def await_image(timeout=300):
    """Wait for the image to appear AND to stop changing size.

    The element exists before it has painted: one run captured a 334x206 black
    placeholder, sliced it, and wrote two solid-black "heroes" without a word
    of complaint. So appearing is not enough -- the geometry has to be stable
    across two polls before the picture is really there."""
    deadline = time.time() + timeout
    last = None
    stable = 0
    while time.time() < deadline:
        time.sleep(5)
        els = state()
        g = image_geometry(els)
        if not g:
            last = None
            stable = 0
            continue
        if g == last:
            stable += 1
            if stable >= 2:
                return g, els
        else:
            stable = 0
        last = g
    return None, state()


def bring_into_view():
    for _ in range(14):
        g = image_geometry()
        if not g:
            return None
        x, y, w, h = g
        if y + h < SAFE_BOTTOM:
            return g
        wheel(1100, 600)
        time.sleep(1)
    return image_geometry()


def browser_window():
    """The X id of the browser's own top-level window.

    Capturing the ROOT window captures whatever happens to be stacked on top
    of it, which is fine right up until something else opens a window on the
    same display -- and then the sheet is a picture of that instead, sliced
    into perfectly clean nonsense. Asking for the browser's own window makes
    the capture independent of stacking."""
    env = dict(os.environ, DISPLAY=DISPLAY)
    r = subprocess.run(["xwininfo", "-root", "-children"],
                       capture_output=True, text=True, env=env)
    best = None
    for line in r.stdout.splitlines():
        if "Google Chrome" in line and line.strip().startswith("0x"):
            wid = line.strip().split()[0]
            # the widest match: Chrome also owns small helper windows
            try:
                geo = line.split(")")[-1].strip().split("+")[0]
                width = int(geo.split("x")[0])
            except (ValueError, IndexError):
                continue
            if best is None or width > best[1]:
                best = (wid, width)
    return best[0] if best else "root"


def capture(path):
    # Park the pointer OFF the image first: its share/copy/download toolbar is
    # drawn on hover over the top-right tile and would be baked into the crop.
    wheel(1750, 950, up=True)
    time.sleep(2)
    g = image_geometry()
    if not g:
        raise RuntimeError("the image vanished between scrolling and capturing")
    x, y, w, h = g
    shot = "/tmp/gen-screen.png"
    subprocess.run(["import", "-window", browser_window(), shot],
                   env=dict(os.environ, DISPLAY=DISPLAY), check=True)
    im = Image.open(shot)
    if im.width < x + w or im.height < y + h:
        raise RuntimeError(f"capture is {im.size}, image rect is {(x, y, w, h)}")
    crop = im.crop((x, y, x + w, y + h))
    blank(crop)
    crop.save(path)
    return w, h


def blank(im):
    """Refuse a frame that is all one colour.

    The cheapest possible check for the failure mode that costs the most: a
    placeholder, a blanked compositor or a capture of the wrong thing produces
    a uniform rectangle, which slices into perfectly clean assets that are
    perfectly useless. Anything genuinely generated has spread in at least one
    channel."""
    ext = im.convert("RGB").getextrema()
    spread = max(hi - lo for lo, hi in ext)
    if spread < 12:
        raise RuntimeError(f"captured a blank frame (channel spread {spread}) -- "
                           "the image had not painted yet")


# ── one image, no job file ───────────────────────────────────────────────
# Everything else here is built around asking for a GRID and cutting it, which
# is the right shape for game assets and the wrong shape for "I want a
# picture of X". A single image is that same machinery with grid 1, nothing
# keyed out, nothing trimmed, and no resize -- so it is expressed as a job
# rather than as a second code path, and gets the same submit-verification,
# scrolling and window capture for free.
def one_shot(prompt, out, size=0, edge=14):
    out = os.path.abspath(out)
    stem, ext = os.path.splitext(os.path.basename(out))
    return {
        "name": stem or "image",
        "prompt": prompt,
        "out": os.path.dirname(out) or ".",
        "prefix": stem or "image",
        "grid": 1,
        "size": size,
        "inset": 0,
        "fit": "bbox",
        # The page draws images in a container with ROUNDED CORNERS, and the
        # capture is a rectangle, so a few pixels of the container's dark
        # background come with every corner. For a grid that lands inside cells
        # the inset already trims; for a single image it is the picture's own
        # corners, so it has to be trimmed here and it has to be enough to
        # clear the radius.
        "edge": edge,
        "_single": out,
    }


def outputs(job):
    if job.get("_single"):
        return [job["_single"]]
    names = job.get("names") or [f"{i:02d}" for i in range(job.get("grid", 4) ** 2)]
    d = os.path.join(ROOT, job["out"])
    return [os.path.join(d, f"{job['prefix']}_{n}.png") for n in names if n != "-"]


def cut_sheet(job, sheet):
    if job.get("_single"):
        # A grid of one, cut to the frame the page actually drew. The sheet is
        # already exactly the image; copying it through the cutter keeps the
        # edge trim (the page draws images in a rounded container) in one place.
        dst = job["_single"]
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        im = Image.open(sheet)
        e = int(job.get("edge", 14))
        if e > 0:
            im = im.crop((e, e, im.width - e, im.height - e))
        if job.get("size"):
            k = job["size"] / max(im.size)
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))),
                           Image.LANCZOS)
        im.save(dst)
        print(f"   1 -> {dst}  ({im.width}x{im.height})")
        return
    args = [sheet, "--out", os.path.join(ROOT, job["out"]), "--prefix", job["prefix"],
            "--grid", str(job.get("grid", 4)), "--size", str(job.get("size", 256))]
    if job.get("names"):
        args += ["--names", ",".join(job["names"])]
    for k in ("chroma", "tol", "feather", "pad", "inset", "edge", "fit"):
        if k in job:
            args += [f"--{k}", str(job[k])]
    if job.get("seamless"):
        args += ["--seamless"]
    saved = sys.argv
    sys.argv = ["cut.py", *args]
    try:
        cut.main()
    finally:
        sys.argv = saved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs", nargs="*")
    ap.add_argument("--image", default="", help="a single prompt; skips job files")
    ap.add_argument("--out", default="", help="where --image is written")
    ap.add_argument("--size", type=int, default=0,
                    help="longest side for --image; 0 keeps what the page rendered")
    ap.add_argument("--edge", type=int, default=14,
                    help="pixels trimmed off each side of a --image capture, to "
                         "clear the rounded corners of the page's image container")
    ap.add_argument("--force", action="store_true", help="regenerate even if the assets exist")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", default="", help="resolve job `out` paths against this "
                                               "directory (default: $GEN_ROOT, else cwd)")
    ap.add_argument("--sheets", default="", help="where captured sheets are kept "
                                                 "(default: $GEN_SHEETS, else docs/sheets)")
    ap.add_argument("--recut", action="store_true",
                    help="re-cut the sheets already in the sheet store, generating nothing")
    a = ap.parse_args()
    global ROOT, SHEETS
    if a.root:
        ROOT = a.root
    if a.sheets:
        SHEETS = a.sheets

    if a.image:
        if not a.out:
            print("--image needs --out", file=sys.stderr)
            return 2
        jobs = [(a.out, one_shot(a.image, a.out, a.size, a.edge))]
    else:
        if not a.jobs:
            print("give job files, or --image PROMPT --out PATH", file=sys.stderr)
            return 2
        jobs = []
        for pat in a.jobs:
            for p in sorted(glob.glob(pat)) or [pat]:
                with open(p) as fh:
                    jobs.append((p, json.load(fh)))

    failed = []
    for p, job in jobs:
        name = job.get("name") or os.path.splitext(os.path.basename(p))[0]
        outs = outputs(job)
        sheet = os.path.join(ROOT, SHEETS, f"{name}.png")
        have = all(os.path.exists(o) for o in outs)

        if a.dry_run:
            print(f"{'skip' if have else 'GEN '} {name:16s} {len(outs)} assets -> {job['out']}")
            continue
        if a.recut:
            if os.path.exists(sheet):
                print(f"== {name}: re-cutting")
                cut_sheet(job, sheet)
            else:
                print(f"== {name}: no sheet at {sheet}")
            continue
        if have and not a.force:
            print(f"== {name}: {len(outs)} assets already present, skipping")
            continue

        print(f"== {name}: prompting")
        try:
            submit(job["prompt"])
            g, els = await_image(job.get("timeout", 300))
            if not g:
                why = page_text(els)
                print(f"   NO IMAGE. page said: {why[:400]}", file=sys.stderr)
                failed.append((name, "no image"))
                continue
            if not bring_into_view():
                failed.append((name, "could not scroll into view"))
                continue
            os.makedirs(os.path.dirname(sheet), exist_ok=True)
            w, h = capture(sheet)
            print(f"   captured {w}x{h} -> {os.path.join(SHEETS, name)}.png")
            cut_sheet(job, sheet)
        except Exception as exc:                      # keep the queue moving
            print(f"   FAILED: {exc}", file=sys.stderr)
            failed.append((name, str(exc)))

    if failed:
        print("\nfailed:", file=sys.stderr)
        for n, why in failed:
            print(f"  {n}: {why}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
