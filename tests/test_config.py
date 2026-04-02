from __future__ import annotations

from pathlib import Path

import pytest

from memory_engine.config import load_config


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_load_config_supports_legacy_memory_keys_and_legacy_db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(
        tmp_path / "config.yaml",
        """
memory:
  candidate_limit_each: 22
  default_top_k: 7
  recency_half_life_days: 14
  rank_weights:
    reflection: 0.60
    raw: 0.30
    recency: 0.10
  importance_weight: 0.04
""".strip(),
    )

    monkeypatch.delenv("DATABASE_DSN", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "clawbie")
    monkeypatch.setenv("DB_USER", "postgres")
    monkeypatch.setenv("DB_PASSWORD", "1234")

    cfg = load_config(tmp_path / "config.yaml")

    assert cfg.database_dsn == "postgresql://postgres:1234@127.0.0.1:5432/clawbie"
    assert cfg.memory.retrieval.default_top_k == 7
    assert cfg.memory.retrieval.raw_candidate_k == 22
    assert cfg.memory.retrieval.reflection_candidate_k == 22
    assert cfg.memory.retrieval.weights.reflection_weight == 0.60
    assert cfg.memory.retrieval.weights.importance_weight == 0.04
    assert cfg.memory.ingestion_retry.max_retries == 2
    assert cfg.memory.ingestion_retry.backoff_seconds == 0.2


def test_load_config_rejects_unsafe_bind_host(tmp_path: Path) -> None:
    _write(
        tmp_path / "config.yaml",
        """
app:
  host: 0.0.0.0
""".strip(),
    )

    with pytest.raises(ValueError, match="Unsafe bind host"):
        load_config(tmp_path / "config.yaml")


def test_load_config_rejects_invalid_rank_weights(tmp_path: Path) -> None:
    _write(
        tmp_path / "config.yaml",
        """
memory:
  retrieval:
    reflection_weight: 0
    raw_weight: 0
    recency_weight: 0
""".strip(),
    )

    with pytest.raises(ValueError, match="sum to > 0"):
        load_config(tmp_path / "config.yaml")


def test_load_config_rejects_negative_ingestion_retry_max_retries(tmp_path: Path) -> None:
    _write(
        tmp_path / "config.yaml",
        """
memory:
  ingestion_retry:
    max_retries: -1
""".strip(),
    )

    with pytest.raises(ValueError, match="memory.ingestion_retry.max_retries must be >= 0"):
        load_config(tmp_path / "config.yaml")


def test_load_config_supports_legacy_model_host_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path / "config.yaml", "{}")
    monkeypatch.setenv("EMBEDDING_HOST", "http://127.0.0.1:9101")
    monkeypatch.setenv("INFERENCE_HOST", "http://127.0.0.1:9102")
    monkeypatch.delenv("EMBEDDING_URL", raising=False)
    monkeypatch.delenv("INFERENCE_URL", raising=False)

    cfg = load_config(tmp_path / "config.yaml")

    assert cfg.embedding.url == "http://127.0.0.1:9101/api/embed"
    assert cfg.inference.url == "http://127.0.0.1:9102/api/generate"


def test_load_config_preserves_host_when_path_is_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path / "config.yaml", "{}")
    monkeypatch.setenv("EMBEDDING_HOST", "http://127.0.0.1:9101/custom/embed")
    monkeypatch.setenv("INFERENCE_HOST", "http://127.0.0.1:9102/custom/generate")
    monkeypatch.delenv("EMBEDDING_URL", raising=False)
    monkeypatch.delenv("INFERENCE_URL", raising=False)

    cfg = load_config(tmp_path / "config.yaml")

    assert cfg.embedding.url == "http://127.0.0.1:9101/custom/embed"
    assert cfg.inference.url == "http://127.0.0.1:9102/custom/generate"
