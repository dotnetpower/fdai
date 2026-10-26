"""Audited recovery for the legacy native-transition timestamp precision defect."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_native_reconciliation import (
    LegacyNativeScopeTransitionReportedState,
    NativeScopeTransitionStateReconciliationApproval,
    NativeScopeTransitionStateReconciliationCompletion,
    NativeScopeTransitionStateReconciliationReceipt,
    NativeScopeTransitionStateReconciliationRequest,
    SignedNativeScopeTransitionStateReconciliationApproval,
    canonical_transition_reported_state,
    regenerated_transition_receipt_digest,
    same_transition_state_fields,
    sign_transition_state_reconciliation_approval,
    transition_reported_state_digest,
)
from fdai_deployment_cli.lifecycle_native_transition import existing_resources_digest
from sqlalchemy import select
from sqlalchemy.orm import Session

from fdai_lifecycle_hub import audit, mapping, models, rows, schemas
from fdai_lifecycle_hub.migrations import require_schema
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.store import HubStore

_APPROVAL_ACTION = "entity.native_transition_state_reconciliation_approved"
_COMPLETION_ACTION = "entity.native_transition_state_reconciled"
_TRANSITION_COMPLETION_ACTION = "entity.native_transition_completed"
_MAX_PRECISION_DELTA = timedelta(milliseconds=1)


class NativeTransitionReconciliationError(ValueError):
    """Stable fail-closed denial for a legacy state reconciliation."""


class NativeTransitionReconciliationStore:
    def __init__(self, store: HubStore) -> None:
        self._store = store

    def approve(
        self,
        installation_id: str,
        request: NativeScopeTransitionStateReconciliationRequest,
        *,
        operator: str,
        now: datetime,
        key: HubSigningKey,
    ) -> SignedNativeScopeTransitionStateReconciliationApproval:
        operator = schemas.actor_name.validate_python(operator)
        if request.installation_id != installation_id:
            raise NativeTransitionReconciliationError(
                "native_transition_reconciliation_installation_mismatch"
            )
        subject = "native-transition-reconciliation-" + request.request_id.hex
        with self._store._write() as session:
            row = rows.lock_enrolled(session, installation_id)
            require_schema(session.connection(), "lifecycle_hub")
            previous = session.scalar(
                select(models.AuditRecord).where(
                    models.AuditRecord.installation_id == installation_id,
                    models.AuditRecord.action == _APPROVAL_ACTION,
                    models.AuditRecord.subject == subject,
                )
            )
            if previous is not None:
                if (
                    previous.payload.get("request_digest") != request.digest
                    or previous.payload.get("operator") != operator
                ):
                    raise NativeTransitionReconciliationError(
                        "native_transition_reconciliation_request_conflict"
                    )
                return SignedNativeScopeTransitionStateReconciliationApproval.model_validate_json(
                    canonical_bytes(previous.payload["signed_approval"])
                )
            self._require_no_other_attempt(session, installation_id, request)
            installation = mapping.to_domain(session, row)
            try:
                request.require_current(now)
            except ValueError as error:
                raise NativeTransitionReconciliationError(
                    "native_transition_reconciliation_request_expired"
                ) from error
            if installation.open_plan is not None:
                raise NativeTransitionReconciliationError(
                    "native_transition_reconciliation_plan_pending"
                )
            try:
                source = _reported_state_model(session, row)
            except ValueError as error:
                raise NativeTransitionReconciliationError(
                    "native_transition_reconciliation_source_state_invalid"
                ) from error
            completion_audit = self._validate_evidence(
                session,
                installation_id,
                request,
                source,
            )
            authoritative = canonical_transition_reported_state(source)
            approval = NativeScopeTransitionStateReconciliationApproval(
                schema_version=(
                    "fdai.lifecycle-native-transition-state-reconciliation-approval.v1"
                ),
                request=request,
                source_hub_reported_state=source,
                authoritative_reported_state=authoritative,
                approved_by=operator,
                approved_at=now,
                expires_at=request.expires_at,
                completion_audit_digest="sha256:" + completion_audit.record_hash,
                hub_key_id=key.key_id,
                hub_key_epoch=key.epoch,
            )
            signed = sign_transition_state_reconciliation_approval(
                approval,
                key.private_key,
            )
            audit.append(
                session,
                now,
                _APPROVAL_ACTION,
                installation_id,
                subject,
                {
                    "operator": operator,
                    "request_digest": request.digest,
                    "transition_receipt_digest": request.transition_receipt.record_digest,
                    "hub_completion_receipt_digest": (request.completion_receipt.receipt_digest),
                    "legacy_reported_state_digest": request.legacy_reported_state.digest,
                    "source_hub_reported_state_digest": source.digest,
                    "authoritative_reported_state_digest": authoritative.digest,
                    "expires_at": request.expires_at.isoformat(),
                    "completion_audit_digest": approval.completion_audit_digest,
                    "signed_approval": signed.model_dump(mode="json"),
                },
            )
            return signed

    def complete(
        self,
        installation_id: str,
        command: NativeScopeTransitionStateReconciliationCompletion,
        *,
        principal: str,
        now: datetime,
        key: HubSigningKey,
        after_write: Callable[[str], None] | None = None,
    ) -> NativeScopeTransitionStateReconciliationReceipt:
        principal = schemas.actor_name.validate_python(principal)
        approval = command.approval.approval
        request = approval.request
        if request.installation_id != installation_id:
            raise NativeTransitionReconciliationError(
                "native_transition_reconciliation_installation_mismatch"
            )
        subject = "native-transition-reconciliation-" + request.request_id.hex
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
                    previous.payload.get("completion_digest") != command.digest
                    or previous.payload.get("agent_principal") != principal
                ):
                    raise NativeTransitionReconciliationError(
                        "native_transition_reconciliation_completion_conflict"
                    )
                return NativeScopeTransitionStateReconciliationReceipt.model_validate(
                    previous.payload["receipt"]
                )
            installation = mapping.to_domain(session, row)
            if installation.open_plan is not None:
                raise NativeTransitionReconciliationError(
                    "native_transition_reconciliation_plan_pending"
                )
            if not command.approval.verify(
                key.public_key.public_bytes_raw(),
                key_id=key.key_id,
                key_epoch=key.epoch,
            ):
                raise NativeTransitionReconciliationError(
                    "native_transition_reconciliation_hub_approval_invalid"
                )
            try:
                approval.require_current(now)
            except ValueError as error:
                raise NativeTransitionReconciliationError(
                    "native_transition_reconciliation_approval_expired"
                ) from error
            if principal != request.completion_receipt.agent_principal:
                raise NativeTransitionReconciliationError(
                    "native_transition_reconciliation_execution_identity_mismatch"
                )
            approved = session.scalar(
                select(models.AuditRecord).where(
                    models.AuditRecord.installation_id == installation_id,
                    models.AuditRecord.action == _APPROVAL_ACTION,
                    models.AuditRecord.subject == subject,
                )
            )
            if (
                approved is None
                or approved.payload.get("request_digest") != request.digest
                or approved.payload.get("signed_approval")
                != command.approval.model_dump(mode="json")
            ):
                raise NativeTransitionReconciliationError(
                    "native_transition_reconciliation_approval_not_audited"
                )
            try:
                current = _reported_state_model(session, row)
            except ValueError as error:
                raise NativeTransitionReconciliationError(
                    "native_transition_reconciliation_concurrent_state"
                ) from error
            if (
                current != approval.source_hub_reported_state
                or command.reported_state != approval.authoritative_reported_state
                or transition_reported_state_digest(command.reported_state)
                != command.reported_state.digest
            ):
                raise NativeTransitionReconciliationError(
                    "native_transition_reconciliation_concurrent_state"
                )
            row.state_reports.add(
                mapping.state_report_row(
                    installation_id,
                    schemas.reported_state_json.validate_python(
                        command.reported_state.model_dump(mode="python")
                    ),
                    now,
                )
            )
            row.recorded_at = now
            if after_write is not None:
                after_write("state-recorded")
            receipt = _reconciliation_receipt(command, principal=principal, now=now)
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
                    "transition_receipt_digest": request.transition_receipt.record_digest,
                    "hub_completion_receipt_digest": (request.completion_receipt.receipt_digest),
                    "old_reported_state_digest": current.digest,
                    "new_reported_state_digest": command.reported_state.digest,
                    "receipt": receipt.model_dump(mode="json"),
                },
            )
            if after_write is not None:
                after_write("audit-appended")
            return receipt

    @staticmethod
    def _require_no_other_attempt(
        session: Session,
        installation_id: str,
        request: NativeScopeTransitionStateReconciliationRequest,
    ) -> None:
        records = session.scalars(
            select(models.AuditRecord).where(
                models.AuditRecord.installation_id == installation_id,
                models.AuditRecord.action.in_((_APPROVAL_ACTION, _COMPLETION_ACTION)),
            )
        )
        for record in records:
            if (
                record.payload.get("transition_receipt_digest")
                == request.transition_receipt.record_digest
            ):
                raise NativeTransitionReconciliationError(
                    "native_transition_reconciliation_repeat_conflict"
                )

    @staticmethod
    def _validate_evidence(
        session: Session,
        installation_id: str,
        request: NativeScopeTransitionStateReconciliationRequest,
        source: LegacyNativeScopeTransitionReportedState,
    ) -> models.AuditRecord:
        local = request.transition_receipt
        completed = request.completion_receipt
        legacy = request.legacy_reported_state
        expected_confirmation = (
            f"reconcile native transition {installation_id} "
            f"{local.record_digest} {completed.receipt_digest}"
        )
        if request.confirmation != expected_confirmation:
            raise NativeTransitionReconciliationError(
                "native_transition_reconciliation_confirmation_mismatch"
            )
        if (
            completed.installation_id != installation_id
            or completed.request_digest != local.request_digest
            or completed.hub_approval_digest != local.hub_approval_digest
            or completed.old_entity_id != local.old_entity_id
            or completed.new_entity_id != local.new_entity_id
            or completed.old_scope_digest != local.old_scope_digest
            or completed.new_scope_digest != local.new_scope_digest
            or completed.old_reported_state_digest != local.old_reported_state_digest
            or completed.transition_receipt_digest
            != regenerated_transition_receipt_digest(
                local,
                new_reported_state_digest=completed.new_reported_state_digest,
            )
            or legacy.digest != local.new_reported_state_digest
        ):
            raise NativeTransitionReconciliationError(
                "native_transition_reconciliation_receipt_mismatch"
            )
        native = request.native_approval
        if (
            native.profile != "full-authority-development"
            or native.scope.installation_id != installation_id
            or native.scope.entity_id != local.new_entity_id
            or native.scope.digest != local.new_scope_digest
            or existing_resources_digest(
                [item.model_dump(mode="json") for item in native.existing_resources]
            )
            != completed.authoritative_uids_digest
            or local.existing_resources_digest != completed.authoritative_uids_digest
            or "sha256:"
            + canonical_digest(
                [{"kind": kind, "name": name} for kind, name in sorted(native.scope.resources)]
            )
            != completed.object_scope_digest
        ):
            raise NativeTransitionReconciliationError(
                "native_transition_reconciliation_scope_mismatch"
            )
        if (
            not same_transition_state_fields(legacy, source)
            or transition_reported_state_digest(legacy, milliseconds=True) != legacy.digest
            or legacy.observed_at
            != local.completed_at.replace(
                microsecond=(local.completed_at.microsecond // 1000) * 1000
            )
            or source.observed_at != local.completed_at
            or source.digest != completed.new_reported_state_digest
            or source.digest != transition_reported_state_digest(source)
            or transition_reported_state_digest(source, milliseconds=True) != legacy.digest
            or completed.completed_at < local.completed_at
            or source.digest == legacy.digest
        ):
            raise NativeTransitionReconciliationError(
                "native_transition_reconciliation_non_time_difference"
            )
        precision_delta = local.completed_at - legacy.observed_at
        if precision_delta <= timedelta(0) or precision_delta > _MAX_PRECISION_DELTA:
            raise NativeTransitionReconciliationError(
                "native_transition_reconciliation_precision_out_of_bounds"
            )
        completion = session.scalar(
            select(models.AuditRecord)
            .where(
                models.AuditRecord.installation_id == installation_id,
                models.AuditRecord.action == _TRANSITION_COMPLETION_ACTION,
                models.AuditRecord.payload["request_digest"].as_string() == local.request_digest,
            )
            .order_by(models.AuditRecord.sequence.desc())
            .limit(1)
        )
        if (
            completion is None
            or completion.payload.get("agent_principal") != completed.agent_principal
            or completion.payload.get("request_digest") != local.request_digest
            or completion.payload.get("transition_receipt_digest")
            != completed.transition_receipt_digest
            or completion.payload.get("new_reported_state_digest")
            != completed.new_reported_state_digest
            or completion.payload.get("receipt") != completed.model_dump(mode="json")
        ):
            raise NativeTransitionReconciliationError(
                "native_transition_reconciliation_completion_not_audited"
            )
        return completion


def _reported_state_model(
    session: Session,
    row: models.Installation,
) -> LegacyNativeScopeTransitionReportedState:
    latest = session.scalars(
        row.state_reports.select()
        .order_by(
            models.StateReport.observed_at.desc(),
            models.StateReport.id.desc(),
        )
        .limit(1)
    ).one()
    document: dict[str, object] = {
        "digest": latest.digest,
        "schema_revision": latest.schema_revision,
        "entities": {
            state.entity_id: {
                "release_id": state.release_id,
                "artifact_digests": list(state.artifact_digests),
                "health": state.health,
            }
            for state in sorted(latest.entity_states, key=lambda item: item.entity_id)
        },
        "observed_at": latest.observed_at.isoformat().replace("+00:00", "Z"),
    }
    if latest.available_artifact_digests is not None:
        document["available_artifact_digests"] = list(latest.available_artifact_digests)
    return LegacyNativeScopeTransitionReportedState.model_validate_json(canonical_bytes(document))


def _reconciliation_receipt(
    command: NativeScopeTransitionStateReconciliationCompletion,
    *,
    principal: str,
    now: datetime,
) -> NativeScopeTransitionStateReconciliationReceipt:
    approval = command.approval.approval
    request = approval.request
    document = {
        "schema_version": "fdai.lifecycle-native-transition-state-reconciliation-receipt.v1",
        "completion_digest": command.digest,
        "request_digest": request.digest,
        "approval_digest": approval.digest,
        "transition_receipt_digest": request.transition_receipt.record_digest,
        "hub_completion_receipt_digest": request.completion_receipt.receipt_digest,
        "installation_id": request.installation_id,
        "old_reported_state_digest": approval.source_hub_reported_state.digest,
        "new_reported_state_digest": command.reported_state.digest,
        "agent_principal": principal,
        "authoritative_reported_state": command.reported_state.model_dump(mode="json"),
        "completed_at": now.isoformat().replace("+00:00", "Z"),
    }
    return NativeScopeTransitionStateReconciliationReceipt.model_validate_json(
        canonical_bytes(
            {
                **document,
                "receipt_digest": "sha256:" + canonical_digest(document),
            }
        )
    )
