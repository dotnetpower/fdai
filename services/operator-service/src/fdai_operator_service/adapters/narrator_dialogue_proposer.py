"""Small-model (T1) dialogue-state proposer for the service-local narrator.

The model proposes anchors as verbatim quotes. Deterministic code locates each quote in its cited
turn and the dialogue-state verifier accepts the proposal only when every span reproduces its value
exactly, so the model never supplies identity, offsets, or authority. A compacted range that does
not fit the bounded prompt abstains with a typed fallback instead of being truncated silently.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from fdai_service_contracts.dialogue_state import (
    MAX_ANCHOR_VALUE_CHARS,
    MAX_DIALOGUE_ANCHORS,
    DialogueAnchor,
    DialogueAnchorKind,
    DialogueStateProposal,
    DialogueTurn,
)

DIALOGUE_T1_ENV = "FDAI_NARRATOR_DIALOGUE_STATE_T1_ENABLED"
MAX_PROPOSER_PROMPT_CHARS = 24_000
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"", "0", "false", "no", "off"})
_SYSTEM_PROMPT = (
    "You extract anchors from earlier turns of an operator conversation. Return one JSON object "
    '{"anchors":[{"kind":"target|scope|time|constraint|decision|open_question",'
    '"value":"<exact verbatim text copied from the turn>","turn_id":"<id of that turn>"}]}. '
    "Copy each value character for character from the cited turn; never paraphrase, translate, "
    "infer, or add facts. Return only anchors that the turn states explicitly, and "
    '{"anchors":[]} when there are none. Output JSON only.'
)

Completion = Callable[[list[dict[str, Any]]], Awaitable[str | None]]


def dialogue_t1_enabled(values: Mapping[str, str]) -> bool:
    """Parse the opt-in flag strictly; an unrecognized value fails instead of guessing."""

    raw = values.get(DIALOGUE_T1_ENV, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ValueError(f"{DIALOGUE_T1_ENV} MUST be a boolean")


class NarratorDialogueProposer:
    """Propose anchors with one bounded completion over the compacted turns."""

    def __init__(self, complete: Completion) -> None:
        self._complete = complete

    async def propose(self, turns: Sequence[DialogueTurn]) -> DialogueStateProposal | None:
        payload = json.dumps(
            [{"turn_id": t.turn_id, "role": t.role.value, "content": t.content} for t in turns],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(payload) > MAX_PROPOSER_PROMPT_CHARS:
            return None
        answer = await self._complete(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": payload},
            ]
        )
        if answer is None:
            return None
        return _parse(answer, {turn.turn_id: turn.content for turn in turns})


def _parse(answer: str, contents: Mapping[str, str]) -> DialogueStateProposal | None:
    try:
        document = json.loads(answer)
    except (json.JSONDecodeError, RecursionError):
        return None
    rows = document.get("anchors") if isinstance(document, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_DIALOGUE_ANCHORS:
        return None
    anchors: list[DialogueAnchor] = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        kind, value, turn_id = row.get("kind"), row.get("value"), row.get("turn_id")
        if not (isinstance(value, str) and isinstance(turn_id, str) and isinstance(kind, str)):
            return None
        if not 1 <= len(value) <= MAX_ANCHOR_VALUE_CHARS:
            return None
        try:
            anchor_kind = DialogueAnchorKind(kind)
        except ValueError:
            return None
        # A quote that is absent keeps start 0, so the verifier rejects it instead of this code.
        start = max(contents.get(turn_id, "").find(value), 0)
        anchors.append(
            DialogueAnchor(
                kind=anchor_kind,
                value=value,
                turn_id=turn_id,
                start=start,
                end=start + len(value),
            )
        )
    return DialogueStateProposal(anchors=tuple(anchors))


__all__ = [
    "DIALOGUE_T1_ENV",
    "MAX_PROPOSER_PROMPT_CHARS",
    "NarratorDialogueProposer",
    "dialogue_t1_enabled",
]
