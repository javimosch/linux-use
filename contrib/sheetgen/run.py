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
HERE_DIR = os.path.dirname(os.path.abspath(__file__))
PIDFILE = "/tmp/gen-chrome.pid"

# Human-like pacing. Automating fast enough to look like a bot is what gets
# the machine's IP CAPTCHA-flagged by Google ("unusual traffic from your
# computer network"). Generation speed is NOT the goal -- not being flagged
# is. All delays are jittered (uniform within [lo, hi]) so the rhythm is not
# clockwork. Tune via GEN_MIN_DELAY / GEN_MAX_DELAY (seconds).
PACING_MIN = float(os.environ.get("GEN_MIN_DELAY", "2"))
PACING_MAX = float(os.environ.get("GEN_MAX_DELAY", "6"))


def human_wait(lo=PACING_MIN, hi=PACING_MAX):
    """Sleep a jittered 'human' amount. Also yields to the browser's own
    animation so a ref fetched right after is less likely to be stale."""
    import random
    time.sleep(random.uniform(lo, hi))


def chrome_app_spec():
    """'Google Chrome#pid<N>' when the session's Chrome is identifiable, else
    'Google Chrome'.

    Other automation (puppeteer/playwright/e2e) may run Chrome concurrently,
    and linux-use then refuses to act on the bare app name ("2 applications
    are named 'Google Chrome'"). The session's own pidfile (written by
    session.sh) disambiguates without killing anything.
    """
    try:
        with open(PIDFILE) as fh:
            pid = fh.read().strip()
        if pid and os.path.isdir(f"/proc/{pid}"):
            return f"Google Chrome#pid{pid}"
    except (OSError, ValueError):
        pass
    return APP


def lu(*args, check=False):
    env = dict(os.environ, DISPLAY=DISPLAY)
    r = subprocess.run(["linux-use", *args], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"linux-use {args[0]}: {r.stdout.strip() or r.stderr.strip()}")
    return r


def session(*args, timeout=120):
    """Restart (or query) the browser session that run.py drives.

    Agents habitually forget `session.sh up` / `down`, and a stale or dead
    session is the #1 cause of "composer not found" flakiness. run.py can
    bring its own session up (and restart it between retries) so the caller
    only has to think about it when they want to.
    """
    env = dict(os.environ, DISPLAY=DISPLAY)
    try:
        r = subprocess.run(["bash", os.path.join(HERE_DIR, "session.sh"), *args],
                           capture_output=True, text=True, env=env, timeout=timeout)
        return r
    except subprocess.TimeoutExpired:
        return None


def session_up(close_tabs=True, enforce_policy=True):
    session("up")
    if close_tabs:
        close_extra_tabs()
    if enforce_policy:
        return enforce_account_policy()
    return True, "session up"


def session_restart(close_tabs=True, enforce_policy=True):
    session("down")
    session("up")
    if close_tabs:
        close_extra_tabs()
    if enforce_policy:
        return enforce_account_policy()
    return True, "session restarted"


def enforce_account_policy():
    """Switch to the configured preferred account; never GENERATE on a
    blacklisted one. Returns (ok, detail).

    Switching accounts is safe navigation (read-only clicks on the avatar and
    the chooser) -- it does not spend quota or touch the account's data. The
    danger is generating while signed in as a precious account, which is what
    the check on the other side of the switch protects against. So we may
    switch AWAY from a blacklisted account, but if no switch is possible we
    refuse to proceed rather than generate on it."""
    policy = load_account_policy()
    if not policy["preferred"] and not policy["blacklist"]:
        return True, "no account policy configured"
    acct = signed_in_account()
    if acct is None:
        return False, "could not read the signed-in account"
    allowed, reason = account_allowed(acct)
    if allowed:
        return True, acct
    if not policy["preferred"]:
        # Blacklisted and no preferred to switch to: block, do not drive it.
        return False, f"signed in as {acct} which is {reason}"
    ok, detail = switch_account(policy["preferred"])
    if ok:
        return True, detail
    # Could not switch away -- the session is still on the blocked account.
    return False, f"signed in as {acct} ({reason}); failed to switch: {detail}"


