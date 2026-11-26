#!/bin/sh
# Regenerate docs/version.json from the latest GitHub release's binary asset.
# The update command (cli-update-spec) fetches this file via the gh-pages site:
#   https://javimosch.github.io/linux-use/version.json
# Usage: contrib/mk-version-json.sh [tag]     (default: latest release)
set -eu

TAG="${1:-$(gh release view --json tagName -q .tagName)}"
ASSET="$(gh release view "$TAG" --json assets -q '.assets[] | select(.name | endswith("x86_64-linux")) | .name' | head -1)"
[ -n "$ASSET" ] || { echo "no x86_64-linux asset on $TAG" >&2; exit 1; }

SHA="$(curl -sfL "https://github.com/javimosch/linux-use/releases/download/$TAG/$ASSET.sha256" | awk '{print $1}')"
[ ${#SHA} -eq 64 ] || { echo "bad sha256: $SHA" >&2; exit 1; }

SHORT="${SHA%"${SHA#????????????}"}"
printf '{"ok":true,"version":"%s","download":"https://github.com/javimosch/linux-use/releases/download/%s/%s","sha256":"%s"}\n' \
  "$SHORT" "$TAG" "$ASSET" "$SHA" > docs/version.json
echo "wrote docs/version.json ($TAG, $SHORT)"
