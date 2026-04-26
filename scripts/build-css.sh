#!/usr/bin/env bash
# Compile webapp/static/_src/input.css → webapp/static/css/app.css minifié.
# Le binaire tailwindcss standalone (Linux x64) est versionné dans scripts/.
#
# Usage : ./scripts/build-css.sh [--watch]

set -euo pipefail
cd "$(dirname "$0")/.."

WATCH=""
if [ "${1:-}" = "--watch" ]; then
    WATCH="--watch"
fi

./scripts/tailwindcss \
    -c tailwind.config.js \
    -i webapp/static/_src/input.css \
    -o webapp/static/css/app.css \
    --minify \
    $WATCH

ls -lh webapp/static/css/app.css 2>/dev/null || true
