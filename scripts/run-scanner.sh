#!/bin/bash
# Move to project directory
cd "$(dirname "$0")/.."

# Ensure we use the virtual environment
export PATH="$(pwd)/.venv/bin:$PATH"

# Environment variables for notifications
export TELEGRAM_BOT_TOKEN="8585207095:AAGpZSDJoqOOsd0z7tf21yHmWXFnp1dHb0w"
export TELEGRAM_CHAT_ID="-1003585664858"

echo "--- Scan started at $(date) ---"

# Add random jitter (0-600 seconds) to stagger runs
JITTER=$(( RANDOM % 601 ))
echo "Jitter: sleeping for ${JITTER}s..."
sleep $JITTER

# Use xvfb-run with the resolution we verified works
xvfb-run -s "-screen 0 1280x1024x24" -a python3 scanner.py --config config.json "$@"

echo "--- Scan finished at $(date) ---"
