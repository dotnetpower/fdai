"""Typed, no-authority dialogue state that accounts for every compacted conversation turn.

Older turns of a long conversation are compacted into a ``DialogueState`` instead of being
dropped. The state is context only: it grants no authority and never replaces current evidence.

Deterministic code never infers meaning from text. The T0 state carries exact accounting (turn ids
and a digest of the compacted range). A small model (T1) MAY propose anchors, each a kind and a
value cited by an exact source span; deterministic code accepts a proposal only when every span
reproduces its value verbatim. An abstaining, failing, absent, or rejected proposer leaves the T0
state with a typed fallback reason. T2 is never used.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
BoundedId = Annotated[str, Field(min_length=1, max_length=256)]
MAX_DIALOGUE_ANCHORS = 64
MAX_ANCHOR_VALUE_CHARS = 512
DIALOGUE_VERBATIM_WINDOW = 8
"""Prior turns the adaptive conversation path carries verbatim; older turns are compacted."""

DialogueFallbackReason = Literal[
    "t1_unconfigured",
    "t1_abstained",
    "t1_failed",
    "t1_rejected_unverified_anchor",
]


class DialogueRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class DialogueAnchorKind(StrEnum):
    TARGET = "target"
    SCOPE = "scope"
    TIME = "time"
    CONSTRAINT = "constraint"
    DECISION = "decision"
    OPEN_QUESTION = "open_question"


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class DialogueTurn(_Contract):
    """One conversation turn offered for compaction."""

    turn_id: BoundedId
    role: DialogueRole
    content: Annotated[str, Field(min_length=1)]


class DialogueAnchor(_Contract):
    """One proposed fact, cited by the exact span that reproduces it."""

    kind: DialogueAnchorKind
    value: Annotated[str, Field(min_length=1, max_length=MAX_ANCHOR_VALUE_CHARS)]
    turn_id: BoundedId
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def _span_is_ordered(self) -> DialogueAnchor:
        if self.end <= self.start:
            raise ValueError("dialogue anchor span MUST be non-empty")
        return self


class DialogueStateProposal(_Contract):
    """Untrusted T1 output; it has no effect until deterministic verification accepts it."""

    anchors: Annotated[tuple[DialogueAnchor, ...], Field(max_length=MAX_DIALOGUE_ANCHORS)]


class DialogueState(_Contract):
    """Exact accounting of a compacted turn range plus its verified anchors."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    tier: Literal["T0", "T1"]
    source_turn_count: Annotated[int, Field(ge=0)]
    compacted_turn_ids: tuple[BoundedId, ...]
    kept_turn_ids: tuple[BoundedId, ...]
    compacted_digest: Digest | None
    anchors: Annotated[tuple[DialogueAnchor, ...], Field(max_length=MAX_DIALOGUE_ANCHORS)] = ()
    fallback_reason: DialogueFallbackReason | None = None
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _accounting_is_exact(self) -> DialogueState:
        total = len(self.compacted_turn_ids) + len(self.kept_turn_ids)
        if total != self.source_turn_count:
            raise ValueError("dialogue state MUST account for every source turn exactly once")
        if len({*self.compacted_turn_ids, *self.kept_turn_ids}) != total:
            raise ValueError("dialogue state turn ids MUST be unique")
        if (self.compacted_digest is None) != (not self.compacted_turn_ids):
            raise ValueError("a compacted range MUST carry exactly one digest")
        if self.tier == "T0" and self.anchors:
            raise ValueError("T0 dialogue state MUST NOT carry model-proposed anchors")
        if self.tier == "T1" and self.fallback_reason is not None:
            raise ValueError("T1 dialogue state MUST NOT record a fallback")
        compacted = set(self.compacted_turn_ids)
        if any(anchor.turn_id not in compacted for anchor in self.anchors):
            raise ValueError("dialogue anchors MUST cite only compacted turns")
        return self


