"""StateStore-backed policy revision persistence for Mimir."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.approval_profile import ApprovalProfileKind, ApprovalProfileRevision
from fdai_service_contracts.policy_administration import (
    ApprovalPolicyContent,
    PolicyActivationEvent,
    PolicyKind,
    PolicyRevisionRecord,
    PolicyRevisionSignatureVerifier,
)

from fdai.agents._framework.mimir_policy_errors import PolicyRevisionRejectedError
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class StateStorePolicyRevisionStore:
    """Persist Mimir policy revisions through the existing StateStore seam."""

    store: StateStore
    signature_verifier: PolicyRevisionSignatureVerifier | None = None

    async def append_revision(self, record: PolicyRevisionRecord) -> bool:
        key = _revision_key(record.policy_kind, record.revision_id)
        return await self.store.write_state_with_audit_if_absent(
            key,
            record.model_dump(mode="json"),
            {
                "event_type": "policy_revision_recorded",
                "actor": "Mimir",
                "policy_kind": record.policy_kind.value,
                "revision_id": record.revision_id,
                "policy_digest": record.content_digest,
                "author_principal": record.author_principal,
                "validation_digest": record.validation.validation_digest,
            },
        )

    async def revision(
        self,
        *,
        policy_kind: PolicyKind,
        revision_id: str,
    ) -> PolicyRevisionRecord | None:
        stored = await self.store.read_state(_revision_key(policy_kind, revision_id))
        if stored is None:
            return None
        return PolicyRevisionRecord.model_validate(stored)

    async def active_revision_id(self, policy_kind: PolicyKind) -> str | None:
        stored = await self.store.read_state(_activation_key(policy_kind))
        revision_id = stored.get("revision_id") if stored is not None else None
        return revision_id if isinstance(revision_id, str) and revision_id else None

    async def active_activation(self, policy_kind: PolicyKind) -> PolicyActivationEvent | None:
        stored = await self.store.read_state(_activation_key(policy_kind))
        if stored is None:
            return None
        return PolicyActivationEvent.model_validate(
            {key: value for key, value in stored.items() if key != "revision"}
        )

    async def active_approval_profile(self) -> ApprovalProfileRevision | None:
        active = await self.active_revision_id(PolicyKind.APPROVAL)
        if active is None:
            return None
        revision = await self.revision(policy_kind=PolicyKind.APPROVAL, revision_id=active)
        if revision is None or not isinstance(revision.content, ApprovalPolicyContent):
            return None
        if self.signature_verifier is None:
            return None
        if not await self.signature_verifier.verify_policy_revision_signature(revision):
            return None
        document = revision.content.document
        effective_from = document.get("effective_from")
        parsed_effective_from = (
            datetime.fromisoformat(effective_from.replace("Z", "+00:00"))
            if isinstance(effective_from, str)
            else effective_from
        )
        if not isinstance(parsed_effective_from, datetime):
            return None
        profile = document.get("approval_profile")
        parsed_profile = ApprovalProfileKind(profile) if isinstance(profile, str) else profile
        if not isinstance(parsed_profile, ApprovalProfileKind):
            return None
        return ApprovalProfileRevision(
            revision_id=str(document.get("revision_id") or revision.revision_id),
            approval_profile=parsed_profile,
            executor_principal=str(document.get("executor_principal") or ""),
            policy_digest=str(document.get("policy_digest") or revision.content_digest),
            effective_from=parsed_effective_from,
            operator_principal=(
                str(document["operator_principal"])
                if document.get("operator_principal") is not None
                else None
            ),
        )

    async def request_revision_id(self, request_id: str) -> str | None:
        stored = await self.store.read_state(_request_key(request_id))
        revision_id = stored.get("revision_id") if stored is not None else None
        return revision_id if isinstance(revision_id, str) and revision_id else None

    async def record_request_revision(self, *, request_id: str, revision_id: str) -> bool:
        return await self.store.write_state_if_absent(
            _request_key(request_id),
            {"request_id": request_id, "revision_id": revision_id, "state": "recorded"},
        )

    async def request_activation(self, request_id: str) -> PolicyActivationEvent | None:
        stored = await self.store.read_state(_request_key(request_id))
        activation = stored.get("activation") if stored is not None else None
        if not isinstance(activation, dict):
            return None
        return PolicyActivationEvent.model_validate(activation)

    async def record_request_activation(
        self,
        *,
        request_id: str,
        revision_id: str,
        activation: PolicyActivationEvent,
    ) -> None:
        await self.store.write_state(
            _request_key(request_id),
            {
                "kind": "policy_revision_request",
                "request_id": request_id,
                "revision_id": revision_id,
                "state": "activated",
                "activation": activation.model_dump(mode="json"),
            },
        )

    async def activate_revision(
        self,
        *,
        policy_kind: PolicyKind,
        revision_id: str,
        policy_digest: str,
        author_principal: str,
        activated_at: datetime,
        validation_digest: str,
        expected_parent_revision_id: str | None,
    ) -> PolicyActivationEvent:
        key = _activation_key(policy_kind)
        existing = await self.store.read_state(key)
        revision = int(existing.get("revision", 0)) if existing is not None else 0
        active_revision_id = existing.get("revision_id") if existing is not None else None
        if active_revision_id != expected_parent_revision_id:
            raise PolicyRevisionRejectedError("stale_parent_revision")
        event = PolicyActivationEvent(
            kind="policy_activation",
            policy_id=f"{policy_kind.value}:{revision_id}",
            policy_kind=policy_kind,
            revision_id=revision_id,
            policy_digest=policy_digest,
            activated_at=activated_at,
            author_principal=author_principal,
            validation_digest=validation_digest,
            correlation_id=f"policy-activation:{policy_kind.value}:{revision_id}",
            idempotency_key=stable_idempotency_key(
                "policy-activation",
                policy_kind.value,
                revision_id,
                policy_digest,
            ),
        )
        updated = {**event.model_dump(mode="json"), "revision": revision + 1}
        audit_entry = {
            "event_type": "policy_activation_recorded",
            "actor": "Mimir",
            "policy_kind": policy_kind.value,
            "revision_id": revision_id,
            "policy_digest": policy_digest,
            "author_principal": author_principal,
            "validation_digest": validation_digest,
        }
        if existing is None:
            if not await self.store.write_state_with_audit_if_absent(key, updated, audit_entry):
                raise PolicyRevisionRejectedError("policy_activation_conflict")
        elif not await self.store.compare_and_set_state_with_audit(
            key,
            updated,
            expected_revision=revision,
            audit_entry=audit_entry,
        ):
            raise PolicyRevisionRejectedError("policy_activation_conflict")
        return event


def _revision_key(policy_kind: PolicyKind, revision_id: str) -> str:
    return f"policy_revision:{policy_kind.value}:{revision_id}"


def _activation_key(policy_kind: PolicyKind) -> str:
    return f"policy_activation:{policy_kind.value}"


def _request_key(request_id: str) -> str:
    return f"policy_request:{request_id}"


__all__ = ["StateStorePolicyRevisionStore"]
