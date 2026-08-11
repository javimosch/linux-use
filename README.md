# machin-linux-use

Agent-first, CLI-first GUI control for Linux desktops — the Linux answer to
[Windows-Use](https://github.com/Jeomon/Windows-Use), built in
[machin (MFL)](https://github.com/javimosch/machin) as a single 145 KB binary
with no runtime dependencies.

**v0.2.0** — perception, actuation, an event stream, and a warm-registry
daemon, aligned to [cli-specs.intrane.fr](https://cli-specs.intrane.fr/).

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

An element ref is `app : child-path # fingerprint(role+name)`. Pass refs back
verbatim. When the UI changes underneath one, the fingerprint mismatches and
you get **exit 83 `ref_stale`** with a suggestion to re-run `state` — the tool
never silently acts on the wrong widget.

### act vs click

`act` invokes the widget's own accessible action: no focus change, no pointer
movement, and **it works while the window is fully occluded by another window**.
`click` synthesizes a real XTEST pointer event and is the fallback for widgets
that expose no action. Prefer `act`.

## Commands

```
apps                          list applications exposing accessibility
windows [--app X]             top-level windows: geometry, title, active
state --app X [--depth N] [--role R] [--all]
find <query> [--app X]        search elements by name substring
act <ref> [--action N]        invoke the accessible action (preferred)
read <ref>                    text, name, description
type <ref> <text> [--replace] [--allow-password]
key <combo>                   e.g. ctrl+shift+t   (X11 only)
click <ref> | --x N --y N [--button B]
launch <cmd> [--wait-for APP] [--timeout MS]
watch [--app X] [--events ...] [--max-events N] [--duration MS]
                              stream AT-SPI events as NDJSON
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
- **A label's name IS its text.** So a ref captured from an event on a label
  reports `ref_stale` on the next read — correctly: the staleness *is* the
  signal that the content changed. Drop the `#fingerprint` to address the path
  alone, or re-run `state`.

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
`87` no_display · `88` daemon · `89` refused.

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
- **watch memory**: 8436 kB → **8436 kB** across 450 events after the arena fix
  (before it: 8304 → 15812 kB, ~17 kB leaked per event).

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
7. **`atspi_accessible_get_index_in_parent` can return -1.** Skipping such a
   level while reconstructing a path silently produces a ref that *looks* valid
   and resolves to the WRONG widget. Fall back to scanning the parent's
   children, and if that fails too, report the ref as unusable.
8. MFL specifics: `for` is range-only (use `while`); no `eprintln`
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
- `watch` cannot yet filter by role or dedupe repeated events; a chatty app can
  produce a lot of lines. Bound it with `--max-events`/`--duration`.

## Next (v0.3)

1. `atspi_collection_get_matches` — server-side filtering, one D-Bus round trip
   instead of per-property chatter (the remaining perf win).
2. `watch --role` filtering + consecutive-event dedupe.
3. Injector backend abstraction (`xtest | uinput | libei | portal`) so Wayland
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
