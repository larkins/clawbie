from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from .db import InsertResult, MemoryRepository
from .providers import EmbeddingProvider, InferenceProvider

SUMMARY_PROMPT = "summarise this in 20 lines or less"


@dataclass
class IngestRequest:
    raw_text: str
    user_id: str
    source_type: str
    source_ref: str | None = None
    session_id: str | None = None
    importance: int = 0
    token_count: int | None = None
    metadata: dict[str, Any] | None = None
    expires_at: datetime | None = None


@dataclass
class IngestResult:
    memory_id: int
    inserted: bool
    reflection_created: bool
    dedupe_hash: str


class MemoryIngestionService:
    def __init__(
        self,
        *,
        repository: MemoryRepository,
        embedding_provider: EmbeddingProvider,
        inference_provider: InferenceProvider,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.inference_provider = inference_provider

    @staticmethod
    def normalize_text(raw_text: str) -> str:
        lines = [line.rstrip() for line in raw_text.replace("\r\n", "\n").split("\n")]
        normalized = "\n".join(lines).strip()
        if not normalized:
            raise ValueError("raw_text must not be empty")
        return normalized

    @staticmethod
    def compute_hash(normalized_text: str, user_id: str, source_type: str, source_ref: str | None) -> str:
        base = "::".join([user_id, source_type, source_ref or "", normalized_text])
        return sha256(base.encode("utf-8")).hexdigest()

    def ingest(self, request: IngestRequest) -> IngestResult:
        normalized = self.normalize_text(request.raw_text)
        dedupe_hash = self.compute_hash(normalized, request.user_id, request.source_type, request.source_ref)

        metadata = dict(request.metadata or {})
        metadata.setdefault("pipeline_errors", [])
        metadata.setdefault("ingested_at", datetime.now(timezone.utc).isoformat())

        raw_embedding = self.embedding_provider.embed(normalized)

        reflection: str | None = None
        reflection_embedding: list[float] | None = None
        reflection_created = False

        try:
            reflection = self.inference_provider.summarize(normalized, SUMMARY_PROMPT).strip()
            if reflection:
                reflection_embedding = self.embedding_provider.embed(reflection)
                reflection_created = True
            else:
                metadata["pipeline_errors"].append("inference_empty_reflection")
        except Exception as exc:  # noqa: BLE001
            metadata["pipeline_errors"].append(f"reflection_stage_failed:{exc.__class__.__name__}")
            reflection = None
            reflection_embedding = None

        payload = {
            "raw_text": normalized,
            "reflection": reflection,
            "raw_embedding": raw_embedding,
            "reflection_embedding": reflection_embedding,
            "memory_hash": dedupe_hash,
            "source_type": request.source_type,
            "source_ref": request.source_ref,
            "session_id": request.session_id,
            "user_id": request.user_id,
            "importance": int(request.importance),
            "token_count": request.token_count,
            "metadata": metadata,
            "expires_at": request.expires_at,
            "archive_status": "active",
            "archived_at": None,
        }

        insert_result: InsertResult = self.repository.insert_memory(payload)
        return IngestResult(
            memory_id=insert_result.memory_id,
            inserted=insert_result.inserted,
            reflection_created=reflection_created,
            dedupe_hash=dedupe_hash,
        )
