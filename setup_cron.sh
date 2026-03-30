#!/bin/bash
BOT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Setting up MLB Bot cron jobs..."
echo "Bot directory: $BOT_DIR"

# Morning analysis at 10 AM ET (14:00 UTC)
CRON_RUN="0 14 * * * cd $BOT_DIR && bash run_daily.sh >> $BOT_DIR/logs/cron.log 2>&1"

# Grade results at midnight ET (04:00 UTC)
CRON_GRADE="0 4 * * * cd $BOT_DIR && source venv/bin/activate && python main.py --grade-results >> $BOT_DIR/logs/grade.log 2>&1"

(crontab -l 2>/dev/null | grep -v "mlb-bot"; echo "$CRON_RUN"; echo "$CRON_GRADE") | crontab -

echo "Cron jobs installed:"
echo "  10:00 AM ET — Daily analysis"
echo "  12:00 AM ET — Grade results"
echo ""
echo "View with: crontab -l"
