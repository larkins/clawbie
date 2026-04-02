from __future__ import annotations

from scripts.backfill_status_commentary import _row_is_status_commentary


def test_backfill_classifier_uses_role_and_channel_metadata() -> None:
    assert (
        _row_is_status_commentary(
            content="**Scanning transcript files**",
            metadata={"role": "assistant", "channel": "commentary"},
        )
        is True
    )
    assert (
        _row_is_status_commentary(
            content="**Scanning transcript files**",
            metadata={"role": "user", "channel": "commentary"},
        )
        is False
    )
    assert (
        _row_is_status_commentary(
            content="Running repair job for missing vectors",
            metadata={"role": "assistant", "channel": "commentary"},
        )
        is True
    )
