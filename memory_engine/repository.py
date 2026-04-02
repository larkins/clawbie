from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

import json

if TYPE_CHECKING:
    from psycopg import Connection


@dataclass(frozen=True)
class PersistedMemory:
    id: Any
    created_at: datetime
    inserted: bool = True


@dataclass(frozen=True)
class MemoryRow:
    id: Any
    content: str
    reflection: str | None
    metadata: dict[str, Any]
    created_at: datetime
    importance: int
    raw_similarity: float
    reflection_similarity: float


class MemoryRepository:
    def __init__(self, conn: "Connection") -> None:
        self._conn = conn
        self._content_column = self._resolve_content_column()
        self._status_commentary_column = self._resolve_status_commentary_column()

    def _resolve_content_column(self) -> str:
        from psycopg.rows import dict_row

        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'user_memories'
                  AND column_name IN ('content', 'memory_text')
                """
            )
            columns = {row["column_name"] for row in cur.fetchall()}
        if "content" in columns:
            return "content"
        if "memory_text" in columns:
            return "memory_text"
        raise RuntimeError("user_memories must include either 'content' or 'memory_text' column")

    def _resolve_status_commentary_column(self) -> str | None:
        from psycopg.rows import dict_row

        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'user_memories'
                  AND column_name = 'status_commentary'
                """
            )
            row = cur.fetchone()
        if row is None:
            return None
        return "status_commentary"

    @staticmethod
    def _vector_literal(values: list[float] | None) -> str | None:
        if values is None:
            return None
        return "[" + ",".join(f"{value:.8f}" for value in values) + "]"

    def get_by_memory_hash(self, memory_hash: str) -> PersistedMemory | None:
        from psycopg.rows import dict_row

        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, created_at
                FROM user_memories
                WHERE memory_hash = %s
                LIMIT 1
                """,
                (memory_hash,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return PersistedMemory(id=row["id"], created_at=row["created_at"])

    def insert_memory(
        self,
        *,
        content: str,
        raw_embedding: list[float] | None,
        reflection: str | None,
        reflection_embedding: list[float] | None,
        source_type: str | None,
        source_ref: str | None,
        session_id: str | None,
        user_id: str | None,
        importance: int,
        token_count: int | None,
        memory_hash: str,
        metadata: dict[str, Any],
        project: str | None,
        area: str | None,
        archive_status: str,
        expires_at: datetime | None,
        archived_at: datetime | None,
        status_commentary: bool = False,
    ) -> PersistedMemory:
        from psycopg.rows import dict_row

        raw_vector = self._vector_literal(raw_embedding)
        reflection_vector = self._vector_literal(reflection_embedding)
        content_column = self._content_column

        columns = [
            content_column,
            "raw_embedding",
            "reflection",
            "reflection_embedding",
            "source_type",
            "source_ref",
            "session_id",
            "user_id",
            "importance",
            "token_count",
            "memory_hash",
            "metadata",
            "project",
            "area",
            "archive_status",
            "expires_at",
            "archived_at",
        ]
        values = [
            "%(content)s",
            "%(raw_embedding)s::vector",
            "%(reflection)s",
            "%(reflection_embedding)s::vector",
            "%(source_type)s",
            "%(source_ref)s",
            "%(session_id)s",
            "%(user_id)s",
            "%(importance)s",
            "%(token_count)s",
            "%(memory_hash)s",
            "%(metadata)s::jsonb",
            "%(project)s",
            "%(area)s",
            "%(archive_status)s",
            "%(expires_at)s",
            "%(archived_at)s",
        ]
        if self._status_commentary_column is not None:
            columns.append(self._status_commentary_column)
            values.append("%(status_commentary)s")

        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                INSERT INTO user_memories (
                    {", ".join(columns)}
                ) VALUES (
                    {", ".join(values)}
                )
                ON CONFLICT (memory_hash)
                DO UPDATE SET
                    metadata = user_memories.metadata || EXCLUDED.metadata
                RETURNING id, created_at, (xmax = 0) AS inserted
                """,
                {
                    "content": content,
                    "raw_embedding": raw_vector,
                    "reflection": reflection,
                    "reflection_embedding": reflection_vector,
                    "source_type": source_type,
                    "source_ref": source_ref,
                    "session_id": session_id,
                    "user_id": user_id,
                    "importance": importance,
                    "token_count": token_count,
                    "memory_hash": memory_hash,
                    "metadata": json.dumps(metadata),
                    "project": project,
                    "area": area,
                    "archive_status": archive_status,
                    "expires_at": expires_at,
                    "archived_at": archived_at,
                    "status_commentary": status_commentary,
                },
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Insert did not return id/created_at")
        self._conn.commit()
        return PersistedMemory(
            id=row["id"],
            created_at=row["created_at"],
            inserted=bool(row.get("inserted")),
        )

    def search_raw(
        self,
        *,
        query_embedding: list[float],
        limit: int,
        filters_sql: str,
        params: list[Any],
    ) -> list[MemoryRow]:
        from psycopg.rows import dict_row

        query_vector = self._vector_literal(query_embedding)
        content_column = self._content_column
        sql = f"""
            SELECT
                id,
                {content_column} AS content,
                reflection,
                metadata,
                created_at,
                importance,
                1 - (raw_embedding <=> %s::vector) AS raw_similarity,
                NULL::double precision AS reflection_similarity
            FROM user_memories
            WHERE raw_embedding IS NOT NULL
            {filters_sql}
            ORDER BY raw_embedding <=> %s::vector
            LIMIT %s
        """
        all_params = [query_vector, *params, query_vector, limit]
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, all_params)
            rows = cur.fetchall()
        return [
            MemoryRow(
                id=row["id"],
                content=row["content"],
                reflection=row["reflection"],
                metadata=row["metadata"] or {},
                created_at=row["created_at"],
                importance=int(row.get("importance") or 0),
                raw_similarity=float(row.get("raw_similarity") or 0.0),
                reflection_similarity=0.0,
            )
            for row in rows
        ]

    def search_reflection(
        self,
        *,
        query_embedding: list[float],
        limit: int,
        filters_sql: str,
        params: list[Any],
    ) -> list[MemoryRow]:
        from psycopg.rows import dict_row

        query_vector = self._vector_literal(query_embedding)
        content_column = self._content_column
        sql = f"""
            SELECT
                id,
                {content_column} AS content,
                reflection,
                metadata,
                created_at,
                importance,
                NULL::double precision AS raw_similarity,
                1 - (reflection_embedding <=> %s::vector) AS reflection_similarity
            FROM user_memories
            WHERE reflection_embedding IS NOT NULL
            {filters_sql}
            ORDER BY reflection_embedding <=> %s::vector
            LIMIT %s
        """
        all_params = [query_vector, *params, query_vector, limit]
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, all_params)
            rows = cur.fetchall()
        return [
            MemoryRow(
                id=row["id"],
                content=row["content"],
                reflection=row["reflection"],
                metadata=row["metadata"] or {},
                created_at=row["created_at"],
                importance=int(row.get("importance") or 0),
                raw_similarity=0.0,
                reflection_similarity=float(row.get("reflection_similarity") or 0.0),
            )
            for row in rows
        ]

    def search_exact_text(
        self,
        *,
        query_text: str,
        limit: int,
        filters_sql: str,
        params: list[Any],
    ) -> list[MemoryRow]:
        from psycopg.rows import dict_row

        content_column = self._content_column
        normalized_query = query_text.strip()
        if not normalized_query:
            return []
        like_query = f"%{normalized_query}%"

        sql = f"""
            SELECT
                id,
                {content_column} AS content,
                reflection,
                metadata,
                created_at,
                importance
            FROM user_memories
            WHERE (
                {content_column} ILIKE %s
                OR COALESCE(reflection, '') ILIKE %s
                OR COALESCE(source_ref, '') ILIKE %s
                OR LOWER(COALESCE(metadata->>'source_marker', '')) = LOWER(%s)
            )
            {filters_sql}
            ORDER BY created_at DESC
            LIMIT %s
        """
        all_params = [like_query, like_query, like_query, normalized_query, *params, limit]
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, all_params)
            rows = cur.fetchall()
        return [
            MemoryRow(
                id=row["id"],
                content=row["content"],
                reflection=row["reflection"],
                metadata=row["metadata"] or {},
                created_at=row["created_at"],
                importance=int(row.get("importance") or 0),
                raw_similarity=1.0,
                reflection_similarity=1.0,
            )
            for row in rows
        ]
