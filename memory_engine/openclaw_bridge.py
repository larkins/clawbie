from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import glob
import json
import os
import time
from typing import Any, Protocol

import yaml

from .config import AppConfig, load_config
from .db import open_connection
from .ingestion import IngestionInput, MemoryIngestionService, FilteredContentError
from .providers import HttpEmbeddingProvider, HttpInferenceProvider
from .repository import MemoryRepository
from .status_commentary import is_status_commentary_text


DEFAULT_TRANSCRIPT_GLOBS = [
    "~/.openclaw/sessions/main*.jsonl",
]

DEFAULT_ALLOWED_ROLES = {"user", "assistant"}
DEFAULT_EXCLUDED_CHANNELS = {"analysis", "tool"}
DEFAULT_SOURCE_MARKER = "openclaw_transcript"


@dataclass(frozen=True)
class TranscriptMessage:
    index: int
    text: str
    role: str
    timestamp: datetime | None
    channel: str | None
    source_ref: str
    session_id: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BridgeConfig:
    transcript_globs: list[str]
    source_marker: str
    source_type: str
    user_id: str | None
    allowed_roles: set[str]
    excluded_channels: set[str]
    poll_interval_seconds: float
    state_path: Path


@dataclass(frozen=True)
class ScanResult:
    scanned_messages: int
    ingested_messages: int
    deduplicated_messages: int
    skipped_messages: int