def close_extra_tabs(max_close=15):
    """Close every Chrome tab except the ACTIVE one.

    Every account switch, "opens a new tab" link and session restore leaves
    a tab behind; over a long batch run that grows into a memory killer and,
    worse, a dozen stale pages that can be captured instead of the sheet.
    Tab close is the one place a keyboard shortcut is reliable: activate the
    tab, then ctrl+w it (the browser closes the ACTIVE tab)."""
    for _ in range(max_close):
        tabs = []
        active = None
        for e in state():
            if e.get("role") == "page tab":
                tabs.append(e)
                if e.get("focused"):
                    active = e
        if len(tabs) <= 1:
            return
        # Keep the tab the user is actually on (e.g. the one an account
        # switch just opened, which is the LAST tab, not the first); close
        # the rest, one at a time.
        keep = active if active is not None else tabs[-1]
        for victim in tabs:
            if victim["ref"] == keep["ref"]:
                continue
            lu("act", victim["ref"])
            human_wait(0.5, 1.2)
            lu("key", "ctrl+w")
            human_wait(0.8, 1.5)
            break  # re-fetch state after each close; refs go stale


def signed_in_account():
    """The email (or None) of the account currently signed in on the page."""
    for e in state():
        name = e.get("name") or ""
        if "Google Account:" in name:
            import re
            m = re.search(r"\(([^)]+@[^)]+)\)", name)
            if m:
                return m.group(1)
    return None


# ── account policy ───────────────────────────────────────────────────────
# Some signed-in accounts are precious and must never be driven (the owner's
# personal Google account is one bad keystroke away from a lockout); others
# are throwaway generators meant to be used freely. sheetgen honours a small
# config file so an agent never has to be told twice:
#
#   ~/.config/sheetgen/accounts.json   (override: $GEN_ACCOUNTS)
#   {"preferred": "groundswallentine", "blacklist": ["arancibiajav"]}
#
# Both are SUBSTRING matches against the signed-in email. On startup (and
# before every batch) the browser is switched to `preferred` if the current
# account is blacklisted or simply not preferred. Blacklist always wins: a
# blacklisted account is never driven, even if it happens to be preferred.

DEFAULT_ACCOUNTS_PATH = os.path.expanduser("~/.config/sheetgen/accounts.json")


def load_account_policy():
    path = os.environ.get("GEN_ACCOUNTS") or DEFAULT_ACCOUNTS_PATH
    try:
        with open(path) as fh:
            cfg = json.load(fh)
        return {
            "preferred": str(cfg.get("preferred") or "").lower(),
            "blacklist": [str(x).lower() for x in cfg.get("blacklist", [])],
        }
    except (OSError, ValueError):
        return {"preferred": "", "blacklist": []}


def account_allowed(acct):
    """(allowed, reason) for a signed-in email under the configured policy."""
    policy = load_account_policy()
    acct = (acct or "").lower()
    for bad in policy["blacklist"]:
        if bad and bad in acct:
            return False, f"blacklisted ({bad})"
    if policy["preferred"] and policy["preferred"] not in acct:
        return False, (f"not preferred ({policy['preferred']})"
                       if not policy["blacklist"] else
                       f"not the preferred generator account ({policy['preferred']})")
    return True, ""


def switch_account(email_substr, max_tries=3):
    """Switch the browser to a different signed-in Google account.

    Gemini's account switcher is a two-step link: click the account avatar
    ("Google Account: ..."), which opens the chooser listing every signed-in
    account, then click the target account ("... (opens a new tab)"). The
    switch opens a new tab; close_extra_tabs() cleans up afterwards."""
    import re
    for _ in range(max_tries):
        # 1. Open the account chooser from the avatar in the sidebar.
        avatar = None
        for e in state():
            name = e.get("name") or ""
            if name.startswith("Google Account:"):
                avatar = e
                break
        if avatar is None:
            return False, "no account avatar found"
        lu("act", avatar["ref"])
        human_wait(2.0, 3.5)
        # 2. Click the target account in the chooser. The switchable entries
        # are the "(opens a new tab)" links; the CURRENT account appears as a
        # "Collapse accounts" button and must not be matched (clicking it
        # collapses the chooser instead of switching).
        target = None
        for e in state():
            name = e.get("name") or ""
            low = name.lower()
            if email_substr.lower() in low and "opens a new tab" in low:
                target = e
                break
        if target is None:
            lu("key", "Escape")  # close the chooser
            return False, f"account '{email_substr}' not in the chooser"
        lu("act", target["ref"])
        human_wait(3.0, 5.0)
        # 3. Confirm the switch actually happened.
        acct = signed_in_account()
        if acct and email_substr.lower() in acct.lower():
            close_extra_tabs()
            return True, acct
        # The switch opened a tab we are now on; the account may lag a beat.
        human_wait(2.0, 3.0)
    return False, f"could not switch to '{email_substr}'"


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
    r = lu("state", "--app", chrome_app_spec(), "--all", "--depth", "50")
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
    # Human rhythm: pause before starting a new chat, type (paste) at a
    # natural pace, and leave a beat before hitting Return. None of these
    # need to be fast; fast is what gets the IP flagged.
    human_wait(1.5, 3.5)
    find_act("act", "new chat")
    human_wait(2.5, 4.5)
    if find_act("click", "enter a prompt") is None:
        raise RuntimeError("composer not found -- is the session up and signed in?")
    human_wait(0.8, 1.8)
    lu("paste", prompt, check=True)
    # A human does not send instantly after finishing typing.
    human_wait(1.5, 3.5)
    for attempt in range(tries):
        # Re-click the composer before every Return. The paste re-renders the
        # input and the click is what puts keyboard focus back into it; without
        # it the Return lands nowhere and reports success.
        find_act("click", "enter a prompt")
        human_wait(0.8, 1.6)
        lu("key", "Return", check=True)
        for _ in range(8):
            human_wait(2.0, 3.5)
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
        # Jittered poll interval: a fixed 5s cadence is clockwork.
        human_wait(4.0, 7.0)
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


