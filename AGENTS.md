# AGENTS.md — Clawbie Memory Engine

> ⚠️ **Security note:** This is an open source project. Before working with secrets, credentials, or external APIs, read `SECURITY.md` for the project's security guidelines and secrets policy.

This document defines the implementation plan for Clawbie's core memory architecture using PostgreSQL + pgvector, local embedding services, and local inference.

## Objective

Build a robust memory engine that supports:

- durable storage of raw memories
- semantic reflection/summarization of memories
- dual-vector retrieval (raw + reflection)
- metadata-aware ranking and filtering
- extensible ingestion from chat, code blocks, prompts, and email

## Environment Assumptions

- PostgreSQL database: `clawbie`
- Existing table: `user_memories`
- Existing vector columns:
  - `raw_embedding vector(1024)`
  - `reflection_embedding vector(1024)`
- Embedding service available on local network
- Inference LLM available on local network
- Email server available on local network

(Endpoints and credentials are configured in local `.env`.)

## Technical Requirements (Integrated)

The following are mandatory engineering constraints for this project:

- Language/runtime: Python only.
- Web/API stack (if needed): Flask app.
  - Local development: Flask dev server.
  - Service mode: Gunicorn.
- Testing framework: `pytest`.
- Network binding: never `0.0.0.0`; bind to `127.0.0.1` or a specific local interface IP.
- Database: local PostgreSQL.
- Python environment: project-local `.venv` only.
  - Install packages with `pip` into `.venv`.
  - Never use system-wide package installs.
- Dependencies: maintain tracked `requirements.txt`.
- Secrets/machine-specific values: `.env` (untracked).
- Tracked environment template: `.env.example`.
- Non-secret runtime/config settings: tracked `config.yaml`.
- Service orchestration: `systemctl --user` for API service and daily timer jobs.
- Engineering workflow quality gate:
  - After code changes, update/add tests as needed.
  - Run `pytest` and require passing tests before completion.

## Core Memory Flow

### Write / Ingestion Pipeline

For each memory candidate:

1. Receive raw text payload (chat, code, prompt, email excerpt, etc.)
2. Normalize and hash payload for dedupe
3. Generate embedding for raw text
4. Send raw text to inference model with prompt:
   - `summarise this in 20 lines or less`
5. Store summary as `reflection`
6. Generate embedding for reflection
7. Persist row with both vectors + metadata

### Read / Retrieval Pipeline

For each query:

1. Embed query text
2. Perform vector similarity search against:
   - `raw_embedding`
   - `reflection_embedding`
3. Merge candidates and rerank with weighted scoring
4. Apply metadata filters (`project`, `area`, `archive_status`, etc.)
5. Return top-K memory packets for context injection

## Schema Evolution Plan

Extend `user_memories` with:

- `source_type text` (`chat`, `email`, `code`, `doc`, `system`)
- `source_ref text` (message-id, file path, URL, etc.)
- `session_id text`
- `user_id text`
- `importance smallint default 0`
- `token_count int`
- `memory_hash text unique`
- `metadata jsonb default '{}'::jsonb`
- `expires_at timestamp null`
- `archived_at timestamp null`

Validation/consistency:

- enforce controlled values for `archive_status`
- optional check constraints for known `source_type`

## Indexing Plan

### Vector Indexes

Create pgvector indexes for:

- `raw_embedding`
- `reflection_embedding`

Choose index type and params based on scale:

- initial: IVFFlat for simplicity
- upgrade path: HNSW for higher recall/latency tradeoff

### Relational Indexes

Create supporting indexes on:

- `created_at`
- `archive_status`
- `(project, area)`
- `metadata` (GIN)

## Ranking Strategy

Default blended scoring:

- `0.55 * reflection_similarity`
- `0.35 * raw_similarity`
- `0.10 * recency_boost`
- plus optional `importance` boost

Rationale:

