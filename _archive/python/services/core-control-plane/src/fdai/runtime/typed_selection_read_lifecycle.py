"""Real Forseti preparation and Thor/Vidar adapters for the governed read ActionType."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.ontology_query import content_digest

from fdai.agents import (
    ActionRun,
    AnomalyActionPreparation,
    PreflightSimulationResult,
    action_run_identity_digest,
    read_current_action_approval,
)
from fdai.agents import (
    action_approval_state_key as approval_state_key,
)
from fdai.agents import (
    validate_final_approval_record as validate_final_record,
)
from fdai.core.ontology_platform.typed_selection_contracts import READ_PROMOTION_ACTION
from fdai.delivery.persistence.state_store_typed_selection_read import StateStoreTypedSelectionRead
from fdai.delivery.promotion import StateStorePromotionAttestationStore
from fdai.delivery.typed_selection_read_governance import TypedSelectionQualificationSource
from fdai.shared.providers.direct_api import DirectApiOutcome, DirectApiReceipt
from fdai.shared.providers.state_store import StateStore

_ORIGINAL = "typed-selection-read:v1:original:"


class FinalizedTypedReadApproval:
    """Read only authenticated Var final approvals or existing governed review completions."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.governance = StateStorePromotionAttestationStore(store)

    async def load_replay(self, key: str, fingerprint: str) -> DirectApiReceipt | None:
        if not key.startswith("pantheon/var/"):
            return await self.governance.load_replay(key, fingerprint)
        raw = await self.store.read_state(key)
        if raw is None:
            return None
        approval, _ = validate_final_record(raw, str(raw.get("correlation_id") or ""))
        if (
            approval.get("state") != "approved"
            or approval.get("producer_principal") != "Var"
            or content_digest(approval) != fingerprint
        ):
            return None
        return DirectApiReceipt(outcome=DirectApiOutcome.SUCCEEDED, receipt_ref=fingerprint)


class TypedReadLifecycle(TypedSelectionQualificationSource):
    """No agent calls: existing typed handlers invoke these mechanical execution ports."""

    def __init__(
        self,
        registry: StateStoreTypedSelectionRead,
        *,
        can_approve: Callable[[str, str], bool] | None = None,
    ) -> None:
        super().__init__(registry)
        self.can_approve = can_approve

    async def prepare(self, verdict: Mapping[str, Any]) -> AnomalyActionPreparation:
        if verdict.get("action_type") != READ_PROMOTION_ACTION:
            raise PermissionError("typed read original action type mismatch")
        params = verdict.get("params")
        if not isinstance(params, Mapping):
            raise PermissionError("typed read original arguments are unavailable")
        await self.registry.qualification("sha256:" + str(params.get("evidence_digest") or ""))
        identity = str(uuid5(NAMESPACE_URL, str(verdict["idempotency_key"])))
        value = {
            "action_id": identity,
            "correlation_id": str(verdict["correlation_id"]),
            "resource_id": str(verdict["resource_id"]),
            "params": dict(params),
        }
        if not await self.registry.store.write_state_if_absent(_ORIGINAL + identity, value):
            if await self.registry.store.read_state(_ORIGINAL + identity) != value:
                raise PermissionError("typed read retained action identity changed")
        return AnomalyActionPreparation(action_id=identity, shadow_only=False, quorum_required=2)

    async def simulate(self, run: ActionRun) -> PreflightSimulationResult:
        try:
            await self._original(run)
            await self.registry.qualification("sha256:" + str(run.params["evidence_digest"]))
        except (PermissionError, KeyError, ValueError):
            return PreflightSimulationResult(
                "failed",
                "typed-selection-read",
                "1",
                "typed_read_qualification_or_original_unavailable",
            )
        return PreflightSimulationResult(
            "passed", "typed-selection-read", "1", "typed_read_exact_receipt_dry_run"
        )

    async def _original(self, run: ActionRun) -> Mapping[str, Any]:
        original = await self.registry.store.read_state(_ORIGINAL + str(run.action_id))
        if (
            run.action_type != READ_PROMOTION_ACTION
            or original is None
            or original.get("correlation_id") != run.correlation_id
            or original.get("resource_id") != run.resource_id
            or original.get("params") != run.params
        ):
            raise PermissionError("typed read retained action or target changed")
        return original

    async def execute(self, context: dict[str, Any]) -> bool:
        run = context.get("run")
        if not isinstance(run, ActionRun) or run.action_type != READ_PROMOTION_ACTION:
            return False
        original = await self._original(run)
        if self.can_approve is None:
            raise PermissionError("typed read current human authorization is unavailable")
        run_payload = asdict(run)
        run_payload["approval_expires_at"] = (
            run.approval_expires_at.isoformat() if run.approval_expires_at is not None else None
        )
        await read_current_action_approval(
            store=self.registry.store,
            action_run=run_payload,
            can_approve=self.can_approve,
            clock=self.registry.clock,
        )
        identity = action_run_identity_digest(asdict(run))
        key = approval_state_key(run.correlation_id, "final", identity)
        record = await self.registry.store.read_state(key)
        if record is None:
            raise PermissionError("typed read promotion requires exact Var human approval")
        approval, _ = validate_final_record(record, run.correlation_id)
        if (
            approval.get("state") != "approved"
            or approval.get("action_run_identity") != identity
            or approval.get("action_idempotency_key") != run.idempotency_key
        ):
            raise PermissionError("typed read human approval is stale or mismatched")
        params = run.params
        qualification = await self.registry.qualification(
            "sha256:" + str(params["evidence_digest"])
        )
        if (
            params.get("fdai_revision") != qualification.binding.source_revision
            or run.resource_id
            != "typed-selection-read:" + qualification.binding.principal_scope_digest
            or params.get("target_resource_ref") != run.resource_id
            or params.get("action_type_id") != READ_PROMOTION_ACTION
            or params.get("target_mode") != "enforce"
            or type(params.get("expected_revision")) is not int
        ):
            raise PermissionError("typed read promotion scope or source changed")
        current = await self.registry.pointer(qualification.binding.principal_scope_digest)
        fingerprint = content_digest(approval)
        if (
            current is not None
            and current.enabled
            and current.approval_key == key
            and current.approval_fingerprint == fingerprint
        ):
            return True
        await self.registry.promote(
            qualification_digest=qualification.digest,
            expected_revision=int(params["expected_revision"]),
            approval_key=key,
            approval_fingerprint=fingerprint,
            request_digest=content_digest(dict(original)),
            actor="Thor",
        )
        return True

    async def rollback(self, action_run: dict[str, Any]) -> str | None:
        if action_run.get("action_type") != READ_PROMOTION_ACTION:
            return None
        resource = str(action_run.get("resource_id") or "")
        scope = resource.removeprefix("typed-selection-read:")
        pointer = await self.registry.pointer(scope)
        if pointer is None:
            return None
        params = action_run.get("params")
        if (
            not isinstance(params, Mapping)
            or pointer.qualification_digest != "sha256:" + str(params.get("evidence_digest") or "")
            or pointer.revision != int(params.get("expected_revision", -2)) + 1
        ):
            raise PermissionError("typed read rollback cannot affect a newer promotion")
        lowered = await self.registry.demote(
            scope_digest=scope, expected_revision=pointer.revision, reason="rollback", actor="Vidar"
        )
        return f"typed-selection-read:{scope}:r{lowered.revision}"
