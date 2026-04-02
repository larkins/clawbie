# Nightly Reverie System

A daily memory synthesis system that generates coherent summaries of the previous day's activity for day-to-day continuity.

## Overview

The nightly reverie system:
- Synthesizes memory entries from the previous day into a coherent narrative
- Identifies key themes, decisions, blockers, and progress
- Generates action items for the next day
- Emails the summary to the user
- Provides continuity between sessions without loading all raw memories

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     TRIGGER FLOW                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  systemd timer (00:01 AEST)                                     │
│       │                                                         │
│       ▼                                                         │
│  run_reverie.sh                                                 │
│       │                                                         │
│       │ Writes to: memory/heartbeat-state.json                 │
│       │   { "pendingReverie": { "date": "2026-03-20" } }         │
│       │                                                         │
│       ▼                                                         │
│  Next heartbeat (6:00am+)                                      │
│       │                                                         │
│       │ Checks HEARTBEAT.md → sees pendingReverie               │
│       │                                                         │
│       ▼                                                         │
│  sessions_spawn (runtime: subagent)                            │
│       │                                                         │
│       │ Reads {date} memories from user_memories                │
│       │ Synthesizes into markdown                               │
│       │ Writes to nightly_reverie table                         │
│       │ Updates reverie_summarized = TRUE                       │
│       │ Emails summary                                          │
│       │                                                         │
│       ▼                                                         │
│  DONE: Reverie generated, email sent                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## File Locations

| File | Purpose |
|------|---------|
| `skills/nightly-reverie/SKILL.md` | Skill documentation |
| `skills/nightly-reverie/scripts/run_reverie.sh` | Trigger script (writes to heartbeat-state.json) |
| `skills/nightly-reverie/scripts/reverie.py` | CLI tool for status, get-latest, etc. |
| `skills/nightly-reverie/scripts/oneoff_yesterday.py` | One-off generation script |
| `skills/nightly-reverie/prompts/generate.md` | LLM prompt template |
| `HEARTBEAT.md` | Defines heartbeat behavior (includes reverie check) |
| `memory/heartbeat-state.json` | State file with pendingReverie |
| `clawbie/systemd/clawbie-nightly-reverie.{service,timer}` | Systemd units |
| `clawbie/systemd/install.sh` | Installation script |
| `clawbie/scripts/openclaw_ws_client.py` | WebSocket client (not currently used) |

## Database Schema

### nightly_reverie table

```sql
CREATE TABLE nightly_reverie (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    summary_md TEXT NOT NULL,
    reflections TEXT,
    next_day_ideas TEXT,
    memory_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    emailed_at TIMESTAMPTZ
);

CREATE INDEX idx_nightly_reverie_date ON nightly_reverie(date DESC);
```

### user_memories table (modified)

```sql
ALTER TABLE user_memories 
ADD COLUMN reverie_summarized BOOLEAN DEFAULT FALSE;

CREATE INDEX idx_user_memories_reverie_summarized 
ON user_memories(reverie_summarized) 
WHERE reverie_summarized = FALSE;
```

## Session Startup

From `AGENTS.md`, sessions now load:

1. `SOUL.md` - Who you are
2. `USER.md` - Who you're helping
3. **Get latest reverie** - Synthesizes yesterday's context
4. `memory/YYYY-MM-DD.md` - Today + yesterday's raw memories
5. `MEMORY.md` - Long-term memory (main session only)

```bash
# Get latest reverie
python skills/nightly-reverie/scripts/reverie.py get-latest
```

## Heartbeat Integration

From `HEARTBEAT.md`, the heartbeat checks for `pendingReverie`:

```json
// memory/heartbeat-state.json
{
  "pendingReverie": {
    "date": "2026-03-20",
    "triggered_at": "2026-03-20T19:46:14+10:00",
    "status": "pending"
  }
}
```

If found, the heartbeat **spawns a subagent** to generate the reverie using `sessions_spawn` with `runtime: "subagent"`.

## Heartbeat Schedule

The heartbeat runs on a schedule:
- **On:** 6:00am - 10:00pm at 30-minute intervals
- **Off:** 10:00pm - 6:00am (no heartbeats)

Reveries triggered at 00:01 will be processed at **6:00am** when heartbeats resume.

## Reverie Content Format

```markdown
# Nightly Reverie - YYYY-MM-DD

## Summary
[2-3 paragraphs summarizing the day's work]

## Key Decisions
- [Decision 1 and rationale]
- [Decision 2 and rationale]

## Blockers & Issues
- [Issue and current status]

## Progress
- ✅ [Completed item 1]
- ✅ [Completed item 2]

## Reflections
[Insights, patterns, things that went well or could improve]

## Next Day Ideas
- [Action item 1]
- [Action item 2]

---
*Processed N memories*
```

## CLI Commands

```bash
# Check status of unsummarized memories
python skills/nightly-reverie/scripts/reverie.py status

# Get latest reverie
python skills/nightly-reverie/scripts/reverie.py get-latest

# Get reverie by date
python skills/nightly-reverie/scripts/reverie.py get --date 2026-03-19

# List recent reveries
python skills/nightly-reverie/scripts/reverie.py list --limit 10

# Generate reverie for a date (manual trigger)
python skills/nightly-reverie/scripts/reverie.py generate --date 2026-03-19 --mark
```

## Systemd Timer

```bash
# Install
cd ~/git/clawbie/systemd && bash install.sh

# Manual trigger
systemctl --user start clawbie-nightly-reverie.service

# Check timer status
systemctl --user list-timers | grep reverie

# View logs
journalctl --user -u clawbie-nightly-reverie.service -n 50
```

## Logs

- **Trigger log:** `~/.openclaw/workspace/logs/nightly_reverie.log`
- **Reveries database:** `clawbie.nightly_reverie` table

## Troubleshooting

### No reverie generated

1. Check if trigger ran: `cat ~/.openclaw/workspace/logs/nightly_reverie.log`
2. Check heartbeat state: `cat ~/.openclaw/workspace/memory/heartbeat-state.json`
3. Check systemd status: `systemctl --user status clawbie-nightly-reverie.service`
4. Check reveries table: `python skills/nightly-reverie/scripts/reverie.py status`

### Memories not being summarized

1. Check `reverie_summarized` column: `SELECT COUNT(*) FROM user_memories WHERE reverie_summarized = FALSE`
2. Generate manually: `python skills/nightly-reverie/scripts/reverie.py generate --date YYYY-MM-DD`

### Duplicate reveries

The table has `UNIQUE(date)` constraint. Re-running for the same date will update the existing row.

## Data Quality Tracking

Each reverie tracks:
- `memory_count` - Number of memories processed
- `created_at` - When the reverie was generated
- `emailed_at` - When the summary was emailed

## Integration with Clawbie Memory

The system integrates with the `user_memories` table in Clawbie:
- Memories have `reverie_summarized` boolean column
- After synthesis, all processed memories are marked `TRUE`
- Next reverie only processes `reverie_summarized = FALSE` rows

## History

- **2026-03-20**: Implemented heartbeat-based generation using `sessions_spawn`
- **2026-03-20**: Added `reverie_summarized` column to `user_memories`
- **2026-03-19**: First reverie generated manually (174 memories)
- **2026-03-20**: Second reverie generated via subagent (91 memories)

## Future Improvements

1. **Email sending**: Currently manual in subagent - could be automated
2. **Quality metrics**: Track average memory length, processing time
3. **Multi-day synthesis**: Generate weekly/monthly summaries
4. **Export formats**: PDF, HTML in addition to email