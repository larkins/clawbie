#!/bin/bash
# Wrapper to generate reverie for yesterday
cd /home/mal/git/clawbie
source .env
DATE=$(date -d "yesterday" +%Y-%m-%d)
exec /home/mal/git/clawbie/.venv/bin/python skills/nightly-reverie/scripts/generate_reverie.py --date "$DATE"