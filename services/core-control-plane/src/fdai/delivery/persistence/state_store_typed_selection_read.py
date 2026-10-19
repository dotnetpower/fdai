"""Durable, approval-finalization-gated read pointers and single-use selection evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform.typed_selection_contracts import (
    READ_QUALIFICATION_PURPOSE,
    ReadCapabilityBinding,
    ReadCapabilityPointer,
    ReadQualification,
    ReadSelectionEvidence,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)
from fdai.shared.providers.direct_api import DirectApiOutcome, DirectApiReceipt
from fdai.shared.providers.state_store import StateStore

_PREFIX = "typed-selection-read:v1:"


class FinalizedReadApproval(Protocol):
    async def load_replay(
        self, idempotency_key: str, request_fingerprint: str
    ) -> DirectApiReceipt | None: ...


class StateStoreTypedSelectionRead:
    """No implicit promotion. Trusted callers bind the existing governed dispatcher."""

    def __init__(
        self,
        store: StateStore,
        *,
        admission: DecisionEvidenceAdmissionProvider | None,
        approvals: FinalizedReadApproval | None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.admission = admission
        self.approvals = approvals
        self.clock = clock or (lambda: datetime.now(UTC))

    async def save_qualification(self, qualification: ReadQualification) -> None:
        await self._admit(qualification)
        await self._immutable(
            f"qualification:{qualification.digest}", qualification.model_dump(mode="json")
        )
        await self.store.write_state(
            _PREFIX + "candidate:" + qualification.binding.principal_scope_digest,
            {"qualification_digest": qualification.digest},
        )

    async def qualification(self, digest: str) -> ReadQualification:
        raw = await self.store.read_state(_PREFIX + "qualification:" + digest)
        if raw is None:
            raise PermissionError("typed selection qualification is unavailable")
        qualification = ReadQualification.model_validate(raw)
        if qualification.digest != digest:
            raise PermissionError("typed selection qualification content changed")
        await self._admit(qualification)
        return qualification

    async def _admit(self, qualification: ReadQualification) -> None:
        now = self.clock()
        if (
            now.tzinfo is None
            or qualification.outcome != "qualified"
            or not qualification.issued_at <= now < qualification.expires_at
            or self.admission is None
            or await self.store.read_state(_PREFIX + "withdrawn:" + qualification.digest)
        ):
            raise PermissionError("typed selection qualification is not current and admitted")
        binding = qualification.binding
        receipt = await self.admission.admit(
            evidence_digest=qualification.digest,
            scope_digest=binding.digest,
            purpose_id=READ_QUALIFICATION_PURPOSE,
            source_revision=binding.source_revision,
        )
        if receipt is None or assess_decision_evidence_admission(
            receipt,
            expected_evidence_digest=qualification.digest,
            expected_scope_digest=binding.digest,
            expected_purpose_id=READ_QUALIFICATION_PURPOSE,
            expected_source_revision=binding.source_revision,
            evaluated_at=now,
        ):
            raise PermissionError("typed selection independent qualification admission failed")

    async def pointer(self, scope_digest: str) -> ReadCapabilityPointer | None:
        raw = await self.store.read_state(_PREFIX + "active:" + scope_digest)
        return ReadCapabilityPointer.model_validate(raw) if raw is not None else None

    async def active(self, binding: ReadCapabilityBinding) -> ReadCapabilityPointer:
        pointer = await self.pointer(binding.principal_scope_digest)
        if pointer is None or not pointer.enabled or pointer.binding != binding:
            raise PermissionError("typed selection read capability is disabled or drifted")
        qualification = await self.qualification(pointer.qualification_digest)
        if qualification.binding != binding or self.approvals is None:
            raise PermissionError("typed selection promotion binding is not admitted")
        approval = await self.approvals.load_replay(
            pointer.approval_key, pointer.approval_fingerprint
        )
        if approval is None or approval.outcome not in {
            DirectApiOutcome.SUCCEEDED,
            DirectApiOutcome.ALREADY_APPLIED,
        }:
            raise PermissionError("typed selection exact human approval is not finalized")
        return pointer

    async def promote(
        self,
        *,
        qualification_digest: str,
        expected_revision: int,
        approval_key: str,
        approval_fingerprint: str,
        request_digest: str,
        actor: str,
    ) -> ReadCapabilityPointer:
        if actor != "Thor":
            raise PermissionError("only Thor applies a governed read promotion")
        qualification = await self.qualification(qualification_digest)
        pointer = ReadCapabilityPointer(
            revision=expected_revision + 1,
            binding=qualification.binding,
            qualification_digest=qualification.digest,
            enabled=True,
            approval_key=approval_key,
            approval_fingerprint=approval_fingerprint,
            promotion_request_digest=request_digest,
        )
        key = _PREFIX + "active:" + pointer.binding.principal_scope_digest
        applied = await self.store.compare_and_set_state_with_audit(
            key,
            pointer.model_dump(mode="json"),
            expected_revision=expected_revision,
            audit_entry={
                "actor": "Thor",
                "action_kind": "typed_selection_read.promote",
                "binding_digest": pointer.binding.digest,
                "qualification_digest": qualification.digest,
                "revision": pointer.revision,
                "recorded_at": self.clock().isoformat(),
            },
        )
        if not applied:
            raise PermissionError("typed selection promotion revision changed")
        return pointer

    async def demote(
        self, *, scope_digest: str, expected_revision: int, reason: str, actor: str
    ) -> ReadCapabilityPointer:
        if actor != "Vidar" or reason not in {"revoked", "regression", "rollback"}:
            raise PermissionError("typed selection demotion requires Vidar and a typed reason")
        pointer = await self.pointer(scope_digest)
        if pointer is None or pointer.revision != expected_revision:
            raise PermissionError("typed selection demotion revision changed")
        lowered = pointer.model_copy(update={"revision": pointer.revision + 1, "enabled": False})
        # Withdraw first: a concurrent promotion cannot make old qualification usable again.
        await self.store.write_state_if_absent(
            _PREFIX + "withdrawn:" + pointer.qualification_digest,
            {"qualification_digest": pointer.qualification_digest, "reason": reason},
        )
        applied = await self.store.compare_and_set_state_with_audit(
            _PREFIX + "active:" + scope_digest,
            lowered.model_dump(mode="json"),
            expected_revision=expected_revision,
            audit_entry={
                "actor": "Vidar",
                "action_kind": "typed_selection_read.demote",
                "reason": reason,
                "revision": lowered.revision,
                "binding_digest": pointer.binding.digest,
                "recorded_at": self.clock().isoformat(),
            },
        )
        if not applied:
            raise PermissionError("typed selection concurrent demotion is held")
        return lowered

    async def save_selection(self, evidence: ReadSelectionEvidence) -> str:
        pointer = await self.active(evidence.binding)
        if (
            pointer.revision != evidence.registry_revision
            or pointer.qualification_digest != evidence.qualification_digest
        ):
            raise PermissionError("typed selection registry changed before evidence persistence")
        await self._immutable("selection:" + evidence.digest, evidence.model_dump(mode="json"))
        return evidence.digest

    async def begin_request(self, request_ref: str) -> None:
        if not await self.store.write_state_if_absent(
            self._request_key(request_ref), {"revision": 1, "active": True}
        ):
            raise PermissionError("typed selection request was already used")

    async def cancel_request(self, request_ref: str) -> None:
        await self.store.compare_and_set_state(
            self._request_key(request_ref),
            {"revision": 2, "active": False},
            expected_revision=1,
        )

    @staticmethod
    def _request_key(request_ref: str) -> str:
        return _PREFIX + "request:" + content_digest({"request_ref": request_ref})

    async def selection(self, digest: str) -> ReadSelectionEvidence:
        raw = await self.store.read_state(_PREFIX + "selection:" + digest)
        if raw is None:
            raise PermissionError("typed selection evidence is unavailable")
        evidence = ReadSelectionEvidence.model_validate(raw)
        if (
            evidence.digest != digest
            or not evidence.issued_at <= self.clock() < evidence.expires_at
        ):
            raise PermissionError("typed selection evidence expired or changed")
        request = await self.store.read_state(self._request_key(evidence.request_ref))
        if request != {"revision": 1, "active": True}:
            raise PermissionError("typed selection request was cancelled or changed")
        return evidence

    async def consume(self, evidence: ReadSelectionEvidence) -> None:
        pointer = await self.active(evidence.binding)
        if (
            pointer.revision != evidence.registry_revision
            or pointer.qualification_digest != evidence.qualification_digest
        ):
            raise PermissionError("typed selection registry changed before evidence consumption")
        if not await self.store.compare_and_set_state_pair_with_audit_before(
            _PREFIX + "active:" + evidence.binding.principal_scope_digest,
            pointer.model_dump(mode="json"),
            expected_revision=pointer.revision,
            second_key=_PREFIX + "consumed:" + evidence.digest,
            second_value={"revision": 1, "evidence_digest": evidence.digest},
            expected_second_revision=0,
            guard_key=self._request_key(evidence.request_ref),
            guard_value={"revision": 1, "active": True},
            expected_guard_revision=1,
            not_before=evidence.issued_at,
            expires_at=evidence.expires_at,
            audit_entry={
                "actor": "Bragi",
                "action_kind": "typed_selection_read.consume",
                "evidence_digest": evidence.digest,
                "execution_authority": False,
            },
        ):
            raise PermissionError("typed selection evidence is replayed, revoked or cancelled")

    async def _immutable(self, suffix: str, value: dict[str, object]) -> None:
        key = _PREFIX + suffix
        if not await self.store.write_state_if_absent(key, value):
            if await self.store.read_state(key) != value:
                raise PermissionError("typed selection immutable evidence collision")
