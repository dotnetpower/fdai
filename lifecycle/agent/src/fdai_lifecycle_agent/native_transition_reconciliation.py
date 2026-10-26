"""Crash-safe repair for the legacy native-transition timestamp precision defect."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fdai_deployment_cli.lifecycle_native import NativeApproval
from fdai_deployment_cli.lifecycle_native_reconciliation import (
    LegacyNativeScopeTransitionReceipt,
    NativeScopeTransitionStateReconciliationApproval,
    NativeScopeTransitionStateReconciliationCompletion,
    NativeScopeTransitionStateReconciliationReceipt,
    NativeScopeTransitionStateReconciliationRequest,
    SignedNativeScopeTransitionStateReconciliationApproval,
    regenerated_transition_receipt_digest,
    same_transition_state_fields,
    transition_reported_state_digest,
)
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionCompletionReceipt,
    NativeScopeTransitionReportedState,
    existing_resources_digest,
)

from fdai_lifecycle_agent.native_cluster import UidCluster
from fdai_lifecycle_agent.native_state import NativeStateStore
from fdai_lifecycle_agent.native_transition import (
    _encoded_file,
    _load_record,
    _require_idle,
    _require_native_state,
    _restore_file,
    _unlink_fsync,
    _verify_inventory,
    _write_new_record,
)
from fdai_lifecycle_agent.state import LocalStateStore, write_json_atomically
from fdai_lifecycle_agent.strict_json import load_json, read_limited
from fdai_lifecycle_agent.workload import WorkloadError

RECONCILIATION_ROLLBACK_FILE_NAME = "lifecycle-native-transition-state-reconciliation-rollback.json"
RECONCILIATION_PENDING_FILE_NAME = "lifecycle-native-transition-state-reconciliation-pending.json"
RECONCILIATION_RECEIPT_FILE_NAME = "lifecycle-native-transition-state-reconciliation-receipt.json"
_MAX_PRECISION_DELTA = timedelta(milliseconds=1)

type ReconciliationCompleter = Callable[
    [NativeScopeTransitionStateReconciliationCompletion],
    NativeScopeTransitionStateReconciliationReceipt,
]


def prepare_native_transition_state_reconciliation_request(
    *,
    state_dir: Path,
    current_state_path: Path,
    completion_receipt: NativeScopeTransitionCompletionReceipt,
    native_approval: NativeApproval,
    installation_public_key: bytes,
    now: datetime,
    lifetime: timedelta = timedelta(minutes=10),
) -> NativeScopeTransitionStateReconciliationRequest:
    """Build a bounded operator request without changing any durable state."""

    with LocalStateStore(state_dir).lock():
        _require_idle(state_dir)
        local = _transition_receipt(state_dir)
        legacy = _reported_state(current_state_path)
        native = _require_native_state(NativeStateStore(state_dir).path)
        _validate_local_evidence(
            local,
            completion_receipt,
            legacy,
            native_approval,
            native,
            installation_public_key,
        )
        return NativeScopeTransitionStateReconciliationRequest(
            schema_version=("fdai.lifecycle-native-transition-state-reconciliation-request.v1"),
            request_id=uuid4(),
            transition_receipt=local,
            completion_receipt=completion_receipt,
            native_approval=native_approval,
            legacy_reported_state=legacy,
            requested_at=now,
            expires_at=now + lifetime,
            confirmation=(
                f"reconcile native transition {local.installation_id} "
                f"{local.record_digest} {completion_receipt.receipt_digest}"
            ),
        )


def reconcile_native_transition_state(
    cluster: UidCluster,
    *,
    state_dir: Path,
    current_state_path: Path,
    native_approval: NativeApproval,
    completion_receipt: NativeScopeTransitionCompletionReceipt,
    signed_approval: SignedNativeScopeTransitionStateReconciliationApproval,
    hub_public_key: bytes,
    expected_hub_key_id: str,
    expected_hub_key_epoch: int,
    installation_public_key: bytes,
    now: datetime,
    complete: ReconciliationCompleter,
    after_write: Callable[[str], None] | None = None,
) -> NativeScopeTransitionStateReconciliationReceipt:
    """Correct only current-state, submit it, and retain exact rollback and readback."""

    approval = signed_approval.approval
    request = approval.request
    with LocalStateStore(state_dir).lock():
        _require_signed_approval(
            signed_approval,
            hub_public_key=hub_public_key,
            expected_hub_key_id=expected_hub_key_id,
            expected_hub_key_epoch=expected_hub_key_epoch,
        )
        existing = _reconciliation_receipt(state_dir, required=False)
        if existing is not None:
            local = _transition_receipt(state_dir)
            native = _require_native_state(NativeStateStore(state_dir).path)
            proof = native.proof
            if (
                existing.request_digest != request.digest
                or existing.approval_digest != approval.digest
                or existing.authoritative_reported_state != approval.authoritative_reported_state
                or local != request.transition_receipt
                or completion_receipt != request.completion_receipt
                or native_approval != request.native_approval
                or native.scope != native_approval.scope
                or proof is None
                or not proof.verify(installation_public_key)
            ):
                raise WorkloadError("native_transition_reconciliation_repeat_conflict")
            if _reported_state(current_state_path) != existing.authoritative_reported_state:
                raise WorkloadError("native_transition_reconciliation_completed_state_mismatch")
            pending_path = state_dir / RECONCILIATION_PENDING_FILE_NAME
            if pending_path.exists():
                pending = _load_record(pending_path, required=True)
                rollback = _load_record(
                    state_dir / RECONCILIATION_ROLLBACK_FILE_NAME,
                    required=True,
                )
                if (
                    pending is None
                    or rollback is None
                    or pending.get("request_digest") != request.digest
                    or rollback.get("request_digest") != request.digest
                    or pending.get("rollback_record_digest") != rollback.get("record_digest")
                ):
                    raise WorkloadError("native_transition_reconciliation_record_conflict")
                _unlink_fsync(pending_path)
            return existing
        try:
            approval.require_current(now)
        except ValueError as error:
            raise WorkloadError("native_transition_reconciliation_approval_expired") from error
        pending_path = state_dir / RECONCILIATION_PENDING_FILE_NAME
        rollback_path = state_dir / RECONCILIATION_ROLLBACK_FILE_NAME
        rollback = _load_record(rollback_path, required=False)
        if pending_path.exists():
            pending = _load_record(pending_path, required=True)
            if (
                pending is None
                or rollback is None
                or pending.get("request_digest") != request.digest
                or rollback.get("request_digest") != request.digest
                or pending.get("rollback_record_digest") != rollback.get("record_digest")
            ):
                raise WorkloadError("native_transition_reconciliation_record_conflict")
            _restore_reconciliation(current_state_path, rollback)
            _unlink_fsync(pending_path)
        if rollback is not None and rollback.get("request_digest") != request.digest:
            raise WorkloadError("native_transition_reconciliation_record_conflict")
        _require_idle(state_dir)
        local = _transition_receipt(state_dir)
        legacy = _reported_state(current_state_path)
        native = _require_native_state(NativeStateStore(state_dir).path)
        _validate_local_evidence(
            local,
            completion_receipt,
            legacy,
            native_approval,
            native,
            installation_public_key,
        )
        if (
            request.transition_receipt != local
            or request.completion_receipt != completion_receipt
            or request.native_approval != native_approval
            or request.legacy_reported_state != legacy
        ):
            raise WorkloadError("native_transition_reconciliation_authorization_mismatch")
        _validate_authoritative_approval(approval)
        _verify_inventory(cluster, native, native_approval)
        rollback = rollback or {
            "schema_version": ("fdai.lifecycle-native-transition-state-reconciliation-rollback.v1"),
            "request_digest": request.digest,
            "current_state": _encoded_file(current_state_path, required=True),
        }
        if rollback_path.exists():
            if _load_record(rollback_path, required=True) != rollback:
                raise WorkloadError("native_transition_reconciliation_record_conflict")
        else:
            from fdai_lifecycle_agent.native_transition import _record

            rollback = _record(rollback)
            _write_new_record(rollback_path, rollback)
        from fdai_lifecycle_agent.native_transition import _record

        pending = _record(
            {
                "schema_version": (
                    "fdai.lifecycle-native-transition-state-reconciliation-pending.v1"
                ),
                "request_digest": request.digest,
                "rollback_record_digest": rollback["record_digest"],
                "started_at": now.isoformat(),
            }
        )
        _write_new_record(pending_path, pending)
        if after_write is not None:
            after_write("pending")
        hub_receipt: NativeScopeTransitionStateReconciliationReceipt | None = None
        try:
            write_json_atomically(
                current_state_path,
                approval.authoritative_reported_state.model_dump(mode="json"),
            )
            if after_write is not None:
                after_write("current-state")
            command = NativeScopeTransitionStateReconciliationCompletion(
                schema_version=(
                    "fdai.lifecycle-native-transition-state-reconciliation-completion.v1"
                ),
                approval=signed_approval,
                reported_state=approval.authoritative_reported_state,
            )
            hub_receipt = complete(command)
            _validate_hub_readback(hub_receipt, command)
            _write_reconciliation_receipt(state_dir, hub_receipt)
            if after_write is not None:
                after_write("receipt")
            _unlink_fsync(pending_path)
            return hub_receipt
        except Exception as error:
            retained_receipt = _reconciliation_receipt(state_dir, required=False)
            if hub_receipt is not None and retained_receipt == hub_receipt:
                raise WorkloadError(
                    "native_transition_reconciliation_completion_uncertain"
                ) from error
            _restore_reconciliation(current_state_path, rollback)
            _unlink_fsync(pending_path)
            raise WorkloadError("native_transition_reconciliation_failed_restored") from error


def _validate_local_evidence(
    local: LegacyNativeScopeTransitionReceipt,
    completion: NativeScopeTransitionCompletionReceipt,
    legacy: NativeScopeTransitionReportedState,
    approval: NativeApproval,
    native: object,
    installation_public_key: bytes,
) -> None:
    if not hasattr(native, "scope") or not hasattr(native, "proof"):
        raise WorkloadError("native_transition_reconciliation_native_state_invalid")
    proof = native.proof
    if proof is None or not proof.verify(installation_public_key):
        raise WorkloadError("native_transition_reconciliation_native_proof_invalid")
    precision_delta = local.completed_at - legacy.observed_at
    full_precision_digest = transition_reported_state_digest(
        legacy,
        observed_at=local.completed_at,
    )
    if (
        native.scope != approval.scope
        or native.scope.installation_id != local.installation_id
        or native.scope.entity_id != local.new_entity_id
        or native.scope.digest != local.new_scope_digest
        or proof.claim.digest != local.ownership_claim_digest
        or completion.installation_id != local.installation_id
        or completion.request_digest != local.request_digest
        or completion.hub_approval_digest != local.hub_approval_digest
        or completion.old_entity_id != local.old_entity_id
        or completion.new_entity_id != local.new_entity_id
        or completion.old_scope_digest != local.old_scope_digest
        or completion.new_scope_digest != local.new_scope_digest
        or completion.old_reported_state_digest != local.old_reported_state_digest
        or completion.new_reported_state_digest != full_precision_digest
        or completion.transition_receipt_digest
        != regenerated_transition_receipt_digest(
            local,
            new_reported_state_digest=completion.new_reported_state_digest,
        )
        or existing_resources_digest(
            [item.model_dump(mode="json") for item in approval.existing_resources]
        )
        != completion.authoritative_uids_digest
        or local.existing_resources_digest != completion.authoritative_uids_digest
        or legacy.digest != local.new_reported_state_digest
        or transition_reported_state_digest(legacy, milliseconds=True) != legacy.digest
        or legacy.observed_at
        != local.completed_at.replace(microsecond=(local.completed_at.microsecond // 1000) * 1000)
        or precision_delta <= timedelta(0)
        or precision_delta > _MAX_PRECISION_DELTA
        or completion.completed_at < local.completed_at
        or full_precision_digest == legacy.digest
    ):
        raise WorkloadError("native_transition_reconciliation_evidence_mismatch")


def _validate_authoritative_approval(
    approval: NativeScopeTransitionStateReconciliationApproval,
) -> None:
    request = approval.request
    source = approval.source_hub_reported_state
    authoritative = approval.authoritative_reported_state
    legacy = request.legacy_reported_state
    if (
        not same_transition_state_fields(legacy, source)
        or source.observed_at != request.transition_receipt.completed_at
        or source.digest != request.completion_receipt.new_reported_state_digest
        or source.digest != transition_reported_state_digest(source)
        or source.digest == legacy.digest
        or authoritative != source
        or request.completion_receipt.completed_at < source.observed_at
    ):
        raise WorkloadError("native_transition_reconciliation_authoritative_state_invalid")


def _require_signed_approval(
    signed: SignedNativeScopeTransitionStateReconciliationApproval,
    *,
    hub_public_key: bytes,
    expected_hub_key_id: str,
    expected_hub_key_epoch: int,
) -> None:
    if not signed.verify(
        hub_public_key,
        key_id=expected_hub_key_id,
        key_epoch=expected_hub_key_epoch,
    ):
        raise WorkloadError("native_transition_reconciliation_hub_approval_invalid")


def _validate_hub_readback(
    receipt: NativeScopeTransitionStateReconciliationReceipt,
    command: NativeScopeTransitionStateReconciliationCompletion,
) -> None:
    approval = command.approval.approval
    request = approval.request
    if (
        receipt.completion_digest != command.digest
        or receipt.request_digest != request.digest
        or receipt.approval_digest != approval.digest
        or receipt.transition_receipt_digest != request.transition_receipt.record_digest
        or receipt.hub_completion_receipt_digest != request.completion_receipt.receipt_digest
        or receipt.installation_id != request.installation_id
        or receipt.old_reported_state_digest != approval.source_hub_reported_state.digest
        or receipt.new_reported_state_digest != approval.authoritative_reported_state.digest
        or receipt.authoritative_reported_state != approval.authoritative_reported_state
    ):
        raise WorkloadError("native_transition_reconciliation_readback_mismatch")


def _transition_receipt(state_dir: Path) -> LegacyNativeScopeTransitionReceipt:
    from fdai_lifecycle_agent.native_transition import RECEIPT_FILE_NAME

    record = _load_record(state_dir / RECEIPT_FILE_NAME, required=True)
    if record is None:
        raise WorkloadError("native_transition_reconciliation_receipt_missing")
    try:
        return LegacyNativeScopeTransitionReceipt.model_validate_json(
            json.dumps(record, sort_keys=True)
        )
    except ValueError as error:
        raise WorkloadError("native_transition_reconciliation_receipt_invalid") from error


def _reported_state(path: Path) -> NativeScopeTransitionReportedState:
    try:
        raw = read_limited(path, limit=1024 * 1024, label="native transition reconciliation state")
        load_json(raw, label="native transition reconciliation state")
        return NativeScopeTransitionReportedState.model_validate_json(raw)
    except (OSError, ValueError) as error:
        raise WorkloadError("native_transition_reconciliation_state_invalid") from error


def _restore_reconciliation(current_state_path: Path, rollback: dict[str, object]) -> None:
    _restore_file(current_state_path, rollback.get("current_state"), required=True)


def _reconciliation_receipt(
    state_dir: Path,
    *,
    required: bool,
) -> NativeScopeTransitionStateReconciliationReceipt | None:
    path = state_dir / RECONCILIATION_RECEIPT_FILE_NAME
    try:
        raw = read_limited(path, limit=256 * 1024, label="native transition reconciliation receipt")
    except FileNotFoundError:
        if required:
            raise WorkloadError("native_transition_reconciliation_receipt_missing") from None
        return None
    try:
        load_json(raw, label="native transition reconciliation receipt")
        return NativeScopeTransitionStateReconciliationReceipt.model_validate_json(raw)
    except ValueError as error:
        raise WorkloadError("native_transition_reconciliation_receipt_invalid") from error


def _write_reconciliation_receipt(
    state_dir: Path,
    receipt: NativeScopeTransitionStateReconciliationReceipt,
) -> None:
    path = state_dir / RECONCILIATION_RECEIPT_FILE_NAME
    if path.exists() or path.is_symlink():
        raise WorkloadError("native_transition_reconciliation_receipt_conflict")
    from fdai_lifecycle_agent.state import write_bytes_atomically

    write_bytes_atomically(
        path,
        json.dumps(receipt.model_dump(mode="json"), sort_keys=True, indent=2).encode() + b"\n",
    )
