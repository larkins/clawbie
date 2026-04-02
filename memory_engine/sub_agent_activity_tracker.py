from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import time
from typing import Any

import yaml

from .config import load_config
from .db import open_connection


DEFAULT_CODEX_SESSIONS_INDEX = "~/.openclaw/agents/codex/sessions/sessions.json"
DEFAULT_MAIN_SESSIONS_INDEX = "~/.openclaw/agents/main/sessions/sessions.json"
DEFAULT_AGENT_ID = "codex"


@dataclass(frozen=True)
class TrackerPaths:
    codex_sessions_index: Path
    main_sessions_index: Path


@dataclass(frozen=True)
class SpawnInfo:
    child_session_key: str
    run_id: str | None
    parent_session_key: str
    task_label: str | None
    task_summary: str | None
    timestamp: datetime | None
    raw_status: str | None


@dataclass(frozen=True)
class TranscriptSummary:
    has_assistant_reply: bool
    first_user_text: str | None
    last_message_at: datetime | None
    last_assistant_at: datetime | None


@dataclass(frozen=True)
class ParentSessionSummary:
    last_assistant_at: datetime | None


@dataclass(frozen=True)
class ActivityRecord:
    child_session_key: str
    run_id: str | None
    agent_id: str
    parent_session_key: str | None
    parent_session_id: str | None
    task_label: str | None
    task_summary: str | None
    status: str
    source_updated_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    notification_status: str
    notification_sent_at: datetime | None
    session_file: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ScanReport:
    scanned_sessions: int
    upserted_rows: int


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw >= 1_000_000_000_000:
            raw = raw / 1000.0
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return _parse_ts(float(text))
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _expand_path(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve()


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    parts.append(text)
                continue
            if not isinstance(item, dict):
                continue
            if str(item.get("type", "")).lower() != "text":
                continue
            nested = item.get("text") or item.get("content")
            nested_text = _extract_text(nested)
            if nested_text:
                parts.append(nested_text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message", "value"):
            if key in value:
                text = _extract_text(value[key])
                if text:
                    return text
    return ""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events


def _extract_spawn_info(events: list[dict[str, Any]], *, parent_session_key: str) -> dict[str, SpawnInfo]:
    pending_calls: dict[str, dict[str, Any]] = {}
    out: dict[str, SpawnInfo] = {}
    for event in events:
        if event.get("type") != "message":
            continue
        msg = event.get("message")
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).lower()
        ts = _parse_ts(msg.get("timestamp") or event.get("timestamp"))
        if role == "assistant":
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if str(part.get("type", "")).lower() != "toolcall":
                    continue
                if str(part.get("name", "")) != "sessions_spawn":
                    continue
                call_id = str(part.get("id", "")).strip()
                if not call_id:
                    continue
                args = part.get("arguments") if isinstance(part.get("arguments"), dict) else {}
                pending_calls[call_id] = {
                    "timestamp": ts,
                    "task_label": args.get("label"),
                    "task_summary": _extract_text(args.get("task")),
                }
            continue

        if role != "toolresult":
            continue
        if str(msg.get("toolName", "")) != "sessions_spawn":
            continue
        details = msg.get("details") if isinstance(msg.get("details"), dict) else {}
        child_session_key = str(details.get("childSessionKey") or "").strip()
        if not child_session_key:
            continue
        call_id = str(msg.get("toolCallId", "")).strip()
        pending = pending_calls.get(call_id, {})
        out[child_session_key] = SpawnInfo(
            child_session_key=child_session_key,
            run_id=str(details.get("runId")).strip() if details.get("runId") is not None else None,
            parent_session_key=parent_session_key,
            task_label=str(pending.get("task_label")).strip() if pending.get("task_label") is not None else None,
            task_summary=str(pending.get("task_summary")).strip() if pending.get("task_summary") is not None else None,
            timestamp=ts or pending.get("timestamp"),
            raw_status=str(details.get("status")).strip() if details.get("status") is not None else None,
        )
    return out


def _extract_notification_sent(events: list[dict[str, Any]]) -> dict[str, datetime]:
    sent: dict[str, datetime] = {}
    for event in events:
        if event.get("type") != "message":
            continue
        msg = event.get("message")
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role", "")).lower() != "user":
            continue
        provenance = msg.get("provenance")
        if not isinstance(provenance, dict):
            continue
        source_session_key = str(provenance.get("sourceSessionKey") or "").strip()
        if not source_session_key:
            continue
        ts = _parse_ts(msg.get("timestamp") or event.get("timestamp"))
        if ts is None:
            continue
        prior = sent.get(source_session_key)
        if prior is None or ts > prior:
            sent[source_session_key] = ts
    return sent


def _summarize_parent_session(events: list[dict[str, Any]]) -> ParentSessionSummary:
    last_assistant_at: datetime | None = None
    for event in events:
        if event.get("type") != "message":
            continue
        msg = event.get("message")
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).lower()
        if role != "assistant":
            continue
        ts = _parse_ts(msg.get("timestamp") or event.get("timestamp"))
        if ts is None:
            continue
        if last_assistant_at is None or ts > last_assistant_at:
            last_assistant_at = ts
    return ParentSessionSummary(last_assistant_at=last_assistant_at)


