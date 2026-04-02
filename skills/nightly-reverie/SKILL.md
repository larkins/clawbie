---
name: nightly-reverie
description: Run nightly reflection on day's memories, write summary to database, and email to user. Use for daily continuity - each session should start by loading the latest reverie. Can also retrieve historical reveries by date.
---

# Nightly Reverie

Daily reflection and synthesis of memories into a coherent summary for day-to-day continuity.

## Quick start

### Generate tonight's reverie

```bash
python skills/nightly-reverie/scripts/reverie.py generate --date 2026-03-20
```

### Get latest reverie (for session startup)

```bash
python skills/nightly-reverie/scripts/reverie.py get-latest
```

### Get reverie by date

```bash
python skills/nightly-reverie/scripts/reverie.py get --date 2026-03-19
```

### List recent reveries

```bash
python skills/nightly-reverie/scripts/reverie.py list --limit 10
```

## Workflow

### Generation (cron job at 00:01 AEST)

1. Fetch all unsummarized memories from previous day
2. Order by timestamp for temporal sequence
3. Consider the flow of events, decisions, and context
4. Synthesize into markdown summary with:
   - **Summary** - Key events and progress
   - **Reflections** - Insights and learnings
   - **Next Day Ideas** - Actionable items for continuity
5. Write to `nightly_reverie` table
6. Mark processed memories as `reverie_summarized = TRUE`
7. Email summary to user

### Session Startup

1. Call `get-latest` to retrieve yesterday's reverie
2. Read alongside today's memory files
3. Provides context for current session

## Database Schema

### nightly_reverie table

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| date | DATE | Date of the reverie (unique) |
| summary_md | TEXT | Markdown summary of the day |
| reflections | TEXT | Reflections and insights |
| next_day_ideas | TEXT | Ideas for next day |
| memory_count | INTEGER | Number of memories processed |
| created_at | TIMESTAMPTZ | When reverie was generated |
| emailed_at | TIMESTAMPTZ | When email was sent |

### user_memories table updates

| Column | Type | Description |
|--------|------|-------------|
| reverie_summarized | BOOLEAN | Whether this memory has been included in a reverie |

## Email format

- Subject: `Nightly Reverie - YYYY-MM-DD`
- Body: Markdown rendered to HTML (via MIME)
- Contains: Summary, Reflections, Next Day Ideas

## Integration with AGENTS.md

Session startup should include:
1. Read latest reverie (via `get-latest`)
2. Read today's memory file (`memory/YYYY-MM-DD.md`)
3. Read yesterday's memory file (`memory/YYYY-MM-DD.md`)
4. (If main session) Read `MEMORY.md`

This provides full context continuity without loading all raw memories.

## Troubleshooting

### No unsummarized memories

If `reverie_summarized = TRUE` for all recent rows, check:
```bash
python skills/nightly-reverie/scripts/reverie.py status
```

### Missing emails

Check email logs:
```bash
journalctl --user -u clawbie-reverie -n 50
```

### Manual mark as summarized

```sql
UPDATE user_memories SET reverie_summarized = TRUE WHERE DATE(created_at) = '2026-03-20';
```