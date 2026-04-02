from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from .config import DatabaseConfig


@dataclass
class InsertResult:
    memory_id: int
    inserted: bool


class MemoryRepository:
    def insert_memory(self, payload: dict[str, Any]) -> InsertResult:
        raise NotImplementedError

    def query_candidates(
        self,
        *,
        vector: list[float],
        search_field: str,
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.9f}" for v in vector) + "]"


class PostgresMemoryRepository(MemoryRepository):
    def __init__(self, db: DatabaseConfig, table_name: str = "user_memories") -> None:
        self._dsn = (
            f"host={db.host} port={db.port} dbname={db.dbname} user={db.user} "
            f"password={db.password}"
        )
        self._table = table_name

    def insert_memory(self, payload: dict[str, Any]) -> InsertResult:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self._table} (
                        raw_text,
                        reflection,
                        raw_embedding,
                        reflection_embedding,
                        memory_hash,
                        source_type,
                        source_ref,
                        session_id,
                        user_id,
                        importance,
                        token_count,
                        metadata,
                        expires_at,
                        archive_status,
                        archived_at
                    ) VALUES (
                        %(raw_text)s,
                        %(reflection)s,
                        %(raw_embedding)s::vector,
                        %(reflection_embedding)s::vector,
                        %(memory_hash)s,
                        %(source_type)s,
                        %(source_ref)s,
                        %(session_id)s,
                        %(user_id)s,
                        %(importance)s,
                        %(token_count)s,
                        %(metadata)s,
                        %(expires_at)s,
                        %(archive_status)s,
                        %(archived_at)s
                    )
                    ON CONFLICT (memory_hash) DO NOTHING
                    RETURNING id
                    """,
                    {
                        "raw_text": payload["raw_text"],
                        "reflection": payload.get("reflection"),
                        "raw_embedding": _vector_literal(payload["raw_embedding"]),
                        "reflection_embedding": _vector_literal(payload["reflection_embedding"])
                        if payload.get("reflection_embedding") is not None
                        else None,
                        "memory_hash": payload.get("memory_hash"),
                        "source_type": payload.get("source_type"),
                        "source_ref": payload.get("source_ref"),
                        "session_id": payload.get("session_id"),
                        "user_id": payload.get("user_id"),
                        "importance": payload.get("importance", 0),
                        "token_count": payload.get("token_count"),
                        "metadata": Json(payload.get("metadata", {})),
                        "expires_at": payload.get("expires_at"),
                        "archive_status": payload.get("archive_status", "active"),
                        "archived_at": payload.get("archived_at"),
                    },
                )
                inserted_row = cur.fetchone()
                if inserted_row:
                    conn.commit()
                    return InsertResult(memory_id=int(inserted_row["id"]), inserted=True)

                cur.execute(
                    f"SELECT id FROM {self._table} WHERE memory_hash = %(memory_hash)s",
                    {"memory_hash": payload.get("memory_hash")},
                )
                existing = cur.fetchone()
                conn.commit()
                if not existing:
                    raise RuntimeError("insert skipped but memory not found")
                return InsertResult(memory_id=int(existing["id"]), inserted=False)

    def query_candidates(
        self,
        *,
        vector: list[float],
        search_field: str,
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        allowed_search_fields = {"raw_embedding", "reflection_embedding"}
        if search_field not in allowed_search_fields:
            raise ValueError(f"unsupported search field: {search_field}")

        where_parts = ["archive_status = 'active'", f"{search_field} IS NOT NULL"]
        params: dict[str, Any] = {
            "query_vector": _vector_literal(vector),
            "limit": limit,
        }

        filters = filters or {}
        if filters.get("user_id"):
            where_parts.append("user_id = %(user_id)s")
            params["user_id"] = filters["user_id"]
        if filters.get("source_type"):
            where_parts.append("source_type = %(source_type)s")
            params["source_type"] = filters["source_type"]
        if filters.get("session_id"):
            where_parts.append("session_id = %(session_id)s")
            params["session_id"] = filters["session_id"]
        if filters.get("archive_status"):
            where_parts = [part for part in where_parts if not part.startswith("archive_status")]
            where_parts.append("archive_status = %(archive_status)s")
            params["archive_status"] = filters["archive_status"]
        if filters.get("metadata_contains"):
            where_parts.append("metadata @> %(metadata_contains)s::jsonb")
            params["metadata_contains"] = Json(filters["metadata_contains"])

        where_sql = " AND ".join(where_parts)
        query = f"""
            SELECT
                id,
                raw_text,
                reflection,
                importance,
                created_at,
                metadata,
                source_type,
                source_ref,
                user_id,
                session_id,
                archive_status,
                ({search_field} <=> %(query_vector)s::vector) AS distance
            FROM {self._table}
            WHERE {where_sql}
            ORDER BY {search_field} <=> %(query_vector)s::vector
            LIMIT %(limit)s
        """

        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
                conn.commit()
        return [dict(row) for row in rows]
