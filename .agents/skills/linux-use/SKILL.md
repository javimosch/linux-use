---
name: linux-use
description: Operate a desktop app or a browser web app with no API — click buttons, type text, read the screen, automate a GUI, drive a signed-in session, control a window. Addresses widgets by name via the AT-SPI2 accessibility tree instead of pixel coordinates or screenshots. Works on GTK and Qt applications and on Chromium/Edge web content (Microsoft Teams, settings windows, editors, file managers); also keyboard shortcuts, waiting for UI changes, and verifying what an application is really displaying.
tags: gui,desktop,automation,accessibility,at-spi,x11,browser,web-app,teams,click,keyboard,screenshot-alternative,no-api
---

# linux-use

Agent-first GUI control for Linux — <https://github.com/javimosch/linux-use>,
docs at <https://javimosch.github.io/linux-use/>.

If `command -v linux-use` is empty, install it first (single static binary):

```sh
curl -L -o /tmp/linux-use https://github.com/javimosch/linux-use/releases/latest/download/linux-use-v0.7.0-x86_64-linux
install -m755 /tmp/linux-use ~/.local/bin/linux-use
sudo apt install libatspi2.0-0 libxtst6 libx11-6 libglib2.0-0 xclip
```

It reads the AT-SPI2 accessibility tree and acts on it. **It contains no LLM —
you are the loop.** JSON on stdout, context on stderr, semantic exit codes.

Run `linux-use guide` first: the complete operator manual is embedded in the
binary and is always current for the installed version.

## When to use it — and when not

| Situation | Use |
|---|---|
| Operate a desktop app (settings, editor, calculator, file manager) | **linux-use** |
| Operate a web app when only the browser has the session | **linux-use** + the browser flag below |
| Read what an app is currently displaying | **linux-use** `state` / `read` |
| Wait for a UI change | **linux-use** `watch` |
| Drive a terminal TUI (an AI CLI, htop, vim) | **tmux**, not this — `tmux send-keys` / `capture-pane` gives a deterministic text buffer |
| Scrape or automate a website with no session requirement | **playwright/agent-browser**, far more reliable |
| Send a message / create a record when an API exists | **the API** — GUI automation is the last resort |

Do not reach for this when a CLI or API can do the job. It is for when the GUI
is genuinely the only door.

## Preflight (once per machine)

```sh
linux-use doctor        # session type, a11y bus, XTEST, clipboard backend
```

Fix whatever it reports. The two usual ones:

```sh
gsettings set org.gnome.desktop.interface toolkit-accessibility true
sudo apt install xclip     # without it, text entry falls back to a path that CRASHES Chromium
```

`doctor` exits non-zero and lists `problems` when something is wrong. Trust it
over assumptions.

## The loop

```sh
linux-use apps                                   # what exposes accessibility (+ pid, toolkit)
linux-use state --app gnome-calculator           # interactive elements, each with a ref
linux-use act 'gnome-calculator:/0/1/0/1/0/0/1/0/22#18124260'
linux-use read <ref>                             # verify the effect
```

Every element carries a **ref**. Pass refs back verbatim; never construct or
edit one. Two kinds exist, and `ref_kind` says which:

- **path** — `app:/0/1/0/22#fingerprint` — addressed by child indices.
- **geometry** — `app:@43~150,352,64,44#fingerprint` — role + on-screen
  rectangle, issued when a widget has no provable tree path. Tied to screen
  position, so moving/resizing the window invalidates it (exit 84).

The fingerprint is `role+name`. When the UI changes underneath a ref you get
**exit 83 `ref_stale`** — re-run `state` and use fresh refs. The tool refuses
rather than acting on the wrong widget; treat a refusal as correct behaviour.

### act vs click

`act` invokes the widget's own accessible action — no pointer movement, no
focus stealing, and **it works while the window is fully occluded**. Prefer it.
`click` synthesizes a real XTEST pointer event and is the fallback for widgets
exposing no action.

## Command surface

```
apps                          applications with pid, toolkit, window count
windows [--app X]             top-level windows: geometry, title, active
state --app X [--pid N] [--role R] [--all] [--depth N]
find <query> [--app X]        search elements by name substring
act <ref> [--action N]        invoke the accessible action (preferred)
read <ref>                    text, name, description
type <ref> <text>             editable-text if available, else focus-verified clipboard
sendtext <text>               type at current focus (no ref)
paste <text>                  clipboard + ctrl+v
key <combo> [--dry-run]       ctrl+shift+t, alt+F4 — --dry-run resolves without sending
click <ref> | --x N --y N
launch <cmd> [--wait-for APP]
watch [--app X] [--role R] [--max-events N] [--duration MS] [--max-rss KB]
roles                         every valid --role name
doctor | guide | help-json | version
serve | daemon start|stop|status
```

`linux-use daemon start` keeps the AT-SPI registry warm for repeated calls.

## Landmines (these will bite)

1. **`SHOWING` != visible to the user.** An occluded widget is still SHOWING.
   Never tell a user "you can see X" based on the tree.
2. **A read returning 0 elements means "no accessibility", not "empty window".**
   Check `truncated` / `depth_limited` in the envelope — the tool tells you when
   an answer is incomplete.