def _summarize_transcript(path: Path) -> TranscriptSummary:
    events = _read_jsonl(path)
    first_user_text: str | None = None
    has_assistant_reply = False
    last_message_at: datetime | None = None
    last_assistant_at: datetime | None = None

    for event in events:
        if event.get("type") != "message":
            continue
        msg = event.get("message")
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).lower()
        ts = _parse_ts(msg.get("timestamp") or event.get("timestamp"))
        if ts is not None and (last_message_at is None or ts > last_message_at):
            last_message_at = ts
        if role == "user" and first_user_text is None:
            text = _extract_text(msg.get("content"))
            if text:
                first_user_text = text
        if role == "assistant":
            has_assistant_reply = True
            if ts is not None and (last_assistant_at is None or ts > last_assistant_at):
                last_assistant_at = ts

    return TranscriptSummary(
        has_assistant_reply=has_assistant_reply,
        first_user_text=first_user_text,
        last_message_at=last_message_at,
        last_assistant_at=last_assistant_at,
    )


def _normalize_status(
    *,
    acp_state: str | None,
    spawn_raw_status: str | None,
    transcript: TranscriptSummary,
    transcript_exists: bool,
    source_updated_at: datetime | None,
    spawn_timestamp: datetime | None,
    now: datetime,
    fresh_window_seconds: int = 300,
) -> tuple[str, datetime | None]:
    state = (acp_state or "").strip().lower()
    raw_status = (spawn_raw_status or "").strip().lower()
    recent_threshold = now.timestamp() - max(0, fresh_window_seconds)

    if state == "running":
        return "running", None
    if state in {"failed", "error"} or raw_status in {"failed", "rejected", "error"}:
        return "failed", None
    if transcript.has_assistant_reply:
        return "completed", transcript.last_assistant_at
    if state in {"queued", "pending"}:
        return "pending", None
    if raw_status in {"accepted", "queued", "pending"}:
        return "pending", None
    if state == "idle":
        if transcript_exists:
            return "pending", None
        for ts in (source_updated_at, spawn_timestamp):
            if ts is not None and ts.timestamp() >= recent_threshold:
                return "pending", None
        return "unknown", None
    return "unknown", None


def _task_summary_from_sources(spawn: SpawnInfo | None, transcript: TranscriptSummary) -> str | None:
    if spawn is not None and spawn.task_summary:
        return spawn.task_summary
    return transcript.first_user_text


def _load_tracker_paths(config_path: str | Path) -> TrackerPaths:
    try:
        payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    config = payload
    tracker_cfg = config.get("sub_agent_activity_tracker")
    if not isinstance(tracker_cfg, dict):
        tracker_cfg = {}
    codex_index = str(tracker_cfg.get("codex_sessions_index", DEFAULT_CODEX_SESSIONS_INDEX))
    main_index = str(tracker_cfg.get("main_sessions_index", DEFAULT_MAIN_SESSIONS_INDEX))
    return TrackerPaths(
        codex_sessions_index=_expand_path(codex_index),
        main_sessions_index=_expand_path(main_index),
    )


