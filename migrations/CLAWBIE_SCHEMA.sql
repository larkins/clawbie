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

-- ============================================================
-- active_projects
-- Tracks the current project/state machine driving session focus
-- ============================================================

CREATE TABLE active_projects (
    id              SERIAL PRIMARY KEY,
    
    -- Project identity
    project_name    TEXT NOT NULL,
    description     TEXT,
    
    -- Status
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'paused', 'completed', 'abandoned')),
    
    -- Timeline
    started_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    completed_at    TIMESTAMP,
    
    -- State machine fields
    next_step       TEXT,
    blocked_by      TEXT,
    progress_note   TEXT,
    
    -- Priority (higher = more important)
    priority        SMALLINT NOT NULL DEFAULT 0,
    
    -- Metadata
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_active_projects_status ON active_projects (status);
CREATE INDEX idx_active_projects_priority ON active_projects (priority DESC);
CREATE INDEX idx_active_projects_started ON active_projects (started_at DESC);

-- ============================================================
-- session_intentions
-- What I intended to accomplish this session, with fulfillment tracking
-- ============================================================

CREATE TABLE session_intentions (
    id              SERIAL PRIMARY KEY,
    
    -- Context
    session_id      TEXT NOT NULL,
    project_id      INTEGER REFERENCES active_projects(id) ON DELETE SET NULL,
    
    -- What was intended
    intention_text  TEXT NOT NULL,
    description     TEXT,
    description_embedding VECTOR(1024),
    
    -- Status
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_progress', 'fulfilled', 'abandoned', 'superseded')),
    
    -- Urgency
    urgency         TEXT DEFAULT 'normal'
                    CHECK (urgency IN ('low', 'normal', 'high', 'critical')),
    deadline        TIMESTAMP,
    
    -- Tracking
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    fulfilled_at    TIMESTAMP,
    
    -- Fulfillment detail
    fulfillment_note TEXT,
    outcome         TEXT CHECK (outcome IN ('success', 'partial', 'failed', 'redirected'))
);

CREATE INDEX idx_session_intentions_session ON session_intentions (session_id);
CREATE INDEX idx_session_intentions_status ON session_intentions (status);
CREATE INDEX idx_session_intentions_created ON session_intentions (created_at DESC);
CREATE INDEX idx_session_intentions_pending ON session_intentions (created_at DESC) WHERE status IN ('pending', 'in_progress');

-- ============================================================
-- session_redirects
-- Logs when I steer the conversation back to a project
-- Used for pattern detection: am I constantly redirecting from X to Y?
-- ============================================================

CREATE TABLE session_redirects (
    id              SERIAL PRIMARY KEY,
    
    -- Context
    session_id      TEXT NOT NULL,
    
    -- What was redirected
    redirected_from TEXT NOT NULL,
    redirected_to  TEXT NOT NULL,
    reason          TEXT,
    
    -- Outcome
    accepted        BOOLEAN DEFAULT TRUE,
    accepted_note   TEXT,
    
    -- For semantic search on redirect patterns
    description_embedding VECTOR(1024),
    
    -- Metadata
    metadata        JSONB NOT NULL DEFAULT '{}',
    
    -- Tracking
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_session_redirects_session ON session_redirects (session_id);
CREATE INDEX idx_session_redirects_created ON session_redirects (created_at DESC);
CREATE INDEX idx_session_redirects_from ON session_redirects (redirected_from);
CREATE INDEX idx_session_redirects_to ON session_redirects (redirected_to);

-- ============================================================
-- core_memories
-- Long-range strategic context — loaded at session start
-- Unlike user_memories which are reactive, these are foundational
-- ============================================================

CREATE TABLE IF NOT EXISTS core_memories (
    id              SERIAL PRIMARY KEY,
    category        TEXT NOT NULL
                        CHECK (category IN ('business', 'product', 'personality', 'architecture', 'values', 'relationships', 'goals')),
    memory_text     TEXT NOT NULL,
    embedding       VECTOR(1024),
    source          TEXT DEFAULT 'conversation'
                        CHECK (source IN ('conversation', 'explicit', 'inferred')),
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMP DEFAULT NOW(),
    updated_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_core_memories_category ON core_memories (category);
CREATE INDEX IF NOT EXISTS idx_core_memories_active ON core_memories (active);
