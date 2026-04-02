from __future__ import annotations

from pathlib import Path


def test_clawbie_schema_contains_required_tables() -> None:
    """Verify the consolidated schema has all required tables."""
    migration = Path(__file__).resolve().parents[1] / "migrations" / "CLAWBIE_SCHEMA.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "CREATE TABLE user_memories" in sql
    assert "CREATE TABLE sub_agent_activity" in sql
    assert "CREATE TABLE nightly_reverie" in sql


def test_clawbie_schema_contains_required_columns() -> None:
    """Verify user_memories table has all required columns."""
    migration = Path(__file__).resolve().parents[1] / "migrations" / "CLAWBIE_SCHEMA.sql"
    sql = migration.read_text(encoding="utf-8")

    required = [
        "memory_text",        # Core content
        "raw_embedding",      # Primary vector
        "reflection",         # Reflection text
        "reflection_embedding", # Reflection vector
        "source_type",        # Source tracking
        "source_ref",        # Source reference
        "session_id",        # Session tracking
        "user_id",           # User tracking
        "importance",        # Importance scoring
        "token_count",       # Token tracking
        "memory_hash",       # Deduplication
        "metadata",          # Flexible metadata
        "expires_at",        # Expiry
        "archived_at",       # Archival
        "status_commentary",  # Commentary flag
        "reverie_summarized", # Summarization flag
    ]

    for col in required:
        assert col in sql, f"Missing column: {col}"


def test_clawbie_schema_contains_vector_support() -> None:
    """Verify pgvector extension and vector indexes are present."""
    migration = Path(__file__).resolve().parents[1] / "migrations" / "CLAWBIE_SCHEMA.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "VECTOR(1024)" in sql
    assert "ivfflat" in sql or "IVFFlat" in sql or "hnsw" in sql or "HNSW" in sql


def test_clawbie_schema_contains_indexes() -> None:
    """Verify all required indexes are present."""
    migration = Path(__file__).resolve().parents[1] / "migrations" / "CLAWBIE_SCHEMA.sql"
    sql = migration.read_text(encoding="utf-8")

    required_indexes = [
        "idx_user_memories_created_at",
        "idx_user_memories_archive_status",
        "idx_user_memories_project_area",
        "idx_user_memories_reverie_summarized",
        "idx_user_memories_raw_embedding",
        "idx_user_memories_reflection_embedding",
        "idx_user_memories_metadata_gin",
    ]

    for idx in required_indexes:
        assert idx in sql, f"Missing index: {idx}"


def test_clawbie_schema_contains_constraints() -> None:
    """Verify CHECK constraints and unique constraints are present."""
    migration = Path(__file__).resolve().parents[1] / "migrations" / "CLAWBIE_SCHEMA.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "PRIMARY KEY" in sql
    assert "UNIQUE" in sql
    assert "CHECK" in sql


def test_clawbie_schema_sub_agent_activity_has_required_columns() -> None:
    """Verify sub_agent_activity table has required columns."""
    migration = Path(__file__).resolve().parents[1] / "migrations" / "CLAWBIE_SCHEMA.sql"
    sql = migration.read_text(encoding="utf-8")

    required = [
        "child_session_key",      # Unique identifier
        "agent_id",              # Agent tracking
        "status",                # Status field
        "notification_status",    # Notification tracking
        "parent_session_key",     # Parent routing
        "metadata",              # Flexible metadata
        "created_at",            # Timestamps
        "updated_at",
        "completed_at",
    ]

    for col in required:
        assert col in sql, f"Missing sub_agent_activity column: {col}"


def test_clawbie_schema_nightly_reverie_has_required_columns() -> None:
    """Verify nightly_reverie table has required columns."""
    migration = Path(__file__).resolve().parents[1] / "migrations" / "CLAWBIE_SCHEMA.sql"
    sql = migration.read_text(encoding="utf-8")

    required = [
        "date",                  # Unique date
        "summary_md",            # Summary content
        "reflections",           # Reflections
        "next_day_ideas",        # Next day ideas
        "memory_count",          # Memory count
        "created_at",            # Creation timestamp
        "emailed_at",            # Email delivery tracking
    ]

    for col in required:
        assert col in sql, f"Missing nightly_reverie column: {col}"
