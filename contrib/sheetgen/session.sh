#!/usr/bin/env bash
# session.sh — bring up (or tear down) the browser the generator drives.
#
#   tools/gen/session.sh up | down | status
#
# The browser runs on a VIRTUAL X display so it does not fight the human for
# the screen, and on Chrome's DEFAULT PROFILE so it is already signed in. A
# dedicated --user-data-dir starts logged out and there is no password to type;
# the whole premise is that the session already exists.
#
# Two hard requirements:
#   * --force-renderer-accessibility, or Chromium exposes exactly one `frame`
#     to AT-SPI and zero web content. It cannot be applied retroactively.
#   * a window manager on that display, or X input focus is unset and no
#     keystroke ever lands.
#
# `down` is not optional housekeeping: leaving this running means the human's
# next ordinary Chrome launch surfaces the invisible instance on :99 and looks
# broken.
set -euo pipefail
# Its own display, deliberately. Sharing one with the game's headless
# screenshots meant a capture could photograph the game instead of the page.
: "${GEN_DISPLAY:=:98}"
: "${GEN_W:=1900}"
: "${GEN_H:=1040}"
: "${GEN_URL:=https://gemini.google.com/app}"
FLAG=--force-renderer-accessibility
PIDFILE=/tmp/gen-chrome.pid
# NEVER match on the flag alone. This machine runs a Microsoft Edge with
# --force-renderer-accessibility for unrelated work, and a `pkill -f
# force-renderer-accessibility` would take it down with us. Match this
# browser, on this display, and prefer the pid we recorded at launch.
PAT="google-chrome.*$FLAG"

ours() {
    pid=""
    [ -f "$PIDFILE" ] && pid=$(cat "$PIDFILE" 2>/dev/null || true)
    if [ -n "$pid" ] && [ -r "/proc/$pid/cmdline" ]; then echo "$pid"; return 0; fi
    pid=$(pgrep -f -- "$PAT" 2>/dev/null | head -1 || true)
    [ -n "$pid" ] && echo "$pid"
    return 0
}

xvfb_up() {
    # Not `pgrep -f "Xvfb $GEN_DISPLAY" || start` -- pgrep matches this very
    # shell's own command line, so the guard passes and nothing is started.
    if DISPLAY="$GEN_DISPLAY" xdpyinfo >/dev/null 2>&1; then return; fi
    Xvfb "$GEN_DISPLAY" -screen 0 "${GEN_W}x$((GEN_H + 40))x24" -ac \
        +extension RANDR +extension GLX +render -noreset >/tmp/gen-xvfb.log 2>&1 &
    sleep 3
}

wm_up() {
    pgrep -f "xfwm4 --display=$GEN_DISPLAY" >/dev/null 2>&1 && return
    DISPLAY="$GEN_DISPLAY" nohup xfwm4 --display="$GEN_DISPLAY" --sm-client-disable \
        >/tmp/gen-wm.log 2>&1 &
    sleep 2
}

case "${1:-status}" in
up)
    xvfb_up
    wm_up
    if [ -n "$(ours)" ]; then
        echo "session: already up on $GEN_DISPLAY (pid $(ours))"
    else
        if pgrep -x chrome >/dev/null 2>&1 || pgrep -x google-chrome >/dev/null 2>&1; then
            echo "session: Chrome is already running on another display." >&2
            echo "          This needs its default profile, which one process owns at" >&2
            echo "          a time. Close Chrome and try again." >&2
            exit 1
        fi
        DISPLAY="$GEN_DISPLAY" nohup google-chrome "$FLAG" \
            --disable-session-crashed-bubble --no-first-run \
            --window-size="$GEN_W,$GEN_H" --window-position=0,0 \
            "$GEN_URL" >/tmp/gen-chrome.log 2>&1 &
        echo $! > "$PIDFILE"
        sleep 22
        echo "session: up on $GEN_DISPLAY"
    fi
    # A first load can land on the signed-out shell even with the account
    # present in the profile; pressing Sign in completes it without a password.
    if DISPLAY="$GEN_DISPLAY" "$(dirname "$0")/lu.sh" ref "sign in" >/dev/null 2>&1; then
        echo "session: completing sign-in"
        DISPLAY="$GEN_DISPLAY" "$(dirname "$0")/lu.sh" act "sign in" >/dev/null || true
        sleep 12
    fi
    DISPLAY="$GEN_DISPLAY" "$(dirname "$0")/lu.sh" ref "enter a prompt" >/dev/null 2>&1 \
        && echo "session: composer is reachable" \
        || { echo "session: composer NOT reachable -- look at the page" >&2; exit 1; }
    ;;
down)
    pid="$(ours)"
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null || true
        sleep 2
        # Chrome's zygote children die with the parent; anything left that is
        # ours by pattern gets a second, still narrowly targeted, pass.
        pkill -f -- "$PAT" 2>/dev/null || true
        rm -f "$PIDFILE"
        echo "session: browser stopped (pid $pid)"
    else
        echo "session: not running"
    fi
    ;;
status)
    DISPLAY="$GEN_DISPLAY" xdpyinfo >/dev/null 2>&1 && echo "display $GEN_DISPLAY: up" || echo "display $GEN_DISPLAY: down"
    pgrep -f "xfwm4 --display=$GEN_DISPLAY" >/dev/null 2>&1 && echo "wm: up" || echo "wm: down"
    p="$(ours)"
    [ -n "$p" ] && echo "browser: up (pid $p)" || echo "browser: down"
    ;;
*)  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac
