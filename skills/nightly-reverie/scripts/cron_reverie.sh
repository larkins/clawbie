#!/bin/bash
# Nightly reverie cron - runs at 00:01 AEST
# Generates daily summary from memories and emails to user
#
# Environment variables (set or override in systemd unit):
#   REPO_ROOT      - path to clawbie repo (default: ~/git/clawbie)
#   OPENCLAW_WORKSPACE - path to OpenClaw workspace (default: ~/.openclaw/workspace)

set -e

REPO_ROOT="${REPO_ROOT:-$HOME/git/clawbie}"
OPENCLAW_WORKSPACE="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}"

REVERIE_SCRIPT="${REPO_ROOT}/skills/nightly-reverie/scripts/reverie.py"
LOG_FILE="${OPENCLAW_WORKSPACE}/logs/nightly_reverie.log"

# Load DATABASE_URL from clawbie .env
if [ -f "${REPO_ROOT}/.env" ]; then
    export DATABASE_URL=$(grep "^DATABASE_URL=" "${REPO_ROOT}/.env" | cut -d'=' -f2- | tr -d '"')
fi

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Log function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG_FILE"
}

log "Starting nightly reverie generation..."

# Get yesterday's date
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)

# Run the reverie generation
log "Generating reverie for $YESTERDAY..."

# Source virtual environment
source "${REPO_ROOT}/.venv/bin/activate"
export DATABASE_URL

python "$REVERIE_SCRIPT" status >> "$LOG_FILE" 2>&1

log "Nightly reverie cron completed"
