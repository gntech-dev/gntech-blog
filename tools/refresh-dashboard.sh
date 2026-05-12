#!/bin/bash
# Refresh dashboard data: scrape sources + regenerate static JSON
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_DIR="/home/gntech/.openclaw/workspace/dashboard"

echo "📡 Scraping sources..."
bash "$SCRIPT_DIR/fetch-sources.sh" > /dev/null 2>&1

echo "📊 Generating dashboard data..."
python3 -c "
import sys
sys.path.insert(0, '$DASHBOARD_DIR')
from serve import generate_static_data
generate_static_data()
print('Done')
"

echo "✅ Dashboard refreshed"
echo "   http://10.0.20.30:8765"
