"""Readbacks for source-specific forecast-history operational evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import OperationalEvidenceRejectionClass

from fdai.core.detection.forecast_history import ForecastHistoryBinding
from fdai.core.ontology_platform.state_transitions import StateTransitionStore
from fdai.shared.providers.forecast_context import ForecastContextEvidence, ForecastContextRequest

from ..rejections import ReadbackRejection, reject
from .base import ReadbackContext, ReadbackFacts

_R = OperationalEvidenceRejectionClass
_BOUND_KINDS = frozenset({"changes", "resource_lifecycle"})


class ForecastHistorySliceSource(Protocol):
    """Read one source-specific history slice from authoritative retained source rows."""

    async def read_slice(
        self, *, purpose_id: str, request: ForecastContextRequest
    ) -> ForecastContextEvidence | None: ...


class StateTransitionForecastHistorySliceSource:
    """Recompute source-specific forecast slices from the operational state-transition store."""

    def __init__(
        self, *, store: StateTransitionStore, bindings: tuple[ForecastHistoryBinding, ...]
    ) -> None:
        self._store = store
        self._bindings: dict[tuple[str, str, str], ForecastHistoryBinding] = {}
        for binding in bindings:
            if binding.kind in _BOUND_KINDS:
                target_digest = _target_digest(binding.target_ref)
                key = (binding.access_scope_digest, target_digest, binding.kind)
                if key in self._bindings:
                    raise ValueError("forecast history binding is duplicated")
                self._bindings[key] = binding

    async def read_slice(
        self, *, purpose_id: str, request: ForecastContextRequest
    ) -> ForecastContextEvidence | None:
        kind = _kind_from_purpose(purpose_id)
        if kind not in _BOUND_KINDS:
            return None
        binding = self._bindings.get((request.access_scope_digest, request.target_digest, kind))
        if binding is None:
            return None
        stateful = kind == "resource_lifecycle"
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
            return None
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
            or request.as_of >= coverage.recorded_at + timedelta(seconds=binding.freshness_seconds)
        ):
            return None
        refs = {coverage.evidence_ref}
        interventions = set()
        expires = coverage.recorded_at + timedelta(seconds=binding.freshness_seconds)
        if len({item.transition_id for item in result.transitions}) != len(result.transitions):
            return None
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
                return None
            refs.update(item.evidence_refs)
            if kind == "changes":
                interventions.add("state-transition:" + item.transition_id)
        resource_deleted = False
        if stateful:
            ordered = sorted(
                result.transitions,
                key=lambda item: (item.effective_at, item.recorded_at),
            )
            if not ordered:
                return None
            if any(
                first.effective_at == second.effective_at
                or (
                    second.to_state != first.to_state
                    if second.from_state == "checkpoint"
                    else first.to_state != second.from_state
                )
                for first, second in zip(ordered, ordered[1:], strict=False)
            ):
                return None
            prior = [item for item in ordered if item.effective_at <= request.horizon_started_at]
            initial = prior[-1].to_state if prior else ordered[0].from_state
            if initial not in binding.to_states:
                return None
            resource_deleted = initial in binding.active_states or any(
                item.to_state in binding.active_states
                for item in ordered
                if item.effective_at > request.horizon_started_at
            )
        return ForecastContextEvidence(
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
                    "transitions": sorted(item.transition_id for item in result.transitions),
                }
            ).removeprefix("sha256:"),
            evidence_refs=tuple(sorted(refs)),
            intervention_refs=tuple(sorted(interventions)),
            resource_deleted=resource_deleted,
            excluded_window=False,
        )


class ForecastHistorySliceReadback:
    """Issue source-specific proof only from recomputed authoritative forecast-history slices."""

    purposes = frozenset({f"forecast-history-{kind}" for kind in _BOUND_KINDS})

    def __init__(self, *, source: ForecastHistorySliceSource) -> None:
        self._source = source

    async def read(self, context: ReadbackContext) -> ReadbackFacts | ReadbackRejection:
        try:
            request = _request_from_context(context)
        except ValueError:
            return reject(_R.PARTIAL, "forecast_locator_malformed")
        evidence = await self._source.read_slice(
            purpose_id=context.request.lookup.purpose_id, request=request
        )
        if evidence is None:
            return reject(_R.PARTIAL, "forecast_source_coverage_unavailable")
        if evidence.digest != context.request.lookup.evidence_digest.removeprefix("sha256:"):
            return reject(_R.REPLAY_SUBSTITUTED, "evidence_mismatch")
        if evidence.access_scope_digest != context.access_scope_digest:
            return reject(_R.CROSS_SCOPE, "scope_mismatch")
        if evidence.source_revision != context.request.lookup.source_revision:
            return reject(_R.REPLAY_SUBSTITUTED, "source_revision_mismatch")
        if not evidence.complete:
            return reject(_R.PARTIAL, "forecast_source_incomplete")
        kind = _kind_from_purpose(context.request.lookup.purpose_id)
        return ReadbackFacts(
            evidence_digest=context.request.lookup.evidence_digest,
            source_identity=_source_identity(kind),
            authentication={"kind": kind, "source_revision": evidence.source_revision},
            completeness={
                "evidence_refs": list(evidence.evidence_refs),
                "intervention_refs": list(evidence.intervention_refs),
                "resource_deleted": evidence.resource_deleted,
            },
            conflict={"conflicts": 0},
            provenance={
                "locator": dict(context.request.locator.coordinates),
                "slice": _json_evidence(evidence),
            },
            event_at=evidence.recorded_at,
            evidence_cutoff=evidence.recorded_at,
            valid_until_cap=evidence.valid_until,
        )


def _request_from_context(context: ReadbackContext) -> ForecastContextRequest:
    coordinates = context.request.locator.coordinates
    return ForecastContextRequest(
        access_scope_digest=coordinates["access_scope_digest"],
        target_digest=coordinates["target_digest"],
        horizon_started_at=_timestamp(coordinates["horizon_started_at"]),
        horizon_ended_at=_timestamp(coordinates["horizon_ended_at"]),
        as_of=context.read_at,
    )


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be aware")
    return parsed


def _kind_from_purpose(purpose_id: str) -> str:
    prefix = "forecast-history-"
    if not purpose_id.startswith(prefix):
        raise ValueError("not a forecast-history purpose")
    return purpose_id.removeprefix(prefix)


def _source_identity(kind: str) -> str:
    return {
        "changes": "inventory.observation-journal",
        "resource_lifecycle": "inventory.incarnation-ledger",
    }.get(kind, "unavailable")


def _target_digest(target_ref: str) -> str:
    import hashlib

    return hashlib.sha256(target_ref.encode()).hexdigest()


def _json_evidence(evidence: ForecastContextEvidence) -> Mapping[str, object]:
    value = asdict(evidence)
    for name in ("horizon_started_at", "horizon_ended_at", "recorded_at", "valid_until"):
        value[name] = getattr(evidence, name).astimezone(UTC).isoformat()
    value["evidence_refs"] = sorted(evidence.evidence_refs)
    value["intervention_refs"] = sorted(evidence.intervention_refs)
    return value


__all__ = [
    "ForecastHistorySliceReadback",
    "ForecastHistorySliceSource",
    "StateTransitionForecastHistorySliceSource",
]
