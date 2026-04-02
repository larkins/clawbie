# Clawbie Memory Schema and Query Notes

## Table

Primary table used by this skill:
- `public.user_memories`

Relevant columns seen locally:
- `id`
- `memory_text`
- `reflection`
- `created_at`
- `source_type`
- `source_ref`
- `session_id`
- `user_id`
- `metadata`
- `status_commentary`

## Data source

Default connection details come from:
- `.env` (copy `.env.example` to `.env` and configure)

Expected env vars:
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`

## Useful patterns

### Recent rows
Use a small recent window first to avoid drowning in noise.

### Since a specific id
Best for debugging a known sequence.

### Exact text search
Useful for phrases like:
- `report back`
- `i'm pulling`
- `DONE:`
- `FAILED:`
- `heartbeat_ok`

### Promise scan
Use lexical heuristics first, then manually check whether a later row clearly closed the promise.

## Important caveats

- Recent rows may include duplicated heartbeat/main-agent relay chatter.
- Reflections can compress commitments more clearly than raw text.
- A promise-looking row is not enough by itself; check for a later close signal.
- System/status chatter may look like activity without meaningfully notifying the user.