class IngestionServiceLike(Protocol):
    def ingest(self, memory: IngestionInput) -> Any:
        raise NotImplementedError


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _as_map(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw <= 0:
            return None
        if raw >= 1_000_000_000_000:
            raw = raw / 1000.0
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            raw = float(text)
            if raw <= 0:
                return None
            if raw >= 1_000_000_000_000:
                raw = raw / 1000.0
            try:
                return datetime.fromtimestamp(raw, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


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
            elif isinstance(item, dict):
                item_type = str(item.get("type", "")).lower()
                if item_type and item_type != "text":
                    continue
                nested = (
                    item.get("text")
                    or item.get("content")
                    or item.get("value")
                    or item.get("message")
                )
                nested_text = _extract_text(nested)
                if nested_text:
                    parts.append(nested_text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "value", "message"):
            if key in value:
                text = _extract_text(value[key])
                if text:
                    return text
    return ""


def _likely_tool_or_thinking(message: dict[str, Any]) -> bool:
    role = str(message.get("role") or "").lower()
    channel = str(message.get("channel") or "").lower()
    if role in {"tool", "function", "toolresult", "tool_result"}:
        return True
    if channel in {"analysis", "tool"}:
        return True
    if "tool_calls" in message or "function_call" in message:
        return True
    return False


def _flatten_message_event(obj: dict[str, Any]) -> dict[str, Any]:
    nested = obj.get("message")
    if not isinstance(nested, dict):
        return obj

    merged = dict(nested)
    for key in (
        "id",
        "timestamp",
        "created_at",
        "createdAt",
        "ts",
        "time",
        "session_id",
        "session",
        "session_key",
        "sessionKey",
        "channel",
        "stream",
    ):
        if key not in merged and key in obj:
            merged[key] = obj[key]
    if "message_id" not in merged and "id" in obj:
        merged["message_id"] = obj["id"]
    return merged


def _is_status_commentary_message(message: TranscriptMessage) -> bool:
    return is_status_commentary_text(
        text=message.text,
        role=message.role,
        channel=message.channel,
    )


def _iter_message_candidates(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        out: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                out.append(item)
        return out

    if isinstance(payload, dict):
        for key in ("messages", "entries", "turns", "conversation"):
            nested = payload.get(key)
            if isinstance(nested, list):
                out = []
                for item in nested:
                    if isinstance(item, dict):
                        out.append(item)
                return out
        if any(k in payload for k in ("content", "message", "text")) and any(
            k in payload for k in ("role", "author")
        ):
            return [payload]

    return []


def _is_message_event(obj: dict[str, Any]) -> bool:
    event_type = obj.get("type")
    if event_type is None:
        return True
    return str(event_type).strip().lower() == "message"


def parse_transcript_messages(path: Path) -> list[TranscriptMessage]:
    text = path.read_text(encoding="utf-8")
    objects: list[dict[str, Any]] = []
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and _is_message_event(obj):
                objects.append(obj)
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = []
        objects.extend(_iter_message_candidates(payload))

    messages: list[TranscriptMessage] = []
    for idx, obj in enumerate(objects):
        candidate = _flatten_message_event(obj)

        if _likely_tool_or_thinking(candidate):
            continue

        role = str(candidate.get("role") or candidate.get("author") or "").strip().lower()
        channel_value = candidate.get("channel") or candidate.get("stream")
        channel = str(channel_value).strip().lower() if channel_value is not None else None
        raw_text = candidate.get("content")
        if raw_text is None:
            raw_text = candidate.get("message")
        if raw_text is None:
            raw_text = candidate.get("text")
        message_text = _extract_text(raw_text).strip()
        if not message_text:
            continue

        timestamp = _parse_datetime(
            candidate.get("timestamp")
            or candidate.get("created_at")
            or candidate.get("createdAt")
            or candidate.get("ts")
            or candidate.get("time")
        )
        session_id = str(
            candidate.get("session_id")
            or candidate.get("session")
            or candidate.get("session_key")
            or candidate.get("sessionKey")
            or path.stem
        ).strip()
        message_id = str(candidate.get("id") or candidate.get("message_id") or candidate.get("uuid") or idx)
        source_ref = f"{path}:{message_id}"

        metadata = {
            "source_file": str(path),
            "source_message_id": message_id,
        }
        if channel:
            metadata["channel"] = channel

        messages.append(
            TranscriptMessage(
                index=idx,
                text=message_text,
                role=role,
                timestamp=timestamp,
                channel=channel,
                source_ref=source_ref,
                session_id=session_id,
                metadata=metadata,
            )
        )
    return messages


def _expand_globs(patterns: list[str]) -> list[Path]:
    matches: set[Path] = set()
    for pattern in patterns:
        expanded = os.path.expanduser(pattern)
        for match in glob.glob(expanded, recursive=True):
            path = Path(match)
            if path.is_file():
                matches.add(path.resolve())
    return sorted(matches)


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"files": {}}
    if not isinstance(data, dict):
        return {"files": {}}
    files = data.get("files")
    if not isinstance(files, dict):
        return {"files": {}}
    return {"files": files}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class OpenClawBridge:
    def __init__(self, *, ingestion_service: IngestionServiceLike, bridge_config: BridgeConfig) -> None:
        self._ingestion_service = ingestion_service
        self._bridge_config = bridge_config

    def scan_once(self) -> ScanResult:
        state = _load_state(self._bridge_config.state_path)
        files_state = _as_map(state.get("files"))

        scanned = 0
        ingested = 0
        deduplicated = 0
        skipped = 0

        transcript_paths = _expand_globs(self._bridge_config.transcript_globs)
        for transcript_path in transcript_paths:
            file_key = str(transcript_path)
            file_state = _as_map(files_state.get(file_key))
            last_index = int(file_state.get("last_index", -1))
            messages = parse_transcript_messages(transcript_path)
            max_seen_index = last_index

            if messages and last_index >= len(messages):
                last_index = -1

            for message in messages:
                if message.index <= last_index:
                    continue
                scanned += 1

                if message.role not in self._bridge_config.allowed_roles:
                    skipped += 1
                    max_seen_index = message.index
                    continue
                if message.channel and message.channel in self._bridge_config.excluded_channels:
                    skipped += 1
                    max_seen_index = message.index
                    continue

                metadata = dict(message.metadata)
                metadata["source_marker"] = self._bridge_config.source_marker
                metadata["role"] = message.role
                if message.timestamp is not None:
                    metadata["source_timestamp"] = message.timestamp.isoformat()
                status_commentary = _is_status_commentary_message(message)
                if status_commentary:
                    metadata["status_commentary"] = True

                try:
                    result = self._ingestion_service.ingest(
                        IngestionInput(
                            content=message.text,
                            source_type=self._bridge_config.source_type,
                            source_ref=message.source_ref,
                            session_id=message.session_id,
                            user_id=self._bridge_config.user_id,
                            metadata=metadata,
                            status_commentary=status_commentary,
                        )
                    )
                    if bool(getattr(result, "deduplicated", False)):
                        deduplicated += 1
                    else:
                        ingested += 1
                except FilteredContentError:
                    # Skip filtered content (heartbeat/system messages)
                    skipped += 1
                max_seen_index = message.index

            files_state[file_key] = {
                "last_index": max_seen_index,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        state["files"] = files_state
        _save_state(self._bridge_config.state_path, state)
        return ScanResult(
            scanned_messages=scanned,
            ingested_messages=ingested,
            deduplicated_messages=deduplicated,
            skipped_messages=skipped,
        )


def load_bridge_config(config_path: str | Path, *, state_path_override: str | None = None) -> tuple[AppConfig, BridgeConfig]:
    config_path = Path(config_path)
    app_cfg = load_config(config_path)
    raw = _load_yaml(config_path)
    bridge = _as_map(raw.get("openclaw_bridge"))

    globs_from_env = os.getenv("OPENCLAW_TRANSCRIPT_GLOBS", "").strip()
    if globs_from_env:
        transcript_globs = [part.strip() for part in globs_from_env.split(",") if part.strip()]
    else:
        transcript_globs = bridge.get("transcript_globs", DEFAULT_TRANSCRIPT_GLOBS)
    transcript_globs = [str(item) for item in transcript_globs if str(item).strip()]
    if not transcript_globs:
        transcript_globs = list(DEFAULT_TRANSCRIPT_GLOBS)

    state_path = state_path_override or str(bridge.get("state_path", ".state/openclaw-bridge-state.json"))
    poll_interval_seconds = float(bridge.get("poll_interval_seconds", 60))
    source_marker = str(bridge.get("source_marker", DEFAULT_SOURCE_MARKER))
    source_type = str(bridge.get("source_type", "chat"))
    user_id = bridge.get("user_id")
    if user_id is not None:
        user_id = str(user_id)

    allowed_roles = {
        str(item).strip().lower()
        for item in bridge.get("allowed_roles", sorted(DEFAULT_ALLOWED_ROLES))
        if str(item).strip()
    }
    if not allowed_roles:
        allowed_roles = set(DEFAULT_ALLOWED_ROLES)
    excluded_channels = {
        str(item).strip().lower()
        for item in bridge.get("excluded_channels", sorted(DEFAULT_EXCLUDED_CHANNELS))
        if str(item).strip()
    }

    return app_cfg, BridgeConfig(
        transcript_globs=transcript_globs,
        source_marker=source_marker,
        source_type=source_type,
        user_id=user_id,
        allowed_roles=allowed_roles,
        excluded_channels=excluded_channels,
        poll_interval_seconds=max(1.0, poll_interval_seconds),
        state_path=Path(state_path),
    )


def run_bridge_loop(
    *,
    bridge: OpenClawBridge,
    interval_seconds: float,
    once: bool,
    sleep_fn: Any = time.sleep,
) -> int:
    while True:
        result = bridge.scan_once()
        print(
            "scan_result "
            f"scanned={result.scanned_messages} "
            f"ingested={result.ingested_messages} "
            f"deduplicated={result.deduplicated_messages} "
            f"skipped={result.skipped_messages}"
        )
        if once:
            return 0
        sleep_fn(interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest OpenClaw session transcripts into user_memories.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--state-path", default=None, help="Optional override for state file path")
    parser.add_argument("--once", action="store_true", help="Run one scan and exit")
    parser.add_argument("--interval-seconds", type=float, default=None, help="Override polling interval")
    args = parser.parse_args(argv)

    app_cfg, bridge_cfg = load_bridge_config(args.config, state_path_override=args.state_path)
    if args.interval_seconds is not None:
        bridge_cfg = BridgeConfig(
            transcript_globs=bridge_cfg.transcript_globs,
            source_marker=bridge_cfg.source_marker,
            source_type=bridge_cfg.source_type,
            user_id=bridge_cfg.user_id,
            allowed_roles=bridge_cfg.allowed_roles,
            excluded_channels=bridge_cfg.excluded_channels,
            poll_interval_seconds=max(1.0, args.interval_seconds),
            state_path=bridge_cfg.state_path,
        )

    embedding_provider = HttpEmbeddingProvider(
        url=app_cfg.embedding.url,
        model=app_cfg.embedding.model,
        timeout_seconds=app_cfg.embedding.timeout_seconds,
    )
    inference_provider = HttpInferenceProvider(
        url=app_cfg.inference.url,
        model=app_cfg.inference.model,
        timeout_seconds=app_cfg.inference.timeout_seconds,
    )

    with open_connection(app_cfg.database_dsn) as conn:
        repository = MemoryRepository(conn)
        ingestion = MemoryIngestionService(
            repository=repository,
            embedding_provider=embedding_provider,
            inference_provider=inference_provider,
            reflection_prompt=app_cfg.memory.reflection_prompt,
            max_retries=app_cfg.memory.ingestion_retry.max_retries,
            retry_backoff_seconds=app_cfg.memory.ingestion_retry.backoff_seconds,
        )
        bridge = OpenClawBridge(ingestion_service=ingestion, bridge_config=bridge_cfg)
        return run_bridge_loop(
            bridge=bridge,
            interval_seconds=bridge_cfg.poll_interval_seconds,
            once=args.once,
        )


if __name__ == "__main__":
    raise SystemExit(main())
