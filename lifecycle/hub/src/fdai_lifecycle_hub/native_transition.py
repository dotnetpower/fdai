"""Audited Hub approval for one recovered development installation scope transition."""

from __future__ import annotations

from datetime import datetime

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_enrollment import installation_key_id
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionApproval,
    SignedNativeScopeTransitionApproval,
    SignedNativeScopeTransitionRequest,
    sign_transition_approval,
)
from sqlalchemy import select

from fdai_lifecycle_hub import audit, mapping, models, rows, schemas
from fdai_lifecycle_hub.migrations import require_schema
from fdai_lifecycle_hub.native_ownership import NATIVE_ENTITY_KIND
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.store import HubStore

_ACTION = "entity.native_transition_approved"
_OWNERSHIP_ACTION = "entity.native_creation_accepted"
_RECOVERY_ACTION = "configuration.identity.development-recovered"


class NativeTransitionError(ValueError):
    """Stable transition-approval denial without private scope or object identities."""


class NativeTransitionStore:
    def __init__(self, store: HubStore) -> None:
        self._store = store

    def approve(
        self,
        installation_id: str,
        signed: SignedNativeScopeTransitionRequest,
        *,
        operator: str,
        now: datetime,
        key: HubSigningKey,
    ) -> SignedNativeScopeTransitionApproval:
        operator = schemas.actor_name.validate_python(operator)
        request = signed.request
        if request.installation_id != installation_id:
            raise NativeTransitionError("native_transition_installation_mismatch")
        subject = "native-transition-" + request.request_id.hex
        with self._store._write() as session:
            row = rows.lock_enrolled(session, installation_id)
            require_schema(session.connection(), "lifecycle_hub")
            previous = session.scalar(
                select(models.AuditRecord).where(
                    models.AuditRecord.installation_id == installation_id,
                    models.AuditRecord.action == _ACTION,
                    models.AuditRecord.subject == subject,
                )
            )
            if previous is not None:
                if (
                    previous.payload["request_digest"] != request.digest
                    or previous.payload["operator"] != operator
                ):
                    raise NativeTransitionError("native_transition_request_conflict")
                return SignedNativeScopeTransitionApproval.model_validate_json(
                    canonical_bytes(previous.payload["signed_approval"])
                )
            installation = mapping.to_domain(session, row)
            try:
                request.require_current(now)
            except ValueError as error:
                raise NativeTransitionError("native_transition_request_expired") from error
            if not signed.verify(row.installation_key):
                raise NativeTransitionError("native_transition_recovered_proof_invalid")
            if installation_key_id(row.installation_key) != request.recovered_identity_key_id:
                raise NativeTransitionError("native_transition_recovered_identity_mismatch")
            if installation.open_plan is not None:
                raise NativeTransitionError("native_transition_plan_pending")
            if installation.reported.digest != request.old_reported_state_digest:
                raise NativeTransitionError("native_transition_reported_state_mismatch")
            old_state = installation.reported.entities.get(request.old_entity_id)
            new_state = installation.reported.entities.get(request.new_entity_id)
            if old_state is None or old_state.release_id is None:
                raise NativeTransitionError("native_transition_legacy_state_missing")
            if new_state is not None and new_state.release_id is not None:
                raise NativeTransitionError("native_transition_new_entity_installed")
            entity = session.scalar(
                select(models.Entity).where(
                    models.Entity.installation_id == installation_id,
                    models.Entity.entity_id == request.new_entity_id,
                )
            )
            if (
                entity is None
                or entity.kind != NATIVE_ENTITY_KIND
                or entity.ownership is None
                or entity.ownership.get("native_creation_receipt_digest")
                != request.ownership_claim_digest
            ):
                raise NativeTransitionError("native_transition_ownership_not_accepted")
            ownership = session.scalar(
                select(models.AuditRecord).where(
                    models.AuditRecord.installation_id == installation_id,
                    models.AuditRecord.action == _OWNERSHIP_ACTION,
                    models.AuditRecord.payload["claim_digest"].as_string()
                    == request.ownership_claim_digest,
                )
            )
            if ownership is None:
                raise NativeTransitionError("native_transition_ownership_not_audited")
            proof = ownership.payload.get("proof")
            claim = proof.get("claim") if isinstance(proof, dict) else None
            if not isinstance(claim, dict) or claim.get("scope_digest") != request.new_scope_digest:
                raise NativeTransitionError("native_transition_scope_not_accepted")
            recovery = session.scalar(
                select(models.AuditRecord).where(
                    models.AuditRecord.installation_id == installation_id,
                    models.AuditRecord.action == _RECOVERY_ACTION,
                    models.AuditRecord.subject == request.recovery_request_digest,
                )
            )
            if (
                recovery is None
                or recovery.payload.get("profile") != "full-authority-development"
                or recovery.payload.get("replacement_identity_key_id")
                != request.recovered_identity_key_id
            ):
                raise NativeTransitionError("native_transition_recovery_not_audited")
            approval = NativeScopeTransitionApproval(
                schema_version="fdai.lifecycle-native-transition-approval.v1",
                request=signed,
                profile="full-authority-development",
                approved_by=operator,
                approved_at=now,
                expires_at=request.expires_at,
                recovery_audit_digest="sha256:" + recovery.record_hash,
                ownership_audit_digest="sha256:" + ownership.record_hash,
                hub_key_id=key.key_id,
                hub_key_epoch=key.epoch,
            )
            result = sign_transition_approval(approval, key.private_key)
            audit.append(
                session,
                now,
                _ACTION,
                installation_id,
                subject,
                {
                    "operator": operator,
                    "request_digest": request.digest,
                    "old_entity_id": request.old_entity_id,
                    "new_entity_id": request.new_entity_id,
                    "old_scope_digest": request.old_scope_digest,
                    "new_scope_digest": request.new_scope_digest,
                    "reported_state_digest": request.old_reported_state_digest,
                    "expires_at": request.expires_at.isoformat(),
                    "recovery_audit_digest": approval.recovery_audit_digest,
                    "ownership_audit_digest": approval.ownership_audit_digest,
                    "existing_resources_digest": request.existing_resources_digest,
                    "signed_approval": result.model_dump(mode="json"),
                },
            )
            return result
