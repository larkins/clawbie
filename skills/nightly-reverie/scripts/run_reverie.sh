#!/bin/bash
# Nightly reverie trigger - writes pending task for heartbeat to process
# Runs at 00:01 AEST (configurable in systemd timer)
#
# This script writes a pending reverie task to heartbeat-state.json.
# The next heartbeat (6am+) will see this and spawn a subagent to generate the reverie.
#
# Environment variables (set in systemd unit or .env):
#   OPENCLAW_WORKSPACE  - path to OpenClaw workspace (default: ~/.openclaw/workspace)

set -e

OPENCLAW_WORKSPACE="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}"

HEARTBEAT_STATE="${OPENCLAW_WORKSPACE}/memory/heartbeat-state.json"
LOG_FILE="${OPENCLAW_WORKSPACE}/logs/nightly_reverie.log"
PROMPT_FILE="${OPENCLAW_WORKSPACE}/skills/nightly-reverie/prompts/generate.md"

# Ensure directories exist
mkdir -p "$(dirname "$HEARTBEAT_STATE")"
mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$(dirname "$PROMPT_FILE")"

# Get yesterday's date
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG_FILE"
}

log "=========================================="
log "Reverie trigger for $YESTERDAY"
log "=========================================="

# Read existing state or create empty
if [ -f "$HEARTBEAT_STATE" ]; then
    STATE=$(cat "$HEARTBEAT_STATE")
else
    STATE="{}"
fi

# Add pending reverie task using Python (for JSON handling)
python3 << PY
import json
from pathlib import Path
from datetime import date, timedelta

state_file = Path("$HEARTBEAT_STATE")
yesterday = "$YESTERDAY"

# Read existing state
if state_file.exists():
    try:
        state = json.loads(state_file.read_text())
    except:
        state = {}
else:
    state = {}

# Add pending reverie task
state["pendingReverie"] = {
    "date": yesterday,
    "triggered_at": "$(date -Iseconds)",
    "status": "pending"
}

# Write back
state_file.write_text(json.dumps(state, indent=2))
print(f"Written pending reverie for {yesterday}")
PY

log "Pending reverie task written to $HEARTBEAT_STATE"
log "Next heartbeat will process and generate reverie"

if [ -f "$PROMPT_FILE" ]; then
    log "Prompt file exists: $PROMPT_FILE"
else
    log "WARNING: Prompt file not found: $PROMPT_FILE"
fi

log "Reverie trigger complete. Waiting for heartbeat to process."
