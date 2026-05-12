#!/bin/bash
# Fetch blog content sources for topic discovery
# Outputs JSON topics pool to stdout
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/fetch-sources.py" "$@"
