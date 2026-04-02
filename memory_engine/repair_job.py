from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import os
import sys
import time
from typing import Any, Callable, Protocol
from urllib.parse import urljoin

import requests

from .config import load_config
from .db import open_connection
from .providers import HttpEmbeddingProvider, HttpInferenceProvider


@dataclass(frozen=True)
class RepairCandidate:
    id: Any
    content: str
    reflection: str | None
    raw_embedding_present: bool
    reflection_embedding_present: bool
    status_commentary: bool = False


@dataclass(frozen=True)
class RepairFailure:
    memory_id: Any
    errors: list[str]


@dataclass(frozen=True)
class RepairReport:
    scanned_count: int
    repaired_count: int
    still_failed_count: int
    failure_samples: list[RepairFailure]
    generated_at: datetime


class RepairRepository(Protocol):
    def get_repair_candidates(self, *, limit: int | None = None) -> list[RepairCandidate]:
        raise NotImplementedError

    def update_memory_fields(
        self,
        *,
        memory_id: Any,
        raw_embedding: list[float] | None = None,
        reflection: str | None = None,
        reflection_embedding: list[float] | None = None,
        repair_errors: list[str] | None = None,
        clear_repair_errors: bool = False,
    ) -> None:
        raise NotImplementedError


class PostgresRepairRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._content_column = self._resolve_content_column()
        self._has_status_commentary_column = self._resolve_status_commentary_column()

    def _resolve_content_column(self) -> str:
        from psycopg.rows import dict_row

        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'user_memories'
                  AND column_name IN ('content', 'memory_text')
                """
            )
            columns = {row["column_name"] for row in cur.fetchall()}
        if "content" in columns:
            return "content"
        if "memory_text" in columns:
            return "memory_text"
        raise RuntimeError("user_memories must include either 'content' or 'memory_text' column")

    def _resolve_status_commentary_column(self) -> bool:
        from psycopg.rows import dict_row

        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'user_memories'
                  AND column_name = 'status_commentary'
                """
            )
            return cur.fetchone() is not None

    @staticmethod
    def _vector_literal(values: list[float]) -> str:
        return "[" + ",".join(f"{value:.8f}" for value in values) + "]"

    def get_repair_candidates(self, *, limit: int | None = None) -> list[RepairCandidate]:
        from psycopg.rows import dict_row

        limit_sql = "LIMIT %s" if limit is not None else ""
        params: list[Any] = [limit] if limit is not None else []
        status_select = (
            "COALESCE(status_commentary, FALSE) AS status_commentary"
            if self._has_status_commentary_column
            else "FALSE AS status_commentary"
        )
        status_filter = "AND COALESCE(status_commentary, FALSE) = FALSE" if self._has_status_commentary_column else ""
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT
                    id,
                    {self._content_column} AS content,
                    reflection,
                    raw_embedding IS NOT NULL AS raw_embedding_present,
                    reflection_embedding IS NOT NULL AS reflection_embedding_present,
                    {status_select}
                FROM user_memories
                WHERE (
                    raw_embedding IS NULL
                    OR reflection IS NULL
                    OR reflection_embedding IS NULL
                )
                {status_filter}
                ORDER BY created_at ASC
                {limit_sql}
                """,
                params,
            )
            rows = cur.fetchall()
        return [
            RepairCandidate(
                id=row["id"],
                content=row["content"],
                reflection=row["reflection"],
                raw_embedding_present=bool(row["raw_embedding_present"]),
                reflection_embedding_present=bool(row["reflection_embedding_present"]),
                status_commentary=bool(row.get("status_commentary")),
            )
            for row in rows
        ]

    def update_memory_fields(
        self,
        *,
        memory_id: Any,
        raw_embedding: list[float] | None = None,
        reflection: str | None = None,
        reflection_embedding: list[float] | None = None,
        repair_errors: list[str] | None = None,
        clear_repair_errors: bool = False,
    ) -> None:
        set_fragments: list[str] = []
        params: list[Any] = []

        if raw_embedding is not None:
            set_fragments.append("raw_embedding = %s::vector")
            params.append(self._vector_literal(raw_embedding))
        if reflection is not None:
            set_fragments.append("reflection = %s")
            params.append(reflection)
        if reflection_embedding is not None:
            set_fragments.append("reflection_embedding = %s::vector")
            params.append(self._vector_literal(reflection_embedding))

        metadata_patch: dict[str, Any] = {
            "repair_last_run_at": datetime.now(timezone.utc).isoformat(),
        }
        if repair_errors is not None:
            metadata_patch["repair_last_errors"] = repair_errors
        elif clear_repair_errors:
            metadata_patch["repair_last_errors"] = []

        set_fragments.append("metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb")
        params.append(json.dumps(metadata_patch))

        params.append(memory_id)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE user_memories
                SET {", ".join(set_fragments)}
                WHERE id = %s
                """,
                params,
            )
        self._conn.commit()


