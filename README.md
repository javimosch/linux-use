# linux-use

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![built with machin](https://img.shields.io/badge/built%20with-machin%20(MFL)-6366f1)](https://github.com/javimosch/machin)
[![agent-first CLI](https://img.shields.io/badge/agent--first-cli--specs-10b981)](https://cli-specs.intrane.fr/)

Agent-first, CLI-first GUI control for Linux desktops — the Linux answer to
[Windows-Use](https://github.com/Jeomon/Windows-Use), built in
[machin (MFL)](https://github.com/javimosch/machin) as a single 175 KB binary
with no runtime dependencies.

📖 **[Docs & changelog](https://javimosch.github.io/linux-use/)** ·
📦 **[Releases](https://github.com/javimosch/linux-use/releases)** ·
✨ **[awesome-machin](https://github.com/javimosch/awesome-machin)**

**v0.6.2** — perception (memoized collection queries + walk fallback), actuation, a
filterable event stream, and a warm-registry daemon, aligned to [cli-specs.intrane.fr](https://cli-specs.intrane.fr/).

## The design bet

Windows-Use is a Python library with the LLM *inside* it (LangChain, provider
keys, its own `max_steps` agent loop). linux-use inverts that: it ships **zero
LLM code**. It is a pure sensor/actuator binary — perception in, actions out,
JSON both ways. Claude/Devin *is* the loop.

That makes it model-agnostic, testable, fast, and a natural fit for the
agent-first CLI specs.

## Install

```sh
sudo apt install libatspi2.0-dev libxtst-dev libx11-dev libglib2.0-dev
gsettings set org.gnome.desktop.interface toolkit-accessibility true
./build.sh
```

`linux-use doctor` will tell you if anything is missing.

## The loop

```sh
linux-use apps                              # who is running and exposes a11y
linux-use state --app gnome-calculator      # interactive elements, with refs
linux-use act 'gnome-calculator:/0/1/0/1/0/0/1/0/22#18124260'
linux-use read <ref>                        # verify the effect
```

An element ref comes in two kinds, and `ref_kind` says which:

- **path** — `app:/0/1/0/22#18124260` — addressed by child indices.
- **geometry** — `app:@43~150,352,64,44#18124261` — addressed by role and
  on-screen rectangle, issued when a node has no provable path (see below).

Pass refs back verbatim. When the UI changes underneath one, the fingerprint
mismatches and you get **exit 83 `ref_stale`** with a suggestion to re-run
`state` — the tool never silently acts on the wrong widget.

### act vs click

`act` invokes the widget's own accessible action: no focus change, no pointer
movement, and **it works while the window is fully occluded by another window**.
`click` synthesizes a real XTEST pointer event and is the fallback for widgets
that expose no action. Prefer `act`.

## Commands

```
apps                          list applications exposing accessibility
windows [--app X]             top-level windows: geometry, title, active
state --app X [--depth N] [--role R] [--all] [--collection|--walk]
find <query> [--app X]        search elements by name substring
act <ref> [--action N]        invoke the accessible action (preferred)
read <ref>                    text, name, description
type <ref> <text> [--replace] [--allow-password]
sendtext <text> [--via auto|clipboard|atspi]
                              type at the current focus (no ref needed)
paste <text> [--no-restore]   clipboard + ctrl+v
key <combo>                   e.g. ctrl+shift+t   (X11 only)
click <ref> | --x N --y N [--button B]
launch <cmd> [--wait-for APP] [--timeout MS]
watch [--app X] [--role R] [--events ...] [--max-events N] [--duration MS]
      [--max-rss KB]
                              stream AT-SPI events as NDJSON
roles                         every valid --role name
pointer                       current pointer position
doctor                        environment health
serve [--port] | daemon start|stop|status
guide [--human] | help-json | version
```

## watch — block on a UI change instead of polling

```sh
linux-use watch --app gnome-calculator --duration 5000
{"event":"object:text-changed:insert","app":"gnome-calculator","role":"editbar",
 "name":"","ref":"gnome-calculator:/0/1/0/1/0/1/1/0#749312667","ref_ok":true,
 "detail1":0,"detail2":1,"ts":1786455..}
```

One JSON object per line on stdout, flushed immediately; the banner goes to
stderr so stdout stays pure NDJSON. `--max-events N` stops after **exactly** N.
`--duration MS` bounds the wait. Events are real AT-SPI callbacks — no polling.

Each event carries a reconstructed `ref` (walked UP from the event source to
its application) plus **`ref_ok`**. `ref_ok:false` means an ancestor index could
not be determined and the ref would be wrong — it is reported as unusable
rather than emitted as a plausible lie.

Two behaviours worth knowing:

- **Observer effect.** Reading the tree (`state`/`find`) makes toolkits emit
  accessibility events. In one measured run, 72 of 101 events were
  `state-changed:checked` churn induced by linux-use's own walks. That event
  type is therefore **not** in the default set (opt back in with `--events`);
  the same run then yielded 38 events, all genuine.
- **`--role` is the cheapest noise filter.** One sample run went from 54 events
  to the 6 that mattered by adding `--role editbar`.
- **A label's name IS its text.** So a ref captured from an event on a label
  reports `ref_stale` on the next read — correctly: the staleness *is* the
  signal that the content changed. Drop the `#fingerprint` to address the path
  alone, or re-run `state`.

## Geometry refs: when a widget has no provable path

v0.5 fell back to a full tree walk whenever a collection match could not be
pathed (14 of 37 elements in gnome-control-center). Diagnosing it turned up
something more interesting than an identity bug — **broken parent/child
reciprocity**:

```
NODE   filler '' [472,112 578x100]
parent panel  '' [472,112 578x100]  children=1  index_in_parent=-1
  -> pointer match: -1 | role+name+extents match: -1
```

The node's `get_parent()` returns a container that does **not** list it among
its children, by any comparison. Such a node is reachable top-down but has no
child-index path at all — impossible, not merely unknown. No identity test
could ever have fixed it.

So those nodes get a **geometry ref** instead: `app:@<roleId>~x,y,w,h#<fp>`,
resolved with a collection query for that role, matched on exact extents and
verified by the same role+name fingerprint. Two widgets sharing a role and
rectangle are reported ambiguous; a rectangle with no match returns exit 84.
A geometry ref never silently resolves to the wrong widget — but it *is* tied
to screen position, so moving or resizing the window invalidates it.

The `collection+walk` fallback is gone. Every match is addressable:

| app | method | default | `--walk` | geometry refs |
|---|---|---|---|---|
| gnome-calculator | collection | **15 ms** | 65 ms | 0 |
| gnome-text-editor | collection | **12 ms** | 53 ms | 0 |
| gnome-control-center | collection | **25 ms** | 44 ms | 14 |

All three return the same element set as the walk with every ref usable.
All 14 geometry refs in gnome-control-center resolve to the widget they
describe; `act` through one drives the app correctly.

## Collection queries: measured, not assumed

`state`/`find` ask AT-SPI's **Collection** interface to match server-side in one
round trip, and fall back to a tree walk when a match's ref cannot be proven.

v0.4 memoizes the climb from a match back to the application root — collection
matches are siblings sharing ancestors, so without it the same chain was
re-walked once per match and ate the entire benefit. Measured across six apps:

| app | default | method | `--walk` |
|---|---|---|---|
| gnome-text-editor | **12 ms** | collection | 71 ms |
| gnome-calculator | **23 ms** | collection | 97 ms |
| gnome-disks | **5 ms** | collection | 15 ms |
| seahorse | **15 ms** | collection | 29 ms |
| Nautilus | **560 ms** | collection | 625 ms |
| gnome-control-center | 76 ms | collection+walk | 69 ms |
| gnome-control-center `--role "push button"` | **4 ms** | collection | 47 ms |

Five of six apps are 1.1–5.9x faster with identical refs. The sixth cannot path
every match, so the query is re-run as a walk (`method: "collection+walk"`) and
costs ~10% more than walking directly — the price of never returning an
incomplete set by default.

Forcing: `--collection` keeps the fast result *including* `ref_ok:false`
entries; `--walk` skips the query entirely. `method` always reports what ran.

`linux-use roles` lists all 130 role names and flags the 18 interactive by
default. An unknown `--role` matches nothing and says so on stderr.

## The `watch` memory growth is upstream, and now bounded

`watch` grows about **0.14 kB per event**. v0.5 set out to close it and instead
proved it is not ours to close.

A probe with three callback bodies — a **no-op that only counts**, one that
reads role+name, and the full path-reconstructing one — all leak at the same
rate:

| callback | kB/event |
|---|---|
| null (count only) | +0.163 |
| props (role + name) | +0.157 |
| full (+ parent climb) | +0.181 |

Every allocation the probe makes lives inside an `arena` block, including its
own periodic reporting. A callback that does *nothing* still grows, so the
growth is inside libatspi's event delivery on at-spi2-core 2.44 — not in
linux-use. (The historical `AtspiEventListener` leak was fixed upstream in
2.21.1; this is a separate residual.) `atspi_accessible_clear_cache()` makes it
*worse*: +0.886 kB/event and roughly half the event throughput.

So the fix is to make it **bounded** rather than pretend it is closed:

```sh
# exit 90 above the ceiling; a supervisor restarts and keeps streaming
while :; do
  linux-use watch --app firefox --max-rss 262144 || [ $? -eq 90 ] || break
done
```

`--max-rss` is off by default. At 0.14 kB/event a 256 MB ceiling is roughly
1.8 million events, so most agent workloads never reach it — bound short runs
with `--duration`/`--max-events` instead and this never comes up.

## Text entry: the clipboard is the default, for a reason

AT-SPI key synthesis (`atspi_generate_keyboard_event`) **crashes Chromium/Edge
launched with `--force-renderer-accessibility`** — reproduced on a bare
`<input>` page with focus verified, 3/3 times, payloads of 11/16/112 chars
([#4](https://github.com/javimosch/linux-use/issues/4)). Since that flag is the
only way to make a browser expose web content to AT-SPI, the crash lands exactly
where the tool is most useful.

So since v0.6.2 text entry goes through the **clipboard** by default: set the
CLIPBOARD selection, send `ctrl+v` via XTEST, restore the previous clipboard.
That path never touches the AT-SPI input controller.

| command | what it does |
|---|---|
| `type <ref> <text>` | editable-text interface if available; else verifies focus, then clipboard |
| `sendtext <text>` | types at current focus; `--via auto` (default) picks clipboard when `xclip` is present |
| `paste <text>` | clipboard + `ctrl+v` explicitly |

Measured A/B on the repro page, focus verified on the input:

| mechanism | result |
|---|---|
| default (`clipboard+ctrl_v`) | text lands, **browser alive** |
| `sendtext --via atspi` | **browser dead** |

`linux-use doctor` reports which backend is actually in use, and warns if
`xclip` is missing (in which case entry falls back to the crashing path and says
so on stderr rather than silently killing a browser).

`type <ref>` also **verifies the element actually took focus** before
synthesizing anything — `grab_focus` silently does nothing on some web
elements, and typing into an unknown focus is how a stray space presses whatever
button happens to be focused.

## Depth: shallow answers are now loud

v0.1 defaulted to `--depth 14` and silently returned a shallow tree.
gnome-text-editor's document node lives at depth 16, so `state --role text`
returned **0 elements** — an agent would conclude "there is no text field".

v0.2 defaults to `--depth 64` and every walk reports `deepest`,
`nodes_visited`, `depth_limit`, `depth_limited` and `truncated`. When a subtree
*is* cut, it warns on stderr and sets `depth_limited:true`:

```
$ linux-use state --app gnome-text-editor --role text --depth 14
warning: subtrees were cut at --depth 14 — deeper widgets are NOT in this result
  -> count 0, depth_limited true      # v0.1 said count 0 and nothing else
$ linux-use state --app gnome-text-editor --role text
  -> count 1, deepest 16, depth_limited false
```

## Testing without touching your desktop

`test/env.sh` brings up a private Xvfb `:99` with its own D-Bus session **and
its own `XDG_RUNTIME_DIR`**:

```sh
. test/env.sh start   # exports DISPLAY, DBUS_SESSION_BUS_ADDRESS, XDG_RUNTIME_DIR
. test/env.sh stop
```

The `XDG_RUNTIME_DIR` override is **not optional**. `at-spi-bus-launcher` puts
its socket at `$XDG_RUNTIME_DIR/at-spi/bus_0` — a fixed per-user path that does
*not* vary with `DBUS_SESSION_BUS_ADDRESS`. Without the override a private
launcher shares that path with the real session, and tearing the test
environment down **deletes the real session's a11y socket**, breaking
accessibility for every already-running app until it restarts. This was learned
by doing it.

## Spec compliance (v0.2)

| Spec | Status |
|---|---|
| cli-output-spec | ✅ stdout JSON only, stderr for warnings, semantic exit codes 80–89, typed errors with `recoverable` + `suggestions` |
| cli-guide-spec | ✅ `guide` (JSON) and `guide --human`, plus `help-json` |
| cli-daemon-spec | ✅ `serve`, `daemon start\|stop\|status`, `GET /_health`, `POST /_shutdown`, loopback-only, health-polled (no fixed sleeps), idempotent |
| cli-update-spec | ⬜ deferred to v0.3 |
| cli-feedback-spec | ⬜ deferred to v0.3 |
| cli-telemetry-spec | ⬜ deferred to v0.3 |

Exit codes: `0` ok · `80` usage · `81` no_a11y · `82` app_not_found ·
`83` ref_stale · `84` ref_not_found · `85` no_capability · `86` action_failed ·
`87` no_display · `88` daemon · `89` refused · `90` rss_limit.

## Verified (Ubuntu 22.04, GNOME 42.9, X11 — v0.2 on an isolated Xvfb desktop)

- **Perception**: 20+ apps enumerated; `gnome-calculator` → 28 interactive
  elements in **88 ms**. Microsoft Edge (Chromium) exposes its tree too.
- **Full loop**: `find 7 / + / 5 / =` → four `act` calls → tree shows
  `label '7+5'` and `label '12'`. The window was **occluded the whole time**.
- **type**: inserted 25 chars into gnome-text-editor via the editable-text
  interface, read back byte-identical.
- **key**: `ctrl+shift+z` resolved to `Control_L + Shift_L + z` through the
  live keyboard layout and injected via XTEST.
- **Errors**: tampered fingerprint → exit 83; bad path → 84; unknown app → 82.
- **Daemon**: warm registry, `/v1/apps` in ~50 ms, clean `/_shutdown`.
- **Refcounting**: RSS 4500 → 4532 kB across **300 tree walks** (~8,700 nodes);
  4488 → 4512 kB across 200 walks at the new depth 64. Essentially flat.
- **watch**: 450 events streamed while driving the app; `--max-events 5`
  returned exactly 5; an event ref resolved to the right widget once the
  volatile fingerprint was accounted for.
- **Collection**: identical refs to the walk on every app tested, zero wrong
  refs; 1.1–5.9x faster on five of six apps after memoizing path reconstruction.
- **watch --role**: 54 events → 6 with `--role editbar`.
- **watch memory**: the arena fix cut per-event growth from **~17 kB/event**
  (8304 → 15812 kB over 450 events) to **~0.17 kB/event** — a ~100x reduction,
  but *not* zero. An earlier version of this README claimed zero; that was read
  off two samples that happened to coincide over a short run. Measured across
  ~1000 events, v0.3 and v0.4 both grow ~190 kB per 1000 events. Bound long
  watches with `--duration`/`--max-events`; see Known limitations.

## Hard-won machin FFI findings

These cost real debugging time and are the non-obvious part of this codebase.

1. **A `string` returned across the FFI boundary ALIASES the C buffer — it does
   not copy.** A helper returning a shared static buffer is therefore unsafe:
   the next call clobbers every outstanding value. This showed up as `role` and
   `app` both reading `"Calculator"`.
2. **The copy is lazy enough that `g_free` beats it.** `substr(v, 0, len(v))`
   *looks* like a copy and survives a buffer overwrite, but freeing the
   underlying pointer afterwards yields **silently truncated strings**, not a
   crash. `bytes_str(bytes(v))` forces a materialized copy and is safe — that
   is what `takestr()` uses, and the reason it is written that way.
3. **`len()` on an FFI-aliased string can return a stale length**, so even a
   C-provided `strlen` does not rescue `substr`.
4. **Do not name a function after a machweb/framework parameter.** A top-level
   `func handler(...)` collides with `serve(port, handler)`'s parameter and
   surfaces as the misleading `cannot infer struct type for field .path`.
5. **`cflags` must come from `pkg-config --cflags atspi-2`** — atspi's headers
   pull in `dbus/dbus.h`, which is not on the default include path.
6. **A long-lived FFI callback needs an `arena` block.** Per-request work in a
   machweb daemon is freed when its goroutine ends, but an AT-SPI event
   callback runs forever in one frame — every string it builds accumulates
   (measured: ~17 kB/event). Wrapping the body in `arena { }` made growth
   exactly zero. Two constraints: the callback must be **captureless** (globals
   only — a captured variable is a compile error), and **no `return` may appear
   inside the arena block** (ARENA002), so early exits become a flag.
7. **`atspi_accessible_get_index_in_parent` cannot be trusted, in two ways.**
   It returns -1 for some nodes (skipping that level builds a ref that looks
   valid and resolves to the WRONG widget), and — worse — it can return a
   *confidently wrong* non-negative value: in gnome-control-center it reported
   0 for a child actually at index 1, producing refs that did not resolve at
   all. Refs are addressed with `get_child_at_index`, so that is the authority:
   treat the index as a hint, verify it, and scan the parent when it fails.
8. **`atspi_accessible_get_id` is not a usable identity here.** Tried as a
   fallback for pointer comparison, it produced false matches and therefore
   confidently wrong refs — worse than admitting ignorance. Reverted to pointer
   identity, accepting `ref_ok:false` for the nodes it cannot prove.
9. **An empty AT-SPI match criterion must use `MATCH_ALL`, not `MATCH_ANY`.**
   "Any of zero" is false, so a rule with `MATCH_ANY` over NULL attributes and
   interfaces matches *nothing* — the query runs, succeeds, and returns an
   empty array. Only the roles list uses `MATCH_ANY`.
10. MFL specifics: `for` is range-only (use `while`); no `eprintln`
   (`write(2, …)`); `int()` does not parse strings (`parse_int`); lowercase is
   `to_lower`; a lambda passed to `serve` must be inlined at the call site for
   struct-field inference to flow.

## Known limitations

- **`SHOWING` != visible to the user.** An occluded widget is still `SHOWING`.
  Real visibility needs the window stack; the guide warns agents about this.
- **Coverage is not universal.** GTK/Qt/Chromium/Electron are good; Java needs
  `java-atk-wrapper`; Flutter/canvas UIs may expose nothing. `state` returning
  0 elements means "no accessibility", not "empty window".
- **Wayland is unsupported.** XTEST cannot reach native Wayland clients, so
  `click`/`key` are X11-only. AT-SPI `act`/`type`/`read` still work.
- The tree walk is still recursive with a node budget; it warns and sets
  `truncated:true`/`depth_limited:true` rather than silently capping.
- `watch` cannot yet dedupe repeated events; a chatty app produces a lot of
  lines. Filter with `--role`/`--events` and bound with `--max-events`/`--duration`.
- `watch` grows ~0.14 kB per event inside **libatspi**, not linux-use (proven
  with a no-op callback; see above). Bound long-lived listeners with
  `--max-rss` and restart on exit 90.

## Next (v0.7)

1. Injector backend abstraction for Wayland ([#1](https://github.com/javimosch/linux-use/issues/1)).
2. Disambiguate apps sharing an accessible name ([#3](https://github.com/javimosch/linux-use/issues/3)).
3. Case-sensitive keysyms so `alt+F4` works ([#2](https://github.com/javimosch/linux-use/issues/2)).
4. Consecutive-event dedupe in `watch` (`xtest | uinput | libei | portal`) so Wayland
   becomes a backend rather than a rewrite.
4. The remaining three specs: update, feedback, telemetry.
5. Screenshots + a vision fallback for the apps that expose no tree.
6. supercli/MCP registration + a `SKILL.md`.

## Layout

```
src/main.src      the CLI (one file)
lu_helpers.h      C shims: FFI string ownership + AtspiEvent accessors
build.sh          machin encode (machweb + flags + app) -> machin build
test/env.sh       isolated Xvfb + D-Bus + XDG_RUNTIME_DIR test desktop
spike/            the original feasibility spike, kept for reference
```

## Built with

- **[machin (MFL)](https://github.com/javimosch/machin)** — the Machine-First Language this is written in.
  One source file plus a small C shim, compiled through C to a static binary.
- **[awesome-machin](https://github.com/javimosch/awesome-machin)** — other things built with machin.
- **[cli-specs.intrane.fr](https://cli-specs.intrane.fr/)** — the agent-first CLI spec family this follows.

## Author

Built by [Javier Arancibia](https://www.linkedin.com/in/arancibiajav/) · [intrane.fr](https://intrane.fr)

## License

MIT — see [LICENSE](LICENSE).
