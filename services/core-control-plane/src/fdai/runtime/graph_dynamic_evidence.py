"""Strict production composition for graph-wide Dynamic evidence."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta

from fdai.composition import Container
from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    DynamicInvariant,
    EffectModelStatus,
    GraphEffectModel,
    InvariantOperator,
    StateStoreGraphEffectModelRegistry,
)
from fdai.delivery.azure.graph_operational_evidence import (
    AzureCachedGraphOperationalSnapshotSource,
    AzureGraphDynamicPolicy,
    AzureGraphDynamicSimulationRequestProvider,
)
from fdai.runtime.providers import _build_inventory_context_provider
from fdai.shared.providers.state_store import StateStore

GRAPH_DYNAMIC_CONFIG_ENV = "FDAI_GRAPH_DYNAMIC_CONFIG_JSON"
_MAX_ACTIONS = 64
_MAX_MODELS = 256


class ConfiguredGraphCausalEvidenceVerifier:
    """Accept only graph-model causal receipts admitted by deployment config."""

    def __init__(self, digests: frozenset[str]) -> None:
        if not digests or len(digests) > 256 or any(not _is_digest(item) for item in digests):
            raise ValueError("graph Dynamic causal digests MUST contain 1..256 SHA-256 values")
        self._digests = digests

    def verify(self, model: GraphEffectModel) -> bool:
        return model.causal_evidence_receipt_digest in self._digests


async def bind_graph_dynamic_evidence_from_env(
    container: Container,
    *,
    state_store: StateStore,
    environ: Mapping[str, str],
) -> Container:
    """Bind graph Dynamic only from one complete strict JSON configuration."""

    raw = environ.get(GRAPH_DYNAMIC_CONFIG_ENV, "").strip()
    if not raw:
        return container
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{GRAPH_DYNAMIC_CONFIG_ENV} MUST contain valid JSON") from exc
    if not isinstance(value, Mapping) or set(value) != {
        "actions",
        "causal_receipt_digests",
        "models",
    }:
        raise ValueError(
            f"{GRAPH_DYNAMIC_CONFIG_ENV} MUST contain only actions, "
            "causal_receipt_digests, and models"
        )
    raw_actions = value.get("actions")
    raw_digests = value.get("causal_receipt_digests")
    raw_models = value.get("models")
    if (
        not isinstance(raw_actions, Mapping)
        or not 1 <= len(raw_actions) <= _MAX_ACTIONS
        or not isinstance(raw_digests, list)
        or any(not isinstance(item, str) for item in raw_digests)
        or not isinstance(raw_models, list)
        or not 2 <= len(raw_models) <= _MAX_MODELS
    ):
        raise ValueError("graph Dynamic actions, causal digests, and models are invalid")

    policies = {
        action_type: _policy(action_type, raw_action)
        for action_type, raw_action in raw_actions.items()
        if isinstance(action_type, str) and isinstance(raw_action, Mapping)
    }
    if len(policies) != len(raw_actions):
        raise ValueError("graph Dynamic action identities MUST be non-empty objects")
    verifier = ConfiguredGraphCausalEvidenceVerifier(frozenset(raw_digests))
    models = tuple(_model(item) for item in raw_models)
    trigger_refs = tuple(sorted(policy.action_type_ref for policy in policies.values()))
    if any(model.trigger_ref not in trigger_refs or not verifier.verify(model) for model in models):
        raise ValueError("graph Dynamic model scope or causal receipt is not configured")
    for trigger_ref in trigger_refs:
        statuses = {model.status for model in models if model.trigger_ref == trigger_ref}
        if statuses != {EffectModelStatus.ACTIVE, EffectModelStatus.CHALLENGER}:
            raise ValueError(
                f"graph Dynamic trigger {trigger_ref!r} requires active and challenger models"
            )

    inventory_context = _build_inventory_context_provider()
    if inventory_context is None:
        raise ValueError("graph Dynamic configuration requires durable inventory context")
    registry = StateStoreGraphEffectModelRegistry(state_store)
    for model in models:
        created = await registry.register(model, registered_by="Mimir")
        if created:
            continue
        stored = await registry.list_models(
            status=model.status,
            trigger_refs=(model.trigger_ref,),
        )
        matching = tuple(item for item in stored if _same_scope(item, model))
        if len(matching) != 1:
            raise ValueError("stored graph Dynamic model is missing or ambiguous")
        if model.status is EffectModelStatus.ACTIVE and matching[0] != model:
            raise ValueError("stored active graph Dynamic model conflicts with config")
        if model.status is EffectModelStatus.CHALLENGER and not _challenger_descends_from(
            matching[0], model
        ):
            raise ValueError("stored graph Dynamic challenger conflicts with configured lineage")

    return replace(
        container,
        graph_dynamic_simulation_request_provider=AzureGraphDynamicSimulationRequestProvider(
            snapshots=AzureCachedGraphOperationalSnapshotSource(inventory_context),
            policies=policies,
        ),
        graph_effect_model_reader=registry,
        graph_effect_model_causal_evidence_verifier=verifier,
    )


def _policy(action_type: str, value: Mapping[object, object]) -> AzureGraphDynamicPolicy:
    expected = {
        "action_type_ref",
        "metric",
        "effect_delta",
        "horizon_seconds",
        "divergence_threshold",
        "max_snapshot_age_seconds",
        "max_edges",
        "max_slices",
        "invariants",
    }
    if not action_type or set(value) != expected:
        raise ValueError(f"graph Dynamic action {action_type!r} has unexpected fields")
    action_type_ref = _text(value, "action_type_ref")
    if not action_type_ref.startswith(f"action-type:{action_type}@"):
        raise ValueError("graph Dynamic action_type_ref does not match its action key")
    raw_invariants = value.get("invariants")
    if not isinstance(raw_invariants, list) or not 1 <= len(raw_invariants) <= 256:
        raise ValueError("graph Dynamic invariants MUST contain 1..256 entries")
    return AzureGraphDynamicPolicy(
        action_type_ref=action_type_ref,
        metric=_text(value, "metric"),
        effect_delta=_finite(value, "effect_delta"),
        horizon=timedelta(seconds=_positive_integer(value, "horizon_seconds")),
        invariants=tuple(_invariant(item) for item in raw_invariants),
        divergence_threshold=_nonnegative(value, "divergence_threshold"),
        max_snapshot_age=timedelta(seconds=_positive_integer(value, "max_snapshot_age_seconds")),
        max_edges=_positive_integer(value, "max_edges"),
        max_slices=_positive_integer(value, "max_slices"),
    )


def _invariant(value: object) -> DynamicInvariant:
    if not isinstance(value, Mapping) or set(value) not in (
        {"invariant_id", "metric", "operator", "threshold"},
        {"invariant_id", "metric", "operator", "threshold", "target_ref"},
    ):
        raise ValueError("graph Dynamic invariant has unexpected fields")
    target_ref = value.get("target_ref")
    if target_ref is not None and (not isinstance(target_ref, str) or not target_ref):
        raise ValueError("graph Dynamic invariant target_ref MUST be non-empty")
    return DynamicInvariant(
        invariant_id=_text(value, "invariant_id"),
        metric=_text(value, "metric"),
        operator=InvariantOperator(_text(value, "operator")),
        threshold=_finite(value, "threshold"),
        target_ref=target_ref,
    )


def _model(value: object) -> GraphEffectModel:
    if not isinstance(value, Mapping) or set(value) != {
        "model_id",
        "version",
        "revision",
        "status",
        "trigger_ref",
        "source_type",
        "link_path",
        "target_type",
        "target_metric",
        "propagation_lag_seconds",
        "gain",
        "offset",
        "interval_radius",
        "evidence_grade",
        "causal_evidence_receipt_digest",
        "learned_through",
        "sample_count",
        "mean_absolute_error",
        "applied_observation_digests",
    }:
        raise ValueError("graph Dynamic model has unexpected fields")
    link_path = value.get("link_path")
    applied = value.get("applied_observation_digests")
    if not isinstance(link_path, list) or any(not isinstance(item, str) for item in link_path):
        raise ValueError("graph Dynamic model link_path MUST be a string array")
    if not isinstance(applied, list) or any(not isinstance(item, str) for item in applied):
        raise ValueError("graph Dynamic model observation digests MUST be a string array")
    return GraphEffectModel(
        model_id=_text(value, "model_id"),
        version=_text(value, "version"),
        revision=_positive_integer(value, "revision"),
        status=EffectModelStatus(_text(value, "status")),
        trigger_ref=_text(value, "trigger_ref"),
        source_type=_text(value, "source_type"),
        link_path=tuple(link_path),
        target_type=_text(value, "target_type"),
        target_metric=_text(value, "target_metric"),
        propagation_lag_seconds=_nonnegative_integer(value, "propagation_lag_seconds"),
        gain=_finite(value, "gain"),
        offset=_finite(value, "offset"),
        interval_radius=_nonnegative(value, "interval_radius"),
        evidence_grade=CausalEvidenceGrade(_text(value, "evidence_grade")),
        causal_evidence_receipt_digest=_text(value, "causal_evidence_receipt_digest"),
        learned_through=_timestamp(value, "learned_through"),
        sample_count=_nonnegative_integer(value, "sample_count"),
        mean_absolute_error=_nonnegative(value, "mean_absolute_error"),
        applied_observation_digests=tuple(applied),
    )


def _same_scope(first: GraphEffectModel, second: GraphEffectModel) -> bool:
    return (
        first.trigger_ref,
        first.source_type,
        first.link_path,
        first.target_type,
        first.target_metric,
    ) == (
        second.trigger_ref,
        second.source_type,
        second.link_path,
        second.target_type,
        second.target_metric,
    )


def _challenger_descends_from(
    existing: GraphEffectModel,
    configured: GraphEffectModel,
) -> bool:
    return (
        existing.status is EffectModelStatus.CHALLENGER
        and _same_scope(existing, configured)
        and existing.model_id == configured.model_id
        and existing.version == configured.version
        and existing.evidence_grade is configured.evidence_grade
        and existing.causal_evidence_receipt_digest == configured.causal_evidence_receipt_digest
        and existing.revision >= configured.revision
        and existing.learned_through >= configured.learned_through
        and existing.sample_count >= configured.sample_count
    )


def _text(value: Mapping[object, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"graph Dynamic {key} MUST be non-empty")
    return item


def _finite(value: Mapping[object, object], key: str) -> float:
    item = value.get(key)
    if not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item):
        raise ValueError(f"graph Dynamic {key} MUST be finite")
    return float(item)


def _nonnegative(value: Mapping[object, object], key: str) -> float:
    item = _finite(value, key)
    if item < 0:
        raise ValueError(f"graph Dynamic {key} MUST be non-negative")
    return item


def _positive_integer(value: Mapping[object, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 1:
        raise ValueError(f"graph Dynamic {key} MUST be a positive integer")
    return item


def _nonnegative_integer(value: Mapping[object, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"graph Dynamic {key} MUST be a non-negative integer")
    return item


def _timestamp(value: Mapping[object, object], key: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, key).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"graph Dynamic {key} MUST be timezone-aware")
    return parsed


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "ConfiguredGraphCausalEvidenceVerifier",
    "GRAPH_DYNAMIC_CONFIG_ENV",
    "bind_graph_dynamic_evidence_from_env",
]