class RetryExhaustedError(Exception):
    def __init__(self, *, attempts: int, cause: Exception) -> None:
        super().__init__(str(cause))
        self.attempts = attempts
        self.cause = cause


class MemoryRepairService:
    def __init__(
        self,
        *,
        repository: RepairRepository,
        embedding_provider: Any,
        inference_provider: Any,
        reflection_prompt: str,
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

    def _run_with_retries(self, action: Callable[[], Any]) -> Any:
        attempts = 0
        while True:
            try:
                return action()
            except Exception as exc:  # noqa: BLE001 - controlled retry boundary.
                if attempts >= self._max_retries or not self._is_retryable(exc):
                    raise RetryExhaustedError(attempts=attempts, cause=exc) from exc
                attempts += 1
                self._sleep_fn(self._retry_backoff_seconds * attempts)

    @staticmethod
    def _reflection_missing(value: str | None) -> bool:
        return value is None or not value.strip()

    def run(self, *, limit: int | None = None, sample_size: int = 5) -> RepairReport:
        candidates = self._repository.get_repair_candidates(limit=limit)
        repaired_count = 0
        failures: list[RepairFailure] = []

        for candidate in candidates:
            if candidate.status_commentary:
                continue
            missing_raw = not candidate.raw_embedding_present
            missing_reflection = self._reflection_missing(candidate.reflection)
            missing_reflection_embedding = not candidate.reflection_embedding_present

            stage_errors: list[str] = []
            new_raw_embedding: list[float] | None = None
            new_reflection: str | None = None
            new_reflection_embedding: list[float] | None = None

            if missing_raw:
                try:
                    new_raw_embedding = self._run_with_retries(
                        lambda: self._embedding_provider.embed(candidate.content)
                    )
                except RetryExhaustedError as exc:
                    stage_errors.append(f"raw_embedding:{type(exc.cause).__name__}")

            if missing_reflection:
                try:
                    generated = self._run_with_retries(
                        lambda: self._inference_provider.summarise(candidate.content, self._reflection_prompt)
                    )
                    generated = generated.strip()
                    if generated:
                        new_reflection = generated
                    else:
                        stage_errors.append("reflection:EmptyResponse")
                except RetryExhaustedError as exc:
                    stage_errors.append(f"reflection:{type(exc.cause).__name__}")

            if missing_reflection_embedding:
                reflection_source = new_reflection if new_reflection is not None else candidate.reflection
                if reflection_source and reflection_source.strip():
                    try:
                        new_reflection_embedding = self._run_with_retries(
                            lambda: self._embedding_provider.embed(reflection_source)
                        )
                    except RetryExhaustedError as exc:
                        stage_errors.append(f"reflection_embedding:{type(exc.cause).__name__}")
                else:
                    stage_errors.append("reflection_embedding:MissingReflectionSource")

            self._repository.update_memory_fields(
                memory_id=candidate.id,
                raw_embedding=new_raw_embedding,
                reflection=new_reflection,
                reflection_embedding=new_reflection_embedding,
                repair_errors=stage_errors if stage_errors else None,
                clear_repair_errors=not stage_errors,
            )

            if stage_errors:
                failures.append(RepairFailure(memory_id=candidate.id, errors=stage_errors))
            else:
                repaired_count += 1

        return RepairReport(
            scanned_count=len(candidates),
            repaired_count=repaired_count,
            still_failed_count=len(failures),
            failure_samples=failures[: max(sample_size, 0)],
            generated_at=datetime.now(timezone.utc),
        )


def render_report(report: RepairReport) -> str:
    lines = [
        f"generated_at={report.generated_at.isoformat()}",
        f"scanned_count={report.scanned_count}",
        f"repaired_count={report.repaired_count}",
        f"still_failed_count={report.still_failed_count}",
    ]
    if report.failure_samples:
        lines.append("failure_samples:")
        for sample in report.failure_samples:
            joined = ", ".join(sample.errors)
            lines.append(f"- id={sample.memory_id} errors={joined}")
    else:
        lines.append("failure_samples: none")
    return "\n".join(lines) + "\n"


def write_report_log(*, report_text: str, log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"repair-report-{timestamp}.log"
    log_path.write_text(report_text, encoding="utf-8")
    return log_path


def notify_report_via_email_server(*, report_text: str, timeout_seconds: float = 10.0) -> tuple[bool, str]:
    email_server = (
        os.getenv("EMAIL_API_BASE_URL", "").strip()
        or os.getenv("EMAIL_SERVER", "").strip()
    ).rstrip("/")
    if not email_server:
        return False, "EMAIL_API_BASE_URL/EMAIL_SERVER not configured"

    auth_endpoint = os.getenv("EMAIL_AUTH_ENDPOINT", "/auth/login").strip() or "/auth/login"
    send_endpoint = os.getenv("EMAIL_SEND_ENDPOINT", "/api/emails").strip() or "/api/emails"
    email_address = os.getenv("EMAIL_ADDRESS", "").strip()
    email_password = os.getenv("EMAIL_PASSWORD", "").strip()
    email_bearer_token = os.getenv("EMAIL_BEARER_TOKEN", "").strip()
    email_to = os.getenv("EMAIL_TO", "").strip() or email_address
    timeout_env = os.getenv("EMAIL_TIMEOUT_SECONDS", "").strip()
    if timeout_env:
        try:
            timeout_seconds = float(timeout_env)
        except ValueError:
            return False, "email notify failed (invalid EMAIL_TIMEOUT_SECONDS)"

    if not email_to:
        return False, "EMAIL_TO/EMAIL_ADDRESS not configured"
    if not email_bearer_token and (not email_address or not email_password):
        return False, "EMAIL auth not configured (set EMAIL_BEARER_TOKEN or EMAIL_ADDRESS+EMAIL_PASSWORD)"

    auth_url = urljoin(f"{email_server}/", auth_endpoint.lstrip("/"))
    send_url = urljoin(f"{email_server}/", send_endpoint.lstrip("/"))
    send_payload = {
        "to": email_to,
        "subject": "Clawbie memory repair report",
        "body": report_text,
    }

    def _response_excerpt(response: requests.Response) -> str:
        body = response.text.strip().replace("\n", " ")
        if not body:
            return ""
        return body[:180]

    try:
        token = email_bearer_token
        if not token:
            login_payload = {
                "email": email_address,
                "password": email_password,
            }
            login_response = requests.post(
                auth_url,
                json=login_payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout_seconds,
            )
            login_response.raise_for_status()
            login_obj = login_response.json()
            token = str(login_obj.get("token", "")).strip()
            if not token:
                return False, "email notify failed (login response missing token)"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        send_response = requests.post(
            send_url,
            json=send_payload,
            headers=headers,
            timeout=timeout_seconds,
        )
        send_response.raise_for_status()
        return True, f"sent via EMAIL API ({send_response.status_code})"
    except requests.exceptions.HTTPError as exc:
        response = exc.response
        status = response.status_code if response is not None else "unknown"
        excerpt = _response_excerpt(response) if response is not None else ""
        if excerpt:
            return False, f"email notify failed (HTTP {status}: {excerpt})"
        return False, f"email notify failed (HTTP {status})"
    except Exception as exc:  # noqa: BLE001 - best effort notifier.
        return False, f"email notify failed ({type(exc).__name__})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair user_memories rows with missing embeddings/reflections.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of rows to scan")
    parser.add_argument("--sample-size", type=int, default=5, help="Number of failure samples in report")
    parser.add_argument("--log-dir", default="logs", help="Directory for report logs")
    args = parser.parse_args(argv)

    config = load_config(args.config)
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

    with open_connection(config.database_dsn) as conn:
        repository = PostgresRepairRepository(conn)
        service = MemoryRepairService(
            repository=repository,
            embedding_provider=embedding_provider,
            inference_provider=inference_provider,
            reflection_prompt=config.memory.reflection_prompt,
            max_retries=config.memory.ingestion_retry.max_retries,
            retry_backoff_seconds=config.memory.ingestion_retry.backoff_seconds,
        )
        report = service.run(limit=args.limit, sample_size=args.sample_size)

    report_text = render_report(report)
    log_path = write_report_log(report_text=report_text, log_dir=Path(args.log_dir))
    _, email_status = notify_report_via_email_server(report_text=report_text)

    print(report_text.strip())
    print(f"log_path={log_path}")
    print(f"email_status={email_status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