class DialogueStateProposer(Protocol):
    """Small-model (T1) seam. Implementations MUST NOT call a T2 model."""

    async def propose(self, turns: Sequence[DialogueTurn]) -> DialogueStateProposal | None:
        """Return a proposal over the turns being compacted, or ``None`` to abstain."""
        ...


def compacted_range_digest(turns: Sequence[DialogueTurn]) -> str:
    """Digest ids, roles, and content digests so the range can be replayed and verified."""

    rows = [
        [turn.turn_id, turn.role.value, hashlib.sha256(turn.content.encode("utf-8")).hexdigest()]
        for turn in turns
    ]
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def verify_dialogue_proposal(
    turns: Sequence[DialogueTurn], proposal: DialogueStateProposal
) -> DialogueFallbackReason | None:
    """Return a rejection reason unless every anchor span reproduces its value verbatim."""

    by_id = {turn.turn_id: turn.content for turn in turns}
    for anchor in proposal.anchors:
        content = by_id.get(anchor.turn_id)
        if (
            content is None
            or anchor.end > len(content)
            or content[anchor.start : anchor.end] != (anchor.value)
        ):
            return "t1_rejected_unverified_anchor"
    return None


def compact_dialogue(
    turns: Sequence[DialogueTurn],
    *,
    keep_recent: int,
    proposal: DialogueStateProposal | None = None,
    fallback_reason: DialogueFallbackReason | None = None,
) -> DialogueState:
    """Compact all but the newest ``keep_recent`` turns without dropping any silently."""

    if keep_recent < 0:
        raise ValueError("keep_recent MUST be non-negative")
    split = max(len(turns) - keep_recent, 0)
    compacted, kept = turns[:split], turns[split:]
    accepted = proposal if proposal is not None and compacted else None
    if accepted is not None:
        rejection = verify_dialogue_proposal(compacted, accepted)
        if rejection is not None:
            accepted, fallback_reason = None, rejection
    if not compacted:
        fallback_reason = None
    return DialogueState(
        tier="T1" if accepted is not None else "T0",
        source_turn_count=len(turns),
        compacted_turn_ids=tuple(turn.turn_id for turn in compacted),
        kept_turn_ids=tuple(turn.turn_id for turn in kept),
        compacted_digest=compacted_range_digest(compacted) if compacted else None,
        anchors=accepted.anchors if accepted is not None else (),
        fallback_reason=None if accepted is not None else fallback_reason,
    )


async def build_dialogue_state(
    turns: Sequence[DialogueTurn],
    *,
    keep_recent: int,
    proposer: DialogueStateProposer | None = None,
) -> DialogueState:
    """Build the state, asking the optional T1 proposer only about the compacted range."""

    split = max(len(turns) - max(keep_recent, 0), 0)
    if split == 0:
        return compact_dialogue(turns, keep_recent=keep_recent)
    if proposer is None:
        return compact_dialogue(turns, keep_recent=keep_recent, fallback_reason="t1_unconfigured")
    try:
        proposal = await proposer.propose(turns[:split])
    except Exception:  # noqa: BLE001 - a failing proposer degrades to the typed T0 fallback
        return compact_dialogue(turns, keep_recent=keep_recent, fallback_reason="t1_failed")
    if proposal is None:
        return compact_dialogue(turns, keep_recent=keep_recent, fallback_reason="t1_abstained")
    return compact_dialogue(turns, keep_recent=keep_recent, proposal=proposal)


__all__ = [
    "DIALOGUE_VERBATIM_WINDOW",
    "MAX_ANCHOR_VALUE_CHARS",
    "MAX_DIALOGUE_ANCHORS",
    "DialogueAnchor",
    "DialogueAnchorKind",
    "DialogueFallbackReason",
    "DialogueRole",
    "DialogueState",
    "DialogueStateProposal",
    "DialogueStateProposer",
    "DialogueTurn",
    "build_dialogue_state",
    "compact_dialogue",
    "compacted_range_digest",
    "verify_dialogue_proposal",
]
