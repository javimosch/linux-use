# Agents working on machin-linux-use

## Hard rules

- **NEVER automate the user's live browser profile** with Playwright/CDP or
  `--user-data-dir=<real profile>` (e.g. `~/.config/microsoft-edge`).
  Playwright forces `--use-mock-keychain`; the cookie DB becomes
  undecryptable, Chromium treats it as corrupt and **resets it** — every site
  session is wiped and unrecoverable (`SQLITE_SECURE_DELETE` zeroes deleted
  rows; no WAL, no backup). Verified 2026-10-04 — cost a full Edge session wipe.
  - Use `contrib/a11y-browser -n <name>` (dedicated persistent profile), or a
    throwaway `rsync` copy of the profile if the login is needed.
  - Driving the live session via linux-use/AT-SPI is safe — it touches no
    profile internals. Relaunch with `--force-renderer-accessibility` is
    required for web content, but restores session on restart.
- **The Edge process is `msedge`, not `microsoft-edge`.** `pgrep microsoft-edge`
  matches nothing while the browser is running — check `pgrep -x msedge`
  (and skip `--type=` utility children) before assuming it is safe to kill.

## Build

`./build.sh` — composes framework + `src/main.src` into `app.mfl`, then
`machin build app.mfl -o linux-use`. Edit `src/main.src` (guide text, commands),
never `app.mfl` (generated).

## Skill

`.agents/skills/linux-use/SKILL.md` is the drop-in operator manual — keep it in
sync with `linux-use guide` (`guide_json`/`guide_human` in `src/main.src`).
