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
set -euo pipefail
: "${DISPLAY:=:99}"
export DISPLAY
APP="${LU_APP:-Google Chrome}"
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
