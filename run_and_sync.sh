#!/bin/bash
# MLB Bot: daily run + PocketBase sync
# Starts PocketBase if not running, runs bot, syncs to website
set -e
cd "$(dirname "$0")"

# Start PocketBase if it's not already running
if ! pgrep -f "pocketbase serve" > /dev/null 2>&1; then
    echo "Starting PocketBase..."
    /Users/nickkernaghan/Desktop/pocketbase/bin/pocketbase serve \
        --dir /Users/nickkernaghan/Desktop/pocketbase/pb_data &
    sleep 2
fi

# Activate venv and run bot
source venv/bin/activate
source .env 2>/dev/null || true

LOG_DIR="./logs"
mkdir -p "$LOG_DIR"
DATE=$(date +%Y-%m-%d)

echo "[$DATE] Starting MLB Bot daily run + sync..."
python main.py 2>&1 | tee "$LOG_DIR/daily_${DATE}.log"
echo "[$DATE] Done."
