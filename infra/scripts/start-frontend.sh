#!/usr/bin/env bash
# Start the Next.js standalone server. Run from `frontend/`.
set -euo pipefail

PORT="${PORT:-3000}"

if [ -f server.js ]; then
  exec node server.js
else
  exec npm start -- -p "$PORT"
fi
