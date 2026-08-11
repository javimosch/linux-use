#!/bin/sh
# Build linux-use — compose machweb + flags frameworks with the app source.
set -e
cd "$(dirname "$0")"
machin encode framework/machweb.src framework/flags.src src/main.src > app.mfl
machin build app.mfl -o linux-use
echo "built linux-use ($(ls -lh linux-use | awk '{print $5}'))"
