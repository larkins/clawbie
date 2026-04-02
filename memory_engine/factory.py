from __future__ import annotations

from .config import AppConfig
from .db import open_connection
from .ingestion import MemoryIngestionService
from .providers import HttpEmbeddingProvider, HttpInferenceProvider
from .repository import MemoryRepository
from .retrieval import MemoryRetrievalService


def build_services(config: AppConfig):
    embedding_provider = HttpEmbeddingProvider(
        url=config.embedding.url,
        model=config.embedding.model,
        timeout_seconds=config.embedding.timeout_seconds,
    )
    inference_provider = HttpInferenceProvider(
        url=config.inference.url,
        model=config.inference.model,
        timeout_seconds=config.inference.timeout_seconds,
    )

    conn_ctx = open_connection(config.database_dsn)
    conn = conn_ctx.__enter__()
    repository = MemoryRepository(conn)

    ingestion = MemoryIngestionService(
        repository=repository,
        embedding_provider=embedding_provider,
        inference_provider=inference_provider,
        reflection_prompt=config.memory.reflection_prompt,
        max_retries=config.memory.ingestion_retry.max_retries,
        retry_backoff_seconds=config.memory.ingestion_retry.backoff_seconds,
    )

    retrieval = MemoryRetrievalService(
        repository=repository,
        embedding_provider=embedding_provider,
        reflection_weight=config.memory.retrieval.weights.reflection_weight,
        raw_weight=config.memory.retrieval.weights.raw_weight,
        recency_weight=config.memory.retrieval.weights.recency_weight,
        importance_weight=config.memory.retrieval.weights.importance_weight,
        recency_half_life_days=config.memory.retrieval.weights.recency_half_life_days,
    )

    return conn_ctx, ingestion, retrieval
