from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

from memory_engine.sub_agent_activity_tracker import (
    TranscriptSummary,
    TrackerPaths,
    _extract_notification_sent,
    _extract_spawn_info,
    _normalize_status,
    _parse_ts,
    _summarize_transcript,
    collect_activity_records,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_extract_spawn_info_from_parent_events() -> None:
    events = [
        {
            "type": "message",
            "timestamp": "2026-03-17T10:12:47Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "toolCall",
                        "id": "call_123",
                        "name": "sessions_spawn",
                        "arguments": {"label": "test-label", "task": "Implement feature X"},
                    }
                ],
            },
        },
        {
            "type": "message",
            "timestamp": "2026-03-17T10:12:48Z",
            "message": {
                "role": "toolResult",
                "toolName": "sessions_spawn",
                "toolCallId": "call_123",
                "details": {
                    "status": "accepted",
                    "childSessionKey": "agent:codex:acp:abc",
                    "runId": "run-1",
                },
            },
        },
    ]

    found = _extract_spawn_info(events, parent_session_key="agent:main:main")
    row = found["agent:codex:acp:abc"]
    assert row.run_id == "run-1"
    assert row.task_label == "test-label"
    assert row.task_summary == "Implement feature X"
    assert row.parent_session_key == "agent:main:main"


def test_extract_notification_sent_from_inter_session_user_message() -> None:
    events = [
        {
            "type": "message",
            "timestamp": "2026-03-17T10:20:00Z",
            "message": {
                "role": "user",
                "timestamp": 1773742800000,
                "provenance": {"kind": "inter_session", "sourceSessionKey": "agent:codex:acp:abc"},
            },
        }
    ]
    sent = _extract_notification_sent(events)
    assert "agent:codex:acp:abc" in sent


def test_normalize_status_marks_completed_from_assistant_reply(tmp_path: Path) -> None:
    transcript = tmp_path / "child.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"type":"message","message":{"role":"user","content":"task"},"timestamp":"2026-03-17T10:00:00Z"}',
                '{"type":"message","message":{"role":"assistant","content":[{"type":"text","text":"done"}]},"timestamp":"2026-03-17T10:01:00Z"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    summary = _summarize_transcript(transcript)
    status, completed_at = _normalize_status(
        acp_state="idle",
        spawn_raw_status="accepted",
        transcript=summary,
        transcript_exists=True,
        source_updated_at=None,
        spawn_timestamp=None,
        now=datetime(2026, 3, 17, 10, 2, 0, tzinfo=timezone.utc),
    )
    assert status == "completed"
    assert completed_at is not None


def test_normalize_status_marks_fresh_idle_without_transcript_pending() -> None:
    summary = TranscriptSummary(
        has_assistant_reply=False,
        first_user_text=None,
        last_message_at=None,
        last_assistant_at=None,
    )
    now = datetime(2026, 3, 17, 10, 10, 0, tzinfo=timezone.utc)
    recent = datetime(2026, 3, 17, 10, 8, 0, tzinfo=timezone.utc)
    status, completed_at = _normalize_status(
        acp_state="idle",
        spawn_raw_status="accepted",
        transcript=summary,
        transcript_exists=False,
        source_updated_at=recent,
        spawn_timestamp=None,
        now=now,
    )
    assert status == "pending"
    assert completed_at is None


def test_normalize_status_marks_stale_idle_without_transcript_unknown() -> None:
    summary = TranscriptSummary(
        has_assistant_reply=False,
        first_user_text=None,
        last_message_at=None,
        last_assistant_at=None,
    )
    now = datetime(2026, 3, 17, 10, 10, 0, tzinfo=timezone.utc)
    stale = datetime(2026, 3, 17, 9, 50, 0, tzinfo=timezone.utc)
    status, completed_at = _normalize_status(
        acp_state="idle",
        spawn_raw_status=None,
        transcript=summary,
        transcript_exists=False,
        source_updated_at=stale,
        spawn_timestamp=None,
        now=now,
    )
    assert status == "unknown"
    assert completed_at is None


