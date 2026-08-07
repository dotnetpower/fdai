"""Pure decoding of durable assistant-turn replay payloads."""

from __future__ import annotations

import json
from typing import Any

from fdai.shared.providers.user_context import ConversationTurnRecord

_REPLAY_PAYLOAD_KEY = "replay_payload"


def completed_replay_payload(turn: ConversationTurnRecord) -> dict[str, Any]:
    """Return a validated terminal replay payload or a bounded history fallback."""

    raw = turn.metadata.get(_REPLAY_PAYLOAD_KEY)
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and payload.get("answer") == turn.content:
            return payload
    return {
        "answer": turn.content,
        "model": str(turn.metadata.get("model") or "unknown"),
        "source": "conversation-history",
    }


__all__ = ["completed_replay_payload"]
