"""Content-free trace receipts for Pantheon conversation diagnostics."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_T2_STATUSES = frozenset(
    {
        "not_required",
        "completed",
        "unavailable",
        "budget_denied",
        "error",
        "abstained",
        "output_too_large",
        "sensitive_output",
    }
)


@dataclass(frozen=True, slots=True)
class ParticipantPromptReceipt:
    """Identify one participant and effective prompt without retaining prompt text."""

    agent: str
    prompt_version: str
    prompt_sha256: str
    situation: str

    def __post_init__(self) -> None:
        _require_token(self.agent, "participant agent")
        _require_token(self.prompt_version, "participant prompt version")
        _require_digest(self.prompt_sha256, "participant prompt")
        if not self.situation or len(self.situation) > 512:
            raise ValueError("participant prompt situation MUST be bounded")


@dataclass(frozen=True, slots=True)
class ConversationTurnTraceReceipt:
    """Bind one completed turn to routing, evidence, T1/T2, and timing evidence."""

    campaign_id: str
    case_id: str
    source_revision: str
    source_content_digest: str
    turn_digest: str
    session_digest: str
    correlation_digest: str
    locale: str
    expected_primary_agent: str
    actual_primary_agent: str | None
    routing_method: str
    semantic_score: float | None
    semantic_margin: float | None
    contributors: tuple[str, ...]
    handoff_owner: str | None
    participants: tuple[ParticipantPromptReceipt, ...]
    tool_ids: tuple[str, ...]
    evidence_ref_digests: tuple[str, ...]
    evidence_manifest_digest: str
    answer_digest: str
    verification_status: str
    verification_authority: str
    t1_reason: str
    t1_signal_count: int
    t1_conflict_count: int
    t1_conclusion_preserved: bool
    t2_required: bool
    t2_attempted: bool
    t2_status: str
    t2_model_family: str | None
    budget_reserved: bool
    metering_receipt_digest: str | None
    latency_ms: int
    latency_budget_ms: int
    terminal_status: str
    hard_zero_violations: tuple[str, ...] = ()
    execution_authority: bool = False

    def __post_init__(self) -> None:
        for value, label in (
            (self.campaign_id, "campaign_id"),
            (self.case_id, "case_id"),
            (self.expected_primary_agent, "expected_primary_agent"),
            (self.routing_method, "routing_method"),
            (self.verification_status, "verification_status"),
            (self.verification_authority, "verification_authority"),
            (self.t1_reason, "t1_reason"),
            (self.terminal_status, "terminal_status"),
        ):
            _require_token(value, label)
        if self.actual_primary_agent is not None:
            _require_token(self.actual_primary_agent, "actual_primary_agent")
        if self.handoff_owner is not None:
            _require_token(self.handoff_owner, "handoff_owner")
        if self.t2_model_family is not None:
            _require_token(self.t2_model_family, "t2_model_family")
        if self.locale not in {"en", "ko"}:
            raise ValueError("trace locale MUST be en or ko")
        if not re.fullmatch(r"[0-9a-f]{40}", self.source_revision):
            raise ValueError("trace source_revision MUST be a Git SHA-1")
        for value, label in (
            (self.turn_digest, "turn"),
            (self.session_digest, "session"),
            (self.correlation_digest, "correlation"),
            (self.source_content_digest, "source content"),
            (self.evidence_manifest_digest, "evidence manifest"),
            (self.answer_digest, "answer"),
        ):
            _require_digest(value, label)
        if self.metering_receipt_digest is not None:
            _require_digest(self.metering_receipt_digest, "metering receipt")
        if len(self.participants) > 3 or len(self.contributors) > 2:
            raise ValueError("trace participant and contributor counts MUST be bounded")
        if len({item.agent for item in self.participants}) != len(self.participants):
            raise ValueError("trace participant agents MUST be unique")
        for values, label, limit in (
            (self.contributors, "contributors", 2),
            (self.tool_ids, "tool ids", 16),
            (self.evidence_ref_digests, "evidence refs", 64),
            (self.hard_zero_violations, "hard-zero violations", 16),
        ):
            if len(values) > limit or len(set(values)) != len(values):
                raise ValueError(f"trace {label} MUST be bounded and unique")
        if any(_TOKEN.fullmatch(value) is None for value in (*self.contributors, *self.tool_ids)):
            raise ValueError("trace contributors and tool ids MUST be portable tokens")
        if any(_DIGEST.fullmatch(value) is None for value in self.evidence_ref_digests):
            raise ValueError("trace evidence refs MUST contain SHA-256 digests")
        if any(_TOKEN.fullmatch(value) is None for value in self.hard_zero_violations):
            raise ValueError("trace hard-zero violations MUST be portable tokens")
        if any(value < 0 for value in (self.t1_signal_count, self.t1_conflict_count)):
            raise ValueError("trace T1 counters MUST be non-negative")
        if self.t1_conflict_count > self.t1_signal_count:
            raise ValueError("trace conflict count cannot exceed signal count")
        if self.t2_status not in _T2_STATUSES:
            raise ValueError("trace T2 status is unsupported")
        if self.t2_attempted and not self.budget_reserved:
            raise ValueError("attempted T2 synthesis requires a budget reservation")
        if not self.t2_attempted and self.t2_status not in {
            "not_required",
            "unavailable",
            "budget_denied",
        }:
            raise ValueError("unattempted T2 status is inconsistent")
        if self.latency_ms < 0 or self.latency_budget_ms <= 0:
            raise ValueError("trace latency values are inconsistent")
        for semantic_value in (self.semantic_score, self.semantic_margin):
            if semantic_value is not None and (
                not math.isfinite(semantic_value) or semantic_value < 0
            ):
                raise ValueError("trace semantic values MUST be finite and non-negative")
        if self.execution_authority:
            raise ValueError("conversation trace receipts MUST NOT carry execution authority")

    @property
    def receipt_digest(self) -> str:
        """Return a stable digest over the complete content-free receipt."""

        return hashlib.sha256(_canonical(self.to_dict(include_digest=False))).hexdigest()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> ConversationTurnTraceReceipt:
        """Reconstruct and validate one JSON-decoded trace receipt."""

        participants_raw = raw.get("participants")
        if not isinstance(participants_raw, list | tuple):
            raise ValueError("trace participants MUST be an array")
        participants = tuple(
            ParticipantPromptReceipt(
                agent=str(_required(item, "agent")),
                prompt_version=str(_required(item, "prompt_version")),
                prompt_sha256=str(_required(item, "prompt_sha256")),
                situation=str(_required(item, "situation")),
            )
            for item in participants_raw
            if isinstance(item, Mapping)
        )
        if len(participants) != len(participants_raw):
            raise ValueError("trace participants MUST contain objects")
        return cls(
            campaign_id=_required_str(raw, "campaign_id"),
            case_id=_required_str(raw, "case_id"),
            source_revision=_required_str(raw, "source_revision"),
            source_content_digest=_required_str(raw, "source_content_digest"),
            turn_digest=_required_str(raw, "turn_digest"),
            session_digest=_required_str(raw, "session_digest"),
            correlation_digest=_required_str(raw, "correlation_digest"),
            locale=_required_str(raw, "locale"),
            expected_primary_agent=_required_str(raw, "expected_primary_agent"),
            actual_primary_agent=_optional_str(raw, "actual_primary_agent"),
            routing_method=_required_str(raw, "routing_method"),
            semantic_score=_optional_float(raw, "semantic_score"),
            semantic_margin=_optional_float(raw, "semantic_margin"),
            participants=participants,
            contributors=_string_tuple(raw, "contributors"),
            handoff_owner=_optional_str(raw, "handoff_owner"),
            tool_ids=_string_tuple(raw, "tool_ids"),
            evidence_ref_digests=_string_tuple(raw, "evidence_ref_digests"),
            evidence_manifest_digest=_required_str(raw, "evidence_manifest_digest"),
            answer_digest=_required_str(raw, "answer_digest"),
            verification_status=_required_str(raw, "verification_status"),
            verification_authority=_required_str(raw, "verification_authority"),
            t1_reason=_required_str(raw, "t1_reason"),
            t1_signal_count=_required_int(raw, "t1_signal_count"),
            t1_conflict_count=_required_int(raw, "t1_conflict_count"),
            t1_conclusion_preserved=_required_bool(raw, "t1_conclusion_preserved"),
            t2_required=_required_bool(raw, "t2_required"),
            t2_attempted=_required_bool(raw, "t2_attempted"),
            t2_status=_required_str(raw, "t2_status"),
            t2_model_family=_optional_str(raw, "t2_model_family"),
            budget_reserved=_required_bool(raw, "budget_reserved"),
            metering_receipt_digest=_optional_str(raw, "metering_receipt_digest"),
            latency_ms=_required_int(raw, "latency_ms"),
            latency_budget_ms=_required_int(raw, "latency_budget_ms"),
            terminal_status=_required_str(raw, "terminal_status"),
            hard_zero_violations=_string_tuple(raw, "hard_zero_violations"),
            execution_authority=_required_bool(raw, "execution_authority"),
        )

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        """Serialize the receipt without raw prompts, questions, answers, or resource ids."""

        payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "evidence_kind": "pantheon_conversation_turn_trace",
            **asdict(self),
        }
        if include_digest:
            payload["receipt_digest"] = self.receipt_digest
        return payload


def content_digest(value: str) -> str:
    """Commit bounded private content without retaining it in a trace."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _require_digest(value: str, label: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{label} digest MUST be lowercase SHA-256")


def _require_token(value: str, label: str) -> None:
    if _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{label} MUST be a bounded portable token")


def _required(value: Mapping[str, object], key: str) -> object:
    if key not in value:
        raise ValueError(f"trace participant is missing {key}")
    return value[key]


def _required_str(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise ValueError(f"trace {key} MUST be a string")
    return value


def _optional_str(raw: Mapping[str, object], key: str) -> str | None:
    value = raw.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"trace {key} MUST be a string or null")
    return value


def _optional_float(raw: Mapping[str, object], key: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"trace {key} MUST be numeric or null")
    return float(value)


def _required_int(raw: Mapping[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"trace {key} MUST be an integer")
    return value


def _required_bool(raw: Mapping[str, object], key: str) -> bool:
    value = raw.get(key)
    if type(value) is not bool:
        raise ValueError(f"trace {key} MUST be boolean")
    return value


def _string_tuple(raw: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = raw.get(key, ())
    if not isinstance(value, list | tuple) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"trace {key} MUST be a string array")
    return tuple(value)


__all__ = [
    "ConversationTurnTraceReceipt",
    "ParticipantPromptReceipt",
    "content_digest",
]
