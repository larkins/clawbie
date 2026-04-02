from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp, log
from typing import Any

from .config import MemoryConfig
from .db import MemoryRepository
from .providers import EmbeddingProvider


@dataclass
class RetrievedMemory:
    memory_id: int
    score: float
    raw_text: str
    reflection: str | None
    metadata: dict[str, Any]
    created_at: datetime
    source_type: str | None
    source_ref: str | None


class MemoryRetrievalService:
    def __init__(
        self,
        *,
        repository: MemoryRepository,
        embedding_provider: EmbeddingProvider,
        memory_config: MemoryConfig,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.config = memory_config

    @staticmethod
    def _distance_to_similarity(distance: float | None) -> float:
        if distance is None:
            return 0.0
        similarity = 1.0 - float(distance)
        return max(0.0, min(1.0, similarity))

    def _recency_boost(self, created_at: datetime) -> float:
        created = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created).total_seconds() / 86400.0
        half_life = max(1, self.config.recency_half_life_days)
        decay_constant = log(2) / half_life
        return exp(-decay_constant * max(0.0, age_days))

    def retrieve(
        self,
        *,
        query_text: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedMemory]:
        query = query_text.strip()
        if not query:
            raise ValueError("query_text must not be empty")

        vector = self.embedding_provider.embed(query)
        limit = self.config.candidate_limit_each

        raw_candidates = self.repository.query_candidates(
            vector=vector,
            search_field="raw_embedding",
            limit=limit,
            filters=filters,
        )
        reflection_candidates = self.repository.query_candidates(
            vector=vector,
            search_field="reflection_embedding",
            limit=limit,
            filters=filters,
        )

        by_id: dict[int, dict[str, Any]] = {}

        for row in raw_candidates:
            memory_id = int(row["id"])
            item = by_id.setdefault(memory_id, dict(row))
            item["raw_similarity"] = self._distance_to_similarity(row.get("distance"))

        for row in reflection_candidates:
            memory_id = int(row["id"])
            item = by_id.setdefault(memory_id, dict(row))
            item["reflection_similarity"] = self._distance_to_similarity(row.get("distance"))

        results: list[RetrievedMemory] = []
        for memory_id, row in by_id.items():
            raw_similarity = float(row.get("raw_similarity", 0.0))
            reflection_similarity = float(row.get("reflection_similarity", 0.0))
            recency = self._recency_boost(row["created_at"])
            importance = float(row.get("importance") or 0.0)

            score = (
                self.config.rank_weights.reflection * reflection_similarity
                + self.config.rank_weights.raw * raw_similarity
                + self.config.rank_weights.recency * recency
                + self.config.importance_weight * importance
            )

            results.append(
                RetrievedMemory(
                    memory_id=memory_id,
                    score=score,
                    raw_text=row.get("raw_text", ""),
                    reflection=row.get("reflection"),
                    metadata=row.get("metadata") or {},
                    created_at=row["created_at"],
                    source_type=row.get("source_type"),
                    source_ref=row.get("source_ref"),
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[: (top_k or self.config.default_top_k)]