- reflection vectors capture conceptual intent
- raw vectors preserve exact phrasing/details
- recency helps active-context relevance

## Memory Typing

Store memory class in `metadata.memory_type`:

- `fact`
- `preference`
- `decision`
- `todo`
- `artifact`
- `summary`

Benefits:

- targeted retrieval by memory type
- higher precision for assistant prompts

## Email Integration Plan

Ingest selected email content as memory:

- `source_type = 'email'`
- `source_ref = message-id`
- include sender/subject/timestamps in `metadata`

Gate before storing:

- skip low-value/promotional content
- keep actionable, preference-revealing, or high-context content

## Reliability and Failure Modes

Pipeline should be resilient and non-blocking:

- if reflection generation fails, still persist raw text + raw embedding
- track per-stage failures in `metadata.pipeline_errors`
- support retry queue/backoff for transient network/model failures

## Privacy and Safety Controls

- add optional redaction pass before embedding
- store sensitivity level in metadata (`low|medium|high`)
- exclude high-sensitivity memories from default retrieval unless explicitly requested
- avoid logging secrets in application logs

## Implementation Phases

### Phase 1 - Foundation

- migrations for schema evolution
- vector + relational indexes
- implement ingestion pipeline with dual embedding flow
- implement baseline retrieval query + rerank

### Phase 2 - Hardening

- dedupe via `memory_hash`
- retry/backoff and observability
- memory typing/classification
- ingestion adapters for email + code blocks

### Phase 3 - Optimization

- periodic consolidation (cluster/summarize related memories)
- archival policy for stale/low-value records
- adaptive ranking tuning from usage feedback

## Phase-to-Requirements Mapping

### Phase 1 - Foundation (Constraint Mapping)

- Python-only implementation modules for ingestion/retrieval.
- If API endpoints are introduced, use Flask structure from day one.
- Use project `.venv` for all installs and execution.
- Add/update `requirements.txt` with all new dependencies.
- Keep secrets/endpoints in `.env`; do not hardcode in source.
- Ensure non-secret runtime defaults are represented in tracked `config.yaml`.
- Enforce safe network binding (`127.0.0.1` or explicit interface IP only).
- Add baseline `pytest` coverage for:
  - migration verification
  - ingestion success path
  - retrieval scoring merge behavior

### Phase 2 - Hardening (Constraint Mapping)

- Expand Flask API handlers (if present) with robust validation and error handling.
- Add retries/backoff and verify behavior with `pytest` failure-mode tests.
- Extend `requirements.txt` only as needed; keep dependency footprint minimal.
- Add `.env.example` keys for new required settings (without secrets).
- Ensure service scripts/config are suitable for `systemctl --user` operation.
- Add tests for dedupe, classification, and adapter-level ingestion.

### Phase 3 - Optimization (Constraint Mapping)

- Implement scheduled consolidation/archive workflows designed for `systemctl --user` timers.
- Parameterize optimization settings in `config.yaml` (non-secret values).
- Add performance/regression tests with `pytest` for ranking and archive rules.
- Keep all interfaces bound safely (no `0.0.0.0`) during optimization services.

### Definition of Done (All Phases)

A phase is complete only when all are true:

1. Code is Python-only and runs in project `.venv`.
2. Dependencies are captured in tracked `requirements.txt`.
3. Secrets remain in `.env`, with corresponding non-secret templates/config tracked.
4. Any API/service bind address is safe (`127.0.0.1` or specific local IP).
5. Tests are updated/added and `pytest` passes.

## Deliverables

1. SQL migration scripts
2. Ingestion service contract and implementation
3. Retrieval SQL/function API
4. Basic tests (pipeline + ranking correctness)
5. Operational docs (runbook, failure handling, tuning)

## Notes

- Keep architecture modular: embedding provider and inference provider should be swappable.
- Prefer idempotent writes and deterministic retries.
- Treat this document as the authoritative high-level plan for memory-engine implementation.
