#!/usr/bin/env bash
# bg-test — live-traced pytest run for the Boundless project.
# Streams every line to /tmp/bg_trace.log in real time.
# Usage: bash scripts/bg-test.sh [extra pytest args...]
set -e
cd "$(dirname "$0")/.."
exec ~/.omp/agent/managed-skills/bg-run/run.sh "python -u -m pytest tests/test_e2e.py -v --tb=short $*" pytest
