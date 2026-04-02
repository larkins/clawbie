from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import os
import uuid

import pytest
from psycopg.rows import dict_row

from memory_engine.config import load_config
from memory_engine.factory import build_services
from memory_engine.ingestion import IngestionInput
from memory_engine.retrieval import RetrievalFilters, RetrievalRequest


@dataclass
class PromptCaptureInferenceProvider:
    inner: object
    seen_prompt: str | None = None

    def summarise(self, text: str, prompt: str) -> str:
        self.seen_prompt = prompt
        return self.inner.summarise(text, prompt)


@pytest.mark.skipif(os.environ.get("LIVE_SMOKE") != "1", reason="Set LIVE_SMOKE=1 to run live integration smoke")
def test_live_smoke_ingest_and_retrieve_round_trip() -> None:
    config = load_config("config.yaml")
    config = replace(
        config,
        embedding=replace(config.embedding, timeout_seconds=max(config.embedding.timeout_seconds, 30.0)),
        inference=replace(config.inference, timeout_seconds=max(config.inference.timeout_seconds, 90.0)),
    )
    conn_ctx, ingestion_service, retrieval_service = build_services(config)

    source_ref = f"live-smoke-{uuid.uuid4()}"
    memory_text = (
        "Live smoke memory "
        f"{source_ref} "
        "for end to end ingestion retrieval validation on local services."
    )
    request_time = datetime.now(timezone.utc).replace(tzinfo=None)

    capture = PromptCaptureInferenceProvider(inner=ingestion_service._inference_provider)  # noqa: SLF001
    ingestion_service._inference_provider = capture  # noqa: SLF001

    try:
        result = ingestion_service.ingest(
            IngestionInput(
                content=memory_text,
                source_type="chat",
                source_ref=source_ref,
                session_id=source_ref,
                user_id="smoke-test",
                metadata={"memory_type": "fact", "sensitivity": "low"},
                project="clawbie",
                area="smoke",
            )
        )

        assert capture.seen_prompt == "summarise this in 20 lines or less"
        assert result.deduplicated is False
        assert result.reflection_generated is True

        content_column = ingestion_service._repository._content_column  # noqa: SLF001
        with ingestion_service._repository._conn.cursor(row_factory=dict_row) as cur:  # noqa: SLF001
            cur.execute(
                f"""
                SELECT id, {content_column} AS content, reflection, raw_embedding, reflection_embedding, created_at
                FROM user_memories
                WHERE memory_hash = %s
                LIMIT 1
                """,
                (result.memory_hash,),
            )
            row = cur.fetchone()

        assert row is not None
        assert row["content"] == memory_text
        assert row["reflection"] is not None and row["reflection"].strip() != ""
        assert row["raw_embedding"] is not None
        assert row["reflection_embedding"] is not None
        assert row["created_at"] >= request_time

        retrieved = retrieval_service.search(
            RetrievalRequest(
                query=source_ref,
                top_k=5,
                raw_candidate_k=20,
                reflection_candidate_k=20,
                filters=RetrievalFilters(session_id=source_ref, project="clawbie"),
            )
        )

        retrieved_ids = [item.id for item in retrieved]
        assert result.memory_id in retrieved_ids
    finally:
        ingestion_service._repository._conn.rollback()  # noqa: SLF001
        with ingestion_service._repository._conn.cursor() as cur:  # noqa: SLF001
            cur.execute("DELETE FROM user_memories WHERE source_ref = %s", (source_ref,))
        ingestion_service._repository._conn.commit()  # noqa: SLF001
        conn_ctx.__exit__(None, None, None)
