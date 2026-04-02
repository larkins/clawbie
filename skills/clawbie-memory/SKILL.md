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

---

## Temporal Awareness — Projects, Intentions, and Redirects

These commands track what we're working on, what we intend to do, and when we steer the conversation.

### Active Project

**Set a new project** (pauses any current active project):
```bash
python skills/clawbie-memory/scripts/clawbie_memory.py project-set \
  --name "one_shot_email" \
  --description "AWS SES email relay setup" \
  --next-step "Get AWS credentials from Mal" \
  --priority 5
```

**Get current project:**
```bash
python skills/clawbie-memory/scripts/clawbie_memory.py project-get
```

**Update fields on active project:**
```bash
python skills/clawbie-memory/scripts/clawbie_memory.py project-update \
  --next-step "Walk SES domain verification" \
  --blocked-by "Waiting on Mal to generate AWS keys"
```

**Mark project complete:**
```bash
python skills/clawbie-memory/scripts/clawbie_memory.py project-complete
```

**List all projects:**
```bash
python skills/clawbie-memory/scripts/clawbie_memory.py project-list
```

### Session Intentions

**Add an intention** (what I intend to accomplish this session):
```bash
python skills/clawbie-memory/scripts/clawbie_memory.py intention-add \
  --text "Get AWS credentials from Mal" \
  --urgency high \
  --session-id main
```

**List pending intentions:**
```bash
python skills/clawbie-memory/scripts/clawbie_memory.py intention-pending
```

**Mark an intention fulfilled:**
```bash
python skills/clawbie-memory/scripts/clawbie_memory.py intention-fulfil \
  --id 5 \
  --outcome success \
  --note "Mal sent AWS access key + secret"
```

### Conversation Redirects

**Log when I steer the conversation back to the project:**
```bash
python skills/clawbie-memory/scripts/clawbie_memory.py redirect-add \
  --from-topic "memory chat" \
  --to-topic "one_shot_email" \
  --reason "Mal asked to refocus" \
  --accepted true
```

**View recent redirects:**
```bash
python skills/clawbie-memory/scripts/clawbie_memory.py redirect-recent --limit 10
```

**Redirect pattern stats (which topics do I redirect from most?):**
```bash
python skills/clawbie-memory/scripts/clawbie_memory.py redirect-stats
```

### Session State (Heartbeat)

Comprehensive status check for heartbeat agents:
```bash
python skills/clawbie-memory/scripts/clawbie_memory.py session-state
```

Returns:
- Current active project with next step and blockers
- Pending intentions (sorted by urgency)
- Overdue intentions (past deadline)
- Recent redirects

**Heartbeat usage:** Run `session-state` on every heartbeat. If there are overdue intentions or a stale project, nudge Mal.

---

## Core Memories — Long-Range Strategic Context

These are loaded at the start of every session — not reactive, but proactive. Unlike `user_memories` which are day-to-day reactive notes, `core_memories` capture foundational context that informs how I work.

Categories: `business`, `product`, `personality`, `architecture`, `values`, `relationships`, `goals`

### Write a core memory

```bash
python skills/clawbie-memory/scripts/clawbie_memory.py core-write \
  --category business \
  --text "agieth.ai is the core business — domain registration and email hosting"
```

### Read core memories

```bash
# All core memories
python skills/clawbie-memory/scripts/clawbie_memory.py core-read --limit 20

# Filter by category
python skills/clawbie-memory/scripts/clawbie_memory.py core-read --category business
```

### List categories and counts

```bash
python skills/clawbie-memory/scripts/clawbie_memory.py core-list
```

### Update or archive

```bash
python skills/clawbie-memory/scripts/clawbie_memory.py core-update --id 3 --text "Updated text"
python skills/clawbie-memory/scripts/clawbie_memory.py core-archive --id 3
```

**When to write a core memory:** When Mal tells me something foundational, strategic, or enduring — not something that happened today, but something that shapes how I should think and work going forward.
