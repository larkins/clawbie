from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
import yaml


@dataclass(frozen=True)
class RetrievalWeights:
    reflection_weight: float
    raw_weight: float
    recency_weight: float
    importance_weight: float
    recency_half_life_days: float


@dataclass(frozen=True)
class RetrievalConfig:
    default_top_k: int
    raw_candidate_k: int
    reflection_candidate_k: int
    weights: RetrievalWeights


@dataclass(frozen=True)
class IngestionRetryConfig:
    max_retries: int
    backoff_seconds: float


@dataclass(frozen=True)
class MemoryConfig:
    reflection_prompt: str
    embedding_dimensions: int
    ingestion_retry: IngestionRetryConfig
    retrieval: RetrievalConfig


@dataclass(frozen=True)
class AppNetworkConfig:
    host: str
    port: int


@dataclass(frozen=True)
class ServiceConfig:
    url: str
    model: str
    timeout_seconds: float


@dataclass(frozen=True)
class AppConfig:
    database_dsn: str
    app_network: AppNetworkConfig
    embedding: ServiceConfig
    inference: ServiceConfig
    memory: MemoryConfig


def _must_be_safe_bind(host: str) -> str:
    if host == "0.0.0.0":
        raise ValueError("Unsafe bind host 0.0.0.0 is not allowed")
    return host


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, dict):
        raise ValueError("config.yaml must contain a mapping at root")
    return payload


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _require_positive_int(value: int, name: str) -> int:
    if value <= 0:
        raise ValueError(f"{name} must be > 0")
    return value


def _require_positive_float(value: float, name: str) -> float:
    if value <= 0:
        raise ValueError(f"{name} must be > 0")
    return value


def _require_non_negative(value: float, name: str) -> float:
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


def _require_non_negative_int(value: int, name: str) -> int:
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


def _load_legacy_database_dsn() -> str:
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "clawbie")
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASSWORD", "SET_IN_ENV")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def _service_url(*, explicit_url: str | None, host: str | None, default_url: str, default_path: str) -> str:
    if explicit_url:
        return explicit_url
    if host:
        parsed = urlparse(host)
        path = (parsed.path or "").rstrip("/")
        if path and path != "/":
            return host.rstrip("/")
        return host.rstrip("/") + default_path
    return default_url


def load_config(config_path: str | Path = "config.yaml") -> AppConfig:
    config_path = Path(config_path)
    env_path = config_path.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)

    cfg = _read_yaml(config_path)

    app = _as_mapping(cfg.get("app"))
    memory = _as_mapping(cfg.get("memory"))
    ingestion_retry = _as_mapping(memory.get("ingestion_retry"))
    retrieval = _as_mapping(memory.get("retrieval"))
    legacy_rank_weights = _as_mapping(memory.get("rank_weights"))

    app_host = _must_be_safe_bind(str(app.get("host", os.environ.get("APP_HOST", "127.0.0.1"))))
    app_port = _require_positive_int(int(app.get("port", os.environ.get("APP_PORT", "5000"))), "app.port")

    reflection_prompt = str(memory.get("reflection_prompt", "summarise this in 20 lines or less"))
    embedding_dimensions = _require_positive_int(
        int(memory.get("embedding_dimensions", "1024")),
        "memory.embedding_dimensions",
    )
    ingestion_retry_max_retries = _require_non_negative_int(
        int(ingestion_retry.get("max_retries", "2")),
        "memory.ingestion_retry.max_retries",
    )
    ingestion_retry_backoff_seconds = _require_non_negative(
        float(ingestion_retry.get("backoff_seconds", "0.2")),
        "memory.ingestion_retry.backoff_seconds",
    )

    default_top_k = _require_positive_int(
        int(retrieval.get("default_top_k", memory.get("default_top_k", "10"))),
        "memory.retrieval.default_top_k",
    )
    raw_candidate_k = _require_positive_int(
        int(retrieval.get("raw_candidate_k", memory.get("candidate_limit_each", "40"))),
        "memory.retrieval.raw_candidate_k",
    )
    reflection_candidate_k = _require_positive_int(
        int(retrieval.get("reflection_candidate_k", memory.get("candidate_limit_each", "40"))),
        "memory.retrieval.reflection_candidate_k",
    )

    reflection_weight = _require_non_negative(
        float(retrieval.get("reflection_weight", legacy_rank_weights.get("reflection", "0.55"))),
        "memory.retrieval.reflection_weight",
    )
    raw_weight = _require_non_negative(
        float(retrieval.get("raw_weight", legacy_rank_weights.get("raw", "0.35"))),
        "memory.retrieval.raw_weight",
    )
    recency_weight = _require_non_negative(
        float(retrieval.get("recency_weight", legacy_rank_weights.get("recency", "0.10"))),
        "memory.retrieval.recency_weight",
    )
    importance_weight = _require_non_negative(
        float(retrieval.get("importance_weight", memory.get("importance_weight", "0.02"))),
        "memory.retrieval.importance_weight",
    )
    recency_half_life_days = _require_positive_float(
        float(retrieval.get("recency_half_life_days", memory.get("recency_half_life_days", "30"))),
        "memory.retrieval.recency_half_life_days",
    )

    if (reflection_weight + raw_weight + recency_weight) <= 0:
        raise ValueError("retrieval rank weights must sum to > 0")

    retrieval_cfg = RetrievalConfig(
        default_top_k=default_top_k,
        raw_candidate_k=raw_candidate_k,
        reflection_candidate_k=reflection_candidate_k,
        weights=RetrievalWeights(
            reflection_weight=reflection_weight,
            raw_weight=raw_weight,
            recency_weight=recency_weight,
            importance_weight=importance_weight,
            recency_half_life_days=recency_half_life_days,
        ),
    )

    embedding_url = _service_url(
        explicit_url=os.environ.get("EMBEDDING_URL"),
        host=os.environ.get("EMBEDDING_HOST"),
        default_url="http://127.0.0.1:8001/embed",
        default_path="/api/embed",
    )
    inference_url = _service_url(
        explicit_url=os.environ.get("INFERENCE_URL"),
        host=os.environ.get("INFERENCE_HOST"),
        default_url="http://127.0.0.1:8002/generate",
        default_path="/api/generate",
    )

    embedding = ServiceConfig(
        url=embedding_url,
        model=os.environ.get("EMBEDDING_MODEL", "local-embed-model"),
        timeout_seconds=float(os.environ.get("EMBEDDING_TIMEOUT_SECONDS", "10")),
    )

    inference = ServiceConfig(
        url=inference_url,
        model=os.environ.get("INFERENCE_MODEL", "local-infer-model"),
        timeout_seconds=float(os.environ.get("INFERENCE_TIMEOUT_SECONDS", "20")),
    )

    database_dsn = os.environ.get("DATABASE_DSN", _load_legacy_database_dsn())

    return AppConfig(
        database_dsn=database_dsn,
        app_network=AppNetworkConfig(host=app_host, port=app_port),
        embedding=embedding,
        inference=inference,
        memory=MemoryConfig(
            reflection_prompt=reflection_prompt,
            embedding_dimensions=embedding_dimensions,
            ingestion_retry=IngestionRetryConfig(
                max_retries=ingestion_retry_max_retries,
                backoff_seconds=ingestion_retry_backoff_seconds,
            ),
            retrieval=retrieval_cfg,
        ),
    )
