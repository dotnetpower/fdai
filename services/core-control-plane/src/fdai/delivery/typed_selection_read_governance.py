"""Specialized read promotion through the existing review dispatcher and Vidar rollback."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from fdai.agents import AnomalyActionCandidate
from fdai.agents.vidar import RollbackRecord
from fdai.core.ontology_platform.typed_selection_contracts import (
    READ_DEMOTION_EVENT,
    READ_PROMOTION_ACTION,
    ReadDemotionCommand,
)
from fdai.delivery.persistence.state_store_typed_selection_read import StateStoreTypedSelectionRead
from fdai.delivery.promotion import (
    GovernancePromotionDispatcher,
    StateStorePromotionAttestationStore,
    promotion_request_fingerprint,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.decision_evidence_verifier import assess_decision_evidence_admission
from fdai.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiReceipt,
    DirectApiRequest,
)

READ_QUALIFIED_EVENT = "typed_selection.read.qualified"
_CANDIDATE_PREFIX = "typed-selection-read:v1:candidate:"


class TypedSelectionReadPromotionExecutor:
    """An inner adapter; only bind it behind the existing exact-review dispatcher."""

    def __init__(self, registry: StateStoreTypedSelectionRead) -> None:
        self.registry = registry

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name != READ_PROMOTION_ACTION:
            raise DirectApiPreconditionError("unregistered typed selection promotion")
        args = request.arguments
        digest = args.get("evidence_digest")
        expected = args.get("expected_revision")
        if not isinstance(digest, str) or type(expected) is not int or expected < 0:
            raise DirectApiPreconditionError("typed selection promotion arguments are invalid")
        qualification = await self.registry.qualification("sha256:" + digest)
        binding = qualification.binding
        if (
            args.get("action_type_id") != READ_PROMOTION_ACTION
            or args.get("fdai_revision") != binding.source_revision
            or args.get("scenario_set_version") != "typed-selection-read-v1"
            or args.get("target_mode") != "enforce"
            or request.resource_ref != "typed-selection-read:" + binding.principal_scope_digest
            or args.get("target_resource_ref") != request.resource_ref
        ):
            raise DirectApiPreconditionError("typed selection exact target or source drifted")
        if request.mode is Mode.SHADOW:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref="shadow:typed-selection-read:" + qualification.digest,
            )
        if "enforce" not in request.labels:
            raise DirectApiPreconditionError("typed selection promotion requires enforce dispatch")
        current = await self.registry.pointer(binding.principal_scope_digest)
        fingerprint = promotion_request_fingerprint(request)
        if (
            current is not None
            and current.enabled
            and current.revision == expected + 1
            and current.promotion_request_digest == "sha256:" + fingerprint
            and current.qualification_digest == qualification.digest
        ):
            return DirectApiReceipt(
                outcome=DirectApiOutcome.ALREADY_APPLIED,
                receipt_ref=f"typed-selection-read:{binding.digest}:r{current.revision}",
                already_existed=True,
            )
        pointer = await self.registry.promote(
            qualification_digest=qualification.digest,
            expected_revision=expected,
            approval_key=request.idempotency_key,
            approval_fingerprint=promotion_request_fingerprint(request),
            request_digest="sha256:" + promotion_request_fingerprint(request),
            actor="Thor",
        )
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=f"typed-selection-read:{binding.digest}:r{pointer.revision}",
        )


def governed_read_dispatcher(
    registry: StateStoreTypedSelectionRead,
) -> GovernancePromotionDispatcher:
    return GovernancePromotionDispatcher(
        TypedSelectionReadPromotionExecutor(registry),
        attestation_store=StateStorePromotionAttestationStore(registry.store),
    )


class TypedSelectionQualificationSource:
    """Heimdall supplies an inert candidate; Forseti and Var still decide and approve."""

    def __init__(self, registry: StateStoreTypedSelectionRead) -> None:
        self.registry = registry

    async def resolve(self, *, event_type: str, resource_ref: str) -> AnomalyActionCandidate | None:
        if event_type != READ_QUALIFIED_EVENT or not resource_ref.startswith(
            "typed-selection-read:"
        ):
            return None
        scope = resource_ref.removeprefix("typed-selection-read:")
        candidate = await self.registry.store.read_state(_CANDIDATE_PREFIX + scope)
        if candidate is None:
            return None
        try:
            qualification = await self.registry.qualification(
                str(candidate["qualification_digest"])
            )
        except (PermissionError, KeyError, ValueError):
            return None
        if qualification.binding.principal_scope_digest != scope:
            return None
        pointer = await self.registry.pointer(scope)
        arguments = {
            "action_type_id": READ_PROMOTION_ACTION,
            "fdai_revision": qualification.binding.source_revision,
            "scenario_set_version": "typed-selection-read-v1",
            "evidence_digest": qualification.digest.removeprefix("sha256:"),
            "expected_revision": pointer.revision if pointer is not None else 0,
            "target_mode": "enforce",
            "target_resource_ref": resource_ref,
            "justification": "Apply the exact independently admitted typed read qualification.",
        }
        now = self.registry.clock()
        return AnomalyActionCandidate(
            event_type=event_type,
            resource_ref=resource_ref,
            action_type=READ_PROMOTION_ACTION,
            arguments_json=json.dumps(arguments, sort_keys=True, separators=(",", ":")),
            evidence_ref=qualification.digest,
            observed_at=now,
            expires_at=min(now + timedelta(seconds=60), qualification.expires_at),
        )


class TypedSelectionReadDemoter:
    """Vidar-owned recovery callback; exact admitted regression/revocation only."""

    def __init__(self, registry: StateStoreTypedSelectionRead) -> None:
        self.registry = registry

    async def __call__(self, event: dict[str, Any]) -> RollbackRecord | None:
        if (
            event.get("event_type") != READ_DEMOTION_EVENT
            or event.get("producer_principal") != "Huginn"
        ):
            raise PermissionError("typed selection demotion requires the owned typed Event")
        command = ReadDemotionCommand.model_validate(event.get("attributes"))
        now = self.registry.clock()
        if (
            command.issued_at.tzinfo is None
            or command.expires_at.tzinfo is None
            or not command.issued_at <= now < command.expires_at
            or (command.expires_at - command.issued_at).total_seconds() > 300
            or self.registry.admission is None
        ):
            raise PermissionError("typed selection demotion evidence is unavailable or expired")
        pointer = await self.registry.pointer(command.principal_scope_digest)
        if (
            pointer is None
            or pointer.revision != command.expected_revision
            or pointer.qualification_digest != command.qualification_digest
            or pointer.binding.source_revision != command.source_revision
        ):
            raise PermissionError("typed selection demotion target drifted")
        admission = await self.registry.admission.admit(
            evidence_digest=command.digest,
            scope_digest=pointer.binding.digest,
            purpose_id="typed-selection-read-demotion",
            source_revision=command.source_revision,
        )
        if admission is None or assess_decision_evidence_admission(
            admission,
            expected_evidence_digest=command.digest,
            expected_scope_digest=pointer.binding.digest,
            expected_purpose_id="typed-selection-read-demotion",
            expected_source_revision=command.source_revision,
            evaluated_at=now,
        ):
            raise PermissionError("typed selection demotion independent admission failed")
        await self.registry.store.write_state_with_audit_if_absent(
            "typed-selection-read:v1:demotion-intent:" + command.digest,
            {"command_digest": command.digest},
            {"actor": "Vidar", "phase": "intent", "command_digest": command.digest},
        )
        lowered = await self.registry.demote(
            scope_digest=command.principal_scope_digest,
            expected_revision=command.expected_revision,
            reason=command.reason,
            actor="Vidar",
        )
        return RollbackRecord(
            correlation_id=str(event["correlation_id"]),
            action_run_identity=command.action_run_identity,
            action_type=READ_PROMOTION_ACTION,
            resource_id=str(event.get("resource_id") or ""),
            contract="scripted",
            state="succeeded",
            notes="typed selection capability demoted with qualification withdrawn",
            rollback_ref=f"typed-selection-read:{command.principal_scope_digest}:r{lowered.revision}",
        )
