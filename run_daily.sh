#!/bin/bash
set -e
cd "$(dirname "$0")"
source venv/bin/activate
source .env 2>/dev/null || true

LOG_DIR="./logs"
mkdir -p "$LOG_DIR"

DATE=$(date +%Y-%m-%d)
echo "[$DATE] Starting MLB Bot daily run..."

python main.py 2>&1 | tee "$LOG_DIR/daily_${DATE}.log"

echo "[$DATE] Done."
