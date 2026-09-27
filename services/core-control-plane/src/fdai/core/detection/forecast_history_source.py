"""Source-neutral contracts for authoritative forecast history reads.

Each reviewed source adapter reads records that another owner already recorded and returns
them with a checkpoint. A checkpoint is positive coverage only when it is complete for the
exact subject, window, source identity, and revision. Stateful sources must also name the
initial state proven at the checkpoint start; an empty record set never implies absence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORECAST_HISTORY_KINDS = ("actions", "changes", "excluded_windows", "resource_lifecycle")
STATEFUL_FORECAST_HISTORY_KINDS = frozenset({"excluded_windows", "resource_lifecycle"})
EVENT_BASELINE_STATE = "idle"
_MAX_TEXT = 512
_STATE = re.compile(r"[a-z][a-z0-9_.:-]{0,127}\Z")
_TOKEN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")

_State = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.:-]{0,127}$")]


def bounded_limitation(tokens: set[str]) -> str | None:
    """Join limitation tokens deterministically within the coverage limitation bound."""
    text = ""
    for token in sorted(tokens):
        candidate = f"{text}+{token}" if text else token
        if len(candidate) > 118:
            return f"{text}+truncated"
        text = candidate
    return text or None


def source_limitation_tokens(limitation: str | None) -> set[str]:
    """Accept only bounded source tokens so adapter text cannot reach coverage verbatim."""
    tokens = set((limitation or "source_limitation_missing").split("+"))
    return {token if _TOKEN.fullmatch(token) else "source_limitation_invalid" for token in tokens}


def _bounded(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT:
        raise ValueError(f"forecast history source {name} MUST be bounded non-empty text")


def _aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"forecast history source {name} MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class ForecastSourceRecord:
    """One retained source record; its raw state is meaningful only through a reviewed map."""

    source_event_id: str
    source_revision: str
    source_state: str
    subject_ref: str
    effective_at: datetime
    recorded_at: datetime
    evidence_ref: str
    pending: bool = False

    def __post_init__(self) -> None:
        for name in ("source_event_id", "source_revision", "subject_ref", "evidence_ref"):
            _bounded(name, getattr(self, name))
        if _STATE.fullmatch(self.source_state) is None:
            raise ValueError("forecast history source state MUST be a bounded state token")
        _aware("effective_at", self.effective_at)
        _aware("recorded_at", self.recorded_at)
        if self.effective_at > self.recorded_at:
            raise ValueError("forecast history source record cannot be effective after recording")


@dataclass(frozen=True, slots=True)
class ForecastSourceCheckpoint:
    """Source-attested coverage; an incomplete checkpoint always names its limitation."""

    source_identity: str
    source_revision: str
    subject_ref: str
    coverage_start_at: datetime
    coverage_end_at: datetime
    known_at: datetime
    watermark: str
    evidence_ref: str
    complete: bool
    limitation: str | None = None
    initial_state: str | None = None
    initial_state_ref: str | None = None

    def __post_init__(self) -> None:
        for name in ("source_identity", "source_revision", "subject_ref", "watermark"):
            _bounded(name, getattr(self, name))
        _bounded("evidence_ref", self.evidence_ref)
        for name in ("coverage_start_at", "coverage_end_at", "known_at"):
            _aware(name, getattr(self, name))
        if not self.coverage_start_at <= self.coverage_end_at <= self.known_at:
            raise ValueError("forecast history source checkpoint times are not causally ordered")
        if self.complete == (self.limitation is not None):
            raise ValueError("forecast history source checkpoint limitation is inconsistent")
        if self.limitation is not None:
            _bounded("limitation", self.limitation)
        if (self.initial_state is None) != (self.initial_state_ref is None):
            raise ValueError("forecast history initial state requires its evidence reference")
        if self.initial_state is not None:
            if _STATE.fullmatch(self.initial_state) is None:
                raise ValueError("forecast history initial state MUST be a bounded state token")
            _bounded("initial_state_ref", self.initial_state_ref or "")


@dataclass(frozen=True, slots=True)
class ForecastSourceRead:
    """A bounded source answer; `exhausted` is false whenever a page limit stopped reading."""

    records: tuple[ForecastSourceRecord, ...]
    checkpoint: ForecastSourceCheckpoint
    exhausted: bool


class ForecastHistorySource(Protocol):
    """Read one exact subject and window as known at `known_at` without granting authority."""

    async def read(
        self,
        *,
        subject_ref: str,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
    ) -> ForecastSourceRead: ...


class ForecastHistoryProducerBinding(BaseModel):
    """Reviewed raw-to-canonical mapping for one collector binding; it proves no coverage."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["actions", "changes", "resource_lifecycle", "excluded_windows"]
    access_scope_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    target_ref: Annotated[str, Field(min_length=1, max_length=_MAX_TEXT)]
    source_scope_ref: Annotated[str, Field(min_length=1, max_length=_MAX_TEXT)]
    subject_type: Annotated[str, Field(min_length=1, max_length=128)]
    state_mapping: Annotated[dict[_State, _State], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def _reviewed_mapping(self) -> ForecastHistoryProducerBinding:
        if (
            any(value != value.strip() for value in (self.target_ref, self.source_scope_ref))
            or not self.subject_type.strip()
        ):
            raise ValueError("forecast history producer references MUST be exact text")
        if EVENT_BASELINE_STATE in self.state_mapping.values():
            raise ValueError("forecast history state mapping cannot target a reserved state")
        return self


__all__ = [
    "EVENT_BASELINE_STATE",
    "FORECAST_HISTORY_KINDS",
    "STATEFUL_FORECAST_HISTORY_KINDS",
    "ForecastHistoryProducerBinding",
    "ForecastHistorySource",
    "ForecastSourceCheckpoint",
    "ForecastSourceRead",
    "ForecastSourceRecord",
    "bounded_limitation",
    "source_limitation_tokens",
]
