-- ============================================================
-- Clawbie Memory Engine — Complete Schema
-- PostgreSQL + pgvector
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- user_memories
-- Core memory storage with dual-vector embeddings
-- ============================================================

CREATE TABLE user_memories (
    id              SERIAL PRIMARY KEY,
    
    -- Memory content
    memory_text     TEXT NOT NULL,
    
    -- Vector embeddings (pgvector)
    raw_embedding           VECTOR(1024),
    reflection             TEXT,
    reflection_embedding    VECTOR(1024),
    
    -- Timestamps
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Categorization
    project         TEXT,
    area            TEXT,
    future_resource TEXT,
    archive_status  TEXT CHECK (archive_status IN ('active', 'archived', 'deleted')),
    
    -- Source tracking
    source_type     TEXT CHECK (source_type IN ('chat', 'email', 'code', 'doc', 'system')),
    source_ref      TEXT,
    session_id      TEXT,
    user_id         TEXT,
    
    -- Importance / token tracking
    importance      SMALLINT NOT NULL DEFAULT 0,
    token_count     INTEGER,
    
    -- Deduplication
    memory_hash     TEXT UNIQUE,
    
    -- Flexible metadata
    metadata        JSONB NOT NULL DEFAULT '{}',
    
    -- Expiry / archival
    expires_at      TIMESTAMP,
    archived_at     TIMESTAMP,
    
    -- Special flags
    status_commentary    BOOLEAN NOT NULL DEFAULT FALSE,
    reverie_summarized   BOOLEAN DEFAULT FALSE
);

-- Indexes
CREATE INDEX idx_user_memories_created_at          ON user_memories (created_at DESC);
CREATE INDEX idx_user_memories_archive_status      ON user_memories (archive_status);
CREATE INDEX idx_user_memories_project_area        ON user_memories (project, area);
CREATE INDEX idx_user_memories_reverie_summarized  ON user_memories (reverie_summarized) WHERE reverie_summarized = FALSE;

-- Vector indexes (IVFFlat — good for moderate datasets)
-- For larger scale, consider switching to HNSW:
--   CREATE INDEX idx_user_memories_raw_embedding_hnsw        ON user_memories USING hnsw (raw_embedding vector_cosine_ops);
--   CREATE INDEX idx_user_memories_reflection_embedding_hnsw ON user_memories USING hnsw (reflection_embedding vector_cosine_ops);
CREATE INDEX idx_user_memories_raw_embedding_ivfflat        ON user_memories USING ivfflat (raw_embedding vector_cosine_ops) WITH (lists = '100');
CREATE INDEX idx_user_memories_reflection_embedding_ivfflat ON user_memories USING ivfflat (reflection_embedding vector_cosine_ops) WITH (lists = '100');

-- JSONB GIN index for metadata queries
CREATE INDEX idx_user_memories_metadata_gin ON user_memories USING gin (metadata);

-- ============================================================
-- sub_agent_activity
-- Tracks Codex/ACP sub-agent runs for follow-up detection
-- ============================================================

CREATE TABLE sub_agent_activity (
    id                  BIGSERIAL PRIMARY KEY,
    
    -- Identity
    child_session_key   TEXT NOT NULL UNIQUE,
    run_id              TEXT,
    agent_id            TEXT NOT NULL,
    
    -- Parent session (for notification routing)
    parent_session_key     TEXT,
    parent_session_id       TEXT,
    
    -- Task info
    task_label          TEXT,
    task_summary        TEXT,
    status              TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (status IN ('unknown', 'pending', 'running', 'completed', 'failed')),
    
    -- Timing
    source_updated_at   TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMP,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Notification tracking
    notification_status     TEXT NOT NULL DEFAULT 'unknown'
                            CHECK (notification_status IN ('unknown', 'none', 'pending', 'sent')),
    notification_sent_at   TIMESTAMP,
    
    -- Source tracking
    session_file        TEXT,
    
    -- Flexible metadata
    metadata            JSONB NOT NULL DEFAULT '{}'
);

-- Indexes
CREATE INDEX idx_sub_agent_activity_agent_id              ON sub_agent_activity (agent_id);
CREATE INDEX idx_sub_agent_activity_parent_session_key     ON sub_agent_activity (parent_session_key);
CREATE INDEX idx_sub_agent_activity_status_updated_at     ON sub_agent_activity (status, updated_at DESC);

-- ============================================================
-- nightly_reverie
-- Daily memory synthesis summaries
-- ============================================================

CREATE TABLE nightly_reverie (
    id              SERIAL PRIMARY KEY,
    
    -- Date this reverie covers
    date            DATE NOT NULL UNIQUE,
    
    -- Generated content
    summary_md      TEXT NOT NULL,
    reflections     TEXT,
    next_day_ideas  TEXT,
    memory_count    INTEGER,
    
    -- Delivery tracking
    created_at      TIMESTAMP DEFAULT NOW(),
    emailed_at      TIMESTAMP
);

-- Indexes
CREATE INDEX idx_nightly_reverie_date ON nightly_reverie (date DESC);