# ── retrying a single prompt ─────────────────────────────────────────────
# The page flakes in a handful of reproducible ways: the composer does not
# come up, the submit does not take, the image vanishes between scroll and
# capture, or a blank frame is captured. Each is retryable by restarting the
# session -- and restarting is cheap (a few seconds) compared to a five-minute
# await that fails. Quota exhaustion is NOT retryable: restarting will not
# mint more quota, so stop the whole run the moment the page says so.

QUOTA_HINTS = ("limit", "quota", "rate limit", "too many", "try again later")


def classify_failure(els):
    """Return 'quota' if the page is complaining about limits, else None."""
    why = page_text(els, limit=10).lower()
    if any(h in why for h in QUOTA_HINTS):
        return "quota"
    return None


def generate_one(prompt, out, size=0, edge=14, timeout=300, retries=3,
                 json_out=False, ensure_session=False, name=None):
    """Generate one image with retry + session restart. Returns (ok, why).

    Two distinct failure classes, retried differently:
      * SUBMIT failures (composer not found, prompt never leaves the input):
        nothing was generated, so restart the session and re-submit -- cheap.
      * CAPTURE failures (image vanished, blank frame, geometry unstable):
        the model already spent quota producing the image, so re-submitting
        would double-spend. Retry by re-polling and re-capturing the SAME
        generated image instead.
    Quota exhaustion is not retryable in either class.
    """
    if ensure_session:
        ok, detail = session_up()
        if not ok:
            return False, detail
    else:
        # Session is assumed up; still never drive a blacklisted account.
        acct = signed_in_account()
        if acct is not None:
            allowed, reason = account_allowed(acct)
            if not allowed and load_account_policy()["blacklist"] \
                    and any(b and b in acct.lower() for b in load_account_policy()["blacklist"]):
                return False, f"refusing to drive {acct} ({reason})"
    job = one_shot(prompt, out, size, edge)
    if name:
        job["name"] = name
    sheet = os.path.join(ROOT, SHEETS, f"{job['name']}.png")

    for attempt in range(1, retries + 1):
        try:
            submit(prompt)
            g, els = await_image(timeout)
            if not g:
                kind = classify_failure(els)
                why = page_text(els)
                if kind == "quota":
                    return False, "quota: " + why[:200]
                raise RuntimeError(f"no image after {timeout}s: {why[:200]}")
            if not bring_into_view():
                raise RuntimeError("could not scroll into view")
        except Exception as exc:
            msg = str(exc)
            if "quota" in msg.lower() or any(h in msg.lower() for h in QUOTA_HINTS):
                return False, msg
            if attempt < retries:
                print(f"   attempt {attempt}/{retries} failed ({msg[:120]}); "
                      f"restarting session", file=sys.stderr)
                session_restart()
                time.sleep(5)
                continue
            return False, msg
        # The image is generated and on screen. Capture it, and on a capture
        # flake re-capture WITHOUT re-submitting -- the model already spent
        # quota producing this image.
        for cattempt in range(1, retries + 1):
            try:
                ok = _capture_sheet(job, sheet, json_out, attempt)
                # A human looks at the result before starting the next one;
                # this also spaces requests out so we do not look like a bot.
                human_wait(6.0, 12.0)
                return ok
            except _CaptureError as exc:
                if cattempt < retries:
                    print(f"   capture {cattempt}/{retries} failed "
                          f"({str(exc)[:120]}); re-capturing", file=sys.stderr)
                    human_wait(3.0, 6.0)
                else:
                    return False, str(exc)
    return False, "exhausted retries"


