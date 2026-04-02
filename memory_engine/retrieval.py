from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import re
from typing import Any

from .providers import EmbeddingProvider
from .repository import MemoryRepository, MemoryRow


@dataclass(frozen=True)
class RetrievalFilters:
    project: str | None = None
    area: str | None = None
    archive_status: str | None = "active"
    source_type: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    metadata_contains: dict[str, Any] = field(default_factory=dict)
    include_high_sensitivity: bool = False
    include_status_commentary: bool = False


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    top_k: int
    raw_candidate_k: int
    reflection_candidate_k: int
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)


@dataclass(frozen=True)
class MemoryCandidate:
    id: Any
    content: str
    reflection: str | None
    metadata: dict[str, Any]
    created_at: datetime
    raw_similarity: float
    reflection_similarity: float
    recency_boost: float
    importance_boost: float
    score: float


class MemoryRetrievalService:
    _MARKER_QUERY_PATTERN = re.compile(r"[A-Za-z].{4,}")

    def __init__(
        self,
        *,
        repository: MemoryRepository,
        embedding_provider: EmbeddingProvider,
        reflection_weight: float = 0.55,
        raw_weight: float = 0.35,
        recency_weight: float = 0.10,
        importance_weight: float = 0.02,
        recency_half_life_days: float = 30.0,
    ) -> None:
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._reflection_weight = reflection_weight
        self._raw_weight = raw_weight
        self._recency_weight = recency_weight
        self._importance_weight = importance_weight
        self._recency_half_life_days = recency_half_life_days

    def _compile_filters(self, filters: RetrievalFilters) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if filters.project:
            clauses.append("project = %s")
            params.append(filters.project)
        if filters.area:
            clauses.append("area = %s")
            params.append(filters.area)
        if filters.archive_status:
            clauses.append("archive_status = %s")
            params.append(filters.archive_status)
        if filters.source_type:
            clauses.append("source_type = %s")
            params.append(filters.source_type)
        if filters.user_id:
            clauses.append("user_id = %s")
            params.append(filters.user_id)
        if filters.session_id:
            clauses.append("session_id = %s")
            params.append(filters.session_id)
        if filters.metadata_contains:
            clauses.append("metadata @> %s::jsonb")
            params.append(json.dumps(filters.metadata_contains))
        if not filters.include_high_sensitivity:
            clauses.append("(metadata->>'sensitivity') IS DISTINCT FROM 'high'")
        if not filters.include_status_commentary:
            clauses.append("status_commentary = FALSE")

        filters_sql = ""
        if clauses:
            filters_sql = " AND " + " AND ".join(clauses)
        return filters_sql, params

    def _recency_boost(self, created_at: datetime, now: datetime) -> float:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = max((now - created_at).total_seconds() / 86400.0, 0.0)
        return math.exp(-math.log(2) * age_days / self._recency_half_life_days)

    @classmethod
    def _is_marker_style_query(cls, query: str) -> bool:
        trimmed = query.strip()
        if " " in trimmed or len(trimmed) < 6:
            return False
        if cls._MARKER_QUERY_PATTERN.fullmatch(trimmed) is None:
            return False

        has_digit = any(char.isdigit() for char in trimmed)
        has_marker_punctuation = any(char in "-_:/#." for char in trimmed)
        return has_digit or has_marker_punctuation

    def search(self, request: RetrievalRequest) -> list[MemoryCandidate]:
        query_embedding = self._embedding_provider.embed(request.query)
        filters_sql, params = self._compile_filters(request.filters)

        raw_rows = self._repository.search_raw(
            query_embedding=query_embedding,
            limit=request.raw_candidate_k,
            filters_sql=filters_sql,
            params=params,
        )
        reflection_rows = self._repository.search_reflection(
            query_embedding=query_embedding,
            limit=request.reflection_candidate_k,
            filters_sql=filters_sql,
            params=params,
        )
        exact_rows: list[MemoryRow] = []
        if self._is_marker_style_query(request.query):
            search_exact = getattr(self._repository, "search_exact_text", None)
            if callable(search_exact):
                exact_rows = search_exact(
                    query_text=request.query,
                    limit=max(request.top_k, 1),
                    filters_sql=filters_sql,
                    params=params,
                )

        by_id: dict[Any, MemoryRow] = {}

        for row in raw_rows:
            by_id[row.id] = row

        for row in reflection_rows:
            existing = by_id.get(row.id)
            if existing is None:
                by_id[row.id] = row
            else:
                by_id[row.id] = MemoryRow(
                    id=existing.id,
                    content=existing.content,
                    reflection=existing.reflection or row.reflection,
                    metadata=existing.metadata or row.metadata,
                    created_at=existing.created_at,
                    importance=max(existing.importance, row.importance),
                    raw_similarity=max(existing.raw_similarity, row.raw_similarity),
                    reflection_similarity=max(existing.reflection_similarity, row.reflection_similarity),
                )
        for row in exact_rows:
            existing = by_id.get(row.id)
            if existing is None:
                by_id[row.id] = row
                continue
            by_id[row.id] = MemoryRow(
                id=existing.id,
                content=existing.content or row.content,
                reflection=existing.reflection or row.reflection,
                metadata=existing.metadata or row.metadata,
                created_at=existing.created_at,
                importance=max(existing.importance, row.importance),
                raw_similarity=max(existing.raw_similarity, row.raw_similarity),
                reflection_similarity=max(existing.reflection_similarity, row.reflection_similarity),
            )

        now = datetime.now(timezone.utc)
        ranked: list[MemoryCandidate] = []
        for row in by_id.values():
            recency = self._recency_boost(row.created_at, now)
            importance = max(min(float(row.importance) / 10.0, 1.0), 0.0)
            score = (
                self._reflection_weight * row.reflection_similarity
                + self._raw_weight * row.raw_similarity
                + self._recency_weight * recency
                + self._importance_weight * importance
            )
            ranked.append(
                MemoryCandidate(
                    id=row.id,
                    content=row.content,
                    reflection=row.reflection,
                    metadata=row.metadata,
                    created_at=row.created_at,
                    raw_similarity=row.raw_similarity,
                    reflection_similarity=row.reflection_similarity,
                    recency_boost=recency,
                    importance_boost=importance,
                    score=score,
                )
            )

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[: request.top_k]
