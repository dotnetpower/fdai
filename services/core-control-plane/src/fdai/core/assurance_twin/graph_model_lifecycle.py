"""Governed active-pointer lifecycle for immutable graph effect models."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.core.assurance_twin.effect_model import CausalEvidenceGrade, EffectModelStatus
from fdai.core.assurance_twin.graph_effect import GraphEffectModel
from fdai.core.assurance_twin.graph_model_registry import StateStoreGraphEffectModelRegistry
from fdai.shared.providers.state_store import StateStore

_PREFIX = "dynamic-graph-effect-model-lifecycle:"
_MAX_RECORDS = 1000
_MAX_CAS_ATTEMPTS = 64


class GraphEffectModelLifecycleConflictError(RuntimeError):
    """A stale or conflicting model lifecycle transition was requested."""


class GraphEffectModelPromotionReceiptView(Protocol):
    """Receipt fields required by the lifecycle writer."""

    @property
    def model_ref(self) -> str: ...

    @property
    def model_artifact_digest(self) -> str: ...

    @property
    def expected_active_ref(self) -> str | None: ...

    @property
    def challenger_ref(self) -> str: ...

    @property
    def rollback_ref(self) -> str | None: ...

    @property
    def ontology_release_digest(self) -> str: ...

    @property
    def property_semantics_digest(self) -> str: ...

    @property
    def causal_evidence_receipt_digest(self) -> str: ...

    @property
    def applicability_conditions(self) -> tuple[str, ...]: ...

    @property
    def evidence_grade(self) -> CausalEvidenceGrade: ...

    @property
    def evidence_cutoff(self) -> datetime: ...

    @property
    def ready(self) -> bool: ...

    @property
    def receipt_digest(self) -> str: ...

    def verify_model(self, model: GraphEffectModel) -> bool: ...


@dataclass(frozen=True, slots=True)
class GraphEffectModelLifecycleRecord:
    """Current active pointer and retained rollback target for one model scope."""

    scope_digest: str
    revision: int
    active_ref: str | None
    challenger_ref: str
    rollback_ref: str | None
    promotion_receipt_digest: str
    model_artifact_digest: str
    ontology_release_digest: str
    property_semantics_digest: str
    applicability_conditions: tuple[str, ...]
    promoted_at: datetime


class StateStoreGraphEffectModelLifecycleRegistry:
    """Read graph models through a CAS-governed active pointer."""

    def __init__(
        self,
        *,
        store: StateStore,
        models: StateStoreGraphEffectModelRegistry,
    ) -> None:
        self._store = store
        self._models = models

    async def list_models(
        self,
        *,
        status: EffectModelStatus,
        trigger_refs: tuple[str, ...],
    ) -> tuple[GraphEffectModel, ...]:
        """Return challenger artifacts or active-pointer projections."""

        if status is EffectModelStatus.CHALLENGER:
            return await self._models.list_models(status=status, trigger_refs=trigger_refs)
        rows = await self._store.read_states(_PREFIX, limit=_MAX_RECORDS)
        if len(rows) >= _MAX_RECORDS:
            raise ValueError("graph effect model lifecycle registry is truncated")
        records = tuple(_deserialize(row) for row in rows)
        lifecycle_models: list[GraphEffectModel] = []
        governed_scopes: set[str] = set()
        for record in records:
            governed_scopes.add(record.scope_digest)
            if record.active_ref is None:
                continue
            model = await self._models.get_by_ref(record.active_ref)
            if model is None:
                raise ValueError("graph effect model active pointer target is unavailable")
            _validate_record_model(record, model)
            if model.trigger_ref in trigger_refs:
                lifecycle_models.append(replace(model, status=EffectModelStatus.ACTIVE))
        legacy = await self._models.list_models(
            status=EffectModelStatus.ACTIVE,
            trigger_refs=trigger_refs,
        )
        fallback = tuple(
            model for model in legacy if graph_model_scope_digest(model) not in governed_scopes
        )
        return tuple(
            sorted(
                (*lifecycle_models, *fallback),
                key=lambda item: (item.trigger_ref, item.model_id, item.version, item.revision),
            )
        )

    async def promote(
        self,
        *,
        receipt: GraphEffectModelPromotionReceiptView,
        actor: str,
        promoted_at: datetime,
    ) -> GraphEffectModelLifecycleRecord:
        """Atomically select one immutable challenger as active."""

        if not actor:
            raise ValueError("graph model promotion actor MUST be non-empty")
        if promoted_at.tzinfo is None:
            raise ValueError("graph model promotion timestamp MUST be timezone-aware")
        if not receipt.ready:
            raise ValueError("graph model promotion receipt is not ready")
        model = await self._models.get_by_ref(receipt.challenger_ref)
        if model is None or model.status is not EffectModelStatus.CHALLENGER:
            raise ValueError("graph model promotion challenger is unavailable")
        _validate_receipt_model(receipt, model)
        scope_digest = graph_model_scope_digest(model)
        key = f"{_PREFIX}{scope_digest}"
        for _ in range(_MAX_CAS_ATTEMPTS):
            raw = await self._store.read_state(key)
            if raw is None:
                current_active = await self._legacy_active_ref(model)
                _validate_expected_active(receipt, current_active)
                record = _promotion_record(
                    model=model,
                    receipt=receipt,
                    scope_digest=scope_digest,
                    revision=1,
                    promoted_at=promoted_at,
                )
                if await self._store.write_state_with_audit_if_absent(
                    key,
                    _serialize(record),
                    _audit(record, actor=actor, action_kind="graph_effect_model.promoted"),
                ):
                    return record
                continue
            current = _deserialize(raw)
            if (
                current.active_ref == model.ref
                and current.promotion_receipt_digest == receipt.receipt_digest
            ):
                return current
            _validate_expected_active(receipt, current.active_ref)
            record = _promotion_record(
                model=model,
                receipt=receipt,
                scope_digest=scope_digest,
                revision=current.revision + 1,
                promoted_at=promoted_at,
            )
            if await self._store.compare_and_set_state_with_audit(
                key,
                _serialize(record),
                expected_revision=current.revision,
                audit_entry=_audit(
                    record,
                    actor=actor,
                    action_kind="graph_effect_model.promoted",
                ),
            ):
                return record
        raise RuntimeError("graph effect model promotion conflicted repeatedly")

    async def rollback(
        self,
        *,
        scope_digest: str,
        expected_active_ref: str,
        promotion_receipt_digest: str,
        actor: str,
        rolled_back_at: datetime,
    ) -> GraphEffectModelLifecycleRecord:
        """Restore the retained prior pointer or clear first-promotion active state."""

        if not actor or rolled_back_at.tzinfo is None:
            raise ValueError("graph model rollback actor and timestamp are required")
        key = f"{_PREFIX}{scope_digest}"
        for _ in range(_MAX_CAS_ATTEMPTS):
            raw = await self._store.read_state(key)
            if raw is None:
                raise GraphEffectModelLifecycleConflictError(
                    "graph model lifecycle rollback target is unavailable"
                )
            current = _deserialize(raw)
            if (
                current.active_ref != expected_active_ref
                or current.promotion_receipt_digest != promotion_receipt_digest
            ):
                raise GraphEffectModelLifecycleConflictError(
                    "graph model lifecycle rollback identity is stale"
                )
            rollback_model = (
                await self._models.get_by_ref(current.rollback_ref)
                if current.rollback_ref is not None
                else None
            )
            if current.rollback_ref is not None and rollback_model is None:
                raise ValueError("graph model lifecycle rollback artifact is unavailable")
            if rollback_model is not None and not rollback_model.promotable:
                raise ValueError("graph model lifecycle rollback artifact lacks governed identity")
            if (
                rollback_model is not None
                and graph_model_scope_digest(rollback_model) != scope_digest
            ):
                raise ValueError("graph model lifecycle rollback artifact scope mismatched")
            record = replace(
                current,
                revision=current.revision + 1,
                active_ref=current.rollback_ref,
                rollback_ref=None,
                model_artifact_digest=(
                    rollback_model.artifact_digest
                    if rollback_model is not None and rollback_model.artifact_digest is not None
                    else current.model_artifact_digest
                ),
                ontology_release_digest=(
                    rollback_model.ontology_release_digest
                    if rollback_model is not None
                    and rollback_model.ontology_release_digest is not None
                    else current.ontology_release_digest
                ),
                property_semantics_digest=(
                    rollback_model.property_semantics_digest
                    if rollback_model is not None
                    and rollback_model.property_semantics_digest is not None
                    else current.property_semantics_digest
                ),
                applicability_conditions=(
                    rollback_model.applicability_conditions
                    if rollback_model is not None
                    else current.applicability_conditions
                ),
                promoted_at=rolled_back_at.astimezone(UTC),
            )
            if await self._store.compare_and_set_state_with_audit(
                key,
                _serialize(record),
                expected_revision=current.revision,
                audit_entry=_audit(
                    record,
                    actor=actor,
                    action_kind="graph_effect_model.rolled_back",
                ),
            ):
                return record
        raise RuntimeError("graph effect model rollback conflicted repeatedly")

    async def _legacy_active_ref(self, challenger: GraphEffectModel) -> str | None:
        active = await self._models.list_models(
            status=EffectModelStatus.ACTIVE,
            trigger_refs=(challenger.trigger_ref,),
        )
        matches = tuple(model for model in active if _same_scope(model, challenger))
        if len(matches) > 1:
            raise ValueError("legacy graph active model scope is ambiguous")
        return matches[0].ref if matches else None


def graph_model_scope_digest(model: GraphEffectModel) -> str:
    """Return the stable applicability scope used by the lifecycle pointer."""

    material = {
        "trigger_ref": model.trigger_ref,
        "source_type": model.source_type,
        "link_path": list(model.link_path),
        "target_type": model.target_type,
        "target_metric": model.target_metric,
        "ontology_release_digest": model.ontology_release_digest,
        "property_semantics_digest": model.property_semantics_digest,
        "applicability_conditions": list(model.applicability_conditions),
    }
    encoded = json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _promotion_record(
    *,
    model: GraphEffectModel,
    receipt: GraphEffectModelPromotionReceiptView,
    scope_digest: str,
    revision: int,
    promoted_at: datetime,
) -> GraphEffectModelLifecycleRecord:
    artifact_digest = model.artifact_digest
    ontology_release_digest = model.ontology_release_digest
    property_semantics_digest = model.property_semantics_digest
    if (
        artifact_digest is None
        or ontology_release_digest is None
        or property_semantics_digest is None
    ):
        raise ValueError("graph model promotion requires governed artifact identity")
    return GraphEffectModelLifecycleRecord(
        scope_digest=scope_digest,
        revision=revision,
        active_ref=model.ref,
        challenger_ref=model.ref,
        rollback_ref=receipt.rollback_ref,
        promotion_receipt_digest=receipt.receipt_digest,
        model_artifact_digest=artifact_digest,
        ontology_release_digest=ontology_release_digest,
        property_semantics_digest=property_semantics_digest,
        applicability_conditions=model.applicability_conditions,
        promoted_at=promoted_at.astimezone(UTC),
    )


def _validate_receipt_model(
    receipt: GraphEffectModelPromotionReceiptView,
    model: GraphEffectModel,
) -> None:
    if (
        not receipt.verify_model(model)
        or receipt.model_ref != model.ref
        or receipt.challenger_ref != model.ref
        or receipt.model_artifact_digest != model.artifact_digest
        or receipt.ontology_release_digest != model.ontology_release_digest
        or receipt.property_semantics_digest != model.property_semantics_digest
        or receipt.causal_evidence_receipt_digest != model.causal_evidence_receipt_digest
        or receipt.applicability_conditions != model.applicability_conditions
        or receipt.evidence_grade is not model.evidence_grade
        or receipt.evidence_cutoff < model.learned_through
    ):
        raise ValueError("graph model promotion receipt does not match challenger identity")


def _validate_expected_active(
    receipt: GraphEffectModelPromotionReceiptView,
    current_active_ref: str | None,
) -> None:
    if (
        receipt.expected_active_ref != current_active_ref
        or receipt.rollback_ref != current_active_ref
    ):
        raise GraphEffectModelLifecycleConflictError(
            "graph model promotion expected active pointer is stale"
        )


def _validate_record_model(
    record: GraphEffectModelLifecycleRecord,
    model: GraphEffectModel,
) -> None:
    if (
        record.scope_digest != graph_model_scope_digest(model)
        or record.model_artifact_digest != model.artifact_digest
        or record.ontology_release_digest != model.ontology_release_digest
        or record.property_semantics_digest != model.property_semantics_digest
        or record.applicability_conditions != model.applicability_conditions
    ):
        raise ValueError("graph effect model lifecycle record is not bound to artifact")


def _same_scope(first: GraphEffectModel, second: GraphEffectModel) -> bool:
    return graph_model_scope_digest(first) == graph_model_scope_digest(second)


def _serialize(record: GraphEffectModelLifecycleRecord) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "scope_digest": record.scope_digest,
        "revision": record.revision,
        "active_ref": record.active_ref,
        "challenger_ref": record.challenger_ref,
        "rollback_ref": record.rollback_ref,
        "promotion_receipt_digest": record.promotion_receipt_digest,
        "model_artifact_digest": record.model_artifact_digest,
        "ontology_release_digest": record.ontology_release_digest,
        "property_semantics_digest": record.property_semantics_digest,
        "applicability_conditions": list(record.applicability_conditions),
        "promoted_at": record.promoted_at.isoformat(),
    }


def _deserialize(raw: Mapping[str, Any]) -> GraphEffectModelLifecycleRecord:
    expected = {
        "schema_version",
        "scope_digest",
        "revision",
        "active_ref",
        "challenger_ref",
        "rollback_ref",
        "promotion_receipt_digest",
        "model_artifact_digest",
        "ontology_release_digest",
        "property_semantics_digest",
        "applicability_conditions",
        "promoted_at",
    }
    if set(raw) != expected or raw.get("schema_version") != "1.0.0":
        raise ValueError("unsupported graph effect model lifecycle state")
    conditions = raw.get("applicability_conditions")
    if not isinstance(conditions, list) or any(not isinstance(item, str) for item in conditions):
        raise ValueError("graph model lifecycle applicability conditions are invalid")
    revision = raw.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValueError("graph model lifecycle revision is invalid")
    return GraphEffectModelLifecycleRecord(
        scope_digest=_text(raw, "scope_digest"),
        revision=revision,
        active_ref=_optional_text(raw, "active_ref"),
        challenger_ref=_text(raw, "challenger_ref"),
        rollback_ref=_optional_text(raw, "rollback_ref"),
        promotion_receipt_digest=_text(raw, "promotion_receipt_digest"),
        model_artifact_digest=_text(raw, "model_artifact_digest"),
        ontology_release_digest=_text(raw, "ontology_release_digest"),
        property_semantics_digest=_text(raw, "property_semantics_digest"),
        applicability_conditions=tuple(conditions),
        promoted_at=_time(raw, "promoted_at"),
    )


def _audit(
    record: GraphEffectModelLifecycleRecord,
    *,
    actor: str,
    action_kind: str,
) -> dict[str, object]:
    return {
        "actor": actor,
        "producer_principal": actor,
        "lifecycle_owner": "Mimir",
        "audit_owner": "Saga",
        "action_kind": action_kind,
        "mode": "enforce",
        "scope_digest": record.scope_digest,
        "active_ref": record.active_ref,
        "challenger_ref": record.challenger_ref,
        "rollback_ref": record.rollback_ref,
        "promotion_receipt_digest": record.promotion_receipt_digest,
        "revision": record.revision,
        "recorded_at": record.promoted_at.isoformat(),
        "grants_execution_authority": False,
        "promotes_action_type": False,
    }


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"graph model lifecycle {key} MUST be non-empty")
    return value


def _optional_text(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"graph model lifecycle {key} MUST be non-empty when present")
    return value


def _time(raw: Mapping[str, Any], key: str) -> datetime:
    parsed = datetime.fromisoformat(_text(raw, key).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"graph model lifecycle {key} MUST be timezone-aware")
    return parsed.astimezone(UTC)


__all__ = [
    "GraphEffectModelLifecycleConflictError",
    "GraphEffectModelLifecycleRecord",
    "StateStoreGraphEffectModelLifecycleRegistry",
    "graph_model_scope_digest",
]
