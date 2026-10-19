"""Durable, content-free recurrence observations owned only by Norns."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fdai_service_contracts.post_turn_review import PostTurnProcedureReceipt
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from fdai.core.learning import PostTurnReviewInput
from fdai.shared.providers.state_store import StateStore

_KEY = "pantheon/norns/recurrent-query/v1"
_WINDOW = timedelta(days=7)
_MAX_SHAPES = 128
_PREFIX = "query-shape-v1:"
_Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class _Observation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    principal_scope: _Digest
    completed_at: datetime
    review_id: Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9._:-]+$")]

    @field_validator("completed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recurrent-query completion time MUST be timezone-aware")
        return value.astimezone(UTC)


class RecurrentQuerySignal(BaseModel):
    """An immutable factual discovery input, not a proposed Rule or an approval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fingerprint: Annotated[str, Field(pattern=r"^query-shape-v1:[0-9a-f]{64}$")]
    observations: Annotated[tuple[_Observation, ...], Field(min_length=2, max_length=20)]
    procedure_receipt: PostTurnProcedureReceipt

    @field_validator("observations")
    @classmethod
    def _cohort(cls, value: tuple[_Observation, ...]) -> tuple[_Observation, ...]:
        if len({item.principal_scope for item in value}) != len(value):
            raise ValueError("recurrent-query signal MUST have distinct principals")
        times = tuple(item.completed_at for item in value)
        if min(times) <= max(times) - _WINDOW:
            raise ValueError("recurrent-query signal MUST fit within a rolling week")
        return value

    @property
    def signal_id(self) -> str:
        from fdai_service_contracts.ontology_query import content_digest

        return content_digest(self.model_dump(mode="json"))

    def candidate(self) -> dict[str, object]:
        completed = tuple(item.completed_at for item in self.observations)
        return {
            "source_signal": "console.recurrent_query",
            "proposal_kind": "new",
            "proposed_by": "Norns",
            "target_rule_id": f"console-query-{self.fingerprint.removeprefix(_PREFIX)}",
            "evidence": {
                "procedure_fingerprint": self.fingerprint,
                "distinct_principal_count": len(self.observations),
                "count_basis": "observed_threshold_cohort_not_total",
                "ontology_release_digest": self.procedure_receipt.ontology_release_digest,
                "semantic_catalog_digest": self.procedure_receipt.semantic_catalog_digest,
                "tool_names": [item.tool_name for item in self.procedure_receipt.tool_receipts],
                "window_start": (max(completed) - _WINDOW).isoformat(),
                "window_end": max(completed).isoformat(),
                "evidence_refs": sorted(
                    f"post-turn-review:{item.review_id}" for item in self.observations
                ),
            },
            "provenance": {
                "signal_id": self.signal_id,
                "observed_at": max(completed).isoformat(),
            },
        }