def test_collect_activity_records_uses_sessions_indexes(tmp_path: Path) -> None:
    parent_file = tmp_path / "parent.jsonl"
    parent_file.write_text(
        "\n".join(
            [
                '{"type":"message","timestamp":"2026-03-17T10:12:47Z","message":{"role":"assistant","content":[{"type":"toolCall","id":"call_1","name":"sessions_spawn","arguments":{"label":"my-run","task":"Do work"}}]}}',
                '{"type":"message","timestamp":"2026-03-17T10:12:48Z","message":{"role":"toolResult","toolName":"sessions_spawn","toolCallId":"call_1","details":{"status":"accepted","childSessionKey":"agent:codex:acp:abc","runId":"run-abc"}}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    child_file = tmp_path / "child.jsonl"
    child_file.write_text(
        "\n".join(
            [
                '{"type":"session","id":"s1"}',
                '{"type":"message","timestamp":"2026-03-17T10:13:00Z","message":{"role":"user","content":"Do work"}}',
                '{"type":"message","timestamp":"2026-03-17T10:15:00Z","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    codex_index = tmp_path / "codex_sessions.json"
    _write_json(
        codex_index,
        {
            "agent:codex:acp:abc": {
                "sessionId": "s1",
                "updatedAt": 1773742500000,
                "spawnedBy": "agent:main:main",
                "label": "fallback-label",
                "sessionFile": str(child_file),
                "acp": {"state": "idle", "mode": "oneshot"},
            }
        },
    )
    main_index = tmp_path / "main_sessions.json"
    _write_json(
        main_index,
        {
            "agent:main:main": {
                "sessionId": "main-1",
                "sessionFile": str(parent_file),
            }
        },
    )

    rows = collect_activity_records(
        TrackerPaths(
            codex_sessions_index=codex_index,
            main_sessions_index=main_index,
        )
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.child_session_key == "agent:codex:acp:abc"
    assert row.run_id == "run-abc"
    assert row.task_label == "my-run"
    assert row.task_summary == "Do work"
    assert row.status == "completed"
    assert row.parent_session_id == "main-1"


def test_collect_activity_records_marks_fresh_missing_transcript_pending(tmp_path: Path) -> None:
    parent_file = tmp_path / "parent.jsonl"
    parent_file.write_text(
        "\n".join(
            [
                '{"type":"message","timestamp":"2026-03-17T10:12:47Z","message":{"role":"assistant","content":[{"type":"toolCall","id":"call_1","name":"sessions_spawn","arguments":{"label":"my-run","task":"Do work"}}]}}',
                '{"type":"message","timestamp":"2026-03-17T10:12:48Z","message":{"role":"toolResult","toolName":"sessions_spawn","toolCallId":"call_1","details":{"status":"accepted","childSessionKey":"agent:codex:acp:fresh","runId":"run-fresh"}}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    missing_child = tmp_path / "missing-child.jsonl"
    codex_index = tmp_path / "codex_sessions.json"
    _write_json(
        codex_index,
        {
            "agent:codex:acp:fresh": {
                "sessionId": "s-fresh",
                "updatedAt": 1773742500000,
                "spawnedBy": "agent:main:main",
                "label": "fresh-run",
                "sessionFile": str(missing_child),
                "acp": {"state": "idle", "mode": "oneshot"},
            }
        },
    )
    main_index = tmp_path / "main_sessions.json"
    _write_json(
        main_index,
        {
            "agent:main:main": {
                "sessionId": "main-1",
                "sessionFile": str(parent_file),
            }
        },
    )

    rows = collect_activity_records(
        TrackerPaths(
            codex_sessions_index=codex_index,
            main_sessions_index=main_index,
        )
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "pending"
    assert row.metadata["transcript_exists"] is False


def test_collect_activity_records_infers_sent_for_completed_when_parent_assistant_after_completion(tmp_path: Path) -> None:
    parent_file = tmp_path / "parent.jsonl"
    parent_file.write_text(
        "\n".join(
            [
                '{"type":"message","timestamp":"2026-03-17T10:12:47Z","message":{"role":"assistant","content":[{"type":"toolCall","id":"call_1","name":"sessions_spawn","arguments":{"label":"my-run","task":"Do work"}}]}}',
                '{"type":"message","timestamp":"2026-03-17T10:12:48Z","message":{"role":"toolResult","toolName":"sessions_spawn","toolCallId":"call_1","details":{"status":"accepted","childSessionKey":"agent:codex:acp:done","runId":"run-done"}}}',
                '{"type":"message","timestamp":"2026-03-17T10:16:30Z","message":{"role":"assistant","content":[{"type":"text","text":"Shared the result with the user."}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    child_file = tmp_path / "child.jsonl"
    child_file.write_text(
        "\n".join(
            [
                '{"type":"message","timestamp":"2026-03-17T10:13:00Z","message":{"role":"user","content":"Do work"}}',
                '{"type":"message","timestamp":"2026-03-17T10:15:00Z","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    codex_index = tmp_path / "codex_sessions.json"
    _write_json(
        codex_index,
        {
            "agent:codex:acp:done": {
                "sessionId": "s-done",
                "updatedAt": 1773742500000,
                "spawnedBy": "agent:main:main",
                "label": "done-run",
                "sessionFile": str(child_file),
                "acp": {"state": "idle", "mode": "oneshot"},
            }
        },
    )
    main_index = tmp_path / "main_sessions.json"
    _write_json(
        main_index,
        {
            "agent:main:main": {
                "sessionId": "main-1",
                "sessionFile": str(parent_file),
            }
        },
    )
    rows = collect_activity_records(
        TrackerPaths(
            codex_sessions_index=codex_index,
            main_sessions_index=main_index,
        )
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "completed"
    assert row.notification_status == "sent"
    assert row.notification_sent_at == _parse_ts("2026-03-17T10:16:30Z")
    assert row.metadata["notification_inferred_from"] == "parent_assistant_after_completion"
