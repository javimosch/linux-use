#!/usr/bin/env bash
# lu.sh — find-and-act in one breath.
#
# Gemini's DOM restages on every animation, and linux-use refs are addressed
# by child index. A ref captured in one command and used in the next is very
# often already stale (exit 83/84) — which is the tool being correct, not
# broken. So never carry a ref across a shell command: look it up and use it
# inside the same invocation.
#
#   lu.sh act  "Send message"
#   lu.sh click "Enter a prompt for Gemini"
#   lu.sh ref  "Download"          # print the ref only
#
# DISPLAY resolution: GEN_DISPLAY wins (matches session.sh / run.py), then
# the :98 virtual display, then whatever the shell already has. Agents run
# with DISPLAY=:0 (the real desktop) in their environment, and silently
# driving the HUMAN's desktop instead of the generator's virtual display is
# how clicks end up on the wrong screen.
set -euo pipefail
if [ -n "${GEN_DISPLAY:-}" ]; then
    export DISPLAY="$GEN_DISPLAY"
elif [ "${DISPLAY:-}" = ":0" ]; then
    export DISPLAY=":98"
fi
: "${DISPLAY:=:98}"
export DISPLAY
# Disambiguate our Chrome by pid when other automation Chrome runs
# concurrently ("2 applications are named 'Google Chrome'").
pid=""
[ -f /tmp/gen-chrome.pid ] && pid=$(cat /tmp/gen-chrome.pid 2>/dev/null || true)
if [ -n "$pid" ] && [ -r "/proc/$pid/cmdline" ]; then
    APP="${LU_APP:-Google Chrome#pid$pid}"
else
    APP="${LU_APP:-Google Chrome}"
fi
verb="$1"; shift
query="$1"; shift || true

ref=$(linux-use state --app "$APP" --all --depth 45 2>/dev/null | python3 -c "
import json,sys
q=sys.argv[1].lower()
role=sys.argv[2] if len(sys.argv)>2 else ''
d=json.load(sys.stdin)
best=None
for e in d.get('elements',[]):
    n=(e.get('name') or '').lower()
    if q in n and (not role or e.get('role')==role):
        best=e; break
print(best['ref'] if best else '')
" "$query" "${LU_ROLE:-}")

[ -n "$ref" ] || { echo "lu.sh: no element matching '$query'" >&2; exit 82; }
if [ "$verb" = ref ]; then echo "$ref"; exit 0; fi
exec linux-use "$verb" "$ref" "$@"
