from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from memory_engine.ingestion import IngestionInput
from memory_engine.openclaw_bridge import (
    BridgeConfig,
    OpenClawBridge,
    TranscriptMessage,
    _is_status_commentary_message,
    parse_transcript_messages,
)


@dataclass
class FakeIngestResult:
    deduplicated: bool


class FakeIngestionService:
    def __init__(self) -> None:
        self.calls: list[IngestionInput] = []
        self._seen_texts: set[str] = set()

    def ingest(self, memory: IngestionInput) -> FakeIngestResult:
        self.calls.append(memory)
        key = memory.content
        deduplicated = key in self._seen_texts
        self._seen_texts.add(key)
        return FakeIngestResult(deduplicated=deduplicated)


def test_parse_transcript_messages_ignores_tool_noise_and_extracts_text(tmp_path: Path) -> None:
    transcript = tmp_path / "main.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"id":"m1","role":"user","content":"hello there","timestamp":"2026-03-17T00:00:00Z"}',
                '{"id":"m2","role":"assistant","content":[{"type":"text","text":"answer"}]}',
                '{"id":"m3","role":"assistant","channel":"analysis","content":"private reasoning"}',
                '{"id":"m4","role":"tool","content":"tool output"}',
            ]
        ),
        encoding="utf-8",
    )

    messages = parse_transcript_messages(transcript)

    assert [m.source_ref for m in messages] == [f"{transcript}:m1", f"{transcript}:m2"]
    assert [m.text for m in messages] == ["hello there", "answer"]
    assert messages[0].role == "user"
    assert messages[0].timestamp is not None


def test_parse_transcript_messages_extracts_nested_openclaw_message_events(tmp_path: Path) -> None:
    transcript = tmp_path / "main.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"type":"session","id":"s0","timestamp":"2026-03-17T00:00:00Z"}',
                '{"type":"message","id":"u1","timestamp":1773638255309,"message":{"role":"user","content":[{"type":"text","text":"hello from user"}]}}',
                '{"type":"message","id":"a1","timestamp":"2026-03-17T00:00:02Z","message":{"role":"assistant","content":[{"type":"thinking","thinking":"hidden"},{"type":"toolCall","name":"exec"},{"type":"text","text":"visible assistant reply"}]}}',
                '{"type":"message","id":"t1","timestamp":"2026-03-17T00:00:03Z","message":{"role":"toolResult","content":[{"type":"text","text":"tool payload"}]}}',
                '{"type":"custom_message","id":"x1","content":"hidden internal event"}',
            ]
        ),
        encoding="utf-8",
    )

    messages = parse_transcript_messages(transcript)

    assert [m.source_ref for m in messages] == [f"{transcript}:u1", f"{transcript}:a1"]
    assert [m.role for m in messages] == ["user", "assistant"]
    assert [m.text for m in messages] == ["hello from user", "visible assistant reply"]
    assert messages[0].timestamp is not None
    assert messages[0].timestamp.isoformat() == "2026-03-16T05:17:35.309000+00:00"


def test_bridge_scan_once_is_idempotent_via_state_file(tmp_path: Path) -> None:
    transcript = tmp_path / "main.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"id":"m1","role":"user","content":"alpha"}',
                '{"id":"m2","role":"assistant","content":"beta"}',
            ]
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "bridge-state.json"
    ingestion = FakeIngestionService()
    bridge = OpenClawBridge(
        ingestion_service=ingestion,
        bridge_config=BridgeConfig(
            transcript_globs=[str(transcript)],
            source_marker="openclaw_transcript",
            source_type="chat",
            user_id=None,
            allowed_roles={"user", "assistant"},
            excluded_channels={"analysis", "tool"},
            poll_interval_seconds=30.0,
            state_path=state_path,
        ),
    )

    first = bridge.scan_once()
    second = bridge.scan_once()

    assert first.ingested_messages == 2
    assert first.scanned_messages == 2
    assert second.scanned_messages == 0
    assert len(ingestion.calls) == 2


def test_bridge_filters_roles_and_channels(tmp_path: Path) -> None:
    transcript = tmp_path / "main.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"id":"a","role":"system","content":"internal instruction"}',
                '{"id":"b","role":"assistant","channel":"commentary","content":"visible assistant text"}',
                '{"id":"c","role":"assistant","channel":"analysis","content":"hidden analysis text"}',
            ]
        ),
        encoding="utf-8",
    )
    ingestion = FakeIngestionService()
    bridge = OpenClawBridge(
        ingestion_service=ingestion,
        bridge_config=BridgeConfig(
            transcript_globs=[str(transcript)],
            source_marker="openclaw_transcript",
            source_type="chat",
            user_id=None,
            allowed_roles={"assistant"},
            excluded_channels={"analysis", "tool"},
            poll_interval_seconds=30.0,
            state_path=tmp_path / "state.json",
        ),
    )

    result = bridge.scan_once()

    assert result.scanned_messages == 2
    assert result.ingested_messages == 1
    assert result.skipped_messages == 1
    assert ingestion.calls[0].content == "visible assistant text"
    assert ingestion.calls[0].metadata["channel"] == "commentary"
    assert ingestion.calls[0].metadata["source_marker"] == "openclaw_transcript"


def test_status_commentary_classification_distinguishes_substantive_bold_text() -> None:
    commentary = TranscriptMessage(
        index=1,
        text="**Scanning transcript files**",
        role="assistant",
        timestamp=None,
        channel="commentary",
        source_ref="x",
        session_id="s",
        metadata={},
    )
    substantive = TranscriptMessage(
        index=2,
        text="I updated retrieval and added **status_commentary** filtering with tests.",
        role="assistant",
        timestamp=None,
        channel="commentary",
        source_ref="y",
        session_id="s",
        metadata={},
    )

    assert _is_status_commentary_message(commentary) is True
    assert _is_status_commentary_message(substantive) is False


def test_bridge_marks_status_commentary_flag_on_ingestion(tmp_path: Path) -> None:
    transcript = tmp_path / "main.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"id":"c1","role":"assistant","channel":"commentary","content":"**Checking migration status**"}',
                '{"id":"c2","role":"assistant","channel":"commentary","content":"I added migration 003 and retrieval exclusions."}',
            ]
        ),
        encoding="utf-8",
    )
    ingestion = FakeIngestionService()
    bridge = OpenClawBridge(
        ingestion_service=ingestion,
        bridge_config=BridgeConfig(
            transcript_globs=[str(transcript)],
            source_marker="openclaw_transcript",
            source_type="chat",
            user_id=None,
            allowed_roles={"assistant"},
            excluded_channels={"analysis", "tool"},
            poll_interval_seconds=30.0,
            state_path=tmp_path / "state.json",
        ),
    )

    result = bridge.scan_once()

    assert result.ingested_messages == 2
    assert ingestion.calls[0].status_commentary is True
    assert ingestion.calls[0].metadata["status_commentary"] is True
    assert ingestion.calls[1].status_commentary is False