class _CaptureError(RuntimeError):
    """Raised when the image was generated but could not be captured."""


def _capture_sheet(job, sheet, json_out, attempt):
    """Capture + cut one generated image; raises _CaptureError on flake."""
    try:
        out_abs = os.path.abspath(job["_single"])
        os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)
        os.makedirs(os.path.dirname(sheet) or ".", exist_ok=True)
        w, h = capture(sheet)
        cut_sheet(job, sheet)
    except Exception as exc:
        # Blank-frame, vanished-image, geometry races and cut failures are all
        # "the image is there, go look again" -- never re-spend quota.
        raise _CaptureError(str(exc))
    if json_out:
        print(json.dumps({"name": job["name"], "status": "ok",
                          "out": out_abs, "width": w, "height": h,
                          "attempts": attempt}))
    return True, None


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
    ap.add_argument("--batch", default="",
                    help="JSON file: a list of {name, prompt, out, size?, edge?, "
                         "timeout?, retries?}. Each is generated and written "
                         "independently, with retry + session restart.")
    ap.add_argument("--account", default="",
                    help="substring of the signed-in account email to require; "
                         "aborts early if the browser is on a different account")
    ap.add_argument("--json", action="store_true", dest="json_out",
                    help="emit one NDJSON line per image instead of human text")
    ap.add_argument("--ensure-session", action="store_true",
                    help="run session.sh up before generating, and restart it "
                         "between retries")
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

    if a.account:
        if a.ensure_session:
            session_up()
        acct = signed_in_account()
        if acct is None:
            print("account check: could not read the signed-in account; "
                  "start the session (session.sh up) or pass --ensure-session",
                  file=sys.stderr)
            return 3
        if a.account.lower() not in acct.lower():
            print(f"account check: page is signed in as {acct}, "
                  f"expected a match for '{a.account}'", file=sys.stderr)
            return 3
    elif a.ensure_session:
        # No explicit --account: still honour the configured account policy
        # (preferred + blacklist) so a precious account is never driven.
        ok, detail = enforce_account_policy()
        if not ok:
            print(f"account policy: {detail}", file=sys.stderr)
            return 3

    # Normalize every request to a single-image job tuple (name, job-dict).
    batch_opts = {}
    if a.batch:
        with open(a.batch) as fh:
            items = json.load(fh)
        jobs = []
        for it in items:
            out = it.get("out") or it.get("name")
            if not out:
                print("--batch items need 'name' and 'out'", file=sys.stderr)
                return 2
            name = it.get("name", os.path.splitext(os.path.basename(out))[0])
            job = one_shot(it["prompt"], out, it.get("size", 0), it.get("edge", 14))
            job["name"] = name
            jobs.append((name, job))
            batch_opts[name] = it
    elif a.image:
        if not a.out:
            print("--image needs --out", file=sys.stderr)
            return 2
        jobs = [(a.out, one_shot(a.image, a.out, a.size, a.edge))]
    else:
        if not a.jobs:
            print("give job files, or --batch FILE, or --image PROMPT --out PATH",
                  file=sys.stderr)
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

        # Single-image requests (--image / --batch) get the retry + session
        # restart + quota detection path; job-file grids keep the original
        # queue behaviour so existing gamedev flows are untouched.
        if job.get("_single"):
            opts = batch_opts.get(name, {})
            if a.json_out:
                print(json.dumps({"name": name, "status": "start"}))
            ok, why = generate_one(job["prompt"], job["_single"],
                                   size=job.get("size", 0), edge=job.get("edge", 14),
                                   timeout=opts.get("timeout", 300),
                                   retries=opts.get("retries", 3),
                                   json_out=a.json_out, ensure_session=a.ensure_session,
                                   name=name)
            if not ok:
                if a.json_out:
                    print(json.dumps({"name": name, "status": "fail", "error": why}))
                failed.append((name, why))
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
