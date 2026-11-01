"""ARB-2 owned-topic stage record builder for architecture review observations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fdai.core.architecture_review.observation_loop import ArchitectureReviewObservation
    from fdai.core.architecture_review.observation_trace import ArchitectureReviewStage

_DEFAULT_TRACE_DEADLINE = timedelta(minutes=15)


def _digest(value: object) -> str:
    payload = json.dumps(_json_ready(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _json_ready(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_ready(item) for item in value]
    return value


def _is_conformant_recommendation_status(recommendation: str) -> bool:
    return recommendation in {
        "approved",
        "conditional",
        "conformant",
        "conformant_observation",
        "ready",
    }


def _is_valid_projected_review_case(
    projected_review_case: Mapping[str, object] | None,
    *,
    resolved_case_id: str,
    target_ref: str,
    recommendation: str,
) -> bool:
    if projected_review_case is None:
        return False
    return (
        str(projected_review_case.get("id") or "") == resolved_case_id
        and str(projected_review_case.get("scope_ref") or "") == target_ref
        and str(projected_review_case.get("workflow_ref") or "") == "architecture-review"
        and str(projected_review_case.get("status") or "") == recommendation
    )


def build_owned_architecture_review_stage_records(
    observation: ArchitectureReviewObservation,
    *,
    deadline_at: datetime | None = None,
    review_case_id: str | None = None,
    projected_review_case: Mapping[str, object] | None = None,
    specialist_records: Mapping[ArchitectureReviewStage, Mapping[str, object]] | None = None,
    audit_record: Mapping[str, object] | None = None,
) -> tuple[tuple[str, dict[str, object]], ...]:
    """Emit distinct owned-topic records without synthesizing missing stages."""
    from fdai.core.architecture_review.observation_trace import (
        _STAGE_BINDINGS,
        ArchitectureReviewStage,
    )

    resolved_case_id = review_case_id or f"arb-review:{observation.change_id}"
    base_time = (
        observation.context.recorded_at
        if observation.context is not None
        else datetime.fromtimestamp(0, tz=UTC)
    )
    resolved_deadline = deadline_at or (base_time + _DEFAULT_TRACE_DEADLINE)
    base_meta = {
        "correlation_id": observation.correlation_id,
        "review_case_id": resolved_case_id,
        "deadline_at": resolved_deadline.isoformat(),
    }
    records: list[tuple[str, dict[str, object]]] = []

    change_payload: dict[str, object] = {
        **base_meta,
        "producer_principal": "Huginn",
        "id": resolved_case_id,
        "change_id": observation.change_id,
        "target_ref": observation.target_ref,
        "intent_kind": "planned",
        "occurred_at": base_time.isoformat(),
        "observed_at": (base_time + timedelta(seconds=1)).isoformat(),
        "idempotency_key": f"{observation.idempotency_key}:change",
        "change_digest": observation.change_digest,
    }
    records.append(("object.change", change_payload))

    if observation.context is not None:
        ctx = observation.context
        records.append(
            (
                "object.state-snapshot",
                {
                    **base_meta,
                    "producer_principal": "Muninn",
                    "snapshot_type": "architecture_review_context",
                    "observed_at": (base_time + timedelta(seconds=2)).isoformat(),
                    "idempotency_key": f"{observation.idempotency_key}:context:{ctx.snapshot_id}",
                    "context_snapshot": {
                        "snapshot_id": ctx.snapshot_id,
                        "target_resource_id": ctx.target_resource_id,
                        "cutoff": ctx.cutoff.isoformat(),
                        "recorded_at": ctx.recorded_at.isoformat(),
                        "objective_ids": list(ctx.objective_ids),
                    },
                },
            )
        )

    for index, stage in enumerate(
        (
            ArchitectureReviewStage.RELIABILITY,
            ArchitectureReviewStage.COST,
            ArchitectureReviewStage.CAPACITY,
            ArchitectureReviewStage.RECOVERY,
        ),
        start=3,
    ):
        if specialist_records is not None and stage in specialist_records:
            topic, producer = _STAGE_BINDINGS[stage]
            supplied = dict(specialist_records[stage])
            records.append(
                (
                    topic,
                    {
                        **base_meta,
                        "producer_principal": str(supplied.get("producer_principal") or producer),
                        "observed_at": str(
                            supplied.get("observed_at")
                            or (base_time + timedelta(seconds=index)).isoformat()
                        ),
                        "idempotency_key": str(
                            supplied.get("idempotency_key")
                            or f"{observation.idempotency_key}:{stage.value}"
                        ),
                        **{
                            key: value
                            for key, value in supplied.items()
                            if key
                            not in {
                                "correlation_id",
                                "review_case_id",
                                "deadline_at",
                                "producer_principal",
                                "observed_at",
                                "idempotency_key",
                            }
                        },
                    },
                )
            )

    if observation.evidence is not None:
        bundle = observation.evidence.bundle
        records.append(
            (
                "object.state-snapshot",
                {
                    **base_meta,
                    "producer_principal": "Muninn",
                    "snapshot_type": "architecture_review_evidence_bundle",
                    "observed_at": (base_time + timedelta(seconds=7)).isoformat(),
                    "idempotency_key": f"{observation.idempotency_key}:evidence:{bundle.digest}",
                    "evidence_bundle": {
                        "digest": bundle.digest,
                        "purpose": bundle.purpose,
                        "scope": list(bundle.scope),
                        "cutoff": bundle.cutoff.isoformat(),
                        "hold_required": bundle.hold_required,
                    },
                },
            )
        )

    if observation.scenario is not None:
        scenario = observation.scenario
        records.append(
            (
                "object.verdict",
                {
                    **base_meta,
                    "producer_principal": "Forseti",
                    "kind": "architecture_review_scenario_branch",
                    "observed_at": (base_time + timedelta(seconds=8)).isoformat(),
                    "idempotency_key": (
                        f"{observation.idempotency_key}:scenario:{scenario.scenario_digest}"
                    ),
                    "scenario_branch": {
                        "branch_id": scenario.branch_id,
                        "scenario_digest": scenario.scenario_digest,
                    },
                },
            )
        )

    if observation.decision_case is not None:
        case = observation.decision_case
        records.append(
            (
                "object.verdict",
                {
                    **base_meta,
                    "producer_principal": "Forseti",
                    "kind": "architecture_review_decision_case",
                    "observed_at": (base_time + timedelta(seconds=9)).isoformat(),
                    "idempotency_key": (
                        f"{observation.idempotency_key}:decision_case:{case.case_id}"
                    ),
                    "decision_case": {
                        "case_id": case.case_id,
                        "selected_option_id": "observe-only",
                        "protected_objective_ids": list(case.protected_objective_ids),
                    },
                },
            )
        )

    if observation.impact_envelope is not None:
        envelope = observation.impact_envelope
        records.append(
            (
                "object.verdict",
                {
                    **base_meta,
                    "producer_principal": "Forseti",
                    "kind": "architecture_review_impact_envelope",
                    "observed_at": (base_time + timedelta(seconds=10)).isoformat(),
                    "idempotency_key": (
                        f"{observation.idempotency_key}:impact_envelope:{envelope.envelope_id}"
                    ),
                    "impact_envelope": {
                        "envelope_id": envelope.envelope_id,
                        "decision_case_id": envelope.decision_case_id,
                        "graph_revision": envelope.graph_revision,
                        "affected_set_digest": envelope.affected_set_digest,
                    },
                },
            )
        )

    if _is_conformant_recommendation_status(
        observation.recommendation
    ) and _is_valid_projected_review_case(
        projected_review_case,
        resolved_case_id=resolved_case_id,
        target_ref=observation.target_ref,
        recommendation=observation.recommendation,
    ):
        assert projected_review_case is not None  # noqa: S101 - narrowed by helper above
        projection_body = dict(projected_review_case)
        records.append(
            (
                "object.verdict",
                {
                    **base_meta,
                    "producer_principal": "Forseti",
                    "kind": "architecture_review_recommendation",
                    "observed_at": (base_time + timedelta(seconds=11)).isoformat(),
                    "idempotency_key": f"{observation.idempotency_key}:recommendation",
                    "target_ref": observation.target_ref,
                    "recommendation": observation.recommendation,
                    "derived_review_case_id": resolved_case_id,
                    "review_case_projection": projection_body,
                    "projection_digest": _digest(projection_body),
                    "mutation_authority": False,
                    "execution_authority": False,
                },
            )
        )

    if audit_record is not None:
        supplied_audit = dict(audit_record)
        records.append(
            (
                "object.audit-entry",
                {
                    **base_meta,
                    "producer_principal": str(supplied_audit.get("producer_principal") or "Saga"),
                    "audited_topic": str(supplied_audit.get("audited_topic") or "object.verdict"),
                    "observed_at": str(
                        supplied_audit.get("observed_at")
                        or (base_time + timedelta(seconds=12)).isoformat()
                    ),
                    "idempotency_key": str(
                        supplied_audit.get("idempotency_key")
                        or f"{observation.idempotency_key}:audit"
                    ),
                    "mode": str(supplied_audit.get("mode") or "shadow"),
                },
            )
        )

    return tuple(records)


__all__ = ["build_owned_architecture_review_stage_records"]