def collect_activity_records(paths: TrackerPaths, *, agent_id: str = DEFAULT_AGENT_ID) -> list[ActivityRecord]:
    codex_index = _load_json(paths.codex_sessions_index)
    main_index = _load_json(paths.main_sessions_index)

    spawn_by_child: dict[str, SpawnInfo] = {}
    notification_sent: dict[str, datetime] = {}
    parent_summary_by_key: dict[str, ParentSessionSummary] = {}

    for parent_session_key, raw_session in main_index.items():
        if not isinstance(raw_session, dict):
            continue
        session_file = raw_session.get("sessionFile")
        if not isinstance(session_file, str) or not session_file.strip():
            continue
        events = _read_jsonl(Path(session_file))
        spawn_by_child.update(_extract_spawn_info(events, parent_session_key=parent_session_key))
        parent_summary_by_key[parent_session_key] = _summarize_parent_session(events)
        for child_key, ts in _extract_notification_sent(events).items():
            prior = notification_sent.get(child_key)
            if prior is None or ts > prior:
                notification_sent[child_key] = ts

    now = datetime.now(timezone.utc)
    records: list[ActivityRecord] = []
    for child_session_key, raw in codex_index.items():
        if not isinstance(raw, dict):
            continue
        if not str(child_session_key).startswith("agent:codex:acp:"):
            continue
        session_file_text = raw.get("sessionFile")
        session_file = Path(session_file_text) if isinstance(session_file_text, str) and session_file_text.strip() else None
        transcript = _summarize_transcript(session_file) if session_file is not None else TranscriptSummary(False, None, None, None)
        transcript_exists = session_file is not None and session_file.exists()

        acp = raw.get("acp") if isinstance(raw.get("acp"), dict) else {}
        acp_state = acp.get("state") if isinstance(acp.get("state"), str) else None
        source_updated_at = _parse_ts(raw.get("updatedAt"))
        spawn = spawn_by_child.get(str(child_session_key))
        status, completed_at = _normalize_status(
            acp_state=acp_state,
            spawn_raw_status=spawn.raw_status if spawn is not None else None,
            transcript=transcript,
            transcript_exists=transcript_exists,
            source_updated_at=source_updated_at,
            spawn_timestamp=spawn.timestamp if spawn is not None else None,
            now=now,
        )

        updated_at_candidates = [item for item in (source_updated_at, transcript.last_message_at, now) if item is not None]
        updated_at = max(updated_at_candidates)

        run_id = spawn.run_id if spawn is not None else None
        parent_session_key = spawn.parent_session_key if spawn is not None else raw.get("spawnedBy")
        if parent_session_key is not None:
            parent_session_key = str(parent_session_key).strip() or None

        parent_entry = main_index.get(parent_session_key) if parent_session_key else None
        parent_session_id = None
        if isinstance(parent_entry, dict):
            sid = parent_entry.get("sessionId")
            if sid is not None:
                parent_session_id = str(sid).strip() or None

        task_label = None
        if spawn is not None and spawn.task_label:
            task_label = spawn.task_label
        else:
            raw_label = raw.get("label")
            if raw_label is not None:
                task_label = str(raw_label).strip() or None

        task_summary = _task_summary_from_sources(spawn, transcript)
        if task_summary:
            task_summary = task_summary[:1200]

        sent_at = notification_sent.get(str(child_session_key))
        notification_inferred_from: str | None = None
        parent_summary = parent_summary_by_key.get(parent_session_key) if parent_session_key else None
        parent_assistant_at = parent_summary.last_assistant_at if parent_summary is not None else None
        if (
            sent_at is None
            and status == "completed"
            and completed_at is not None
            and parent_assistant_at is not None
            and parent_assistant_at >= completed_at
        ):
            sent_at = parent_assistant_at
            notification_inferred_from = "parent_assistant_after_completion"

        if sent_at is not None:
            notification_status = "sent"
        elif status in {"pending", "running", "completed"}:
            notification_status = "pending"
        else:
            notification_status = "unknown"

        metadata = {
            "acp_state": acp_state,
            "acp_mode": acp.get("mode"),
            "spawn_raw_status": spawn.raw_status if spawn is not None else None,
            "runtime_session_name": acp.get("runtimeSessionName"),
            "transcript_exists": transcript_exists,
            "notification_inferred_from": notification_inferred_from,
        }

        records.append(
            ActivityRecord(
                child_session_key=str(child_session_key),
                run_id=run_id,
                agent_id=agent_id,
                parent_session_key=parent_session_key,
                parent_session_id=parent_session_id,
                task_label=task_label,
                task_summary=task_summary,
                status=status,
                source_updated_at=source_updated_at,
                updated_at=updated_at,
                completed_at=completed_at,
                notification_status=notification_status,
                notification_sent_at=sent_at,
                session_file=str(session_file) if session_file is not None else None,
                metadata=metadata,
            )
        )
    return records


