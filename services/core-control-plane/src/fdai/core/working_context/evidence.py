"""Persisted evidence records for context-selection shadow comparisons."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from fdai.core.working_context.types import ContextManifest
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "context-selection:evaluation:"


@dataclass(frozen=True, slots=True)
class ContextSelectionEvaluation:
    evaluation_id: str
    input_fingerprint: str
    baseline_policy_ref: str
    candidate_policy_ref: str
    baseline_manifest: ContextManifest
    candidate_manifest: ContextManifest | None
    baseline_tokens: int
    candidate_tokens: int | None
    evidence_overlap: float | None
    omissions: tuple[str, ...]
    pinned_preserved: bool
    relevance: float | None
    answer_quality_ref: str | None
    answer_quality_score: float | None
    latency_ms: float
    failure_reason: str | None
    created_at: datetime


@runtime_checkable
class ContextSelectionEvaluationStore(Protocol):
    async def append(self, evaluation: ContextSelectionEvaluation) -> None: ...

    async def list(self, *, limit: int) -> tuple[ContextSelectionEvaluation, ...]: ...


class InMemoryContextSelectionEvaluationStore:
    """Concurrency-safe test and local store with append-only ids."""

    def __init__(self) -> None:
        self._records: dict[str, ContextSelectionEvaluation] = {}
        self._lock = asyncio.Lock()

    async def append(self, evaluation: ContextSelectionEvaluation) -> None:
        async with self._lock:
            if evaluation.evaluation_id in self._records:
                raise ValueError(f"duplicate evaluation id {evaluation.evaluation_id!r}")
            self._records[evaluation.evaluation_id] = evaluation

    async def list(self, *, limit: int) -> tuple[ContextSelectionEvaluation, ...]:
        if limit < 1:
            raise ValueError("evaluation limit MUST be >= 1")
        async with self._lock:
            records = sorted(
                self._records.values(),
                key=lambda item: (item.created_at, item.evaluation_id),
                reverse=True,
            )
            return tuple(records[:limit])


class StateStoreContextSelectionEvaluationStore:
    """Durable adapter over the existing tracked-state store."""

    def __init__(self, state_store: StateStore) -> None:
        self._state_store = state_store

    async def append(self, evaluation: ContextSelectionEvaluation) -> None:
        created = await self._state_store.write_state_if_absent(
            f"{_STATE_PREFIX}{evaluation.evaluation_id}",
            _encode(evaluation),
        )
        if not created:
            raise ValueError(f"duplicate evaluation id {evaluation.evaluation_id!r}")

    async def list(self, *, limit: int) -> tuple[ContextSelectionEvaluation, ...]:
        if limit < 1:
            raise ValueError("evaluation limit MUST be >= 1")
        rows = await self._state_store.read_states(_STATE_PREFIX, limit=limit)
        return tuple(_decode(row) for row in rows)


def _encode(evaluation: ContextSelectionEvaluation) -> dict[str, Any]:
    payload = asdict(evaluation)
    payload["created_at"] = evaluation.created_at.isoformat()
    return payload


def _decode(payload: Mapping[str, Any]) -> ContextSelectionEvaluation:
    try:
        baseline = _manifest(payload["baseline_manifest"])
        candidate_raw = payload.get("candidate_manifest")
        candidate = _manifest(candidate_raw) if isinstance(candidate_raw, Mapping) else None
        return ContextSelectionEvaluation(
            evaluation_id=str(payload["evaluation_id"]),
            input_fingerprint=str(payload["input_fingerprint"]),
            baseline_policy_ref=str(payload["baseline_policy_ref"]),
            candidate_policy_ref=str(payload["candidate_policy_ref"]),
            baseline_manifest=baseline,
            candidate_manifest=candidate,
            baseline_tokens=int(payload["baseline_tokens"]),
            candidate_tokens=_optional_int(payload.get("candidate_tokens")),
            evidence_overlap=_optional_float(payload.get("evidence_overlap")),
            omissions=tuple(str(item) for item in payload.get("omissions", ())),
            pinned_preserved=bool(payload["pinned_preserved"]),
            relevance=_optional_float(payload.get("relevance")),
            answer_quality_ref=_optional_str(payload.get("answer_quality_ref")),
            answer_quality_score=_optional_float(payload.get("answer_quality_score")),
            latency_ms=float(payload["latency_ms"]),
            failure_reason=_optional_str(payload.get("failure_reason")),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("stored context-selection evaluation is incomplete") from exc


def _manifest(value: object) -> ContextManifest:
    if not isinstance(value, Mapping):
        raise ValueError("context manifest MUST be an object")
    return ContextManifest(
        verbatim_ids=tuple(str(item) for item in value["verbatim_ids"]),
        summary_ids=tuple(str(item) for item in value["summary_ids"]),
        retrieved_ids=tuple(str(item) for item in value["retrieved_ids"]),
        pinned_ids=tuple(str(item) for item in value["pinned_ids"]),
        typed_fact_ids=tuple(str(item) for item in value["typed_fact_ids"]),
        verbatim_tokens=int(value["verbatim_tokens"]),
        summary_tokens=int(value["summary_tokens"]),
        retrieved_tokens=int(value["retrieved_tokens"]),
        pinned_tokens=int(value["pinned_tokens"]),
        typed_fact_tokens=int(value["typed_fact_tokens"]),
        dropped_ids=tuple(str(item) for item in value["dropped_ids"]),
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("optional integer value is invalid")
    return value


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("optional numeric value is invalid")
    return float(value)


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


__all__ = [
    "ContextSelectionEvaluation",
    "ContextSelectionEvaluationStore",
    "InMemoryContextSelectionEvaluationStore",
    "StateStoreContextSelectionEvaluationStore",
]
