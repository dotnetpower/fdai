"""StateStore-backed ActionPromotionRegistry with fail-closed refresh."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from fdai.core.measurement import OperationalPromotionReceipt
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.core.risk_gate import (
    ActionModeRecord,
    ActionPromotionRegistry,
    OperationalPromotionReceiptVerifier,
    PersistedPromotionAuthorityVerifier,
    PromotionMetrics,
)
from fdai.shared.contracts.models import Mode, OntologyActionType
from fdai.shared.providers.state_store import StateStore

_PREFIX = "action_promotion:"
_RECALL_PREFIX = "capability_recall:"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class PromotionKind(StrEnum):
    """Why the current promotion registry record reached its mode."""

    GATE_EVIDENCE = "gate_evidence"
    OPERATOR_OVERRIDE = "operator_override"


class PromotionGateStatus(StrEnum):
    """Gate verdict snapshot captured when an operator override is applied."""

    PASSED = "passed"
    FAILED = "failed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class PromotionRefusedError(ValueError):
    """A promotion attempt was intentionally refused with an audit-safe reason."""

    def __init__(self, *, action_type: str, reason: str) -> None:
        super().__init__(f"promotion refused for {action_type}: {reason}")
        self.action_type = action_type
        self.reason = reason


class OperatorOverrideAuthorityVerifier(Protocol):
    """Verify the Var approval receipt behind a governance override promotion."""

    async def verify_override(
        self,
        *,
        action_type: str,
        action_type_version: str,
        action_type_digest: str,
        gate_evidence_digest: str,
        approval_receipt_digest: str,
        operator_principal: str,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class OperatorOverrideAttribution:
    """Required operator-override evidence stored with the promotion record."""

    gate_status: PromotionGateStatus
    gate_evidence_digest: str
    approval_receipt_digest: str
    operator_principal: str
    reason: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.gate_evidence_digest) is None:
            raise ValueError("operator override gate evidence digest MUST be SHA-256")
        if _DIGEST.fullmatch(self.approval_receipt_digest) is None:
            raise ValueError("operator override approval receipt digest MUST be SHA-256")
        _validate_non_empty_text(self.operator_principal, "operator override principal")
        _validate_non_empty_text(self.reason, "operator override reason")
        _validate_timestamp(self.recorded_at, "operator override recorded_at")

    def as_dict(self) -> dict[str, str]:
        return {
            "gate_status": self.gate_status.value,
            "gate_status_source": "operator_attested",
            "gate_evidence_digest": self.gate_evidence_digest,
            "approval_receipt_digest": self.approval_receipt_digest,
            "operator_principal": self.operator_principal,
            "override_reason": self.reason,
            "override_recorded_at": self.recorded_at.isoformat(),
            "safeguard_proof_source": "operator_attested",
        }


@dataclass(frozen=True, slots=True)
class CapabilityRecallRecord:
    """Small durable recall input that prevents capability promotion."""

    action_type: str
    reason: str
    recalled_at: datetime
    lifted_at: datetime | None = None

    def __post_init__(self) -> None:
        _validate_non_empty_text(self.action_type, "capability recall action_type")
        _validate_non_empty_text(self.reason, "capability recall reason")
        _validate_timestamp(self.recalled_at, "capability recall recalled_at")
        if self.lifted_at is not None:
            _validate_timestamp(self.lifted_at, "capability recall lifted_at")

    @property
    def active(self) -> bool:
        return self.lifted_at is None

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "action_type": self.action_type,
            "active": self.active,
            "reason": self.reason,
            "recalled_at": self.recalled_at.isoformat(),
            "lifted_at": self.lifted_at.isoformat() if self.lifted_at else None,
        }


@dataclass(frozen=True, slots=True)
class _PromotionMetadata:
    kind: PromotionKind = PromotionKind.GATE_EVIDENCE
    override: OperatorOverrideAttribution | None = None

    def __post_init__(self) -> None:
        if self.kind is PromotionKind.OPERATOR_OVERRIDE and self.override is None:
            raise ValueError("operator override promotion requires override attribution")
        if self.kind is PromotionKind.GATE_EVIDENCE and self.override is not None:
            raise ValueError("gate evidence promotion MUST NOT carry override attribution")


class StateStoreActionPromotionRegistry(ActionPromotionRegistry):
    """Keep the RiskGate sync Operator API over an asynchronously refreshed cache."""

    def __init__(
        self,
        *,
        store: StateStore,
        receipt_verifier: OperationalPromotionReceiptVerifier | None = None,
        persisted_authority_verifier: PersistedPromotionAuthorityVerifier | None = None,
        override_authority_verifier: OperatorOverrideAuthorityVerifier | None = None,
        allow_legacy_metrics: bool = False,
    ) -> None:
        super().__init__(
            receipt_verifier=receipt_verifier,
            allow_legacy_metrics=allow_legacy_metrics,
        )
        self._store = store
        self._persisted_authority_verifier = persisted_authority_verifier
        self._override_authority_verifier = override_authority_verifier
        self._observed_revisions: dict[str, int] = {}
        self._observed_absent: set[str] = set()
        self._metadata: dict[str, _PromotionMetadata] = {}
        self._recalls: dict[str, CapabilityRecallRecord] = {}

    def mode_of(self, action_type: str) -> Mode:
        recall = self._recalls.get(action_type)
        if recall is not None and recall.active:
            return Mode.SHADOW
        return super().mode_of(action_type)

    def consider_promotion(
        self,
        *,
        action_type: OntologyActionType,
        metrics: PromotionMetrics,
        receipt: OperationalPromotionReceipt | None = None,
    ) -> ActionModeRecord:
        self._raise_if_recalled(action_type.name)
        record = super().consider_promotion(
            action_type=action_type,
            metrics=metrics,
            receipt=receipt,
        )
        self._metadata[action_type.name] = _PromotionMetadata(PromotionKind.GATE_EVIDENCE)
        return record

    async def consider_operator_override(
        self,
        *,
        action_type: OntologyActionType,
        gate_status: PromotionGateStatus | str,
        gate_evidence_digest: str,
        approval_receipt_digest: str,
        operator_principal: str,
        reason: str,
        recorded_at: datetime,
        fdai_revision: str | None = None,
        scenario_set_version: str | None = None,
        metrics: PromotionMetrics | None = None,
    ) -> ActionModeRecord:
        """Apply an attributed operator override as an enforce upper bound."""

        self._raise_if_recalled(action_type.name)
        override = OperatorOverrideAttribution(
            gate_status=PromotionGateStatus(gate_status),
            gate_evidence_digest=gate_evidence_digest,
            approval_receipt_digest=approval_receipt_digest,
            operator_principal=operator_principal,
            reason=reason,
            recorded_at=recorded_at,
        )
        if metrics is not None and metrics.action_type != action_type.name:
            raise ValueError("operator override metrics do not match ActionType")
        action_digest = action_type_digest(action_type)
        if not await self._verify_operator_override(
            action_type=action_type.name,
            action_type_version=action_type.version,
            action_type_digest=action_digest,
            override=override,
        ):
            raise PromotionRefusedError(
                action_type=action_type.name,
                reason="override_authority_unverified",
            )
        record = ActionModeRecord(
            action_type=action_type.name,
            mode=Mode.ENFORCE,
            promoted_at=recorded_at,
            metrics=metrics,
            promotion_evidence_digest=gate_evidence_digest,
            fdai_revision=fdai_revision,
            scenario_set_version=scenario_set_version,
            action_type_version=action_type.version,
            action_type_digest=action_digest,
            production_ready=False,
        )
        self._records[action_type.name] = record
        self._metadata[action_type.name] = _PromotionMetadata(
            PromotionKind.OPERATOR_OVERRIDE,
            override,
        )
        return record

    def demote(
        self,
        action_type_name: str,
        *,
        metrics: PromotionMetrics | None = None,
    ) -> ActionModeRecord:
        record = super().demote(action_type_name, metrics=metrics)
        self._metadata[action_type_name] = _PromotionMetadata(PromotionKind.GATE_EVIDENCE)
        return record

    def restore(self, action_type: str, record: ActionModeRecord | None) -> None:
        super().restore(action_type, record)
        if record is None:
            self._metadata.pop(action_type, None)
        else:
            self._metadata.setdefault(action_type, _PromotionMetadata(PromotionKind.GATE_EVIDENCE))

    def read_model(self, action_type: str) -> dict[str, Any]:
        """Return the effective registry projection used by mode-reporting surfaces."""

        record = self.record(action_type)
        metadata = self._metadata.get(action_type, _PromotionMetadata(PromotionKind.GATE_EVIDENCE))
        recall = self._recalls.get(action_type)
        mode = Mode.SHADOW if recall is not None and recall.active else self.mode_of(action_type)
        projection: dict[str, Any] = {
            "action_type": action_type,
            "mode": mode.value,
            "promotion_kind": metadata.kind.value,
            "promoted_at": record.promoted_at.isoformat()
            if record is not None and record.promoted_at
            else None,
            "demoted_at": record.demoted_at.isoformat()
            if record is not None and record.demoted_at
            else None,
            "promotion_evidence_digest": record.promotion_evidence_digest
            if record is not None
            else None,
            "capability_recall": recall.as_dict() if recall is not None else None,
        }
        if metadata.override is not None:
            projection.update(metadata.override.as_dict())
        return projection

    def audit_dict(self, action_type: str) -> dict[str, Any]:
        """Return the audit-safe mode projection including promotion_kind."""

        return self.read_model(action_type)

    async def refresh(self, action_type: str) -> None:
        try:
            await self._refresh(action_type)
        except Exception:
            # A stale cached ENFORCE is unsafe when the authority store is
            # unavailable or corrupt. Clear it so mode_of() returns SHADOW.
            self._records.pop(action_type, None)
            self._metadata.pop(action_type, None)

    async def refresh_for_update(self, action_type: str) -> None:
        """Load durable authority for a writer without suppressing failures."""

        await self._refresh(action_type)

    async def _refresh(self, action_type: str) -> None:
        await self._refresh_recall(action_type)
        raw = await self._store.read_state(_key(action_type))
        if raw is None:
            self._records.pop(action_type, None)
            self._metadata.pop(action_type, None)
            self._observed_revisions[action_type] = 0
            self._observed_absent.add(action_type)
            return
        revision = raw.get("revision", 0)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("persisted promotion revision is malformed")
        record, metadata = _deserialize(raw)
        if record.action_type != action_type:
            raise ValueError("persisted action_type does not match key")
        if record.mode is Mode.ENFORCE:
            _validate_enforce_attribution(record, metadata)
            if metadata.kind is PromotionKind.GATE_EVIDENCE:
                verifier = self._persisted_authority_verifier
                attribution = (
                    record.action_type_version,
                    record.action_type_digest,
                    record.promotion_evidence_digest,
                    record.fdai_revision,
                    record.scenario_set_version,
                )
                if verifier is None or any(value is None for value in attribution):
                    raise ValueError("persisted ENFORCE lacks verified O7 attribution")
                accepted = await verifier.verify(
                    action_type=record.action_type,
                    action_type_version=record.action_type_version or "",
                    action_type_digest=record.action_type_digest or "",
                    evidence_digest=record.promotion_evidence_digest or "",
                    fdai_revision=record.fdai_revision or "",
                    scenario_set_version=record.scenario_set_version or "",
                )
                if not accepted:
                    raise ValueError("persisted ENFORCE O7 attribution was rejected")
            else:
                override = metadata.override
                if (
                    override is None
                    or record.action_type_version is None
                    or record.action_type_digest is None
                    or not await self._verify_operator_override(
                        action_type=record.action_type,
                        action_type_version=record.action_type_version,
                        action_type_digest=record.action_type_digest,
                        override=override,
                    )
                ):
                    raise ValueError("persisted operator override authority was rejected")
        self._records[action_type] = record
        self._metadata[action_type] = metadata
        self._observed_revisions[action_type] = revision
        self._observed_absent.discard(action_type)

    async def persist(self, action_type: str) -> None:
        record = self.record(action_type)
        if record is None:
            record = self.demote(action_type)
        expected_revision = self._observed_revisions.get(action_type)
        if expected_revision is None:
            raise RuntimeError("promotion persistence requires a writer refresh")
        next_revision = expected_revision + 1
        metadata = self._metadata.get(action_type, _PromotionMetadata(PromotionKind.GATE_EVIDENCE))
        recall = self._recalls.get(action_type)
        value = {**_serialize(record, metadata, recall), "revision": next_revision}
        audit_entry = {
            "actor": "fdai.delivery.promotion",
            "action_kind": "action_promotion.persisted",
            "action_type": action_type,
            "mode": record.mode.value,
            "promotion_kind": metadata.kind.value,
            "revision": next_revision,
        }
        if recall is not None:
            audit_entry["capability_recall_active"] = recall.active
        if action_type in self._observed_absent:
            applied = await self._store.write_state_with_audit_if_absent(
                _key(action_type),
                value,
                audit_entry,
            )
        else:
            applied = await self._store.compare_and_set_state_with_audit(
                _key(action_type),
                value,
                expected_revision=expected_revision,
                audit_entry=audit_entry,
            )
        if not applied:
            raise RuntimeError("promotion authority changed during persistence")
        self._observed_revisions[action_type] = next_revision
        self._observed_absent.discard(action_type)

    async def recall_capability(
        self,
        action_type: str,
        *,
        reason: str,
        recalled_at: datetime,
    ) -> CapabilityRecallRecord:
        record = CapabilityRecallRecord(
            action_type=action_type,
            reason=reason,
            recalled_at=recalled_at,
        )
        await self._persist_recall(record, action_kind="capability_recall.recorded")
        self._recalls[action_type] = record
        return record

    async def lift_capability_recall(
        self,
        action_type: str,
        *,
        lifted_at: datetime,
    ) -> CapabilityRecallRecord:
        current = self._recalls.get(action_type)
        if current is None:
            await self._refresh_recall(action_type)
            current = self._recalls.get(action_type)
        if current is None:
            raise ValueError("capability recall cannot be lifted before it is recorded")
        record = CapabilityRecallRecord(
            action_type=action_type,
            reason=current.reason,
            recalled_at=current.recalled_at,
            lifted_at=lifted_at,
        )
        await self._persist_recall(record, action_kind="capability_recall.lifted")
        self._recalls[action_type] = record
        return record

    async def _refresh_recall(self, action_type: str) -> None:
        raw = await self._store.read_state(_recall_key(action_type))
        if raw is None:
            self._recalls.pop(action_type, None)
            return
        record = _deserialize_recall(raw)
        if record.action_type != action_type:
            raise ValueError("persisted recall action_type does not match key")
        self._recalls[action_type] = record

    async def _persist_recall(
        self,
        record: CapabilityRecallRecord,
        *,
        action_kind: str,
    ) -> None:
        key = _recall_key(record.action_type)
        raw = await self._store.read_state(key)
        expected_revision = 0
        if raw is not None:
            revision = raw.get("revision", 0)
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise ValueError("persisted recall revision is malformed")
            expected_revision = revision
        next_revision = expected_revision + 1
        value = {**_serialize_recall(record), "revision": next_revision}
        audit_entry = {
            "actor": "fdai.delivery.promotion",
            "action_kind": action_kind,
            "action_type": record.action_type,
            "mode": Mode.SHADOW.value if record.active else self.mode_of(record.action_type).value,
            "capability_recall_active": record.active,
            "revision": next_revision,
        }
        if raw is None:
            applied = await self._store.write_state_with_audit_if_absent(
                key,
                value,
                audit_entry,
            )
        else:
            applied = await self._store.compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=expected_revision,
                audit_entry=audit_entry,
            )
        if not applied:
            raise RuntimeError("capability recall changed during persistence")

    def _raise_if_recalled(self, action_type: str) -> None:
        recall = self._recalls.get(action_type)
        if recall is not None and recall.active:
            raise PromotionRefusedError(
                action_type=action_type,
                reason=f"capability_recall_active:{recall.reason}",
            )

    async def _verify_operator_override(
        self,
        *,
        action_type: str,
        action_type_version: str,
        action_type_digest: str,
        override: OperatorOverrideAttribution,
    ) -> bool:
        verifier = self._override_authority_verifier
        if verifier is None:
            return False
        return await verifier.verify_override(
            action_type=action_type,
            action_type_version=action_type_version,
            action_type_digest=action_type_digest,
            gate_evidence_digest=override.gate_evidence_digest,
            approval_receipt_digest=override.approval_receipt_digest,
            operator_principal=override.operator_principal,
        )


def _key(action_type: str) -> str:
    return f"{_PREFIX}{action_type}"


def _recall_key(action_type: str) -> str:
    return f"{_RECALL_PREFIX}{action_type}"


def _serialize(
    record: ActionModeRecord,
    metadata: _PromotionMetadata,
    recall: CapabilityRecallRecord | None,
) -> dict[str, Any]:
    metrics = record.metrics
    result = {
        "schema_version": "1.0.0",
        "action_type": record.action_type,
        "mode": record.mode.value,
        "promotion_kind": metadata.kind.value,
        "promoted_at": record.promoted_at.isoformat() if record.promoted_at else None,
        "demoted_at": record.demoted_at.isoformat() if record.demoted_at else None,
        "promotion_evidence_digest": record.promotion_evidence_digest,
        "fdai_revision": record.fdai_revision,
        "scenario_set_version": record.scenario_set_version,
        "action_type_version": record.action_type_version,
        "action_type_digest": record.action_type_digest,
        "production_ready": record.production_ready,
        "metrics": (
            {
                "action_type": metrics.action_type,
                "shadow_days": metrics.shadow_days,
                "samples": metrics.samples,
                "accuracy": metrics.accuracy,
                "policy_escapes": metrics.policy_escapes,
            }
            if metrics is not None
            else None
        ),
        "capability_recall": recall.as_dict() if recall is not None else None,
    }
    if metadata.override is not None:
        result.update(metadata.override.as_dict())
    return result


def _deserialize(raw: Any) -> tuple[ActionModeRecord, _PromotionMetadata]:
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0.0":
        raise ValueError("unsupported promotion state")
    metadata = _deserialize_metadata(raw)
    metrics_raw = raw.get("metrics")
    metrics = None
    if isinstance(metrics_raw, dict):
        metrics = PromotionMetrics(
            action_type=str(metrics_raw["action_type"]),
            shadow_days=int(metrics_raw["shadow_days"]),
            samples=int(metrics_raw["samples"]),
            accuracy=float(metrics_raw["accuracy"]),
            policy_escapes=int(metrics_raw["policy_escapes"]),
        )
    return (
        ActionModeRecord(
            action_type=str(raw["action_type"]),
            mode=Mode(str(raw["mode"])),
            promoted_at=_timestamp(raw.get("promoted_at")),
            demoted_at=_timestamp(raw.get("demoted_at")),
            metrics=metrics,
            promotion_evidence_digest=_optional_text(raw.get("promotion_evidence_digest")),
            fdai_revision=_optional_text(raw.get("fdai_revision")),
            scenario_set_version=_optional_text(raw.get("scenario_set_version")),
            action_type_version=_optional_text(raw.get("action_type_version")),
            action_type_digest=_optional_text(raw.get("action_type_digest")),
            production_ready=bool(
                raw.get("production_ready", raw.get("mode") == Mode.ENFORCE.value)
            ),
        ),
        metadata,
    )


def _deserialize_metadata(raw: dict[str, Any]) -> _PromotionMetadata:
    kind = PromotionKind(str(raw.get("promotion_kind", PromotionKind.GATE_EVIDENCE.value)))
    if kind is PromotionKind.GATE_EVIDENCE:
        return _PromotionMetadata(PromotionKind.GATE_EVIDENCE)
    override = OperatorOverrideAttribution(
        gate_status=PromotionGateStatus(str(raw.get("gate_status", ""))),
        gate_evidence_digest=_required_text(
            raw.get("gate_evidence_digest"),
            "operator override gate evidence digest",
        ),
        approval_receipt_digest=_required_text(
            raw.get("approval_receipt_digest"),
            "operator override approval receipt digest",
        ),
        operator_principal=_required_text(
            raw.get("operator_principal"),
            "operator override principal",
        ),
        reason=_required_text(raw.get("override_reason"), "operator override reason"),
        recorded_at=_required_timestamp(
            raw.get("override_recorded_at"),
            "operator override recorded_at",
        ),
    )
    return _PromotionMetadata(kind, override)


def _serialize_recall(record: CapabilityRecallRecord) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "action_type": record.action_type,
        "reason": record.reason,
        "recalled_at": record.recalled_at.isoformat(),
        "lifted_at": record.lifted_at.isoformat() if record.lifted_at else None,
    }


def _deserialize_recall(raw: Any) -> CapabilityRecallRecord:
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0.0":
        raise ValueError("unsupported capability recall state")
    return CapabilityRecallRecord(
        action_type=_required_text(raw.get("action_type"), "capability recall action_type"),
        reason=_required_text(raw.get("reason"), "capability recall reason"),
        recalled_at=_required_timestamp(raw.get("recalled_at"), "capability recall time"),
        lifted_at=_timestamp(raw.get("lifted_at")),
    )


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("promotion timestamp MUST be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("promotion timestamp MUST be timezone-aware")
    return parsed


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("promotion evidence attribution MUST be non-empty text")
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} MUST be non-empty text")
    return value


def _required_timestamp(value: object, field: str) -> datetime:
    return _timestamp(_required_text(value, field)) or _raise_missing_timestamp(field)


def _raise_missing_timestamp(field: str) -> datetime:
    raise ValueError(f"{field} MUST be present")


def _validate_non_empty_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} MUST be non-empty text")


def _validate_timestamp(value: datetime, field: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field} MUST be timezone-aware")


def _validate_enforce_attribution(
    record: ActionModeRecord,
    metadata: _PromotionMetadata,
) -> None:
    if record.promoted_at is None:
        raise ValueError("persisted ENFORCE requires a promotion timestamp")
    if record.metrics is not None and record.metrics.action_type != record.action_type:
        raise ValueError("persisted ENFORCE metrics do not match ActionType")
    if metadata.kind is PromotionKind.OPERATOR_OVERRIDE:
        override = metadata.override
        if override is None:
            raise ValueError("persisted operator override lacks attribution")
        if record.promotion_evidence_digest != override.gate_evidence_digest:
            raise ValueError("persisted operator override evidence digest is inconsistent")
        if (
            record.action_type_digest is None
            or _DIGEST.fullmatch(record.action_type_digest) is None
            or not record.action_type_version
        ):
            raise ValueError("persisted operator override action attribution is malformed")
        return
    if (
        record.promotion_evidence_digest is None
        or _DIGEST.fullmatch(record.promotion_evidence_digest) is None
        or record.action_type_digest is None
        or _DIGEST.fullmatch(record.action_type_digest) is None
        or record.fdai_revision is None
        or _REVISION.fullmatch(record.fdai_revision) is None
        or not record.action_type_version
        or not record.scenario_set_version
    ):
        raise ValueError("persisted ENFORCE attribution is malformed")


__all__ = [
    "CapabilityRecallRecord",
    "OperatorOverrideAttribution",
    "OperatorOverrideAuthorityVerifier",
    "PromotionGateStatus",
    "PromotionKind",
    "PromotionRefusedError",
    "StateStoreActionPromotionRegistry",
]
