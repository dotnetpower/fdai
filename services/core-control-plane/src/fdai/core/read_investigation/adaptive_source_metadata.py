"""Typed source metadata extension for adaptive investigation executions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class AdaptiveObservationSourceMetadata:
    """Bounded source disposition projected without query text or raw rows."""

    source_kind: Literal["telemetry_recipe"]
    receipt_digest: str
    recipe_id: str
    recipe_version: str
    disposition: str
    observed_until: datetime | None
    route_count: int
    queried_route_count: int
    row_count: int
    latency_ms: int
    complete: bool
    truncated: bool

    def __post_init__(self) -> None:
        if self.source_kind != "telemetry_recipe":
            raise ValueError("adaptive observation source kind is unsupported")
        _digest("receipt_digest", self.receipt_digest)
        _text("recipe_id", self.recipe_id)
        _text("recipe_version", self.recipe_version)
        if self.disposition not in {
            "complete",
            "complete_no_data",
            "partial",
            "stale",
            "truncated",
            "timed_out",
            "unauthorized",
            "unavailable",
        }:
            raise ValueError("adaptive observation source disposition is unsupported")
        if self.observed_until is not None:
            _aware("observed_until", self.observed_until)
        for name, value, maximum in (
            ("route_count", self.route_count, 8),
            ("queried_route_count", self.queried_route_count, 8),
            ("row_count", self.row_count, 1000),
            ("latency_ms", self.latency_ms, 300_000),
        ):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError(f"{name} is outside the adaptive source metadata bound")
        if self.queried_route_count > self.route_count:
            raise ValueError("adaptive source queried routes exceed resolved routes")
        if self.complete != (self.disposition in {"complete", "complete_no_data"}):
            raise ValueError("adaptive source completeness conflicts with disposition")
        if self.truncated != (self.disposition == "truncated"):
            raise ValueError("adaptive source truncation conflicts with disposition")


class AdaptiveExecutionMaterial(Protocol):
    @property
    def round_index(self) -> int: ...

    @property
    def frame_digest(self) -> str: ...

    @property
    def selection_digest(self) -> str: ...

    @property
    def candidate_digest(self) -> str: ...

    @property
    def binding_digest(self) -> str: ...

    @property
    def verification_receipt_digest(self) -> str: ...

    @property
    def plan_digest(self) -> str: ...

    @property
    def result_digest(self) -> str: ...

    @property
    def query_status(self) -> str: ...

    @property
    def evidence_refs(self) -> tuple[str, ...]: ...

    @property
    def reserved_cost_units(self) -> int: ...

    @property
    def actual_cost_units(self) -> int | None: ...

    @property
    def source_metadata(self) -> AdaptiveObservationSourceMetadata | None: ...


def execution_actual_cost_units(
    results: Mapping[str, object],
    *,
    reserved_cost_units: int,
) -> int | None:
    """Extract one bounded actual-cost total from typed query results."""

    values: list[int] = []
    for result in results.values():
        value = getattr(result, "value", None)
        if not isinstance(value, Mapping) or "actual_cost_units" not in value:
            continue
        cost = value["actual_cost_units"]
        if type(cost) is not int or cost < 0:
            raise ValueError("adaptive query returned an invalid actual cost")
        values.append(cost)
    if not values:
        return None
    actual = sum(values)
    if actual > reserved_cost_units:
        raise ValueError("adaptive query exceeded its reserved cost")
    return actual


def execution_source_metadata(
    results: Mapping[str, object],
) -> AdaptiveObservationSourceMetadata | None:
    """Extract one typed source receipt projection from query results."""

    candidates: list[Mapping[str, object]] = []
    for result in results.values():
        value = getattr(result, "value", None)
        if (
            isinstance(value, Mapping)
            and value.get("schema_version") == "1.0.0"
            and {"receipt_digest", "recipe_id", "disposition"} <= set(value)
        ):
            candidates.append(value)
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("adaptive query returned multiple source metadata records")
    value = candidates[0]
    observed_raw = value.get("observed_until")
    observed_until = None
    if observed_raw is not None:
        if not isinstance(observed_raw, str):
            raise ValueError("adaptive source observed_until is invalid")
        observed_until = datetime.fromisoformat(observed_raw.replace("Z", "+00:00"))
    return AdaptiveObservationSourceMetadata(
        source_kind="telemetry_recipe",
        receipt_digest=value.get("receipt_digest"),  # type: ignore[arg-type]
        recipe_id=value.get("recipe_id"),  # type: ignore[arg-type]
        recipe_version=value.get("recipe_version"),  # type: ignore[arg-type]
        disposition=value.get("disposition"),  # type: ignore[arg-type]
        observed_until=observed_until,
        route_count=value.get("route_count"),  # type: ignore[arg-type]
        queried_route_count=value.get("queried_route_count"),  # type: ignore[arg-type]
        row_count=value.get("row_count"),  # type: ignore[arg-type]
        latency_ms=value.get("latency_ms"),  # type: ignore[arg-type]
        complete=value.get("complete"),  # type: ignore[arg-type]
        truncated=value.get("truncated"),  # type: ignore[arg-type]
    )


def validate_source_metadata_lineage(
    execution: AdaptiveExecutionMaterial,
    frame_cutoff: datetime,
) -> None:
    """Bind source metadata to one receipt reference and frame cutoff."""

    metadata = execution.source_metadata
    if metadata is None:
        return
    expected_receipt_ref = f"telemetry-receipt:{metadata.receipt_digest}"
    if execution.evidence_refs.count(expected_receipt_ref) != 1:
        raise ValueError("adaptive telemetry metadata does not match its receipt reference")
    if metadata.observed_until is not None and metadata.observed_until > frame_cutoff:
        raise ValueError("adaptive telemetry metadata exceeds the frame cutoff")


def _source_metadata_material(metadata: AdaptiveObservationSourceMetadata) -> dict[str, object]:
    """Return the canonical source metadata digest material."""

    return {
        "source_kind": metadata.source_kind,
        "receipt_digest": metadata.receipt_digest,
        "recipe_id": metadata.recipe_id,
        "recipe_version": metadata.recipe_version,
        "disposition": metadata.disposition,
        "observed_until": (
            metadata.observed_until.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if metadata.observed_until is not None
            else None
        ),
        "route_count": metadata.route_count,
        "queried_route_count": metadata.queried_route_count,
        "row_count": metadata.row_count,
        "latency_ms": metadata.latency_ms,
        "complete": metadata.complete,
        "truncated": metadata.truncated,
    }


def _execution_material(execution: AdaptiveExecutionMaterial) -> dict[str, object]:
    """Return canonical execution material including optional source metadata."""

    material = {
        "round_index": execution.round_index,
        "frame_digest": execution.frame_digest,
        "selection_digest": execution.selection_digest,
        "candidate_digest": execution.candidate_digest,
        "binding_digest": execution.binding_digest,
        "verification_receipt_digest": execution.verification_receipt_digest,
        "plan_digest": execution.plan_digest,
        "result_digest": execution.result_digest,
        "query_status": execution.query_status,
        "evidence_refs": list(execution.evidence_refs),
        "reserved_cost_units": execution.reserved_cost_units,
        "actual_cost_units": execution.actual_cost_units,
        "execution_authority": False,
        "mutation_authority": False,
    }
    if execution.source_metadata is not None:
        material["source_metadata"] = _source_metadata_material(execution.source_metadata)
    return material


def _text(name: str, value: str) -> None:
    if not value.strip() or len(value) > 512:
        raise ValueError(f"{name} MUST be non-empty and bounded")


def _digest(name: str, value: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} MUST be a sha256 digest")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "AdaptiveObservationSourceMetadata",
    "execution_actual_cost_units",
    "_execution_material",
    "execution_source_metadata",
    "_source_metadata_material",
    "validate_source_metadata_lineage",
]
