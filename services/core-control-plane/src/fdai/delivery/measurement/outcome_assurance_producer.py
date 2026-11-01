"""Core-owned producer persisting OutcomeAssuranceProjection under the shared reader key.

Writes validated, non-synthetic `fdai_service_contracts.OutcomeAssuranceProjection` records into
the shared `StateStore` (`state_kv`) under the exact deterministic key consumed by the Operator
Service (`/kpi/outcome-assurance`). Persistence is read-model projection only and grants no
execution, approval, or promotion authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import fdai_service_contracts as sc
from fdai.core.measurement.outcome_assurance import (
    FinalizedOutcomeEvent,
    OutcomeMeasurementObservation,
    summarize_objective_attribution,
)
from fdai.shared.providers.state_store import StateStore

_VALID_VERTICALS = frozenset({"resilience", "change_safety", "cost_governance"})


def _require_bounded_param(name: str, value: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Outcome Assurance {name} MUST be a string")
    stripped = value.strip()
    if not stripped or len(stripped) > maximum or "\x00" in stripped:
        raise ValueError(f"Outcome Assurance {name} is malformed")
    return stripped


def outcome_assurance_projection_key(
    principal_id: str,
    scope_ref: str,
    vertical: str | None,
    window: str,
) -> str:
    """Return the shared StateStore key consumed by the Operator Outcome Assurance reader."""

    cleaned_principal = _require_bounded_param("principal_id", principal_id, maximum=512)
    cleaned_scope = _require_bounded_param("scope_ref", scope_ref, maximum=512)
    cleaned_window = _require_bounded_param("window", window, maximum=64)
    if not (
        cleaned_window.endswith("d")
        and cleaned_window[:-1].isdigit()
        and 1 <= int(cleaned_window[:-1]) <= 366
    ):
        raise ValueError("Outcome Assurance window MUST be an integer day label in 1d..366d")
    cleaned_vertical = ""
    if vertical is not None:
        if not isinstance(vertical, str) or vertical not in _VALID_VERTICALS:
            raise ValueError("Outcome Assurance vertical is malformed")
        cleaned_vertical = vertical
    identity = "\0".join((cleaned_principal, cleaned_scope, cleaned_vertical, cleaned_window))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"outcome-assurance:projection:v1:{digest}"


def _projection_digest(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _validate_projection_for_persistence(projection: sc.OutcomeAssuranceProjection) -> str:
    if (
        projection.execution_authority
        or projection.approval_authority
        or projection.promotion_authority
    ):
        raise ValueError("Outcome Assurance projection MUST NOT carry authority")
    window_label = projection.window.label
    if window_label is None:
        raise ValueError("Outcome Assurance projection window.label is required for persistence")
    metric_ids = [item.metric for item in projection.outcomes]
    if len(metric_ids) != len(set(metric_ids)):
        raise ValueError("Outcome Assurance outcomes MUST NOT contain duplicate metric entries")
    guard_ids = [item.guard_id for item in projection.guards.guard_evaluations]
    if len(guard_ids) != len(set(guard_ids)):
        raise ValueError(
            "Outcome Assurance guard_evaluations MUST NOT contain duplicate guard_id entries"
        )
    for item in projection.outcomes:
        for val in (item.current_value, item.baseline_value, item.target_value):
            if val is not None and not math.isfinite(val):
                raise ValueError("Outcome Assurance metric values MUST be finite")
    return window_label


@dataclass(frozen=True, slots=True)
class OutcomeAssurancePublishReceipt:
    """Immutable receipt returned when Core persists an OutcomeAssuranceProjection."""

    key: str
    principal_id: str
    scope_ref: str
    vertical: str | None
    window_label: str
    state: sc.OutcomeAssuranceReadState
    projection_digest: str
    published_at: datetime
    execution_authority: Literal[False] = field(default=False, init=False)

    def to_mapping(self) -> dict[str, object]:
        return {
            "key": self.key,
            "principal_id": self.principal_id,
            "scope_ref": self.scope_ref,
            "vertical": self.vertical,
            "window_label": self.window_label,
            "state": self.state.value,
            "projection_digest": self.projection_digest,
            "published_at": self.published_at.isoformat(),
            "execution_authority": self.execution_authority,
        }


def _parse_provenance_times(raw: object) -> tuple[datetime, datetime] | None:
    if not isinstance(raw, dict):
        return None
    prov = raw.get("provenance")
    if not isinstance(prov, dict):
        return None
    raw_as_of = prov.get("as_of")
    raw_gen = prov.get("generated_at")
    if not isinstance(raw_as_of, str) or not isinstance(raw_gen, str):
        return None
    try:
        as_of = datetime.fromisoformat(raw_as_of.replace("Z", "+00:00")).astimezone(UTC)
        gen = datetime.fromisoformat(raw_gen.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
    return as_of, gen


async def persist_outcome_assurance_projection(
    *,
    principal_id: str,
    projection: sc.OutcomeAssuranceProjection,
    store: StateStore,
    actor_id: str = "core.outcome-assurance-producer",
    published_at: datetime | None = None,
) -> OutcomeAssurancePublishReceipt:
    """Validate and persist one OutcomeAssuranceProjection under the shared Operator reader key."""

    window_label = _validate_projection_for_persistence(projection)
    cleaned_actor = _require_bounded_param("actor_id", actor_id, maximum=256)
    vertical_value = (
        projection.scope.vertical.value if projection.scope.vertical is not None else None
    )
    key = outcome_assurance_projection_key(
        principal_id,
        projection.scope.scope_ref,
        vertical_value,
        window_label,
    )
    current_time = (published_at or projection.provenance.generated_at).astimezone(UTC)
    payload = projection.model_dump(mode="json")
    digest = _projection_digest(payload)
    audit_entry = {
        "action_kind": "measurement.outcome_assurance.projection.v1",
        "actor_id": cleaned_actor,
        "principal_id": principal_id.strip(),
        "scope_ref": projection.scope.scope_ref,
        "vertical": vertical_value,
        "window_label": window_label,
        "state": projection.state.value,
        "projection_key": key,
        "projection_digest": digest,
        "published_at": current_time.isoformat(),
        "execution_authority": False,
        "approval_authority": False,
        "promotion_authority": False,
    }
    inserted = await store.write_state_with_audit_if_absent(
        key,
        {**payload, "revision": 1},
        audit_entry,
    )
    if not inserted:
        incoming_times = (
            projection.provenance.as_of.astimezone(UTC),
            projection.provenance.generated_at.astimezone(UTC),
        )
        updated = False
        for _attempt in range(5):
            existing = await store.read_state(key)
            if existing is None:
                if await store.write_state_with_audit_if_absent(
                    key,
                    {**payload, "revision": 1},
                    audit_entry,
                ):
                    updated = True
                    break
                continue
            existing_dict = dict(existing)
            existing_times = _parse_provenance_times(existing_dict)
            if existing_times is not None and incoming_times < existing_times:
                raise ValueError("Outcome Assurance projection cannot overwrite newer provenance")
            raw_rev = existing_dict.get("revision", 0)
            expected_revision = (
                raw_rev if isinstance(raw_rev, int) and not isinstance(raw_rev, bool) else 0
            )
            if expected_revision < 0:
                raise RuntimeError("stored Outcome Assurance projection revision is invalid")
            next_revision = expected_revision + 1
            if await store.compare_and_set_state_with_audit(
                key,
                {**payload, "revision": next_revision},
                expected_revision=expected_revision,
                audit_entry={**audit_entry, "revision": next_revision},
            ):
                updated = True
                break
        if not updated:
            raise RuntimeError("Outcome Assurance projection atomic update failed")
    return OutcomeAssurancePublishReceipt(
        key=key,
        principal_id=principal_id.strip(),
        scope_ref=projection.scope.scope_ref,
        vertical=vertical_value,
        window_label=window_label,
        state=projection.state,
        projection_digest=digest,
        published_at=current_time,
    )


class OutcomeAssuranceProjectionProducer:
    """Core-owned service that writes OutcomeAssuranceProjection records to StateStore."""

    def __init__(
        self,
        *,
        store: StateStore,
        actor_id: str = "core.outcome-assurance-producer",
    ) -> None:
        self._store = store
        self._actor_id = _require_bounded_param("actor_id", actor_id, maximum=256)

    async def publish(
        self,
        *,
        principal_id: str,
        projection: sc.OutcomeAssuranceProjection,
        published_at: datetime | None = None,
    ) -> OutcomeAssurancePublishReceipt:
        return await persist_outcome_assurance_projection(
            principal_id=principal_id,
            projection=projection,
            store=self._store,
            actor_id=self._actor_id,
            published_at=published_at,
        )

    async def publish_from_authoritative_sources(
        self,
        *,
        principal_id: str,
        scope: sc.OutcomeAssuranceScope,
        window: sc.OutcomeAssuranceWindow,
        sources: tuple[sc.OutcomeAssuranceSource, ...],
        readiness: tuple[sc.OutcomeAssuranceReadiness, ...],
        finalized_events: tuple[FinalizedOutcomeEvent, ...],
        observations: tuple[OutcomeMeasurementObservation, ...],
        outcomes: tuple[sc.OutcomeAssuranceMetric, ...],
        guards: sc.OutcomeAssuranceControlSummary,
        as_of: datetime,
        generated_at: datetime | None = None,
    ) -> OutcomeAssurancePublishReceipt:
        """Join authoritative Core measurement sources into a projection and persist it."""

        resolved_generated_at = (generated_at or as_of).astimezone(UTC)
        core_summary = summarize_objective_attribution(finalized_events, observations)
        source_states = {item.state for item in sources}
        if not sources or sc.OutcomeAssuranceSourceState.UNAVAILABLE in source_states:
            reason = next(
                (item.reason for item in sources if item.reason is not None),
                sc.OutcomeAssuranceUnavailableReason.SOURCE_MISSING,
            )
            state = sc.OutcomeAssuranceReadState.UNAVAILABLE
            alignment = sc.OutcomeAssuranceAttribution(
                state=sc.OutcomeAssuranceAttributionState.UNAVAILABLE,
                finalized_events=core_summary.finalized_events,
                attributed_events=0,
                unattributed_events=core_summary.finalized_events,
                reason=reason,
            )
        elif sc.OutcomeAssuranceSourceState.STALE in source_states:
            reason = next(
                (item.reason for item in sources if item.reason is not None),
                sc.OutcomeAssuranceUnavailableReason.SOURCE_STALE,
            )
            state = sc.OutcomeAssuranceReadState.STALE
            alignment = sc.OutcomeAssuranceAttribution(
                state=sc.OutcomeAssuranceAttributionState.UNAVAILABLE,
                finalized_events=core_summary.finalized_events,
                attributed_events=0,
                unattributed_events=core_summary.finalized_events,
                reason=reason,
            )
        else:
            reason = None
            state = sc.OutcomeAssuranceReadState.COMPLETE
            alignment = sc.OutcomeAssuranceAttribution(
                state=sc.OutcomeAssuranceAttributionState(core_summary.state.value),
                objective_refs=core_summary.objective_refs,
                workflow_refs=core_summary.workflow_refs,
                action_type_ids=core_summary.action_type_ids,
                finalized_events=core_summary.finalized_events,
                attributed_events=core_summary.attributed_events,
                unattributed_events=core_summary.unattributed_events,
                coverage=core_summary.coverage,
                evidence_refs=core_summary.evidence_refs,
            )

        projection = sc.OutcomeAssuranceProjection(
            state=state,
            reason=reason,
            scope=scope,
            window=window,
            sources=sources,
            readiness=readiness,
            alignment=alignment,
            outcomes=outcomes if state is sc.OutcomeAssuranceReadState.COMPLETE else (),
            guards=guards,
            provenance=sc.OutcomeAssuranceProvenance(
                as_of=as_of.astimezone(UTC),
                generated_at=resolved_generated_at,
                source_names=tuple(item.name for item in sources),
            ),
        )
        return await self.publish(
            principal_id=principal_id,
            projection=projection,
            published_at=resolved_generated_at,
        )


__all__ = [
    "OutcomeAssuranceProjectionProducer",
    "OutcomeAssurancePublishReceipt",
    "outcome_assurance_projection_key",
    "persist_outcome_assurance_projection",
]