def upsert_activity_records(*, dsn: str, records: list[ActivityRecord]) -> int:
    from psycopg.types.json import Json

    if not records:
        return 0
    with open_connection(dsn) as conn:
        with conn.cursor() as cur:
            for record in records:
                cur.execute(
                    """
                    INSERT INTO sub_agent_activity (
                        child_session_key,
                        run_id,
                        agent_id,
                        parent_session_key,
                        parent_session_id,
                        task_label,
                        task_summary,
                        status,
                        source_updated_at,
                        updated_at,
                        completed_at,
                        notification_status,
                        notification_sent_at,
                        session_file,
                        metadata,
                        last_seen_at
                    ) VALUES (
                        %(child_session_key)s,
                        %(run_id)s,
                        %(agent_id)s,
                        %(parent_session_key)s,
                        %(parent_session_id)s,
                        %(task_label)s,
                        %(task_summary)s,
                        %(status)s,
                        %(source_updated_at)s,
                        %(updated_at)s,
                        %(completed_at)s,
                        %(notification_status)s,
                        %(notification_sent_at)s,
                        %(session_file)s,
                        %(metadata)s,
                        now()
                    )
                    ON CONFLICT (child_session_key)
                    DO UPDATE SET
                        run_id = EXCLUDED.run_id,
                        agent_id = EXCLUDED.agent_id,
                        parent_session_key = EXCLUDED.parent_session_key,
                        parent_session_id = EXCLUDED.parent_session_id,
                        task_label = EXCLUDED.task_label,
                        task_summary = EXCLUDED.task_summary,
                        status = EXCLUDED.status,
                        source_updated_at = EXCLUDED.source_updated_at,
                        updated_at = EXCLUDED.updated_at,
                        completed_at = EXCLUDED.completed_at,
                        notification_status = EXCLUDED.notification_status,
                        notification_sent_at = EXCLUDED.notification_sent_at,
                        session_file = EXCLUDED.session_file,
                        metadata = sub_agent_activity.metadata || EXCLUDED.metadata,
                        last_seen_at = now()
                    """,
                    {
                        "child_session_key": record.child_session_key,
                        "run_id": record.run_id,
                        "agent_id": record.agent_id,
                        "parent_session_key": record.parent_session_key,
                        "parent_session_id": record.parent_session_id,
                        "task_label": record.task_label,
                        "task_summary": record.task_summary,
                        "status": record.status,
                        "source_updated_at": record.source_updated_at,
                        "updated_at": record.updated_at,
                        "completed_at": record.completed_at,
                        "notification_status": record.notification_status,
                        "notification_sent_at": record.notification_sent_at,
                        "session_file": record.session_file,
                        "metadata": Json(record.metadata),
                    },
                )
        conn.commit()
    return len(records)


def scan_once(*, config_path: str | Path) -> ScanReport:
    app_cfg = load_config(config_path)
    tracker_paths = _load_tracker_paths(config_path)
    records = collect_activity_records(tracker_paths)
    upserted = upsert_activity_records(dsn=app_cfg.database_dsn, records=records)
    return ScanReport(scanned_sessions=len(records), upserted_rows=upserted)


def run_tracker_loop(*, config_path: str | Path, once: bool, interval_seconds: float, sleep_fn: Any = time.sleep) -> int:
    while True:
        report = scan_once(config_path=config_path)
        print(f"tracker_result scanned={report.scanned_sessions} upserted={report.upserted_rows}")
        if once:
            return 0
        sleep_fn(interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Track Codex ACP activity from local OpenClaw session state.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval-seconds", type=float, default=600.0, help="Loop interval when not using --once")
    args = parser.parse_args(argv)
    interval = max(30.0, float(args.interval_seconds))
    return run_tracker_loop(
        config_path=args.config,
        once=args.once,
        interval_seconds=interval,
    )


if __name__ == "__main__":
    raise SystemExit(main())
