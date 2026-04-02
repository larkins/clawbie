from __future__ import annotations

import re


STANDALONE_BOLD_STATUS_RE = re.compile(r"^\*\*[^*\n]{2,120}\*\*$")
STATUS_PREFIXES = (
    "checking ",
    "scanning ",
    "reading ",
    "implementing ",
    "updating ",
    "running ",
    "applying ",
    "verifying ",
    "retrying ",
    "preparing ",
    "continuing ",
)


def is_status_commentary_text(*, text: str, role: str | None, channel: str | None) -> bool:
    normalized_role = (role or "").strip().lower()
    if normalized_role != "assistant":
        return False

    normalized = " ".join(text.split())
    if not normalized:
        return False
    if len(normalized) > 220:
        return False
    if text.count("\n") > 2:
        return False
    if "```" in text:
        return False

    if STANDALONE_BOLD_STATUS_RE.fullmatch(normalized):
        return True

    normalized_channel = (channel or "").strip().lower()
    if normalized_channel != "commentary":
        return False
    if re.search(r"\*\*.+\*\*.+", normalized):
        return False

    token_count = len(normalized.split())
    if token_count > 32:
        return False

    lowered = normalized.lower()
    if lowered.startswith(STATUS_PREFIXES):
        return True
    return lowered.startswith(("status:", "progress:", "heartbeat:"))
