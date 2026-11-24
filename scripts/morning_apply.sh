#!/bin/bash
# JobPilot Auto-Apply Morning Runner
# Runs between 11:00 AM and 11:30 AM only
# If computer is on during this window, it starts applying automatically

set -e

PROJECT_DIR="/home/neosoft/myWork/AutomateJobApplying"
VENV="$PROJECT_DIR/.venv/bin/jobpilot"
LOG_FILE="$PROJECT_DIR/logs/cron_jobpilot.log"

# Check if current time is within 11:00-11:30 AM window
CURRENT_HOUR=$(date +%H)
CURRENT_MIN=$(date +%M)
CURRENT_TIME=$((CURRENT_HOUR * 100 + CURRENT_MIN))

START_TIME=1100  # 11:00 AM
END_TIME=1130    # 11:30 AM

echo "[$(date)] JobPilot auto-apply check started" >> "$LOG_FILE"

# Only run if within the time window
if [ "$CURRENT_TIME" -ge "$START_TIME" ] && [ "$CURRENT_TIME" -lt "$END_TIME" ]; then
    echo "[$(date)] Time window active (11:00-11:30). Starting JobPilot..." >> "$LOG_FILE"
    
    cd "$PROJECT_DIR"
    
    # Kill any leftover Chrome processes first
    pkill -9 -f chrome 2>/dev/null || true
    pkill -9 -f chromedriver 2>/dev/null || true
    sleep 2
    
    # Clean Chrome lock files
    rm -f "$PROJECT_DIR/data/chrome-profile/DevToolsActivePort" 2>/dev/null || true
    rm -f "$PROJECT_DIR/data/chrome-profile/SingletonLock" 2>/dev/null || true
    
    # Run JobPilot in manual browse mode (you click Easy Apply, bot fills forms)
    # Change to 'auto' if you want fully automatic applying
    "$VENV" --live run --only jobs >> "$LOG_FILE" 2>&1
    
    EXIT_CODE=$?
    echo "[$(date)] JobPilot finished with exit code: $EXIT_CODE" >> "$LOG_FILE"
else
    echo "[$(date)] Outside time window (11:00-11:30). Current time: $(date +%H:%M). Skipping." >> "$LOG_FILE"
fi

echo "[$(date)] JobPilot auto-apply check completed" >> "$LOG_FILE"
