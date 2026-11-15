#!/bin/bash
# Install cron job for JobPilot morning auto-apply
# Runs every 15 minutes between 11:00-11:30 AM on weekdays

CRON_LINE="*/15 11 * * 1-5 /home/neosoft/myWork/AutomateJobApplying/scripts/morning_apply.sh"

echo "=== JobPilot Cron Setup ==="
echo ""
echo "This will add a cron job to run JobPilot every 15 minutes"
echo "between 11:00 AM and 11:30 AM on weekdays (Mon-Fri)."
echo ""
echo "Cron line: $CRON_LINE"
echo ""

# Check if already installed
if crontab -l 2>/dev/null | grep -q "morning_apply.sh"; then
    echo "Cron job already installed!"
    crontab -l | grep "morning_apply.sh"
else
    # Install the cron job
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "Cron job installed successfully!"
    echo ""
    echo "Current crontab:"
    crontab -l
fi

echo ""
echo "To view:   crontab -l"
echo "To remove: crontab -r (removes ALL cron jobs)"
echo "To edit:   crontab -e"
