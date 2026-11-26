"""Audited Hub approval for one recovered development installation scope transition."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_enrollment import installation_key_id
from fdai_deployment_cli.lifecycle_native import SignedNativeScope
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionApproval,
    NativeScopeTransitionCompletion,
    NativeScopeTransitionCompletionReceipt,
    NativeScopeTransitionReportedState,
    SignedNativeScopeTransitionApproval,
    SignedNativeScopeTransitionRequest,
    existing_resources_digest,
    sign_transition_approval,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from fdai_lifecycle_hub import audit, domain, mapping, models, rows, schemas
from fdai_lifecycle_hub.migrations import require_schema
from fdai_lifecycle_hub.native_ownership import NATIVE_ENTITY_KIND
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.store import HubStore

_ACTION = "entity.native_transition_approved"
_COMPLETION_ACTION = "entity.native_transition_completed"
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

    def complete(
        self,
        installation_id: str,
        command: NativeScopeTransitionCompletion,
        *,
        principal: str,
        now: datetime,
        key: HubSigningKey,
        after_write: Callable[[str], None] | None = None,
    ) -> NativeScopeTransitionCompletionReceipt:
        """Atomically replace the managed Entity and state after the Agent's local commit."""

        principal = schemas.actor_name.validate_python(principal)
        approval = command.approval
        request = approval.approval.request.request
        local = command.transition_receipt
        if request.installation_id != installation_id:
            raise NativeTransitionError("native_transition_installation_mismatch")
        subject = "native-transition-" + request.request_id.hex
        with self._store._write() as session:
            row = rows.lock_enrolled(session, installation_id)
            require_schema(session.connection(), "lifecycle_hub")
            previous = session.scalar(
                select(models.AuditRecord).where(
                    models.AuditRecord.installation_id == installation_id,
                    models.AuditRecord.action == _COMPLETION_ACTION,
                    models.AuditRecord.subject == subject,
                )
            )
            if previous is not None:
                if (
                    previous.payload["completion_digest"] != command.digest
                    or previous.payload["agent_principal"] != principal
                ):
                    raise NativeTransitionError("native_transition_completion_conflict")
                return NativeScopeTransitionCompletionReceipt.model_validate(
                    previous.payload["receipt"]
                )
            installation = mapping.to_domain(session, row)
            self._validate_completion(
                session,
                row,
                installation,
                command,
                principal=principal,
                key=key,
            )
            old_row = rows.entity_row(session, installation_id, request.old_entity_id)
            new_row = rows.entity_row(session, installation_id, request.new_entity_id)
            old_entity = mapping.domain_entity(old_row)
            if old_entity.settings is None:
                raise NativeTransitionError("native_transition_source_not_managed")
            reported = schemas.reported_state_json.validate_python(
                command.reported_state.model_dump(mode="python")
            )
            receipt = _completion_receipt(
                command,
                principal=principal,
                settings_digest=old_entity.settings.digest,
                now=now,
            )
            old_row.settings = None
            old_row.recorded_at = now
            if after_write is not None:
                after_write("source-unmanaged")
            row.state_reports.add(mapping.state_report_row(installation_id, reported, now))
            row.recorded_at = now
            if after_write is not None:
                after_write("state-recorded")
            new_row.settings = schemas.entity_settings_json.dump_python(
                old_entity.settings, mode="json"
            )
            new_row.recorded_at = now
            if after_write is not None:
                after_write("target-managed")
            audit.append(
                session,
                now,
                _COMPLETION_ACTION,
                installation_id,
                subject,
                {
                    "completion_digest": command.digest,
                    "agent_principal": principal,
                    "request_digest": request.digest,
                    "transition_receipt_digest": local.record_digest,
                    "old_entity_id": request.old_entity_id,
                    "new_entity_id": request.new_entity_id,
                    "old_scope_digest": request.old_scope_digest,
                    "new_scope_digest": request.new_scope_digest,
                    "old_reported_state_digest": request.old_reported_state_digest,
                    "new_reported_state_digest": command.reported_state.digest,
                    "object_scope_digest": receipt.object_scope_digest,
                    "authoritative_uids_digest": receipt.authoritative_uids_digest,
                    "receipt": receipt.model_dump(mode="json"),
                },
            )
            if after_write is not None:
                after_write("audit-appended")
            return receipt

    @staticmethod
    def _validate_completion(
        session: Session,
        row: models.Installation,
        installation: domain.Installation,
        command: NativeScopeTransitionCompletion,
        *,
        principal: str,
        key: HubSigningKey,
    ) -> None:
        approval = command.approval
        request = approval.approval.request.request
        local = command.transition_receipt
        native = command.native_approval
        state = command.reported_state
        if not approval.verify(
            key.public_key.public_bytes_raw(), key_id=key.key_id, key_epoch=key.epoch
        ):
            raise NativeTransitionError("native_transition_hub_approval_invalid")
        if principal == approval.approval.approved_by:
            raise NativeTransitionError("native_transition_execution_identity_mismatch")
        if not approval.approval.request.verify(row.installation_key):
            raise NativeTransitionError("native_transition_recovered_proof_invalid")
        approved = session.scalar(
            select(models.AuditRecord).where(
                models.AuditRecord.installation_id == installation.installation_id,
                models.AuditRecord.action == _ACTION,
                models.AuditRecord.subject == "native-transition-" + request.request_id.hex,
            )
        )
        if (
            approved is None
            or approved.payload.get("request_digest") != request.digest
            or approved.payload.get("signed_approval") != approval.model_dump(mode="json")
        ):
            raise NativeTransitionError("native_transition_approval_not_audited")
        if installation.open_plan is not None:
            raise NativeTransitionError("native_transition_plan_pending")
        if installation.reported.digest != request.old_reported_state_digest:
            raise NativeTransitionError("native_transition_reported_state_mismatch")
        managed = {
            entity.entity_id for entity in installation.entities if entity.settings is not None
        }
        if managed != {request.old_entity_id}:
            raise NativeTransitionError("native_transition_managed_source_mismatch")
        if set(installation.reported.entities) != {request.old_entity_id}:
            raise NativeTransitionError("native_transition_source_state_mismatch")
        target = rows.entity_row(session, installation.installation_id, request.new_entity_id)
        if target.kind != NATIVE_ENTITY_KIND or target.settings is not None:
            raise NativeTransitionError("native_transition_target_not_unmanaged")
        ownership = session.scalar(
            select(models.AuditRecord).where(
                models.AuditRecord.installation_id == installation.installation_id,
                models.AuditRecord.action == _OWNERSHIP_ACTION,
                models.AuditRecord.payload["claim_digest"].as_string()
                == request.ownership_claim_digest,
            )
        )
        try:
            proof = SignedNativeScope.model_validate(
                None if ownership is None else ownership.payload.get("proof")
            )
        except ValueError as error:
            raise NativeTransitionError("native_transition_ownership_not_audited") from error
        if (
            ownership is None
            or "sha256:" + ownership.record_hash != approval.approval.ownership_audit_digest
            or not proof.verify(row.installation_key)
            or proof.claim.digest != request.ownership_claim_digest
            or proof.claim.installation_id != installation.installation_id
            or proof.claim.entity_id != request.new_entity_id
            or proof.claim.scope_digest != request.new_scope_digest
            or proof.claim.approval_digest != native.digest
        ):
            raise NativeTransitionError("native_transition_ownership_mismatch")
        if (
            native.profile != "full-authority-development"
            or native.scope.installation_id != installation.installation_id
            or native.scope.entity_id != request.new_entity_id
            or native.scope.digest != request.new_scope_digest
            or existing_resources_digest(
                [item.model_dump(mode="json") for item in native.existing_resources]
            )
            != request.existing_resources_digest
            or set(item.key for item in native.existing_resources) - native.scope.resources
        ):
            raise NativeTransitionError("native_transition_scope_mismatch")
        try:
            native.require_current(local.completed_at)
        except ValueError as error:
            raise NativeTransitionError("native_transition_local_approval_expired") from error
        if not (approval.approval.approved_at <= local.completed_at < approval.approval.expires_at):
            raise NativeTransitionError("native_transition_completion_time_invalid")
        expected_local = {
            "request_digest": request.digest,
            "hub_approval_digest": approval.approval.digest,
            "installation_id": installation.installation_id,
            "old_entity_id": request.old_entity_id,
            "new_entity_id": request.new_entity_id,
            "old_scope_digest": request.old_scope_digest,
            "new_scope_digest": request.new_scope_digest,
            "old_reported_state_digest": request.old_reported_state_digest,
            "new_reported_state_digest": state.digest,
            "ownership_claim_digest": request.ownership_claim_digest,
            "recovery_request_digest": request.recovery_request_digest,
            "existing_resources_digest": request.existing_resources_digest,
        }
        if any(getattr(local, field) != value for field, value in expected_local.items()):
            raise NativeTransitionError("native_transition_receipt_mismatch")
        old_state = installation.reported
        new_entity = state.entities.get(request.new_entity_id)
        if (
            set(state.entities) != {request.new_entity_id}
            or new_entity is None
            or new_entity.release_id is not None
            or new_entity.artifact_digests
            or new_entity.health != "unknown"
            or state.schema_revision != old_state.schema_revision
            or (
                None
                if state.available_artifact_digests is None
                else frozenset(state.available_artifact_digests)
            )
            != old_state.available_artifact_digests
            or state.observed_at != local.completed_at
            or state.observed_at <= old_state.observed_at
            or _reported_state_digest(state) != state.digest
        ):
            raise NativeTransitionError("native_transition_new_state_mismatch")


