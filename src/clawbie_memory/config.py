from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv
import os


@dataclass(frozen=True)
class RankingWeights:
    reflection: float
    raw: float
    recency: float


@dataclass(frozen=True)
class MemoryConfig:
    table_name: str
    candidate_limit_each: int
    default_top_k: int
    recency_half_life_days: int
    rank_weights: RankingWeights
    importance_weight: float


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str


@dataclass(frozen=True)
class ModelConfig:
    embedding_host: str
    embedding_model: str
    inference_host: str
    inference_model: str


@dataclass(frozen=True)
class AppConfig:
    database: DatabaseConfig
    models: ModelConfig
    memory: MemoryConfig


def load_config(project_root: Path) -> AppConfig:
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    config_path = project_root / "config.yaml"
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    memory = data.get("memory", {})
    rank_weights = memory.get("rank_weights", {})

    return AppConfig(
        database=DatabaseConfig(
            host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "clawbie"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
        ),
        models=ModelConfig(
            embedding_host=os.getenv("EMBEDDING_HOST", "http://127.0.0.1:8001"),
            embedding_model=os.getenv("EMBEDDING_MODEL", ""),
            inference_host=os.getenv("INFERENCE_HOST", "http://127.0.0.1:8002"),
            inference_model=os.getenv("INFERENCE_MODEL", ""),
        ),
        memory=MemoryConfig(
            table_name=memory.get("table_name", "user_memories"),
            candidate_limit_each=int(memory.get("candidate_limit_each", 40)),
            default_top_k=int(memory.get("default_top_k", 12)),
            recency_half_life_days=int(memory.get("recency_half_life_days", 30)),
            rank_weights=RankingWeights(
                reflection=float(rank_weights.get("reflection", 0.55)),
                raw=float(rank_weights.get("raw", 0.35)),
                recency=float(rank_weights.get("recency", 0.10)),
            ),
            importance_weight=float(memory.get("importance_weight", 0.02)),
        ),
    )
