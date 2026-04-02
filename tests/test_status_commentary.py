from __future__ import annotations

from memory_engine.openclaw_bridge import TranscriptMessage, _is_status_commentary_message
from memory_engine.status_commentary import is_status_commentary_text


def test_status_commentary_helper_matches_bridge_behavior() -> None:
    message = TranscriptMessage(
        index=1,
        text="**Checking migration status**",
        role="assistant",
        timestamp=None,
        channel="commentary",
        source_ref="x",
        session_id="s",
        metadata={},
    )
    helper_result = is_status_commentary_text(
        text=message.text,
        role=message.role,
        channel=message.channel,
    )
    bridge_result = _is_status_commentary_message(message)
    assert helper_result is True
    assert bridge_result == helper_result


def test_status_commentary_helper_rejects_substantive_commentary() -> None:
    assert (
        is_status_commentary_text(
            text="I updated retrieval and added **status_commentary** filtering with tests.",
            role="assistant",
            channel="commentary",
        )
        is False
    )
