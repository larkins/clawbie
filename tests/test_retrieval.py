from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from memory_engine.repository import MemoryRow
from memory_engine.retrieval import MemoryRetrievalService, RetrievalFilters, RetrievalRequest


@dataclass
class FakeEmbeddingProvider:
    def embed(self, text: str) -> list[float]:
        return [0.1, 0.2]


class FakeRepository:
    def __init__(self) -> None:
        self.last_filters_sql: str | None = None
        self.last_params: list[Any] | None = None
        self.last_exact_filters_sql: str | None = None
        self.last_exact_params: list[Any] | None = None
        self.last_exact_query: str | None = None

    def search_raw(self, *, query_embedding, limit, filters_sql, params):
        self.last_filters_sql = filters_sql
        self.last_params = list(params)
        now = datetime.now(timezone.utc)
        return [
            MemoryRow(
                id="a",
                content="alpha",
                reflection="alpha sum",
                metadata={"memory_type": "fact"},
                created_at=now - timedelta(days=1),
                importance=3,
                raw_similarity=0.9,
                reflection_similarity=0.0,
            ),
            MemoryRow(
                id="b",
                content="beta",
                reflection=None,
                metadata={"memory_type": "todo"},
                created_at=now - timedelta(days=60),
                importance=1,
                raw_similarity=0.7,
                reflection_similarity=0.0,
            ),
        ]

    def search_reflection(self, *, query_embedding, limit, filters_sql, params):
        now = datetime.now(timezone.utc)
        return [
            MemoryRow(
                id="a",
                content="alpha",
                reflection="alpha sum",
                metadata={"memory_type": "fact"},
                created_at=now - timedelta(days=1),
                importance=3,
                raw_similarity=0.0,
                reflection_similarity=0.4,
            ),
            MemoryRow(
                id="c",
                content="gamma",
                reflection="gamma sum",
                metadata={"memory_type": "decision"},
                created_at=now - timedelta(days=2),
                importance=8,
                raw_similarity=0.0,
                reflection_similarity=0.95,
            ),
        ]

    def search_exact_text(self, *, query_text, limit, filters_sql, params):
        self.last_exact_query = query_text
        self.last_exact_filters_sql = filters_sql
        self.last_exact_params = list(params)
        return []


class FakeRepositoryWithExactFallback(FakeRepository):
    def search_raw(self, *, query_embedding, limit, filters_sql, params):
        self.last_filters_sql = filters_sql
        self.last_params = list(params)
        now = datetime.now(timezone.utc)
        return [
            MemoryRow(
                id="x",
                content="unrelated note",
                reflection="summary",
                metadata={"memory_type": "summary"},
                created_at=now - timedelta(days=1),
                importance=2,
                raw_similarity=0.91,
                reflection_similarity=0.0,
            )
        ]

    def search_reflection(self, *, query_embedding, limit, filters_sql, params):
        now = datetime.now(timezone.utc)
        return [
            MemoryRow(
                id="y",
                content="another note",
                reflection="different marker",
                metadata={"memory_type": "fact"},
                created_at=now - timedelta(days=2),
                importance=1,
                raw_similarity=0.0,
                reflection_similarity=0.88,
            )
        ]

    def search_exact_text(self, *, query_text, limit, filters_sql, params):
        self.last_exact_query = query_text
        self.last_exact_filters_sql = filters_sql
        self.last_exact_params = list(params)
        now = datetime.now(timezone.utc)
        return [
            MemoryRow(
                id="target",
                content=f"heartbeat marker {query_text}",
                reflection="marker reflection",
                metadata={"memory_type": "fact", "source_marker": "openclaw_transcript"},
                created_at=now,
                importance=1,
                raw_similarity=1.0,
                reflection_similarity=1.0,
            )
        ]


def test_retrieval_merges_dual_candidates_and_reranks() -> None:
    repo = FakeRepository()
    service = MemoryRetrievalService(repository=repo, embedding_provider=FakeEmbeddingProvider())

    results = service.search(
        RetrievalRequest(
            query="what did we decide",
            top_k=3,
            raw_candidate_k=20,
            reflection_candidate_k=20,
            filters=RetrievalFilters(project="clawbie", metadata_contains={"memory_type": "decision"}),
        )
    )

    assert len(results) == 3
    assert results[0].id == "a"

    ids = [item.id for item in results]
    assert ids.count("a") == 1
    assert "project = %s" in (repo.last_filters_sql or "")
    assert "metadata @> %s::jsonb" in (repo.last_filters_sql or "")
    assert "(metadata->>'sensitivity') IS DISTINCT FROM 'high'" in (repo.last_filters_sql or "")
    assert "status_commentary = FALSE" in (repo.last_filters_sql or "")
    assert repo.last_params is not None
    assert repo.last_params[0] == "clawbie"


def test_retrieval_respects_top_k() -> None:
    repo = FakeRepository()
    service = MemoryRetrievalService(repository=repo, embedding_provider=FakeEmbeddingProvider())

    results = service.search(
        RetrievalRequest(
            query="anything",
            top_k=1,
            raw_candidate_k=10,
            reflection_candidate_k=10,
            filters=RetrievalFilters(),
        )
    )

    assert len(results) == 1


def test_retrieval_can_include_high_sensitivity() -> None:
    repo = FakeRepository()
    service = MemoryRetrievalService(repository=repo, embedding_provider=FakeEmbeddingProvider())

    service.search(
        RetrievalRequest(
            query="anything",
            top_k=3,
            raw_candidate_k=10,
            reflection_candidate_k=10,
            filters=RetrievalFilters(include_high_sensitivity=True),
        )
    )

    assert repo.last_filters_sql is not None
    assert "(metadata->>'sensitivity') IS DISTINCT FROM 'high'" not in repo.last_filters_sql


def test_retrieval_excludes_status_commentary_by_default_and_can_opt_in() -> None:
    repo = FakeRepository()
    service = MemoryRetrievalService(repository=repo, embedding_provider=FakeEmbeddingProvider())

    service.search(
        RetrievalRequest(
            query="anything",
            top_k=3,
            raw_candidate_k=10,
            reflection_candidate_k=10,
            filters=RetrievalFilters(),
        )
    )
    assert repo.last_filters_sql is not None
    assert "status_commentary = FALSE" in repo.last_filters_sql

    service.search(
        RetrievalRequest(
            query="anything",
            top_k=3,
            raw_candidate_k=10,
            reflection_candidate_k=10,
            filters=RetrievalFilters(include_status_commentary=True),
        )
    )
    assert repo.last_filters_sql is not None
    assert "status_commentary = FALSE" not in repo.last_filters_sql


def test_retrieval_marker_style_query_uses_exact_fallback_and_returns_target() -> None:
    repo = FakeRepositoryWithExactFallback()
    service = MemoryRetrievalService(repository=repo, embedding_provider=FakeEmbeddingProvider())

    marker_query = "hb-20260317-abc123"
    results = service.search(
        RetrievalRequest(
            query=marker_query,
            top_k=3,
            raw_candidate_k=8,
            reflection_candidate_k=8,
            filters=RetrievalFilters(project="clawbie", session_id="heartbeat"),
        )
    )

    assert results
    assert results[0].id == "target"
    ids = [item.id for item in results]
    assert "target" in ids
    assert repo.last_exact_query == marker_query
    assert repo.last_exact_filters_sql is not None
    assert "project = %s" in repo.last_exact_filters_sql
    assert "session_id = %s" in repo.last_exact_filters_sql
    assert "(metadata->>'sensitivity') IS DISTINCT FROM 'high'" in repo.last_exact_filters_sql