3. **Two apps can share a name.** A plain `--app` matching several is refused
   with `app_ambiguous` (exit 80). Disambiguate: `--app 'Name#pid1234'` or
   `--pid 1234`. `apps` lists pids and flags `ambiguous_names`.
4. **X keysym names are case-sensitive.** `alt+F4` works; `f1`–`f24` are
   accepted in either case. Validate without firing: `key alt+F4 --dry-run`.
5. **Verify focus before `sendtext`.** It types wherever focus happens to be —
   a stray space presses whatever button is focused. Check `focused:true` in
   `state` first. (`type <ref>` verifies for you and fails with `focus_refused`.)
6. **Some widgets lie about their text.** A rich contenteditable (Teams' compose
   box) always reads as the empty placeholder `￼` no matter what it holds. Do
   not verify input by reading it back; verify the *effect* afterwards instead.
7. **`watch` memory grows ~0.14 kB/event inside libatspi**, not in the tool. For
   long-lived listeners pass `--max-rss <kB>` and restart on exit 90.

Exit codes: `0` ok · `80` usage/ambiguous · `81` no_a11y · `82` app_not_found ·
`83` ref_stale · `84` ref_not_found · `85` no_capability · `86` action_failed ·
`87` no_display · `88` daemon · `89` refused · `90` rss_limit.

## Browsers and web apps

**A normally-launched Chromium/Edge exposes exactly one `frame` — zero web
content.** It must be started with `--force-renderer-accessibility`; then the
real DOM appears (buttons, inputs, links) and is addressable by name.

That flag cannot be applied retroactively, and a PWA window shares its process
with ordinary browser windows — so a dedicated instance with its own profile is
the practical approach:

```sh
microsoft-edge --user-data-dir=~/.local/share/linux-use/edge-<app> \
  --force-renderer-accessibility --no-first-run https://example.com &
```

This repo ships a launcher that does the above correctly:

```sh
contrib/a11y-browser -n teams https://teams.microsoft.com/
contrib/a11y-browser -n teams --hidden <url>   # private Xvfb (no WM: keystrokes will NOT work)
contrib/a11y-browser -n teams --stop
```

The profile persists, so any login happens once. `--hidden` also isolates
`XDG_RUNTIME_DIR`, without which teardown would delete the *real* session's
accessibility socket.

### Verified Teams recipe

1. `act` the `Chat (Ctrl+Shift+1)` toggle.
2. `state --all --role "tree item"` — the chat list is **tree items**, not list
   items, so a plain `state` looks empty.
3. `act` the chat whose name contains the person.
4. **Confirm the right conversation** by finding a known message among `static`
   elements. The window title lags and cannot be trusted.
5. `click <compose-box-ref>`, confirm `focused:true`.
6. `paste` the text.
7. `act` the `Send (Ctrl+Enter)` button.
8. Verify the sent message appears among `static` elements.

Element names often embed their own shortcuts (`Send (Ctrl+Enter)`) — a free
source of reliable key combos.

## Testing safely

Never rehearse against the user's live desktop. The repo ships an isolated
harness (`test/env.sh` in the linux-use repo): a private Xvfb `:99` with its own
D-Bus session **and its own `XDG_RUNTIME_DIR`**.

> The `XDG_RUNTIME_DIR` override is not optional. `at-spi-bus-launcher` uses a
> fixed per-user socket path that does not vary with `DBUS_SESSION_BUS_ADDRESS`.
> Without it, tearing the test environment down **deletes the real session's
> accessibility socket** and every already-running app goes invisible to
> accessibility until it restarts.

Also note: an app connects to the a11y bus at **process start**. Restart the
bus and every running app is invisible until *its process* restarts.

## Honest limits

Verified: **GTK 3/4** and **Qt 5** desktop apps, and **Chromium/Edge web
content** with the flag above. Tested on exactly one configuration — Ubuntu
22.04.3, GNOME 42.9, X11, x86-64.

**Not tested / not working:**

- **Wayland** — `click` and `key` do not work (XTEST cannot reach native Wayland
  clients). AT-SPI paths (`act`, `type`, `read`, `state`, `watch`) still do.
  Ubuntu 24.04+ defaults to Wayland, so check `doctor` before promising anything.
- Electron, Java (needs `java-atk-wrapper`), Flutter/canvas UIs.
- KDE/XFCE, other distros, HiDPI/fractional scaling, multi-monitor, non-US
  keyboard layouts, arm64.
- There is **no automated test suite** — behaviour is verified manually.

It can also break what it drives: it has crashed browsers and, through a
test-isolation gap, knocked out a live session's accessibility bus. Prefer
`act` over synthetic input, and prefer a dedicated app instance over the user's
working one.

## Deeper knowledge

1. **`linux-use guide`** — the full operator manual, embedded in the binary and
   always correct for the installed version. Read this before improvising.
2. **The repo README** — measured benchmarks, the AT-SPI landmines in detail,
   and an explicit table of what is verified vs untested.
3. **Issues** — <https://github.com/javimosch/linux-use/issues>. Wayland support
   is [#1](https://github.com/javimosch/linux-use/issues/1) and open.

> On the original author's machine the same caveats are also mirrored into a
> local memgraph project (`memgraph recall "<topic>" --project linux-use`).
> That store is not part of this repo; everything load-bearing is above.
