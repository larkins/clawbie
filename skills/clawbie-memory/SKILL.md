---
name: clawbie-memory
description: Query and analyze Clawbie `user_memories` directly for recent activity, exact-text matches, and follow-up/promise detection. Use when checking what happened recently, debugging heartbeat misses, inspecting `user_memories` rows by id, scanning recent memories/reflections for phrases like `report back`, or identifying open vs closed promises from recent assistant messages.
---

# Clawbie Memory

Use this skill when `memory_search` on workspace files is not enough and you need the underlying Clawbie `user_memories` rows.

## Quick start

- Use `scripts/clawbie_memory.py` instead of hand-writing SQL each time.
- Read `references/schema-and-queries.md` if you need the schema, heuristics, or query patterns.
- Prefer small recent windows first (`10`, `20`, `50`) before wider scans.

## Common commands

### Show recent rows

```bash
python skills/clawbie-memory/scripts/clawbie_memory.py recent --limit 10
```

### Inspect rows from a given id onward

```bash
python skills/clawbie-memory/scripts/clawbie_memory.py since-id 548 --limit 40
```

### Exact text search

```bash
python skills/clawbie-memory/scripts/clawbie_memory.py text-search --query "report back" --limit 20
```

### Promise scan over recent rows

```bash
python skills/clawbie-memory/scripts/clawbie_memory.py promise-scan --limit 20
```

## Workflow

1. Start with `recent` or `since-id`.
2. If debugging follow-up failures, run `promise-scan`.
3. Treat `promise-scan` as a lead generator, not final truth.
4. Manually verify whether a promise was actually closed by a later `DONE:` / `FAILED:` / user-visible completion.

## Promise heuristics

Open-promise markers include language like:
- `report back`
- `i'll update`
- `i'll let you know`
- `i'll confirm`
- `when finished`
- `follow up`
- `check and report`
- `i'll tell you when it's done`
- `i'm checking`
- `i'm pulling`
- `i'll send`
- `i'll message`
- `i'll come back with`

Closure markers include:
- `DONE:`
- `FAILED:`
- `completed`
- `sent`
- `resolved`
- `fixed`
- `I sent`
- `I updated`

## Safety

- Do not paste secrets from memory rows into chat.
- Summarize first; quote only what is needed.
- Be careful with duplicated relay chatter across heartbeat/main-agent session files.
