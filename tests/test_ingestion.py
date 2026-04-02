from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

from memory_engine.ingestion import IngestionInput, MemoryIngestionService, REFLECTION_PROMPT
from memory_engine.repository import PersistedMemory


@dataclass
class FakeEmbeddingProvider:
    calls: list[str]
    fail_on: set[str] | None = None

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if self.fail_on and text in self.fail_on:
            raise RuntimeError("embedding unavailable")
        return [float(len(text)), 1.0]


@dataclass
class FakeInferenceProvider:
    output: str
    fail: bool = False
    seen_prompt: str | None = None

    def summarise(self, text: str, prompt: str) -> str:
        self.seen_prompt = prompt
        if self.fail:
            raise RuntimeError("inference unavailable")
        return self.output


@dataclass
class FlakyEmbeddingProvider:
    calls: list[str]
    fail_counts: dict[str, int]

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        remaining = self.fail_counts.get(text, 0)
        if remaining > 0:
            self.fail_counts[text] = remaining - 1
            raise TimeoutError("temporary embedding timeout")
        return [float(len(text)), 1.0]


@dataclass
class FlakyInferenceProvider:
    output: str
    fail_count: int
    seen_prompt: str | None = None

    def summarise(self, text: str, prompt: str) -> str:
        self.seen_prompt = prompt
        if self.fail_count > 0:
            self.fail_count -= 1
            raise TimeoutError("temporary inference timeout")
        return self.output


class FakeRepository:
    def __init__(self) -> None:
        self.existing: PersistedMemory | None = None
        self.insert_payload: dict[str, Any] | None = None
        self.force_inserted: bool = True

    def get_by_memory_hash(self, memory_hash: str) -> PersistedMemory | None:
        return self.existing

    def insert_memory(self, **kwargs: Any) -> PersistedMemory:
        self.insert_payload = kwargs
        return PersistedMemory(
            id="m1",
            created_at=datetime(2026, 3, 16, tzinfo=timezone.utc),
            inserted=self.force_inserted,
        )


def test_ingestion_success_path_generates_both_embeddings_and_exact_prompt() -> None:
    repo = FakeRepository()
    embedding = FakeEmbeddingProvider(calls=[])
    inference = FakeInferenceProvider(output="short summary")

    service = MemoryIngestionService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
    )

    result = service.ingest(
        IngestionInput(
            content="  hello    world  ",
            metadata={"memory_type": "fact"},
            source_type="chat",
        )
    )

    assert result.deduplicated is False
    assert result.reflection_generated is True
    assert inference.seen_prompt == REFLECTION_PROMPT
    assert embedding.calls == ["hello world", "short summary"]

    assert repo.insert_payload is not None
    assert repo.insert_payload["content"] == "hello world"
    assert repo.insert_payload["reflection"] == "short summary"
    assert repo.insert_payload["reflection_embedding"] == [13.0, 1.0]
    assert repo.insert_payload["metadata"]["memory_type"] == "fact"
    assert repo.insert_payload["metadata"]["pipeline_errors"] == []
    assert repo.insert_payload["metadata"]["pipeline_retries"] == {
        "raw_embedding": 0,
        "reflection": 0,
        "reflection_embedding": 0,
    }


def test_ingestion_degrades_when_reflection_fails() -> None:
    repo = FakeRepository()
    embedding = FakeEmbeddingProvider(calls=[])
    inference = FakeInferenceProvider(output="unused", fail=True)

    service = MemoryIngestionService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
    )

    result = service.ingest(IngestionInput(content="alpha"))

    assert result.reflection_generated is False
    assert embedding.calls == ["alpha"]
    assert repo.insert_payload is not None
    assert repo.insert_payload["reflection"] is None
    assert repo.insert_payload["reflection_embedding"] is None
    assert repo.insert_payload["metadata"]["pipeline_errors"] == ["reflection_stage_failed:RuntimeError"]
    assert repo.insert_payload["metadata"]["pipeline_retries"] == {
        "raw_embedding": 0,
        "reflection": 0,
        "reflection_embedding": 0,
    }


def test_ingestion_degrades_when_embedding_fails_and_tracks_stage_errors() -> None:
    repo = FakeRepository()
    embedding = FakeEmbeddingProvider(calls=[], fail_on={"alpha", "short summary"})
    inference = FakeInferenceProvider(output="short summary")

    service = MemoryIngestionService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
    )

    result = service.ingest(IngestionInput(content="alpha"))

    assert result.reflection_generated is False
    assert repo.insert_payload is not None
    assert repo.insert_payload["raw_embedding"] is None
    assert repo.insert_payload["reflection"] == "short summary"
    assert repo.insert_payload["reflection_embedding"] is None
    assert repo.insert_payload["metadata"]["pipeline_errors"] == [
        "raw_embedding_stage_failed:RuntimeError",
        "reflection_embedding_stage_failed:RuntimeError",
    ]
    assert repo.insert_payload["metadata"]["pipeline_retries"] == {
        "raw_embedding": 0,
        "reflection": 0,
        "reflection_embedding": 0,
    }


def test_ingestion_marks_deduplicated_when_insert_conflicts() -> None:
    repo = FakeRepository()
    repo.force_inserted = False
    embedding = FakeEmbeddingProvider(calls=[])
    inference = FakeInferenceProvider(output="summary")

    service = MemoryIngestionService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
    )

    result = service.ingest(IngestionInput(content="alpha"))

    assert result.deduplicated is True
    assert repo.insert_payload is not None