class _Shape(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    observations: Annotated[tuple[_Observation, ...], Field(max_length=20)] = ()
    pending: RecurrentQuerySignal | None = None
    queued: Annotated[bool, Field(strict=True)] = False

    @field_validator("observations")
    @classmethod
    def _unique(cls, value: tuple[_Observation, ...]) -> tuple[_Observation, ...]:
        if len({item.principal_scope for item in value}) != len(value):
            raise ValueError("recurrent-query observations MUST have distinct principals")
        return value


class _State(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0.0"] = "1.0.0"
    revision: Annotated[int, Field(strict=True, ge=1)]
    threshold: Annotated[int, Field(strict=True, ge=2, le=20)]
    shapes: Annotated[dict[str, _Shape], Field(max_length=_MAX_SHAPES)]

    @field_validator("shapes")
    @classmethod
    def _fingerprints(cls, value: dict[str, _Shape]) -> dict[str, _Shape]:
        for fingerprint in value:
            digest = fingerprint.removeprefix(_PREFIX)
            if not fingerprint.startswith(_PREFIX) or len(digest) != 64:
                raise ValueError("recurrent-query state fingerprint is invalid")
            if any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("recurrent-query state fingerprint is invalid")
        return value

    @model_validator(mode="after")
    def _cohorts(self) -> _State:
        for fingerprint, shape in self.shapes.items():
            if shape.pending is None and len(shape.observations) >= self.threshold:
                raise ValueError("recurrent-query threshold cohort requires a pending signal")
            if shape.queued and shape.pending is None:
                raise ValueError("recurrent-query queued state requires its immutable signal")
            if shape.pending is not None and (
                shape.pending.fingerprint != fingerprint
                or shape.pending.observations != shape.observations
                or len(shape.observations) != self.threshold
                or shape.pending.procedure_receipt.procedure_fingerprint != fingerprint
                or shape.pending.procedure_receipt.principal_scope
                not in {item.principal_scope for item in shape.observations}
            ):
                raise ValueError("recurrent-query signal MUST match its distinct-principal cohort")
        return self


class RecurrentQueryTracker:
    """Count distinct principals in (now - seven days, now] using one bounded CAS record."""

    def __init__(
        self, *, store: StateStore, now: Callable[[], datetime], threshold: int = 5
    ) -> None:
        if type(threshold) is not int or not 2 <= threshold <= 20:
            raise ValueError("recurrent-query threshold MUST be an integer from 2 through 20")
        self._store, self._now, self._threshold = store, now, threshold

    async def observe(self, review: PostTurnReviewInput) -> tuple[RecurrentQuerySignal | None, str]:
        fingerprint = review.procedure_fingerprint
        if (
            fingerprint is None
            or not fingerprint.startswith(_PREFIX)
            or review.procedure_receipt is None
        ):
            return None, "source_absent"
        now = self._clock()
        try:
            observation = _Observation(
                principal_scope=review.principal_scope,
                completed_at=review.completed_at,
                review_id=review.review_id,
            )
        except ValidationError:
            raise ValueError("recurrent-query observation binding is invalid") from None
        if observation.completed_at > now:
            return None, "future_observation"
        if observation.completed_at <= now - _WINDOW:
            return None, "expired_observation"
        for _attempt in range(16):
            state = await self._read()
            shapes = (
                {
                    key: value
                    for key, value in state.shapes.items()
                    if any(item.completed_at > now - _WINDOW for item in value.observations)
                }
                if state is not None
                else {}
            )
            shape = shapes.get(fingerprint, _Shape())
            if any(item.completed_at > now for item in shape.observations):
                raise ValueError("recurrent-query clock precedes the retained cohort")
            if shape.pending is not None and not shape.queued:
                return shape.pending, "pending"
            if shape.queued:
                return None, "already_queued"
            retained = {
                item.principal_scope: item
                for item in shape.observations
                if now - _WINDOW < item.completed_at <= now
            }
            previous = retained.get(observation.principal_scope)
            if previous is None or previous.completed_at < observation.completed_at:
                retained[observation.principal_scope] = observation
            observations = tuple(sorted(retained.values(), key=lambda item: item.principal_scope))
            signal = (
                RecurrentQuerySignal(
                    fingerprint=fingerprint,
                    observations=observations,
                    procedure_receipt=review.procedure_receipt,
                )
                if len(observations) >= self._threshold
                else None
            )
            if fingerprint not in shapes and len(shapes) >= _MAX_SHAPES:
                raise RuntimeError("recurrent-query source capacity exhausted")
            shapes[fingerprint] = _Shape(observations=observations, pending=signal)
            if await self._save(state, shapes):
                return signal, "threshold_met" if signal is not None else "observed"
        raise RuntimeError("recurrent-query observation contention budget exhausted")

    async def mark_queued(self, signal: RecurrentQuerySignal) -> None:
        for _attempt in range(16):
            state = await self._read()
            if state is None:
                raise RuntimeError("recurrent-query pending state disappeared")
            shape = state.shapes.get(signal.fingerprint)
            if shape is None or shape.pending != signal:
                raise RuntimeError("recurrent-query pending signal changed")
            if shape.queued:
                return
            shapes = dict(state.shapes)
            shapes[signal.fingerprint] = shape.model_copy(update={"queued": True})
            if await self._save(state, shapes):
                return
        raise RuntimeError("recurrent-query completion contention budget exhausted")

    async def _read(self) -> _State | None:
        raw = await self._store.read_state(_KEY)
        if raw is None:
            return None
        try:
            state = _State.model_validate(raw)
        except ValidationError:
            raise ValueError("recurrent-query persisted state is invalid") from None
        if state.threshold != self._threshold:
            raise ValueError("recurrent-query persisted threshold differs from runtime binding")
        return state

    async def _save(self, state: _State | None, shapes: dict[str, _Shape]) -> bool:
        updated = _State(
            revision=1 if state is None else state.revision + 1,
            threshold=self._threshold,
            shapes=shapes,
        ).model_dump(mode="json")
        if state is None:
            return await self._store.write_state_if_absent(_KEY, updated)
        return await self._store.compare_and_set_state(
            _KEY, updated, expected_revision=state.revision
        )

    def _clock(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recurrent-query clock MUST be timezone-aware")
        return value.astimezone(UTC)
