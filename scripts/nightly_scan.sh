#!/bin/bash
# Consolidated Frontier Wild Watch Nightly Scan
# Uses the mobile-signed API (no browser required)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Load environment variables if they exist
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

# Fallback environment variables
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-8585207095:AAGpZSDJoqOOsd0z7tf21yHmWXFnp1dHb0w}"
export TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:--1003585664858}"

echo "--- Nightly Scan Started: $(date) ---"

# Jitter to avoid bot detection (0-10 minutes)
JITTER=$(( RANDOM % 601 ))
echo "Jitter: sleeping for ${JITTER}s..."
sleep $JITTER

# Run the scanner
# Note: No xvfb-run needed for mobile API
.venv/bin/python3 scanner.py --config config.json "$@"

echo "--- Nightly Scan Finished: $(date) ---"
