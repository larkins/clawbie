from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from memory_engine.repair_job import (
    MemoryRepairService,
    RepairCandidate,
    RepairFailure,
    RepairReport,
    notify_report_via_email_server,
    render_report,
    write_report_log,
)


@dataclass
class FakeEmbeddingProvider:
    fail_on: set[str]
    calls: list[str]

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if text in self.fail_on:
            raise RuntimeError("embedding failed")
        return [float(len(text))]


@dataclass
class FakeInferenceProvider:
    result: str
    fail_for: set[str]
    calls: list[str]

    def summarise(self, text: str, prompt: str) -> str:
        self.calls.append(f"{prompt}|{text}")
        if text in self.fail_for:
            raise RuntimeError("inference failed")
        return self.result


class FakeRepository:
    def __init__(self, candidates: list[RepairCandidate]) -> None:
        self.candidates = candidates
        self.updates: list[dict[str, Any]] = []

    def get_repair_candidates(self, *, limit: int | None = None) -> list[RepairCandidate]:
        if limit is None:
            return self.candidates
        return self.candidates[:limit]

    def update_memory_fields(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)


def test_repair_only_runs_missing_stages() -> None:
    repo = FakeRepository(
        [
            RepairCandidate(
                id="m1",
                content="alpha",
                reflection="already there",
                raw_embedding_present=False,
                reflection_embedding_present=False,
            )
        ]
    )
    embedding = FakeEmbeddingProvider(fail_on=set(), calls=[])
    inference = FakeInferenceProvider(result="unused", fail_for=set(), calls=[])
    service = MemoryRepairService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
        reflection_prompt="summarise this in 20 lines or less",
        max_retries=0,
    )

    report = service.run()

    assert report.scanned_count == 1
    assert report.repaired_count == 1
    assert report.still_failed_count == 0
    assert inference.calls == []
    assert embedding.calls == ["alpha", "already there"]
    assert repo.updates[0]["raw_embedding"] == [5.0]
    assert repo.updates[0]["reflection"] is None
    assert repo.updates[0]["reflection_embedding"] == [13.0]
    assert repo.updates[0]["clear_repair_errors"] is True


def test_repair_tracks_failures_and_samples() -> None:
    repo = FakeRepository(
        [
            RepairCandidate(
                id="m2",
                content="beta",
                reflection=None,
                raw_embedding_present=True,
                reflection_embedding_present=False,
            )
        ]
    )
    embedding = FakeEmbeddingProvider(fail_on={"ok summary"}, calls=[])
    inference = FakeInferenceProvider(result="ok summary", fail_for=set(), calls=[])
    service = MemoryRepairService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
        reflection_prompt="summarise this in 20 lines or less",
        max_retries=0,
    )

    report = service.run(sample_size=1)

    assert report.repaired_count == 0
    assert report.still_failed_count == 1
    assert report.failure_samples == [
        RepairFailure(memory_id="m2", errors=["reflection_embedding:RuntimeError"])
    ]
    assert repo.updates[0]["reflection"] == "ok summary"
    assert repo.updates[0]["repair_errors"] == ["reflection_embedding:RuntimeError"]


def test_render_report_contains_summary_and_samples() -> None:
    report = RepairReport(
        scanned_count=4,
        repaired_count=3,
        still_failed_count=1,
        failure_samples=[RepairFailure(memory_id=123, errors=["reflection:TimeoutError"])],
        generated_at=datetime(2026, 3, 16, 9, 0, 0, tzinfo=timezone.utc),
    )

    text = render_report(report)

    assert "scanned_count=4" in text
    assert "repaired_count=3" in text
    assert "still_failed_count=1" in text
    assert "id=123 errors=reflection:TimeoutError" in text


def test_write_report_log_creates_file(tmp_path: Path) -> None:
    path = write_report_log(report_text="hello\n", log_dir=tmp_path / "logs")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "hello\n"


def test_notify_report_via_email_server_without_config(monkeypatch) -> None:
    monkeypatch.delenv("EMAIL_API_BASE_URL", raising=False)
    monkeypatch.delenv("EMAIL_SERVER", raising=False)
    sent, status = notify_report_via_email_server(report_text="x")
    assert sent is False
    assert "not configured" in status


