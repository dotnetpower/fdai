"""Strict production composition for scalar Dynamic operational evidence."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta

from fdai.composition import Container
from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    EffectModel,
    EffectModelStatus,
    StateStoreEffectModelRegistry,
)
from fdai.delivery.azure.operational_evidence import (
    AzureCachedOperationalSnapshotSource,
    AzureConfiguredBranchEffect,
    AzureConfiguredBranchEstimator,
    AzureDynamicPolicy,
    AzureDynamicSimulationRequestProvider,
)
from fdai.runtime.providers import _build_inventory_context_provider
from fdai.shared.providers.state_store import StateStore

DYNAMIC_CONFIG_ENV = "FDAI_DYNAMIC_CONFIG_JSON"
_MAX_ACTIONS = 64


class ConfiguredCausalEvidenceVerifier:
    """Accept only model receipts explicitly admitted by deployment configuration."""

    def __init__(self, digests: frozenset[str]) -> None:
        if not digests or len(digests) > 256 or any(not _is_digest(item) for item in digests):
            raise ValueError("Dynamic causal receipt digests MUST contain 1..256 SHA-256 values")
        self._digests = digests

    def verify(self, model: EffectModel) -> bool:
        return model.causal_evidence_receipt_digest in self._digests


async def bind_dynamic_evidence_from_env(
    container: Container,
    *,
    state_store: StateStore,
    environ: Mapping[str, str],
) -> Container:
    """Bind Dynamic only when one complete strict JSON configuration is present."""

    raw = environ.get(DYNAMIC_CONFIG_ENV, "").strip()
    if not raw:
        return container
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{DYNAMIC_CONFIG_ENV} MUST contain valid JSON") from exc
    if not isinstance(value, Mapping) or set(value) != {
        "actions",
        "causal_receipt_digests",
        "models",
    }:
        raise ValueError(
            f"{DYNAMIC_CONFIG_ENV} MUST contain only actions, causal_receipt_digests, and models"
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
        or not 2 <= len(raw_models) <= _MAX_ACTIONS * 2
    ):
        raise ValueError(f"{DYNAMIC_CONFIG_ENV} actions and receipt digests are invalid")

    policies: dict[str, AzureDynamicPolicy] = {}
    effects: dict[str, AzureConfiguredBranchEffect] = {}
    for action_type, raw_action in raw_actions.items():
        if (
            not isinstance(action_type, str)
            or not action_type
            or not isinstance(raw_action, Mapping)
        ):
            raise ValueError("Dynamic action configuration identity MUST be non-empty")
        expected = {
            "metric",
            "objective",
            "effect_delta",
            "interval_radius",
            "divergence_threshold",
            "max_snapshot_age_seconds",
        }
        if set(raw_action) != expected:
            raise ValueError(f"Dynamic action {action_type!r} has unexpected fields")
        metric = _text(raw_action, "metric")
        objective = _text(raw_action, "objective")
        if objective not in {"minimize", "maximize"}:
            raise ValueError("Dynamic objective MUST be minimize or maximize")
        effect_delta = _finite(raw_action, "effect_delta")
        interval_radius = _nonnegative(raw_action, "interval_radius")
        divergence_threshold = _nonnegative(raw_action, "divergence_threshold")
        max_age = _positive_integer(raw_action, "max_snapshot_age_seconds")
        policies[action_type] = AzureDynamicPolicy(
            metric=metric,
            objective=objective,  # type: ignore[arg-type]
            divergence_threshold=divergence_threshold,
            max_snapshot_age=timedelta(seconds=max_age),
        )
        effects[action_type] = AzureConfiguredBranchEffect(
            metric=metric,
            delta=effect_delta,
            interval_radius=interval_radius,
        )

    inventory_context = _build_inventory_context_provider()
    if inventory_context is None:
        raise ValueError("Dynamic configuration requires durable inventory context")
    snapshots = AzureCachedOperationalSnapshotSource(inventory_context)
    registry = StateStoreEffectModelRegistry(state_store)
    verifier = ConfiguredCausalEvidenceVerifier(frozenset(raw_digests))
    models = tuple(_effect_model(item) for item in raw_models)
    configured_scopes = {(action_type, policy.metric) for action_type, policy in policies.items()}
    for scope in configured_scopes:
        statuses = {
            model.status for model in models if (model.action_type_id, model.metric) == scope
        }
        if statuses != {EffectModelStatus.ACTIVE, EffectModelStatus.CHALLENGER}:
            raise ValueError(f"Dynamic scope {scope!r} requires exact active and challenger models")
    for model in models:
        scope = (model.action_type_id, model.metric)
        if scope not in configured_scopes or not verifier.verify(model):
            raise ValueError("Dynamic model scope or causal receipt is not configured")
        existing = await registry.get(
            status=model.status,
            action_type_id=model.action_type_id,
            metric=model.metric,
        )
        if existing is None:
            await registry.register(model, registered_by="Mimir")
        elif model.status is EffectModelStatus.ACTIVE and existing != model:
            raise ValueError("stored Dynamic model conflicts with configured exact model")
        elif model.status is EffectModelStatus.CHALLENGER and not _challenger_descends_from(
            existing,
            model,
        ):
            raise ValueError("stored Dynamic challenger conflicts with configured model lineage")
    return replace(
        container,
        dynamic_simulation_request_provider=AzureDynamicSimulationRequestProvider(
            snapshots=snapshots,
            estimator=AzureConfiguredBranchEstimator(effects),
            policies=policies,
        ),
        effect_model_reader=registry,
        effect_model_causal_evidence_verifier=verifier,
    )


def _text(value: Mapping[object, object], key: str) -> str:
    item = value.get(key)

    def _challenger_descends_from(existing: EffectModel, configured: EffectModel) -> bool:
        return (
            existing.status is EffectModelStatus.CHALLENGER
            and existing.model_id == configured.model_id
            and existing.version == configured.version
            and existing.action_type_id == configured.action_type_id
            and existing.metric == configured.metric
            and existing.evidence_grade is configured.evidence_grade
            and existing.causal_evidence_receipt_digest == configured.causal_evidence_receipt_digest
            and existing.learned_at == configured.learned_at
            and existing.revision >= configured.revision
            and existing.learned_through >= configured.learned_through
            and existing.sample_count >= configured.sample_count
        )

    if not isinstance(item, str) or not item:
        raise ValueError(f"Dynamic action {key} MUST be non-empty")
    return item


def _finite(value: Mapping[object, object], key: str) -> float:
    item = value.get(key)
    if not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item):
        raise ValueError(f"Dynamic action {key} MUST be finite")
    return float(item)


def _nonnegative(value: Mapping[object, object], key: str) -> float:
    item = _finite(value, key)
    if item < 0.0:
        raise ValueError(f"Dynamic action {key} MUST be non-negative")
    return item


def _positive_integer(value: Mapping[object, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 1:
        raise ValueError(f"Dynamic action {key} MUST be a positive integer")
    return item


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _challenger_descends_from(existing: EffectModel, configured: EffectModel) -> bool:
    return (
        existing.status is EffectModelStatus.CHALLENGER
        and existing.model_id == configured.model_id
        and existing.version == configured.version
        and existing.action_type_id == configured.action_type_id
        and existing.metric == configured.metric
        and existing.evidence_grade is configured.evidence_grade
        and existing.causal_evidence_receipt_digest == configured.causal_evidence_receipt_digest
        and existing.learned_at == configured.learned_at
        and existing.revision >= configured.revision
        and existing.learned_through >= configured.learned_through
        and existing.sample_count >= configured.sample_count
    )


def _effect_model(value: object) -> EffectModel:
    if not isinstance(value, Mapping):
        raise ValueError("Dynamic model MUST be an object")
    expected = {
        "model_id",
        "version",
        "revision",
        "action_type_id",
        "metric",
        "status",
        "evidence_grade",
        "causal_evidence_receipt_digest",
        "learned_at",
        "learned_through",
        "sample_count",
        "bias_correction",
        "mean_absolute_error",
        "interval_radius",
    }
    if set(value) != expected:
        raise ValueError("Dynamic model has unexpected fields")
    return EffectModel(
        model_id=_text(value, "model_id"),
        version=_text(value, "version"),
        revision=_positive_integer(value, "revision"),
        action_type_id=_text(value, "action_type_id"),
        metric=_text(value, "metric"),
        status=EffectModelStatus(_text(value, "status")),
        evidence_grade=CausalEvidenceGrade(_text(value, "evidence_grade")),
        causal_evidence_receipt_digest=_text(value, "causal_evidence_receipt_digest"),
        learned_at=_timestamp(value, "learned_at"),
        learned_through=_timestamp(value, "learned_through"),
        sample_count=_nonnegative_integer(value, "sample_count"),
        bias_correction=_finite(value, "bias_correction"),
        mean_absolute_error=_nonnegative(value, "mean_absolute_error"),
        interval_radius=_nonnegative(value, "interval_radius"),
    )


def _nonnegative_integer(value: Mapping[object, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"Dynamic model {key} MUST be a non-negative integer")
    return item


def _timestamp(value: Mapping[object, object], key: str) -> datetime:
    text = _text(value, key)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Dynamic model {key} MUST be timezone-aware")
    return parsed


__all__ = [
    "ConfiguredCausalEvidenceVerifier",
    "DYNAMIC_CONFIG_ENV",
    "bind_dynamic_evidence_from_env",
]