def _completion_receipt(
    command: NativeScopeTransitionCompletion,
    *,
    principal: str,
    settings_digest: str,
    now: datetime,
) -> NativeScopeTransitionCompletionReceipt:
    request = command.approval.approval.request.request
    native = command.native_approval
    document = {
        "schema_version": "fdai.lifecycle-native-transition-completion-receipt.v1",
        "completion_digest": command.digest,
        "request_digest": request.digest,
        "hub_approval_digest": command.approval.approval.digest,
        "transition_receipt_digest": command.transition_receipt.record_digest,
        "installation_id": request.installation_id,
        "old_entity_id": request.old_entity_id,
        "new_entity_id": request.new_entity_id,
        "old_scope_digest": request.old_scope_digest,
        "new_scope_digest": request.new_scope_digest,
        "old_reported_state_digest": request.old_reported_state_digest,
        "new_reported_state_digest": command.reported_state.digest,
        "object_scope_digest": "sha256:"
        + canonical_digest(
            [{"kind": kind, "name": name} for kind, name in sorted(native.scope.resources)]
        ),
        "authoritative_uids_digest": existing_resources_digest(
            [item.model_dump(mode="json") for item in native.existing_resources]
        ),
        "source_settings_digest": settings_digest,
        "agent_principal": principal,
        "completed_at": now.isoformat().replace("+00:00", "Z"),
    }
    return NativeScopeTransitionCompletionReceipt.model_validate_json(
        canonical_bytes(
            {
                **document,
                "receipt_digest": "sha256:" + canonical_digest(document),
            }
        )
    )


def _reported_state_digest(state: NativeScopeTransitionReportedState) -> str:
    document: dict[str, object] = {
        "schema_revision": state.schema_revision,
        "entities": {
            entity_id: {
                "release_id": entity.release_id,
                "artifact_digests": list(entity.artifact_digests),
                "health": entity.health,
            }
            for entity_id, entity in sorted(state.entities.items())
        },
        "observed_at": state.observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }
    if state.available_artifact_digests is not None:
        document["available_artifact_digests"] = list(state.available_artifact_digests)
    return canonical_digest(document)