def test_notify_report_via_email_server_success_with_login(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_API_BASE_URL", "http://mail.local:5003")
    monkeypatch.delenv("EMAIL_SERVER", raising=False)
    monkeypatch.setenv("EMAIL_ADDRESS", "bot@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")
    monkeypatch.delenv("EMAIL_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("EMAIL_TO", raising=False)

    login_response = Mock()
    login_response.raise_for_status.return_value = None
    login_response.json.return_value = {"token": "abc123"}

    send_response = Mock()
    send_response.raise_for_status.return_value = None
    send_response.status_code = 201

    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> Any:
        calls.append({"url": url, **kwargs})
        if url.endswith("/auth/login"):
            return login_response
        if url.endswith("/api/emails"):
            return send_response
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("memory_engine.repair_job.requests.post", fake_post)

    sent, status = notify_report_via_email_server(report_text="hello", timeout_seconds=3.5)

    assert sent is True
    assert status == "sent via EMAIL API (201)"
    assert len(calls) == 2
    assert calls[0]["json"] == {"email": "bot@example.com", "password": "secret"}
    assert calls[0]["headers"] == {"Content-Type": "application/json"}
    assert calls[1]["json"] == {
        "to": "bot@example.com",
        "subject": "Clawbie memory repair report",
        "body": "hello",
    }
    assert calls[1]["headers"] == {
        "Authorization": "Bearer abc123",
        "Content-Type": "application/json",
    }


def test_notify_report_via_email_server_http_error_contains_status(monkeypatch) -> None:
    import requests

    monkeypatch.setenv("EMAIL_SERVER", "http://mail.local:5003")
    monkeypatch.setenv("EMAIL_BEARER_TOKEN", "token")
    monkeypatch.setenv("EMAIL_TO", "ops@example.com")

    response = requests.Response()
    response.status_code = 404
    response._content = b'{"error":"missing route"}'
    response.url = "http://mail.local:5003/api/emails"

    def fake_post(*args: Any, **kwargs: Any) -> Any:
        raise requests.exceptions.HTTPError("not found", response=response)

    monkeypatch.setattr("memory_engine.repair_job.requests.post", fake_post)

    sent, status = notify_report_via_email_server(report_text="hello")

    assert sent is False
    assert "HTTP 404" in status
    assert "missing route" in status


def test_notify_report_via_email_server_requires_auth_details(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_SERVER", "http://mail.local:5003")
    monkeypatch.delenv("EMAIL_API_BASE_URL", raising=False)
    monkeypatch.setenv("EMAIL_TO", "ops@example.com")
    monkeypatch.delenv("EMAIL_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("EMAIL_ADDRESS", raising=False)
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)

    sent, status = notify_report_via_email_server(report_text="hello")

    assert sent is False
    assert "EMAIL auth not configured" in status


def test_notify_report_via_email_server_invalid_timeout(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_SERVER", "http://mail.local:5003")
    monkeypatch.setenv("EMAIL_TO", "ops@example.com")
    monkeypatch.setenv("EMAIL_BEARER_TOKEN", "token")
    monkeypatch.setenv("EMAIL_TIMEOUT_SECONDS", "invalid")

    sent, status = notify_report_via_email_server(report_text="hello")

    assert sent is False
    assert status == "email notify failed (invalid EMAIL_TIMEOUT_SECONDS)"


def test_repair_skips_status_commentary_candidates() -> None:
    repo = FakeRepository(
        [
            RepairCandidate(
                id="m-commentary",
                content="**Checking status**",
                reflection=None,
                raw_embedding_present=False,
                reflection_embedding_present=False,
                status_commentary=True,
            )
        ]
    )
    embedding = FakeEmbeddingProvider(fail_on=set(), calls=[])
    inference = FakeInferenceProvider(result="unused", fail_for=set(), calls=[])
    service = MemoryRepairService(
        repository=repo,
        embedding_provider=embedding,
        inference_provider=inference,
        reflection_prompt="summarise this in 20 lines or less",
        max_retries=0,
    )

    report = service.run()

    assert report.scanned_count == 1
    assert report.repaired_count == 0
    assert report.still_failed_count == 0
    assert embedding.calls == []
    assert inference.calls == []
    assert repo.updates == []
