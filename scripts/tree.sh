#!/usr/bin/env bash
# Generate the project tree for documentation
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."
echo "# adaidea project tree"
echo
find . -type d \( -name node_modules -o -name __pycache__ -o -name .venv -o -name .git -o -name dist -o -name build \) -prune -o -type f -print 2>/dev/null | grep -vE "(__pycache__|\.pyc$)" | sort
