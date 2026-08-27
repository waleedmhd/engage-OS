#!/usr/bin/env bash
# Entrypoint: fix Railway volume permissions then drop to engageos via gosu.
# Railway mounts empty volumes as root:root. Since the Dockerfile does not
# set USER, this script runs as root, can chown the mounted volume, and
# then gosu drops privileges for the CMD.
set -euo pipefail

mkdir -p /app/media/memories
chown engageos:engageos /app/media 2>/dev/null || chmod 777 /app/media 2>/dev/null || true

exec gosu engageos "$@"
