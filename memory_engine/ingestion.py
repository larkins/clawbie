from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import time
from typing import Any
from typing import Callable

import requests

from .hashing import memory_hash, normalize_text
from .providers import EmbeddingProvider, InferenceProvider
from .repository import MemoryRepository, PersistedMemory


REFLECTION_PROMPT = "summarise this in 20 lines or less"

# Prefixes for messages that should be filtered from memory ingestion
# These are system-generated messages that don't represent user/assistant content
FILTERED_PREFIXES = [
    "Read HEARTBEAT.md if it exists (workspace context)",
    "HEARTBEAT_OK",
]


@dataclass(frozen=True)
class IngestionInput:
    content: str
    source_type: str = "chat"
    source_ref: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    importance: int = 0
    token_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    project: str | None = None
    area: str | None = None
    archive_status: str = "active"
    expires_at: datetime | None = None
    archived_at: datetime | None = None
    status_commentary: bool = False


@dataclass(frozen=True)
class IngestionResult:
    memory_id: Any
    created_at: datetime
    deduplicated: bool
    memory_hash: str
    reflection_generated: bool


class RetryExhaustedError(Exception):
    def __init__(self, *, attempts: int, cause: Exception) -> None:
        super().__init__(str(cause))
        self.attempts = attempts
        self.cause = cause


class FilteredContentError(Exception):
    """Raised when content is filtered from memory ingestion."""
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class MemoryIngestionService:
    def __init__(
        self,
        *,
        repository: MemoryRepository,
        embedding_provider: EmbeddingProvider,
        inference_provider: InferenceProvider,
        reflection_prompt: str = REFLECTION_PROMPT,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.2,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._inference_provider = inference_provider
        self._reflection_prompt = reflection_prompt
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleep_fn = sleep_fn

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        retryable = (
            TimeoutError,
            ConnectionError,
            OSError,
            requests.exceptions.RequestException,
        )
        return isinstance(exc, retryable)

    @staticmethod
    def _should_filter(content: str) -> bool:
        """Check if content should be filtered from memory ingestion.
        
        Filters out system-generated messages like heartbeat polls that
        don't represent meaningful user/assistant content.
        """
        content_stripped = content.strip()
        for prefix in FILTERED_PREFIXES:
            if content_stripped.startswith(prefix):
                return True
        return False

    def _run_with_retries(self, action: Callable[[], Any]) -> tuple[Any, int]:
        attempts = 0
        while True:
            try:
                return action(), attempts
            except Exception as exc:  # noqa: BLE001 - controlled retry boundary.
                if attempts >= self._max_retries or not self._is_retryable(exc):
                    raise RetryExhaustedError(attempts=attempts, cause=exc) from exc
                attempts += 1
                self._sleep_fn(self._retry_backoff_seconds * attempts)

    def ingest(self, memory: IngestionInput) -> IngestionResult:
        # Filter out system-generated messages that shouldn't be stored
        if self._should_filter(memory.content):
            raise FilteredContentError("content matches filtered prefix (heartbeat/system message)")
        
        normalized_content = normalize_text(memory.content)
        if not normalized_content:
            raise ValueError("content must not be empty")
        digest = memory_hash(normalized_content)

        existing = self._repository.get_by_memory_hash(digest)
        if existing is not None:
            return IngestionResult(
                memory_id=existing.id,
                created_at=existing.created_at,
                deduplicated=True,
                memory_hash=digest,
                reflection_generated=False,
            )

        pipeline_errors: list[str] = []
        pipeline_retries: dict[str, int] = {
            "raw_embedding": 0,
            "reflection": 0,
            "reflection_embedding": 0,
        }
        reflection: str | None = None
        raw_embedding: list[float] | None = None
        reflection_embedding: list[float] | None = None
        metadata = dict(memory.metadata)
        if memory.status_commentary:
            metadata["embedding_skipped_reason"] = "status_commentary"
        else:
            try:
                raw_embedding, raw_retries = self._run_with_retries(
                    lambda: self._embedding_provider.embed(normalized_content)
                )
                pipeline_retries["raw_embedding"] = raw_retries
            except RetryExhaustedError as exc:  # degrade gracefully and persist raw.
                pipeline_errors.append(f"raw_embedding_stage_failed:{type(exc.cause).__name__}")
                pipeline_retries["raw_embedding"] = exc.attempts

            try:
                reflection, reflection_retries = self._run_with_retries(
                    lambda: self._inference_provider.summarise(normalized_content, self._reflection_prompt)
                )
                pipeline_retries["reflection"] = reflection_retries
                if reflection:
                    try:
                        reflection_embedding, reflection_embedding_retries = self._run_with_retries(
                            lambda: self._embedding_provider.embed(reflection)
                        )
                        pipeline_retries["reflection_embedding"] = reflection_embedding_retries
                    except RetryExhaustedError as exc:  # degrade gracefully and persist summary.
                        pipeline_errors.append(f"reflection_embedding_stage_failed:{type(exc.cause).__name__}")
                        pipeline_retries["reflection_embedding"] = exc.attempts
            except RetryExhaustedError as exc:  # degrade gracefully and persist raw.
                pipeline_errors.append(f"reflection_stage_failed:{type(exc.cause).__name__}")
                reflection = None
                reflection_embedding = None
                pipeline_retries["reflection"] = exc.attempts

        persisted = self._repository.insert_memory(
            content=normalized_content,
            raw_embedding=raw_embedding,
            reflection=reflection,
            reflection_embedding=reflection_embedding,
            source_type=memory.source_type,
            source_ref=memory.source_ref,
            session_id=memory.session_id,
            user_id=memory.user_id,
            importance=memory.importance,
            token_count=memory.token_count,
            memory_hash=digest,
            metadata={**metadata, "pipeline_errors": pipeline_errors, "pipeline_retries": pipeline_retries},
            project=memory.project,
            area=memory.area,
            archive_status=memory.archive_status,
            expires_at=memory.expires_at,
            archived_at=memory.archived_at,
            status_commentary=memory.status_commentary,
        )

        return IngestionResult(
            memory_id=persisted.id,
            created_at=persisted.created_at,
            deduplicated=not persisted.inserted,
            memory_hash=digest,
            reflection_generated=reflection is not None and reflection_embedding is not None,
        )
