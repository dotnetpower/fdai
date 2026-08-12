"""StateStore persistence for governed GraphEffectModel promotion and rollback."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.assurance_twin.effect_model import CausalEvidenceGrade, EffectModelStatus
from fdai.core.assurance_twin.graph_effect import GraphEffectModel
from fdai.core.assurance_twin.model_promotion import (
    GraphModelActivePointer,
    GraphModelEvidenceCohort,
    GraphModelPromotionPolicy,
    GraphModelPromotionReceipt,
    GraphModelRisk,
    graph_effect_model_digest,
    validate_graph_model_promotion,
)
from fdai.shared.providers.state_store import StateStore

_ARTIFACT_PREFIX = "graph-model-promotion:artifact:"
_RECEIPT_PREFIX = "graph-model-promotion:receipt:"
_ACTIVE_PREFIX = "graph-model-promotion:active:"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MODEL_FIELDS = frozenset(
    {
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
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "model_id",
        "model_version",
        "model_revision",
        "model_digest",
        "slot_digest",
        "ontology_release_digest",
        "property_semantics_digest",
        "causal_receipt_digest",
        "evidence_grade",
        "cohort",
        "risk",
        "sample_count",
        "confidence_interval_lower",
        "confidence_interval_upper",
        "fidelity",
        "recurrence_window_complete",
        "recurrence_rate",
        "policy_escapes",
        "invariant_evidence_digests",
        "expected_pointer_revision",
        "rollback_model_ref",
        "rollback_model_digest",
        "sealed_at",
    }
)
_POINTER_FIELDS = frozenset(
    {
        "schema_version",
        "slot_digest",
        "revision",
        "active_model_ref",
        "active_model_digest",
        "prior_active_model_ref",
        "prior_active_model_digest",
        "promotion_receipt_digest",
    }
)


@dataclass(frozen=True, slots=True)
class GraphModelPointerUpdate:
    """Result of one bounded active-pointer CAS operation."""

    applied: bool
    reason: str
    pointer: GraphModelActivePointer


class StateStoreGraphModelPromotionRegistry:
    """Persist immutable evidence and change only active pointers with audited CAS."""

    def __init__(
        self,
        *,
        store: StateStore,
        ontology_release_digest: str,
        property_semantics_digest: str,
        policy: GraphModelPromotionPolicy | None = None,
        max_retries: int = 2,
    ) -> None:
        _require_digest(ontology_release_digest, "ontology release")
        _require_digest(property_semantics_digest, "property semantics")
        if not 1 <= max_retries <= 2:
            raise ValueError("graph model promotion retries MUST be in [1, 2]")
        self._store = store
        self._ontology_release_digest = ontology_release_digest
        self._property_semantics_digest = property_semantics_digest
        self._policy = policy or GraphModelPromotionPolicy()
        self._max_retries = max_retries

    async def save_artifact(self, model: GraphEffectModel, *, recorded_by: str) -> str:
        """Store one immutable model snapshot without changing its active status."""

        _require_actor(recorded_by)
        digest = graph_effect_model_digest(model)
        value = {"schema_version": "1.0.0", "model": _encode_model(model)}
        created = await self._store.write_state_with_audit_if_absent(
            f"{_ARTIFACT_PREFIX}{digest}",
            value,
            {
                "actor": recorded_by,
                "producer_principal": "Norns",
                "action_kind": "graph_model_promotion.artifact_stored",
                "mode": "shadow",
                "model_ref": model.ref,
                "model_digest": digest,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            },
        )
        if not created and await self.load_artifact(digest) != model:
            raise ValueError("graph model promotion artifact key collision")
        return digest

    async def load_artifact(self, model_digest: str) -> GraphEffectModel | None:
        """Load and content-verify one exact immutable model artifact."""

        _require_digest(model_digest, "model")
        raw = await self._store.read_state(f"{_ARTIFACT_PREFIX}{model_digest}")
        if raw is None:
            return None
        model = _decode_envelope(raw, "model", _decode_model)
        if graph_effect_model_digest(model) != model_digest:
            raise ValueError("graph model promotion artifact digest mismatched")
        return model

    async def save_receipt(
        self,
        receipt: GraphModelPromotionReceipt,
        *,
        recorded_by: str,
    ) -> str:
        """Store one immutable promotion receipt without applying it."""

        _require_actor(recorded_by)
        digest = receipt.content_digest
        value = {"schema_version": "1.0.0", "receipt": _encode_receipt(receipt)}
        created = await self._store.write_state_with_audit_if_absent(
            f"{_RECEIPT_PREFIX}{digest}",
            value,
            {
                "actor": recorded_by,
                "producer_principal": "Mimir",
                "action_kind": "graph_model_promotion.receipt_stored",
                "mode": "shadow",
                "model_ref": receipt.model_ref,
                "model_digest": receipt.model_digest,
                "receipt_digest": digest,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            },
        )
        if not created and await self.load_receipt(digest) != receipt:
            raise ValueError("graph model promotion receipt key collision")
        return digest

    async def load_receipt(self, receipt_digest: str) -> GraphModelPromotionReceipt | None:
        """Load and content-verify one exact immutable promotion receipt."""

        _require_digest(receipt_digest, "promotion receipt")
        raw = await self._store.read_state(f"{_RECEIPT_PREFIX}{receipt_digest}")
        if raw is None:
            return None
        receipt = _decode_envelope(raw, "receipt", _decode_receipt)
        if receipt.content_digest != receipt_digest:
            raise ValueError("graph model promotion receipt digest mismatched")
        return receipt

    async def load_active(self, slot_digest: str) -> GraphModelActivePointer | None:
        """Read the current revisioned pointer for one graph-effect slot."""

        _require_digest(slot_digest, "active slot")
        raw = await self._store.read_state(f"{_ACTIVE_PREFIX}{slot_digest}")
        if raw is None:
            return None
        pointer = _decode_pointer(raw)
        if pointer.slot_digest != slot_digest:
            raise ValueError("graph model active pointer slot mismatched")
        return pointer

    async def promote(
        self,
        receipt: GraphModelPromotionReceipt,
        *,
        actor: str,
    ) -> GraphModelPointerUpdate:
        """Verify persisted evidence and atomically activate its challenger snapshot."""

        _require_actor(actor)
        persisted_receipt = await self.load_receipt(receipt.content_digest)
        if persisted_receipt != receipt:
            raise ValueError("exact graph model promotion receipt was not persisted")
        model = await self.load_artifact(receipt.model_digest)
        if model is None:
            raise ValueError("exact graph model promotion artifact was not found")
        for _ in range(self._max_retries):
            current = await self.load_active(receipt.slot_digest)
            if current is not None and _promotion_already_applied(current, receipt):
                return GraphModelPointerUpdate(False, "already_applied", current)
            validate_graph_model_promotion(
                receipt=receipt,
                model=model,
                current_pointer=current,
                expected_ontology_release_digest=self._ontology_release_digest,
                expected_property_semantics_digest=self._property_semantics_digest,
                policy=self._policy,
            )
            expected_revision = current.revision if current is not None else 0
            pointer = GraphModelActivePointer(
                slot_digest=receipt.slot_digest,
                revision=expected_revision + 1,
                active_model_ref=receipt.model_ref,
                active_model_digest=receipt.model_digest,
                prior_active_model_ref=receipt.rollback_model_ref,
                prior_active_model_digest=receipt.rollback_model_digest,
                promotion_receipt_digest=receipt.content_digest,
            )
            if await self._compare_and_set(pointer, expected_revision, actor, "promoted"):
                return GraphModelPointerUpdate(True, "promoted", pointer)
        latest = await self.load_active(receipt.slot_digest)
        if latest is None:
            raise ValueError("graph model promotion CAS conflict left no active pointer")
        if _promotion_already_applied(latest, receipt):
            return GraphModelPointerUpdate(False, "already_applied", latest)
        raise ValueError("graph model promotion pointer conflict")

    async def rollback(
        self,
        receipt: GraphModelPromotionReceipt,
        *,
        actor: str,
    ) -> GraphModelPointerUpdate:
        """Atomically restore only the prior active ref pinned by a promotion receipt."""

        _require_actor(actor)
        persisted_receipt = await self.load_receipt(receipt.content_digest)
        if persisted_receipt != receipt:
            raise ValueError("exact graph model rollback receipt was not persisted")
        for _ in range(self._max_retries):
            current = await self.load_active(receipt.slot_digest)
            if current is None:
                raise ValueError("graph model rollback has no active pointer")
            if _rollback_already_applied(current, receipt):
                return GraphModelPointerUpdate(False, "already_rolled_back", current)
            if (
                current.active_model_ref != receipt.model_ref
                or current.active_model_digest != receipt.model_digest
                or current.prior_active_model_ref != receipt.rollback_model_ref
                or current.prior_active_model_digest != receipt.rollback_model_digest
                or current.promotion_receipt_digest != receipt.content_digest
            ):
                raise ValueError("graph model rollback target is stale or mismatched")
            pointer = GraphModelActivePointer(
                slot_digest=receipt.slot_digest,
                revision=current.revision + 1,
                active_model_ref=receipt.rollback_model_ref,
                active_model_digest=receipt.rollback_model_digest,
                prior_active_model_ref=receipt.model_ref,
                prior_active_model_digest=receipt.model_digest,
                promotion_receipt_digest=receipt.content_digest,
            )
            if await self._compare_and_set(pointer, current.revision, actor, "rolled_back"):
                return GraphModelPointerUpdate(True, "rolled_back", pointer)
        latest = await self.load_active(receipt.slot_digest)
        if latest is not None and _rollback_already_applied(latest, receipt):
            return GraphModelPointerUpdate(False, "already_rolled_back", latest)
        raise ValueError("graph model rollback pointer conflict")

    async def _compare_and_set(
        self,
        pointer: GraphModelActivePointer,
        expected_revision: int,
        actor: str,
        transition: str,
    ) -> bool:
        return await self._store.compare_and_set_state_with_audit(
            f"{_ACTIVE_PREFIX}{pointer.slot_digest}",
            _encode_pointer(pointer),
            expected_revision=expected_revision,
            audit_entry={
                "actor": actor,
                "producer_principal": "Thor",
                "action_kind": f"graph_model_promotion.{transition}",
                "mode": "enforce",
                "slot_digest": pointer.slot_digest,
                "active_model_ref": pointer.active_model_ref,
                "prior_active_model_ref": pointer.prior_active_model_ref,
                "promotion_receipt_digest": pointer.promotion_receipt_digest,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            },
        )


def _promotion_already_applied(
    pointer: GraphModelActivePointer | None,
    receipt: GraphModelPromotionReceipt,
) -> bool:
    return (
        pointer is not None
        and pointer.active_model_ref == receipt.model_ref
        and pointer.active_model_digest == receipt.model_digest
        and pointer.promotion_receipt_digest == receipt.content_digest
    )


def _rollback_already_applied(
    pointer: GraphModelActivePointer,
    receipt: GraphModelPromotionReceipt,
) -> bool:
    return (
        pointer.active_model_ref == receipt.rollback_model_ref
        and pointer.active_model_digest == receipt.rollback_model_digest
        and pointer.prior_active_model_ref == receipt.model_ref
        and pointer.prior_active_model_digest == receipt.model_digest
        and pointer.promotion_receipt_digest == receipt.content_digest
    )


def _encode_model(model: GraphEffectModel) -> dict[str, object]:
    return {
        "model_id": model.model_id,
        "version": model.version,
        "revision": model.revision,
        "status": model.status.value,
        "trigger_ref": model.trigger_ref,
        "source_type": model.source_type,
        "link_path": list(model.link_path),
        "target_type": model.target_type,
        "target_metric": model.target_metric,
        "propagation_lag_seconds": model.propagation_lag_seconds,
        "gain": model.gain,
        "offset": model.offset,
        "interval_radius": model.interval_radius,
        "evidence_grade": model.evidence_grade.value,
        "causal_evidence_receipt_digest": model.causal_evidence_receipt_digest,
        "learned_through": model.learned_through.isoformat(),
        "sample_count": model.sample_count,
        "mean_absolute_error": model.mean_absolute_error,
        "applied_observation_digests": list(model.applied_observation_digests),
    }


def _decode_model(raw: Mapping[str, Any]) -> GraphEffectModel:
    _require_exact_fields(raw, _MODEL_FIELDS, "model artifact")
    return GraphEffectModel(
        model_id=_text(raw, "model_id"),
        version=_text(raw, "version"),
        revision=_integer(raw, "revision"),
        status=EffectModelStatus(_text(raw, "status")),
        trigger_ref=_text(raw, "trigger_ref"),
        source_type=_text(raw, "source_type"),
        link_path=_text_tuple(raw, "link_path"),
        target_type=_text(raw, "target_type"),
        target_metric=_text(raw, "target_metric"),
        propagation_lag_seconds=_integer(raw, "propagation_lag_seconds"),
        gain=_number(raw, "gain"),
        offset=_number(raw, "offset"),
        interval_radius=_number(raw, "interval_radius"),
        evidence_grade=CausalEvidenceGrade(_text(raw, "evidence_grade")),
        causal_evidence_receipt_digest=_text(raw, "causal_evidence_receipt_digest"),
        learned_through=_timestamp(raw, "learned_through"),
        sample_count=_integer(raw, "sample_count"),
        mean_absolute_error=_number(raw, "mean_absolute_error"),
        applied_observation_digests=_text_tuple(raw, "applied_observation_digests"),
    )


def _encode_receipt(receipt: GraphModelPromotionReceipt) -> dict[str, object]:
    return {
        "model_id": receipt.model_id,
        "model_version": receipt.model_version,
        "model_revision": receipt.model_revision,
        "model_digest": receipt.model_digest,
        "slot_digest": receipt.slot_digest,
        "ontology_release_digest": receipt.ontology_release_digest,
        "property_semantics_digest": receipt.property_semantics_digest,
        "causal_receipt_digest": receipt.causal_receipt_digest,
        "evidence_grade": receipt.evidence_grade.value,
        "cohort": receipt.cohort.value,
        "risk": receipt.risk.value,
        "sample_count": receipt.sample_count,
        "confidence_interval_lower": receipt.confidence_interval_lower,
        "confidence_interval_upper": receipt.confidence_interval_upper,
        "fidelity": receipt.fidelity,
        "recurrence_window_complete": receipt.recurrence_window_complete,
        "recurrence_rate": receipt.recurrence_rate,
        "policy_escapes": receipt.policy_escapes,
        "invariant_evidence_digests": list(receipt.invariant_evidence_digests),
        "expected_pointer_revision": receipt.expected_pointer_revision,
        "rollback_model_ref": receipt.rollback_model_ref,
        "rollback_model_digest": receipt.rollback_model_digest,
        "sealed_at": receipt.sealed_at.isoformat(),
    }


def _decode_receipt(raw: Mapping[str, Any]) -> GraphModelPromotionReceipt:
    _require_exact_fields(raw, _RECEIPT_FIELDS, "receipt")
    return GraphModelPromotionReceipt(
        model_id=_text(raw, "model_id"),
        model_version=_text(raw, "model_version"),
        model_revision=_integer(raw, "model_revision"),
        model_digest=_text(raw, "model_digest"),
        slot_digest=_text(raw, "slot_digest"),
        ontology_release_digest=_text(raw, "ontology_release_digest"),
        property_semantics_digest=_text(raw, "property_semantics_digest"),
        causal_receipt_digest=_text(raw, "causal_receipt_digest"),
        evidence_grade=CausalEvidenceGrade(_text(raw, "evidence_grade")),
        cohort=GraphModelEvidenceCohort(_text(raw, "cohort")),
        risk=GraphModelRisk(_text(raw, "risk")),
        sample_count=_integer(raw, "sample_count"),
        confidence_interval_lower=_number(raw, "confidence_interval_lower"),
        confidence_interval_upper=_number(raw, "confidence_interval_upper"),
        fidelity=_number(raw, "fidelity"),
        recurrence_window_complete=_boolean(raw, "recurrence_window_complete"),
        recurrence_rate=_number(raw, "recurrence_rate"),
        policy_escapes=_integer(raw, "policy_escapes"),
        invariant_evidence_digests=_text_tuple(raw, "invariant_evidence_digests"),
        expected_pointer_revision=_integer(raw, "expected_pointer_revision"),
        rollback_model_ref=_optional_text(raw, "rollback_model_ref"),
        rollback_model_digest=_optional_text(raw, "rollback_model_digest"),
        sealed_at=_timestamp(raw, "sealed_at"),
    )


def _encode_pointer(pointer: GraphModelActivePointer) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "slot_digest": pointer.slot_digest,
        "revision": pointer.revision,
        "active_model_ref": pointer.active_model_ref,
        "active_model_digest": pointer.active_model_digest,
        "prior_active_model_ref": pointer.prior_active_model_ref,
        "prior_active_model_digest": pointer.prior_active_model_digest,
        "promotion_receipt_digest": pointer.promotion_receipt_digest,
    }


def _decode_pointer(raw: Mapping[str, Any]) -> GraphModelActivePointer:
    if raw.get("schema_version") != "1.0.0":
        raise ValueError("unsupported graph model active pointer state")
    _require_exact_fields(raw, _POINTER_FIELDS, "active pointer")
    return GraphModelActivePointer(
        slot_digest=_text(raw, "slot_digest"),
        revision=_integer(raw, "revision"),
        active_model_ref=_optional_text(raw, "active_model_ref"),
        active_model_digest=_optional_text(raw, "active_model_digest"),
        prior_active_model_ref=_optional_text(raw, "prior_active_model_ref"),
        prior_active_model_digest=_optional_text(raw, "prior_active_model_digest"),
        promotion_receipt_digest=_text(raw, "promotion_receipt_digest"),
    )


def _decode_envelope[Decoded](
    raw: Mapping[str, Any],
    field: str,
    decoder: Callable[[Mapping[str, Any]], Decoded],
) -> Decoded:
    if raw.get("schema_version") != "1.0.0" or not isinstance(raw.get(field), Mapping):
        raise ValueError(f"unsupported graph model promotion {field} state")
    _require_exact_fields(raw, frozenset({"schema_version", field}), f"{field} envelope")
    return decoder(raw[field])


def _require_exact_fields(
    raw: Mapping[str, Any],
    expected: frozenset[str],
    name: str,
) -> None:
    if frozenset(raw) != expected:
        raise ValueError(f"graph model promotion {name} fields do not match schema")


def _text(raw: Mapping[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"graph model promotion {field} MUST be non-empty text")
    return value


def _optional_text(raw: Mapping[str, Any], field: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"graph model promotion {field} MUST be non-empty text")
    return value


def _integer(raw: Mapping[str, Any], field: str) -> int:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"graph model promotion {field} MUST be an integer")
    return value


def _number(raw: Mapping[str, Any], field: str) -> float:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"graph model promotion {field} MUST be numeric")
    return float(value)


def _boolean(raw: Mapping[str, Any], field: str) -> bool:
    value = raw.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"graph model promotion {field} MUST be boolean")
    return value


def _text_tuple(raw: Mapping[str, Any], field: str) -> tuple[str, ...]:
    value = raw.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"graph model promotion {field} MUST be a string list")
    return tuple(value)


def _timestamp(raw: Mapping[str, Any], field: str) -> datetime:
    value = datetime.fromisoformat(_text(raw, field).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError(f"graph model promotion {field} MUST be timezone-aware")
    return value


def _require_digest(value: str, name: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"graph model promotion {name} MUST be SHA-256")


def _require_actor(actor: str) -> None:
    if not actor or actor != actor.strip() or len(actor) > 256:
        raise ValueError("graph model promotion actor MUST be bounded")


__all__ = ["GraphModelPointerUpdate", "StateStoreGraphModelPromotionRegistry"]
