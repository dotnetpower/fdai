"""Collect exact forecast history from governed state-transition source coverage."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, timedelta
from typing import Annotated, Any, Literal

from fdai_service_contracts.ontology_query import content_digest
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai.core.ontology_platform.state_transitions import StateTransitionStore
from fdai.shared.providers.forecast_context import (
    ForecastContextEvidence,
    ForecastContextRequest,
    ForecastContextUnavailableError,
)


class ForecastHistoryBinding(BaseModel):
    """Reviewed source mapping; neither a query nor empty rows prove its completeness."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["actions", "changes", "resource_lifecycle", "excluded_windows"]
    access_scope_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    target_ref: Annotated[str, Field(min_length=1, max_length=512)]
    state_type: Annotated[str, Field(min_length=1, max_length=128)]
    to_states: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=128)], ...],
        Field(min_length=1, max_length=32),
    ]
    source_identity: Annotated[str, Field(min_length=1, max_length=512)]
    source_revision: Annotated[str, Field(min_length=1, max_length=512)]
    freshness_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)]
    active_states: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=128)], ...], Field(max_length=32)
    ] = ()
    lookback_seconds: Annotated[int, Field(strict=True, ge=1, le=86400)] = 86400

    @field_validator("to_states", "active_states")
    @classmethod
    def _canonical_states(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("forecast history states must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def _unique_states(self) -> ForecastHistoryBinding:
        if self.kind in {"resource_lifecycle", "excluded_windows"}:
            if not self.active_states or not set(self.active_states) < set(self.to_states):
                raise ValueError(
                    "stateful forecast history requires active and inactive state mappings"
                )
        elif self.active_states:
            raise ValueError("event history cannot declare stateful exclusion mappings")
        return self


class StateTransitionForecastHistoryCollector:
    """Read four exact source slices with positive full-window coverage and bounded I/O."""

    def __init__(
        self, *, store: StateTransitionStore, bindings: tuple[ForecastHistoryBinding, ...]
    ) -> None:
        if not bindings or len(bindings) > 256:
            raise ValueError("forecast history bindings must contain between one and 64 targets")
        self._store = store
        self._bindings: dict[tuple[str, str], dict[str, ForecastHistoryBinding]] = {}
        for binding in bindings:
            identity = (
                binding.access_scope_digest,
                hashlib.sha256(binding.target_ref.encode()).hexdigest(),
            )
            group = self._bindings.setdefault(identity, {})
            if binding.kind in group:
                raise ValueError("forecast history source mapping is duplicated")
            group[binding.kind] = binding
        if any(
            set(group) != {"actions", "changes", "resource_lifecycle", "excluded_windows"}
            for group in self._bindings.values()
        ):
            raise ValueError("forecast history requires all four source mappings per target")

    async def collect(self, request: ForecastContextRequest) -> Mapping[str, Any]:
        """Collect retained source records; missing coverage never becomes an empty success."""
        bindings = self._bindings.get((request.access_scope_digest, request.target_digest))
        if bindings is None:
            raise ForecastContextUnavailableError("forecast history target has no reviewed mapping")
        results: dict[str, Any] = {}
        async with asyncio.timeout(5):
            for kind, binding in sorted(bindings.items()):
                stateful = kind in {"resource_lifecycle", "excluded_windows"}
                start_at = request.horizon_started_at - timedelta(
                    seconds=binding.lookback_seconds if stateful else 0
                )
                result = await self._store.read(
                    subject_refs=(binding.target_ref,),
                    state_types=(binding.state_type,),
                    to_states=None,
                    start_at=start_at,
                    end_at=request.horizon_ended_at,
                    known_at=request.as_of,
                    limit=64,
                )
                if len(result.transitions) > 64 or len(result.coverage) != 1:
                    raise ForecastContextUnavailableError(
                        "forecast history coverage is missing or ambiguous"
                    )
                coverage = result.coverage[0]
                if (
                    coverage.subject_ref != binding.target_ref
                    or coverage.state_type != binding.state_type
                    or coverage.source_identity != binding.source_identity
                    or coverage.source_revision != binding.source_revision
                    or coverage.synthetic is not False
                    or coverage.complete is not True
                    or result.complete is not True
                    or coverage.coverage_start_at > start_at
                    or coverage.coverage_end_at < request.horizon_ended_at
                    or not request.horizon_ended_at <= coverage.recorded_at <= request.as_of
                    or request.as_of
                    >= coverage.recorded_at + timedelta(seconds=binding.freshness_seconds)
                ):
                    raise ForecastContextUnavailableError(
                        "forecast history source coverage is unverified or stale"
                    )
                refs = {coverage.evidence_ref}
                interventions = set()
                expires = coverage.recorded_at + timedelta(seconds=binding.freshness_seconds)
                if len({item.transition_id for item in result.transitions}) != len(
                    result.transitions
                ):
                    raise ForecastContextUnavailableError(
                        "forecast history contains duplicate transitions"
                    )
                for item in result.transitions:
                    if (
                        item.subject_ref != binding.target_ref
                        or item.state_type != binding.state_type
                        or item.source_identity != binding.source_identity
                        or item.source_revision != binding.source_revision
                        or item.to_state not in binding.to_states
                        or item.synthetic is not False
                        or item.conflicts
                        or item.completeness_basis_points != 10_000
                        or not start_at <= item.effective_at <= request.horizon_ended_at
                        or item.recorded_at > request.as_of
                    ):
                        raise ForecastContextUnavailableError(
                            "forecast history source record mismatch"
                        )
                    refs.update(item.evidence_refs)
                    if kind in {"actions", "changes"}:
                        interventions.add("state-transition:" + item.transition_id)
                active = False
                if stateful:
                    ordered = sorted(
                        result.transitions, key=lambda item: (item.effective_at, item.recorded_at)
                    )
                    if not ordered:
                        raise ForecastContextUnavailableError(
                            "forecast history initial state is unknown"
                        )
                    if any(
                        first.effective_at == second.effective_at
                        or first.to_state != second.from_state
                        for first, second in zip(ordered, ordered[1:], strict=False)
                    ):
                        raise ForecastContextUnavailableError(
                            "forecast history state chain is conflicting"
                        )
                    prior = [
                        item for item in ordered if item.effective_at <= request.horizon_started_at
                    ]
                    initial = prior[-1].to_state if prior else ordered[0].from_state
                    if initial not in binding.to_states:
                        raise ForecastContextUnavailableError(
                            "forecast history initial state is unmapped"
                        )
                    active = initial in binding.active_states or any(
                        item.to_state in binding.active_states
                        for item in ordered
                        if item.effective_at > request.horizon_started_at
                    )
                evidence = ForecastContextEvidence(
                    access_scope_digest=request.access_scope_digest,
                    target_digest=request.target_digest,
                    horizon_started_at=request.horizon_started_at,
                    horizon_ended_at=request.horizon_ended_at,
                    recorded_at=request.as_of,
                    valid_until=expires,
                    complete=True,
                    source_revision=content_digest(
                        {
                            "binding": binding.model_dump(mode="json"),
                            "coverage": coverage.coverage_id,
                            "transitions": sorted(
                                item.transition_id for item in result.transitions
                            ),
                        }
                    ).removeprefix("sha256:"),
                    evidence_refs=tuple(sorted(refs)),
                    intervention_refs=tuple(sorted(interventions)),
                    resource_deleted=kind == "resource_lifecycle" and active,
                    excluded_window=kind == "excluded_windows" and active,
                )
                value = asdict(evidence)
                for name in (
                    "horizon_started_at",
                    "horizon_ended_at",
                    "recorded_at",
                    "valid_until",
                ):
                    value[name] = getattr(evidence, name).astimezone(UTC).isoformat()
                results[kind] = value
        return results
