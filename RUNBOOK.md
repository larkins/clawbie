# Clawbie Memory Engine Runbook

## Prerequisites

- PostgreSQL reachable locally.
- `user_memories` table already exists with:
  - `raw_embedding vector(1024)`
  - `reflection_embedding vector(1024)`
- Local embedding/inference services reachable from `.env` values.

## Setup

1. Create and activate project virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Prepare environment variables:

```bash
cp .env.example .env
# edit .env for local DSN/endpoints/models
```

## Apply Migrations

Run in order against the `clawbie` DB:

```bash
psql "$DATABASE_DSN" -f migrations/001_phase1_user_memories_evolution.sql
psql "$DATABASE_DSN" -f migrations/002_phase1_user_memories_indexes.sql
psql "$DATABASE_DSN" -f migrations/003_phase1_user_memories_status_commentary.sql
psql "$DATABASE_DSN" -f migrations/004_sub_agent_activity.sql
```

Single-file equivalent:

```bash
psql "$DATABASE_DSN" -f migrations/0001_phase1_memory_engine.sql
```

## Test

```bash
pytest -q
```

## Status Commentary Backfill

Use this when older rows were ingested before `status_commentary` cleanup existed.

Dry run first (no writes):

```bash
.venv/bin/python scripts/backfill_status_commentary.py --config config.yaml --dry-run
```

Apply cleanup:

```bash
.venv/bin/python scripts/backfill_status_commentary.py --config config.yaml
```

Safe rerun notes:

- Script is idempotent; rerunning only updates rows not already cleaned.
- It only updates rows that match the same status-commentary heuristic used by OpenClaw bridge ingestion.
- For matched rows, it enforces:
  - `status_commentary = true`
  - `raw_embedding = NULL`
  - `reflection = NULL`
  - `reflection_embedding = NULL`
  - `metadata.embedding_skipped_reason = "status_commentary"`

## OpenClaw Chat-Memory Bridge

Bridge purpose:

- Scans OpenClaw transcript files and ingests new user/assistant chat turns into `user_memories`.
- Skips tool and analysis/thinking noise by default.
- Stores source metadata (`source_file`, `source_message_id`, role, channel, source timestamp, source marker).
- Maintains idempotent progress in `.state/openclaw-bridge-state.json` so repeated scans do not reprocess old turns.

Config keys in `config.yaml`:

- `openclaw_bridge.transcript_globs`
- `openclaw_bridge.allowed_roles`
- `openclaw_bridge.excluded_channels`
- `openclaw_bridge.source_marker`
- `openclaw_bridge.source_type`
- `openclaw_bridge.poll_interval_seconds`
- `openclaw_bridge.state_path`

Optional env override:

- `OPENCLAW_TRANSCRIPT_GLOBS` (comma-separated glob list)

One-shot run:

```bash
.venv/bin/python -m memory_engine.openclaw_bridge --config config.yaml --once
```

Long-running poll mode:

```bash
.venv/bin/python -m memory_engine.openclaw_bridge --config config.yaml
```

## Systemd Automation (User)

This repository includes a daily memory-repair automation package under `systemd/`.

What it does:

- Scans `user_memories` rows missing any of:
  - `raw_embedding`
  - `reflection`
  - `reflection_embedding`
- Repairs only missing stages per row (does not recompute already-present stages).
- Writes a concise report with scanned/repaired/still-failed counts and failure samples.
- Attempts best-effort report notification via the email API base URL from `.env`.
- Always writes a local report log under `logs/repair-report-*.log`.

Email notification config for Mail Server API:

- Required:
  - `EMAIL_API_BASE_URL` (preferred base URL, example `http://192.168.4.41:5003`) or `EMAIL_SERVER` (legacy alias)
  - `EMAIL_TO` (recipient mailbox) or `EMAIL_ADDRESS` (used as recipient fallback)
- Auth mode A (login flow):
  - `EMAIL_ADDRESS`
  - `EMAIL_PASSWORD`
- Auth mode B (pre-issued token):
  - `EMAIL_BEARER_TOKEN`
- Optional endpoint overrides:
  - `EMAIL_AUTH_ENDPOINT` (default `/auth/login`)
  - `EMAIL_SEND_ENDPOINT` (default `/api/emails`)
  - `EMAIL_TIMEOUT_SECONDS` (default `10`)

Notification behavior:

- Authenticates (unless `EMAIL_BEARER_TOKEN` is supplied), then sends via `POST /api/emails`.
- Sends JSON requests with `Content-Type: application/json` for both login and email POST calls.
- Uses payload fields: `to`, `subject`, `body`.
- Never fails the repair job when notification fails; only `email_status` is marked failed.

Install for `systemctl --user`:

```bash
chmod +x systemd/install.sh
./systemd/install.sh
```

Manual run:

```bash
systemctl --user start clawbie-memory-repair.service
systemctl --user start clawbie-chat-bridge.service
systemctl --user start clawbie-sub-agent-activity.service
```

Inspect timer/service:

```bash
systemctl --user status clawbie-memory-repair.timer
systemctl --user status clawbie-memory-repair.service
systemctl --user status clawbie-chat-bridge.timer
systemctl --user status clawbie-chat-bridge.service
systemctl --user status clawbie-sub-agent-activity.timer
systemctl --user status clawbie-sub-agent-activity.service
```

Direct CLI run (without systemd):

```bash
.venv/bin/python -m memory_engine.repair_job --config config.yaml --log-dir logs
```

## Sub-Agent Activity Tracker

Purpose:

- Track delegated Codex ACP runs independently of heartbeat message delivery.
- Persist follow-up-relevant status into `sub_agent_activity`.

Data sources (local-first):

- `~/.openclaw/agents/codex/sessions/sessions.json`
- `~/.openclaw/agents/main/sessions/sessions.json`
- per-session JSONL transcripts referenced by those indexes

One-shot run:

```bash
.venv/bin/python -m memory_engine.sub_agent_activity_tracker --config config.yaml --once
```

Status heuristic:

- `running` when Codex ACP state is `running`.
- `completed` when Codex transcript has at least one assistant reply.
- `failed` when ACP state or spawn result indicates failure/rejection.
- `pending` when ACP state is queued/pending, or when spawn was accepted and transcript creation is still lagging.
- `pending` (instead of `unknown`) for fresh idle sessions with missing transcript file when source/spawn timestamps are recent.
- `notification_status`:
  - `sent` when parent session shows an inter-session message sourced from child session key.
  - `sent` (inferred) when child is completed and parent has a later assistant message.
  - `pending` for running/pending/completed rows without sent evidence.

Example inspection:

```bash
psql "$DATABASE_DSN" -c "SELECT child_session_key, run_id, status, notification_status, updated_at, completed_at FROM sub_agent_activity ORDER BY updated_at DESC LIMIT 10;"
```

## Integration Notes

- Ingestion service prompt is fixed to exactly: `summarise this in 20 lines or less`.
- If reflection generation fails, memory is still persisted.
- If embedding stages fail, memory is still persisted and stage failures are recorded.
- Pipeline errors are added to `metadata.pipeline_errors`.
- Retrieval performs dual search (`raw_embedding` + `reflection_embedding`) and weighted reranking.
- Default retrieval excludes memories where `metadata.sensitivity == "high"` unless explicitly requested.
