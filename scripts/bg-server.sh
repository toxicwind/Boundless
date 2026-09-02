#!/usr/bin/env bash
# bg-server — live-traced dev server (FastAPI on port 10200 by default).
# Streams every line to /tmp/bg_trace.log in real time.
# Usage: bash scripts/bg-server.sh [extra uvicorn args...]
set -e
cd "$(dirname "$0")/.."
exec ~/.omp/agent/managed-skills/bg-run/run.sh "python -u -m uvicorn web.server:app --host 0.0.0.0 --port 10200 --log-level info $*" server
