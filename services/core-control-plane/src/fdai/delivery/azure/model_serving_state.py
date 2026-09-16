"""Validate and retain passive model serving state facts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final

from fdai_service_contracts.recorded_resource_state import (
    RECORDED_STATE_UNAVAILABLE_REASONS,
    STATE_FACT_UNAVAILABLE_REASONS_PROPERTY,
)

from fdai.delivery.azure.model_deployment import MODEL_DEPLOYMENT_RESOURCE_TYPE
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.metric import MetricPoint
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

MODEL_SERVING_STATE_PROPERTY: Final = "servingState"
MODEL_SERVING_SOURCE_IDENTITY: Final = "azure-monitor-model-serving"
_EVIDENCE_PREFIX: Final = f"{MODEL_SERVING_SOURCE_IDENTITY}:sha256:"
_EVIDENCE_REF = re.compile(r"azure-monitor-model-serving:sha256:[0-9a-f]{64}")
_MODEL_DEPLOYMENT_ARM_ID = re.compile(
    r"^/subscriptions/[A-Za-z0-9-]+/resourceGroups/[A-Za-z0-9_.()-]+"
    r"/providers/Microsoft\.CognitiveServices/accounts/[A-Za-z0-9_.()-]+"
    r"/deployments/(?P<deployment>[A-Za-z0-9_.-]+)$",
    re.IGNORECASE,
)


def model_deployment_name(provider_ref: str | None) -> str | None:
    """Return the exact deployment segment from one reviewed ARM child id."""

    match = _MODEL_DEPLOYMENT_ARM_ID.fullmatch(provider_ref or "")
    return match["deployment"] if match is not None else None


def valid_model_serving_point(
    point: MetricPoint,
    *,
    metric_name: str,
    provider_ref: str,
    deployment_name: str,
    since: datetime,
    until: datetime,
) -> bool:
    """Validate exact target, dimensions, time, and numeric bounds for one metric point."""

    return (
        point.metric_name == metric_name
        and point.at.tzinfo is not None
        and since <= point.at.astimezone(UTC) <= until
        and isinstance(point.value, (int, float))
        and not isinstance(point.value, bool)
        and math.isfinite(point.value)
        and point.value >= 0
        and point.labels.get("resource_id", "").casefold() == provider_ref.casefold()
        and point.labels.get("ModelDeploymentName", "").casefold() == deployment_name.casefold()
        and point.labels.get("StatusCode") == "200"
    )


def model_serving_evidence_ref(
    *,
    resource_id: str,
    effective_at: datetime,
    value: float,
    metric_name: str,
) -> str:
    """Bind one serving fact to the exact metric target, time, and value."""

    material = json.dumps(
        {
            "metric": metric_name,
            "resource_id": resource_id,
            "at": effective_at.astimezone(UTC).isoformat(),
            "value": value,
        },
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{_EVIDENCE_PREFIX}{hashlib.sha256(material.encode()).hexdigest()}"


def model_serving_reason_map(props: Mapping[str, object]) -> dict[str, object]:
    """Copy the bounded per-property unavailable reason map."""

    value = props.get(STATE_FACT_UNAVAILABLE_REASONS_PROPERTY)
    return dict(value) if isinstance(value, Mapping) else {}


def prior_model_serving_resource(
    resource: ResourceRecord | None,
) -> tuple[ResourceRecord, StateFactMetadata] | None:
    """Return a verified prior Serving fact or none."""

    if resource is None or resource.props.get(MODEL_SERVING_STATE_PROPERTY) != "Serving":
        return None
    metadata_root = resource.props.get(STATE_FACT_METADATA_PROPERTY)
    metadata_value = (
        metadata_root.get(MODEL_SERVING_STATE_PROPERTY)
        if isinstance(metadata_root, Mapping)
        else None
    )
    if not isinstance(metadata_value, Mapping):
        return None
    try:
        metadata = StateFactMetadata.from_mapping(metadata_value)
    except (OverflowError, TypeError, ValueError):
        return None
    if (
        metadata.source_identity != MODEL_SERVING_SOURCE_IDENTITY
        or _EVIDENCE_REF.fullmatch(metadata.source_revision) is None
        or metadata.evidence_refs != (metadata.source_revision,)
        or metadata.lane is not StateFactLane.OBSERVED
        or metadata.authority is not StateFactAuthority.TELEMETRY
        or metadata.synthetic
        or metadata.completeness != 1.0
        or metadata.conflicts
    ):
        return None
    return resource, metadata


def carry_prior_model_serving(
    resource: ResourceRecord,
    prior: tuple[ResourceRecord, StateFactMetadata],
) -> ResourceRecord:
    """Carry a verified prior fact without refreshing its evidence time."""

    prior_resource, _metadata = prior
    props = dict(resource.props)
    metadata_root = props.get(STATE_FACT_METADATA_PROPERTY)
    metadata = dict(metadata_root) if isinstance(metadata_root, Mapping) else {}
    prior_metadata_root = prior_resource.props[STATE_FACT_METADATA_PROPERTY]
    if not isinstance(prior_metadata_root, Mapping):
        raise ValueError("prior model serving metadata is malformed")
    metadata[MODEL_SERVING_STATE_PROPERTY] = prior_metadata_root[MODEL_SERVING_STATE_PROPERTY]
    props[MODEL_SERVING_STATE_PROPERTY] = "Serving"
    props[STATE_FACT_METADATA_PROPERTY] = metadata
    reasons = model_serving_reason_map(props)
    reasons.pop(MODEL_SERVING_STATE_PROPERTY, None)
    if reasons:
        props[STATE_FACT_UNAVAILABLE_REASONS_PROPERTY] = reasons
    else:
        props.pop(STATE_FACT_UNAVAILABLE_REASONS_PROPERTY, None)
    return replace(resource, props=props)


def carry_model_serving_or_reason(
    resource: ResourceRecord,
    previous: ResourceRecord | None,
    reason: str,
    *,
    evaluated_at: datetime,
) -> ResourceRecord:
    """Carry verified evidence or attach one allowlisted missing-state reason."""

    if evaluated_at.tzinfo is None:
        raise ValueError("model serving evaluation time MUST be timezone-aware")
    prior = prior_model_serving_resource(previous)
    if prior is not None and evaluated_at.astimezone(UTC) <= (
        prior[1].evidence_cutoff + timedelta(seconds=prior[1].freshness_ceiling_seconds)
    ):
        return carry_prior_model_serving(resource, prior)
    if reason not in RECORDED_STATE_UNAVAILABLE_REASONS:
        reason = "model_serving_response_invalid"
    props = dict(resource.props)
    props.pop(MODEL_SERVING_STATE_PROPERTY, None)
    metadata_root = props.get(STATE_FACT_METADATA_PROPERTY)
    if isinstance(metadata_root, Mapping):
        metadata = dict(metadata_root)
        metadata.pop(MODEL_SERVING_STATE_PROPERTY, None)
        if metadata:
            props[STATE_FACT_METADATA_PROPERTY] = metadata
        else:
            props.pop(STATE_FACT_METADATA_PROPERTY, None)
    reasons = model_serving_reason_map(props)
    reasons[MODEL_SERVING_STATE_PROPERTY] = reason
    props[STATE_FACT_UNAVAILABLE_REASONS_PROPERTY] = reasons
    return replace(resource, props=props)


def retain_model_serving_or_reason(
    observation: PromotedInventoryObservation,
    previous: Mapping[str, ResourceRecord],
    reason: str,
    *,
    evaluated_at: datetime,
) -> PromotedInventoryObservation:
    """Apply one explicit reason to model targets without discarding prior facts."""

    return replace(
        observation,
        resources=tuple(
            carry_model_serving_or_reason(
                resource,
                previous.get(resource.resource_id),
                reason,
                evaluated_at=evaluated_at,
            )
            if resource.type == MODEL_DEPLOYMENT_RESOURCE_TYPE
            else resource
            for resource in observation.resources
        ),
    )


__all__ = [
    "MODEL_SERVING_SOURCE_IDENTITY",
    "MODEL_SERVING_STATE_PROPERTY",
    "carry_model_serving_or_reason",
    "carry_prior_model_serving",
    "model_deployment_name",
    "model_serving_evidence_ref",
    "model_serving_reason_map",
    "prior_model_serving_resource",
    "retain_model_serving_or_reason",
    "valid_model_serving_point",
]
