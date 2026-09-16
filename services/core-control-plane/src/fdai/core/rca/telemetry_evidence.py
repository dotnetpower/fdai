"""Typed, authority-free contracts for adaptive telemetry evidence gathering."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

from ._telemetry_validation import (
    aware_datetime as _aware,
)
from ._telemetry_validation import (
    bounded_int as _bounded_int,
)
from ._telemetry_validation import (
    bounded_text as _text,
)
from ._telemetry_validation import (
    no_authority as _no_authority,
)
from ._telemetry_validation import (
    sha256_digest as _digest,
)

TELEMETRY_EVIDENCE_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
MAX_FACT_TOKENS = 64
MAX_ROUTES = 8
MAX_ROWS = 1_000
MAX_QUERY_COUNT = 8
MAX_COST_UNITS = 1_000_000
_DIGEST_PREFIX = "sha256:"


class TelemetryLookbackProfile(StrEnum):
    """Reviewed bounded windows; callers cannot supply arbitrary durations."""

    FIVE_MINUTES = "five_minutes"
    FIFTEEN_MINUTES = "fifteen_minutes"
    ONE_HOUR = "one_hour"


class TelemetryEvidenceDisposition(StrEnum):
    """Stable source outcomes that do not conflate absence with failure."""

    COMPLETE = "complete"
    COMPLETE_NO_DATA = "complete_no_data"
    PARTIAL = "partial"
    STALE = "stale"
    TRUNCATED = "truncated"
    TIMED_OUT = "timed_out"
    UNAUTHORIZED = "unauthorized"
    UNAVAILABLE = "unavailable"


class TelemetryMechanism(StrEnum):
    """Provider-neutral mechanisms covered by reviewed recipes."""

    FAILED_REQUESTS = "failed_requests"
    ERROR_TIMELINE = "error_timeline"
    DEPENDENCY_LATENCY = "dependency_latency"
    SLOW_TRACES = "slow_traces"
    GUEST_SHUTDOWN = "guest_shutdown"
    CONTAINER_RESTARTS = "container_restarts"
    THROTTLING = "throttling"
    RESOURCE_SATURATION = "resource_saturation"


class TelemetryEvidenceProvider(Protocol):
    """Gather one reviewed evidence need without exposing a raw query method."""

    async def gather(self, need: TelemetryEvidenceNeed) -> TelemetryEvidenceReceipt: ...


@dataclass(frozen=True, slots=True)
class TelemetryEvidenceRecipe:
    """One reviewed recipe descriptor without provider query text."""

    recipe_id: str
    version: str
    mechanism: TelemetryMechanism
    output_schema_digest: str
    estimated_cost_units: int
    default_lookback: TelemetryLookbackProfile
    supports_no_data_refutation: bool
    schema_version: Literal["1.0.0"] = TELEMETRY_EVIDENCE_SCHEMA_VERSION
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False
    query_execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        _text("recipe_id", self.recipe_id)
        _text("version", self.version)
        _digest("output_schema_digest", self.output_schema_digest)
        _bounded_int("estimated_cost_units", self.estimated_cost_units, 1, MAX_COST_UNITS)
        if not isinstance(self.mechanism, TelemetryMechanism):
            raise ValueError("mechanism MUST be a TelemetryMechanism")
        if not isinstance(self.default_lookback, TelemetryLookbackProfile):
            raise ValueError("default_lookback MUST be a TelemetryLookbackProfile")
        _no_authority(self)


@dataclass(frozen=True, slots=True)
class TelemetryEvidenceNeed:
    """Forseti-selected evidence need that cannot carry raw query input."""

    need_id: str
    incident_id: str
    resource_ref: str
    evidence_cutoff: datetime
    recipe_id: str
    recipe_version: str
    lookback: TelemetryLookbackProfile
    expected_output_schema_digest: str
    max_query_count: int
    max_cost_units: int
    idempotency_key: str
    schema_version: Literal["1.0.0"] = TELEMETRY_EVIDENCE_SCHEMA_VERSION
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False
    query_execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        for name in (
            "need_id",
            "incident_id",
            "resource_ref",
            "recipe_id",
            "recipe_version",
            "idempotency_key",
        ):
            _text(name, getattr(self, name))
        _aware("evidence_cutoff", self.evidence_cutoff)
        if not isinstance(self.lookback, TelemetryLookbackProfile):
            raise ValueError("lookback MUST be a TelemetryLookbackProfile")
        _digest("expected_output_schema_digest", self.expected_output_schema_digest)
        _bounded_int("max_query_count", self.max_query_count, 1, MAX_QUERY_COUNT)
        _bounded_int("max_cost_units", self.max_cost_units, 1, MAX_COST_UNITS)
        _no_authority(self)
        if self.need_id != _need_id(_need_material(self)):
            raise ValueError("telemetry evidence need id does not match content")


@dataclass(frozen=True, slots=True)
class TelemetryEvidenceReceipt:
    """Bounded, replay-stable source receipt returned instead of raw rows."""

    receipt_digest: str
    need_id: str
    recipe_id: str
    recipe_version: str
    resource_ref: str
    evidence_cutoff: datetime
    observed_until: datetime | None
    disposition: TelemetryEvidenceDisposition
    route_count: int
    queried_route_count: int
    row_count: int
    latency_ms: int
    estimated_cost_units: int
    actual_cost_units: int
    fact_tokens: tuple[str, ...]
    complete: bool
    truncated: bool
    schema_version: Literal["1.0.0"] = TELEMETRY_EVIDENCE_SCHEMA_VERSION
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False
    query_execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        _digest("receipt_digest", self.receipt_digest)
        for name in ("need_id", "recipe_id", "recipe_version", "resource_ref"):
            _text(name, getattr(self, name))
        _aware("evidence_cutoff", self.evidence_cutoff)
        if self.observed_until is not None:
            _aware("observed_until", self.observed_until)
            if self.observed_until > self.evidence_cutoff:
                raise ValueError("observed_until MUST NOT exceed evidence_cutoff")
        if not isinstance(self.disposition, TelemetryEvidenceDisposition):
            raise ValueError("disposition MUST be a TelemetryEvidenceDisposition")
        _bounded_int("route_count", self.route_count, 0, MAX_ROUTES)
        _bounded_int("queried_route_count", self.queried_route_count, 0, MAX_ROUTES)
        if self.queried_route_count > self.route_count:
            raise ValueError("queried_route_count MUST NOT exceed route_count")
        _bounded_int("row_count", self.row_count, 0, MAX_ROWS)
        _bounded_int("latency_ms", self.latency_ms, 0, 300_000)
        _bounded_int("estimated_cost_units", self.estimated_cost_units, 0, MAX_COST_UNITS)
        _bounded_int("actual_cost_units", self.actual_cost_units, 0, MAX_COST_UNITS)
        if not isinstance(self.fact_tokens, tuple) or len(self.fact_tokens) > MAX_FACT_TOKENS:
            raise ValueError("fact_tokens MUST be a bounded immutable tuple")
        for token in self.fact_tokens:
            _text("fact_token", token)
        if tuple(sorted(set(self.fact_tokens))) != self.fact_tokens:
            raise ValueError("fact_tokens MUST be sorted and unique")
        self._validate_disposition()
        _no_authority(self)
        expected = telemetry_evidence_receipt_digest(self)
        if self.receipt_digest != expected:
            raise ValueError("telemetry evidence receipt digest does not match content")

    def _validate_disposition(self) -> None:
        complete_dispositions = {
            TelemetryEvidenceDisposition.COMPLETE,
            TelemetryEvidenceDisposition.COMPLETE_NO_DATA,
        }
        if self.complete != (self.disposition in complete_dispositions):
            raise ValueError("complete MUST match the source disposition")
        if self.truncated != (self.disposition is TelemetryEvidenceDisposition.TRUNCATED):
            raise ValueError("truncated MUST match the source disposition")
        if self.disposition is TelemetryEvidenceDisposition.COMPLETE_NO_DATA:
            if self.row_count != 0 or self.fact_tokens:
                raise ValueError("complete_no_data MUST contain no rows or facts")
        elif self.disposition is TelemetryEvidenceDisposition.COMPLETE and self.row_count == 0:
            raise ValueError("complete evidence MUST contain at least one row")
        if self.complete and self.queried_route_count != self.route_count:
            raise ValueError("complete evidence MUST cover every resolved route")


def build_telemetry_evidence_need(
    *,
    incident_id: str,
    resource_ref: str,
    evidence_cutoff: datetime,
    recipe: TelemetryEvidenceRecipe,
    max_query_count: int,
    max_cost_units: int,
    idempotency_key: str,
) -> TelemetryEvidenceNeed:
    """Build one recipe-bound evidence need without accepting query text."""

    material = {
        "schema_version": TELEMETRY_EVIDENCE_SCHEMA_VERSION,
        "incident_id": incident_id,
        "resource_ref": resource_ref,
        "evidence_cutoff": _timestamp(evidence_cutoff),
        "recipe_id": recipe.recipe_id,
        "recipe_version": recipe.version,
        "lookback": recipe.default_lookback.value,
        "expected_output_schema_digest": recipe.output_schema_digest,
        "max_query_count": max_query_count,
        "max_cost_units": max_cost_units,
        "idempotency_key": idempotency_key,
    }
    need_id = _need_id(material)
    return TelemetryEvidenceNeed(
        need_id=need_id,
        incident_id=incident_id,
        resource_ref=resource_ref,
        evidence_cutoff=evidence_cutoff,
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.version,
        lookback=recipe.default_lookback,
        expected_output_schema_digest=recipe.output_schema_digest,
        max_query_count=max_query_count,
        max_cost_units=max_cost_units,
        idempotency_key=idempotency_key,
    )


def build_telemetry_evidence_receipt(
    *,
    need: TelemetryEvidenceNeed,
    observed_until: datetime | None,
    disposition: TelemetryEvidenceDisposition,
    route_count: int,
    queried_route_count: int,
    row_count: int,
    latency_ms: int,
    estimated_cost_units: int,
    actual_cost_units: int,
    fact_tokens: tuple[str, ...],
    complete: bool,
    truncated: bool,
) -> TelemetryEvidenceReceipt:
    """Build one canonical receipt bound to the exact evidence need."""

    canonical_facts = tuple(sorted(set(fact_tokens)))
    values = {
        "need_id": need.need_id,
        "recipe_id": need.recipe_id,
        "recipe_version": need.recipe_version,
        "resource_ref": need.resource_ref,
        "evidence_cutoff": need.evidence_cutoff,
        "observed_until": observed_until,
        "disposition": disposition,
        "route_count": route_count,
        "queried_route_count": queried_route_count,
        "row_count": row_count,
        "latency_ms": latency_ms,
        "estimated_cost_units": estimated_cost_units,
        "actual_cost_units": actual_cost_units,
        "fact_tokens": canonical_facts,
        "complete": complete,
        "truncated": truncated,
    }
    material = {
        "schema_version": TELEMETRY_EVIDENCE_SCHEMA_VERSION,
        "need_id": need.need_id,
        "recipe_id": need.recipe_id,
        "recipe_version": need.recipe_version,
        "resource_ref": need.resource_ref,
        "evidence_cutoff": _timestamp(need.evidence_cutoff),
        "observed_until": _timestamp(observed_until) if observed_until is not None else None,
        "disposition": disposition.value,
        "route_count": route_count,
        "queried_route_count": queried_route_count,
        "row_count": row_count,
        "latency_ms": latency_ms,
        "estimated_cost_units": estimated_cost_units,
        "actual_cost_units": actual_cost_units,
        "fact_tokens": list(canonical_facts),
        "complete": complete,
        "truncated": truncated,
    }
    return TelemetryEvidenceReceipt(
        receipt_digest=_content_digest(material),
        **values,  # type: ignore[arg-type]
    )


def telemetry_evidence_receipt_digest(receipt: TelemetryEvidenceReceipt) -> str:
    """Return the canonical digest for one telemetry evidence receipt."""

    return _content_digest(
        {
            "schema_version": receipt.schema_version,
            "need_id": receipt.need_id,
            "recipe_id": receipt.recipe_id,
            "recipe_version": receipt.recipe_version,
            "resource_ref": receipt.resource_ref,
            "evidence_cutoff": _timestamp(receipt.evidence_cutoff),
            "observed_until": (
                _timestamp(receipt.observed_until) if receipt.observed_until is not None else None
            ),
            "disposition": receipt.disposition.value,
            "route_count": receipt.route_count,
            "queried_route_count": receipt.queried_route_count,
            "row_count": receipt.row_count,
            "latency_ms": receipt.latency_ms,
            "estimated_cost_units": receipt.estimated_cost_units,
            "actual_cost_units": receipt.actual_cost_units,
            "fact_tokens": list(receipt.fact_tokens),
            "complete": receipt.complete,
            "truncated": receipt.truncated,
        }
    )


def _need_material(need: TelemetryEvidenceNeed) -> dict[str, object]:
    return {
        "schema_version": need.schema_version,
        "incident_id": need.incident_id,
        "resource_ref": need.resource_ref,
        "evidence_cutoff": _timestamp(need.evidence_cutoff),
        "recipe_id": need.recipe_id,
        "recipe_version": need.recipe_version,
        "lookback": need.lookback.value,
        "expected_output_schema_digest": need.expected_output_schema_digest,
        "max_query_count": need.max_query_count,
        "max_cost_units": need.max_cost_units,
        "idempotency_key": need.idempotency_key,
    }


def _need_id(material: object) -> str:
    return f"telemetry-need:{_content_digest(material).removeprefix(_DIGEST_PREFIX)}"


def _content_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"{_DIGEST_PREFIX}{hashlib.sha256(encoded).hexdigest()}"


def _timestamp(value: datetime) -> str:
    _aware("datetime", value)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "MAX_COST_UNITS",
    "MAX_FACT_TOKENS",
    "MAX_QUERY_COUNT",
    "MAX_ROUTES",
    "MAX_ROWS",
    "TELEMETRY_EVIDENCE_SCHEMA_VERSION",
    "TelemetryEvidenceDisposition",
    "TelemetryEvidenceNeed",
    "TelemetryEvidenceProvider",
    "TelemetryEvidenceReceipt",
    "TelemetryEvidenceRecipe",
    "TelemetryLookbackProfile",
    "TelemetryMechanism",
    "build_telemetry_evidence_need",
    "build_telemetry_evidence_receipt",
    "telemetry_evidence_receipt_digest",
]
