"""A closed ambiguity reading when the judgment and a released form disagree.

The judgment may end ambiguous while the question-form path released one reading that the
blind review found faithful. Neither reader decides alone. A third reader of another model
family answers one closed question from the masked question only: whether it has one
plausible reading or several that would change what is read or answered. It never sees
either reading, so it cannot side with one. Only a concrete ``one`` lets the released
reading answer; ``several``, ``unclear``, no answer, or a failure keeps the clarification.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

AMBIGUITY_READINGS = ("one", "several", "unclear")


class AmbiguityReader(Protocol):
    async def check_ambiguity(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        locale: str,
    ) -> Mapping[str, Any] | None: ...


def ambiguity_schema() -> dict[str, Any]:
    """Return the closed answer the ambiguity reader must give."""

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["readings"],
        "properties": {"readings": {"type": "string", "enum": list(AMBIGUITY_READINGS)}},
    }


def ambiguity_verdict(answer: Mapping[str, Any] | None) -> str:
    """Return the reader's closed verdict, with anything unreadable as ``unavailable``."""

    if not isinstance(answer, Mapping):
        return "unavailable"
    readings = answer.get("readings")
    return readings if isinstance(readings, str) and readings in AMBIGUITY_READINGS else "invalid"


__all__ = ["AMBIGUITY_READINGS", "AmbiguityReader", "ambiguity_schema", "ambiguity_verdict"]