def test_ingestion_returns_existing_memory_for_dedupe_hash() -> None:
    repo = FakeRepository()
    repo.existing = PersistedMemory(id="existing", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    embedding = FakeEmbeddingProvider(calls=[])
    inference = FakeInferenceProvider(output="ignored")

    service = MemoryIngestionService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
    )

    result = service.ingest(IngestionInput(content="same text"))

    assert result.deduplicated is True
    assert result.memory_id == "existing"
    assert embedding.calls == []
    assert repo.insert_payload is None


def test_ingestion_rejects_empty_content() -> None:
    repo = FakeRepository()
    embedding = FakeEmbeddingProvider(calls=[])
    inference = FakeInferenceProvider(output="ignored")

    service = MemoryIngestionService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
    )

    with pytest.raises(ValueError, match="content must not be empty"):
        service.ingest(IngestionInput(content=" \n  "))


def test_ingestion_filters_heartbeat_system_messages() -> None:
    """Heartbeat poll messages should be filtered from memory ingestion."""
    from memory_engine.ingestion import FilteredContentError, FILTERED_PREFIXES

    repo = FakeRepository()
    embedding = FakeEmbeddingProvider(calls=[])
    inference = FakeInferenceProvider(output="ignored")

    service = MemoryIngestionService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
    )

    # Test the heartbeat poll message is filtered
    heartbeat_msg = "Read HEARTBEAT.md if it exists (workspace context). Follow it strictly."
    with pytest.raises(FilteredContentError, match="filtered prefix"):
        service.ingest(IngestionInput(content=heartbeat_msg))

    # Test HEARTBEAT_OK is filtered
    with pytest.raises(FilteredContentError, match="filtered prefix"):
        service.ingest(IngestionInput(content="HEARTBEAT_OK"))

    # Test normal content is NOT filtered
    result = service.ingest(IngestionInput(content="Normal user message about bitcoin"))
    assert result.deduplicated is False
    assert repo.insert_payload is not None

    # Verify no embeddings were called for filtered content (only for normal message)
    # Two embedding calls: one for raw content, one for reflection
    assert len(embedding.calls) == 2
    assert embedding.calls[0] == "Normal user message about bitcoin"
    assert embedding.calls[1] == "ignored"  # reflection


def test_ingestion_retries_transient_failures_then_succeeds() -> None:
    repo = FakeRepository()
    sleeps: list[float] = []
    embedding = FlakyEmbeddingProvider(calls=[], fail_counts={"alpha": 1, "short summary": 2})
    inference = FlakyInferenceProvider(output="short summary", fail_count=1)

    service = MemoryIngestionService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
        max_retries=3,
        retry_backoff_seconds=0.1,
        sleep_fn=sleeps.append,
    )

    result = service.ingest(IngestionInput(content="alpha"))

    assert result.reflection_generated is True
    assert repo.insert_payload is not None
    assert repo.insert_payload["metadata"]["pipeline_errors"] == []
    assert repo.insert_payload["metadata"]["pipeline_retries"] == {
        "raw_embedding": 1,
        "reflection": 1,
        "reflection_embedding": 2,
    }
    assert sleeps == [0.1, 0.1, 0.1, 0.2]


def test_ingestion_stops_retrying_after_max_retries() -> None:
    repo = FakeRepository()
    sleeps: list[float] = []
    embedding = FlakyEmbeddingProvider(calls=[], fail_counts={"alpha": 5})
    inference = FakeInferenceProvider(output="short summary")

    service = MemoryIngestionService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
        max_retries=2,
        retry_backoff_seconds=0.2,
        sleep_fn=sleeps.append,
    )

    result = service.ingest(IngestionInput(content="alpha"))

    assert result.reflection_generated is True
    assert repo.insert_payload is not None
    assert repo.insert_payload["raw_embedding"] is None
    assert repo.insert_payload["metadata"]["pipeline_errors"] == ["raw_embedding_stage_failed:TimeoutError"]
    assert repo.insert_payload["metadata"]["pipeline_retries"] == {
        "raw_embedding": 2,
        "reflection": 0,
        "reflection_embedding": 0,
    }
    assert sleeps == [0.2, 0.4]


def test_ingestion_skips_embedding_and_reflection_for_status_commentary() -> None:
    repo = FakeRepository()
    embedding = FakeEmbeddingProvider(calls=[])
    inference = FakeInferenceProvider(output="unused")

    service = MemoryIngestionService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
    )

    result = service.ingest(
        IngestionInput(
            content="**Checking migration status**",
            status_commentary=True,
            metadata={"role": "assistant"},
        )
    )

    assert result.reflection_generated is False
    assert embedding.calls == []
    assert inference.seen_prompt is None
    assert repo.insert_payload is not None
    assert repo.insert_payload["status_commentary"] is True
    assert repo.insert_payload["raw_embedding"] is None
    assert repo.insert_payload["reflection"] is None
    assert repo.insert_payload["reflection_embedding"] is None
    assert repo.insert_payload["metadata"]["embedding_skipped_reason"] == "status_commentary"
    assert repo.insert_payload["metadata"]["pipeline_errors"] == []
