"""Crash-safe activation of an accepted native scope over installed legacy Agent state."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_enrollment import installation_key_id
from fdai_deployment_cli.lifecycle_native import NativeApproval
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionRequest,
    SignedNativeScopeTransitionApproval,
    SignedNativeScopeTransitionRequest,
    existing_resources_digest,
    sign_transition_request,
)

from fdai_lifecycle_agent.dry_run import (
    CurrentState,
    EntityState,
    load_current_state,
    snapshot_document,
)
from fdai_lifecycle_agent.journal import WORKLOAD_FILE_NAME, WorkloadState, WorkloadStore
from fdai_lifecycle_agent.native_cluster import UidCluster, live_uid, require_live_anchor
from fdai_lifecycle_agent.native_state import NativeState, NativeStateStore
from fdai_lifecycle_agent.state import (
    AgentStateError,
    LocalStateStore,
    write_bytes_atomically,
    write_json_atomically,
)
from fdai_lifecycle_agent.strict_json import load_json, read_limited
from fdai_lifecycle_agent.workload import WorkloadError

ROLLBACK_FILE_NAME = "lifecycle-native-transition-rollback.json"
PENDING_FILE_NAME = "lifecycle-native-transition-pending.json"
RECEIPT_FILE_NAME = "lifecycle-native-transition-receipt.json"
RECOVERY_FILE_NAME = "lifecycle-native-transition-recovery.json"
_MAX_RECORD_BYTES = 8 * 1024 * 1024


def prepare_native_transition_request(
    *,
    state_dir: Path,
    current_state_path: Path,
    new_native_state_path: Path,
    approval: NativeApproval,
    recovery_request_digest: str,
    installation_key: Ed25519PrivateKey,
    now: datetime,
    lifetime: timedelta = timedelta(minutes=10),
) -> SignedNativeScopeTransitionRequest:
    """Create the exact installation proof without changing Agent or workload state."""

    with LocalStateStore(state_dir).lock():
        _require_no_transition(state_dir)
        old = _require_native_state(NativeStateStore(state_dir).path)
        new = _require_native_state(new_native_state_path)
        current = load_current_state(current_state_path)
        _validate_local_inputs(old, new, current, approval)
        _require_idle(state_dir)
        public = installation_key.public_key().public_bytes_raw()
        _require_recovered_proof(new, public)
        new_proof = new.proof
        if new_proof is None:
            raise WorkloadError("native_transition_recovered_proof_invalid")
        expires_at = now + lifetime
        confirmation = (
            f"transition native scope {old.scope.installation_id} "
            f"{old.scope.digest} {new.scope.digest}"
        )
        request = NativeScopeTransitionRequest(
            schema_version="fdai.lifecycle-native-transition-request.v1",
            request_id=uuid4(),
            installation_id=old.scope.installation_id,
            old_entity_id=old.scope.entity_id,
            new_entity_id=new.scope.entity_id,
            old_scope_digest=old.scope.digest,
            new_scope_digest=new.scope.digest,
            old_reported_state_digest=current.digest,
            ownership_claim_digest=new_proof.claim.digest,
            recovery_request_digest=recovery_request_digest,
            recovered_identity_key_id=installation_key_id(public),
            existing_resources_digest=_approval_resources_digest(approval),
            requested_at=now,
            expires_at=expires_at,
            confirmation=confirmation,
        )
        return sign_transition_request(request, installation_key)


def transition_native_scope(
    cluster: UidCluster,
    *,
    state_dir: Path,
    current_state_path: Path,
    new_native_state_path: Path,
    approval: NativeApproval,
    signed_approval: SignedNativeScopeTransitionApproval,
    hub_public_key: bytes,
    expected_hub_key_id: str,
    expected_hub_key_epoch: int,
    installation_public_key: bytes,
    now: datetime,
    after_write: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Commit one state transition or restore its exact old files after any incomplete attempt."""

    request = signed_approval.approval.request.request
    with LocalStateStore(state_dir).lock():
        receipt = _load_record(state_dir / RECEIPT_FILE_NAME, required=False)
        if receipt is not None:
            _require_signed_approval(
                signed_approval,
                hub_public_key=hub_public_key,
                expected_hub_key_id=expected_hub_key_id,
                expected_hub_key_epoch=expected_hub_key_epoch,
                installation_public_key=installation_public_key,
            )
            return _validate_completed_retry(
                receipt,
                request_digest=request.digest,
                state_dir=state_dir,
                current_state_path=current_state_path,
            )
        if (state_dir / PENDING_FILE_NAME).exists():
            _restore_pending(state_dir, current_state_path, now)
            raise WorkloadError("native_transition_interrupted_restored")
        retained_rollback = _load_record(state_dir / ROLLBACK_FILE_NAME, required=False)
        if (
            retained_rollback is not None
            and retained_rollback.get("request_digest") != request.digest
        ):
            raise WorkloadError("native_transition_record_conflict")
        if retained_rollback is None and (state_dir / RECOVERY_FILE_NAME).exists():
            raise WorkloadError("native_transition_record_conflict")
        _require_signed_approval(
            signed_approval,
            hub_public_key=hub_public_key,
            expected_hub_key_id=expected_hub_key_id,
            expected_hub_key_epoch=expected_hub_key_epoch,
            installation_public_key=installation_public_key,
        )
        checked_at = _aware_transition_timestamp(now)
        try:
            request.require_current(checked_at)
            signed_approval.approval.require_current(checked_at)
            approval.require_current(checked_at)
        except ValueError as error:
            raise WorkloadError("native_transition_approval_expired") from error
        old = _require_native_state(NativeStateStore(state_dir).path)
        new = _require_native_state(new_native_state_path)
        current = load_current_state(current_state_path)
        _validate_local_inputs(old, new, current, approval)
        _validate_authorized_request(request, old, new, current, approval)
        _require_recovered_proof(new, installation_public_key)
        _require_idle(state_dir)
        _verify_inventory(cluster, new, approval)
        transitioned_at = (
            checked_at
            if retained_rollback is None
            else _rollback_transition_timestamp(retained_rollback)
        )
        rollback = retained_rollback or _rollback_record(
            request_digest=request.digest,
            state_dir=state_dir,
            current_state_path=current_state_path,
            transitioned_at=transitioned_at,
        )
        rollback_path = state_dir / ROLLBACK_FILE_NAME
        if retained_rollback is None:
            _write_new_record(rollback_path, rollback)
        pending = _record(
            {
                "schema_version": "fdai.lifecycle-native-transition-pending.v1",
                "request_digest": request.digest,
                "rollback_record_digest": rollback["record_digest"],
                "started_at": _format_transition_timestamp(transitioned_at),
            }
        )
        pending_path = state_dir / PENDING_FILE_NAME
        _write_new_record(pending_path, pending)
        if after_write is not None:
            after_write("pending")
        try:
            NativeStateStore(state_dir).save(new)
            if after_write is not None:
                after_write("native-state")
            WorkloadStore(state_dir).save(WorkloadState())
            if after_write is not None:
                after_write("workload-state")
            new_snapshot = snapshot_document(
                {request.new_entity_id: EntityState(None, frozenset())},
                schema_revision=current.schema_revision,
                observed_at=transitioned_at,
                available_artifact_digests=current.available_artifact_digests,
                preserve_timestamp_precision=True,
            )
            write_json_atomically(current_state_path, new_snapshot)
            if after_write is not None:
                after_write("current-state")
            receipt = _record(
                {
                    "schema_version": "fdai.lifecycle-native-transition-receipt.v1",
                    "request_digest": request.digest,
                    "hub_approval_digest": signed_approval.approval.digest,
                    "installation_id": request.installation_id,
                    "old_entity_id": request.old_entity_id,
                    "new_entity_id": request.new_entity_id,
                    "old_scope_digest": request.old_scope_digest,
                    "new_scope_digest": request.new_scope_digest,
                    "old_reported_state_digest": request.old_reported_state_digest,
                    "new_reported_state_digest": new_snapshot["digest"],
                    "ownership_claim_digest": request.ownership_claim_digest,
                    "recovery_request_digest": request.recovery_request_digest,
                    "existing_resources_digest": request.existing_resources_digest,
                    "rollback_record_digest": rollback["record_digest"],
                    "completed_at": _format_transition_timestamp(transitioned_at),
                }
            )
            _write_new_record(state_dir / RECEIPT_FILE_NAME, receipt)
            _unlink_fsync(pending_path)
            return receipt
        except Exception as error:
            _restore(state_dir, current_state_path, rollback)
            _write_recovery_record(state_dir, request.digest, transitioned_at)
            _unlink_fsync(pending_path)
            raise WorkloadError("native_transition_failed_restored") from error


def _validate_local_inputs(
    old: NativeState,
    new: NativeState,
    current: CurrentState,
    approval: NativeApproval,
) -> None:
    old_entity = current.entities.get(old.scope.entity_id)
    if (
        old.scope.installation_id != new.scope.installation_id
        or approval.scope != new.scope
        or old.scope == new.scope
        or set(current.entities) != {old.scope.entity_id}
        or old_entity is None
        or old_entity.release_id is None
        or new.proof is None
        or new.resources
        or new.deleting
        or new.pending is not None
    ):
        raise WorkloadError("native_transition_state_mismatch")


def _validate_authorized_request(
    request: NativeScopeTransitionRequest,
    old: NativeState,
    new: NativeState,
    current: CurrentState,
    approval: NativeApproval,
) -> None:
    proof = new.proof
    if proof is None:
        raise WorkloadError("native_transition_recovered_proof_invalid")
    if (
        request.installation_id != old.scope.installation_id
        or request.old_entity_id != old.scope.entity_id
        or request.new_entity_id != new.scope.entity_id
        or request.old_scope_digest != old.scope.digest
        or request.new_scope_digest != new.scope.digest
        or request.old_reported_state_digest != current.digest
        or request.ownership_claim_digest != proof.claim.digest
        or request.existing_resources_digest != _approval_resources_digest(approval)
    ):
        raise WorkloadError("native_transition_authorization_mismatch")


def _require_recovered_proof(state: NativeState, public_key: bytes) -> None:
    if state.proof is None or not state.proof.verify(public_key):
        raise WorkloadError("native_transition_recovered_proof_invalid")


def _require_signed_approval(
    signed: SignedNativeScopeTransitionApproval,
    *,
    hub_public_key: bytes,
    expected_hub_key_id: str,
    expected_hub_key_epoch: int,
    installation_public_key: bytes,
) -> None:
    if not signed.verify(
        hub_public_key,
        key_id=expected_hub_key_id,
        key_epoch=expected_hub_key_epoch,
    ):
        raise WorkloadError("native_transition_hub_approval_invalid")
    if not signed.approval.request.verify(installation_public_key):
        raise WorkloadError("native_transition_recovered_proof_invalid")


def _require_idle(state_dir: Path) -> None:
    agent = LocalStateStore(state_dir).load()
    if any(
        not record.reported or record.pending_reports or record.report_conflict_attempt is not None
        for record in agent.plans.values()
    ):
        raise WorkloadError("native_transition_plan_open")
    workload = WorkloadStore(state_dir).load()
    if workload.journal is not None and workload.journal.phase in {"prepared", "applying"}:
        raise WorkloadError("native_transition_journal_open")


def _verify_inventory(cluster: UidCluster, state: NativeState, approval: NativeApproval) -> None:
    require_live_anchor(
        cluster.get("Service", state.scope.anchor_name),
        state.anchor_uid,
    )
    existing = {item.key: item.uid for item in approval.existing_resources}
    for kind, name in sorted(state.scope.resources):
        live = cluster.get(kind, name)
        expected_uid = existing.get((kind, name))
        if expected_uid is None:
            if live is not None:
                raise WorkloadError("native_transition_unapproved_object_exists")
        elif live is None or live_uid(live) != expected_uid:
            raise WorkloadError("native_transition_existing_uid_mismatch")


def _approval_resources_digest(approval: NativeApproval) -> str:
    return existing_resources_digest(
        [item.model_dump(mode="json") for item in approval.existing_resources]
    )


def _require_native_state(path: Path) -> NativeState:
    try:
        raw = read_limited(path, limit=128 * 1024, label="native transition state")
        load_json(raw, label="native transition state")
        return NativeState.model_validate_json(raw)
    except (OSError, ValueError) as error:
        raise WorkloadError("native_transition_state_invalid") from error


def _require_no_transition(state_dir: Path) -> None:
    if any(
        (state_dir / name).exists()
        for name in (PENDING_FILE_NAME, RECEIPT_FILE_NAME, ROLLBACK_FILE_NAME)
    ):
        raise WorkloadError("native_transition_already_recorded")


def _rollback_record(
    *,
    request_digest: str,
    state_dir: Path,
    current_state_path: Path,
    transitioned_at: datetime,
) -> dict[str, object]:
    return _record(
        {
            "schema_version": "fdai.lifecycle-native-transition-rollback.v1",
            "request_digest": request_digest,
            "created_at": _format_transition_timestamp(transitioned_at),
            "files": {
                "native_state": _encoded_file(NativeStateStore(state_dir).path, required=True),
                "current_state": _encoded_file(current_state_path, required=True),
                "workload_state": _encoded_file(state_dir / WORKLOAD_FILE_NAME, required=False),
            },
        }
    )


def _aware_transition_timestamp(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise WorkloadError("native_transition_timestamp_invalid")
    return value.astimezone(UTC)


def _format_transition_timestamp(value: datetime) -> str:
    return _aware_transition_timestamp(value).isoformat().replace("+00:00", "Z")


def _rollback_transition_timestamp(rollback: dict[str, object]) -> datetime:
    value = rollback.get("created_at")
    if not isinstance(value, str):
        raise AgentStateError("native transition rollback timestamp is invalid")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AgentStateError("native transition rollback timestamp is invalid") from error
    try:
        return _aware_transition_timestamp(timestamp)
    except WorkloadError as error:
        raise AgentStateError("native transition rollback timestamp is invalid") from error


def _encoded_file(path: Path, *, required: bool) -> dict[str, str] | None:
    try:
        data = read_limited(path, limit=4 * 1024 * 1024, label="native transition rollback input")
    except FileNotFoundError:
        if required:
            raise WorkloadError("native_transition_rollback_input_missing") from None
        return None
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "base64": base64.b64encode(data).decode("ascii"),
    }


def _restore_pending(state_dir: Path, current_state_path: Path, now: datetime) -> None:
    pending = _load_record(state_dir / PENDING_FILE_NAME, required=True)
    rollback = _load_record(state_dir / ROLLBACK_FILE_NAME, required=True)
    if pending is None or rollback is None:
        raise AgentStateError("native transition recovery record is missing")
    request_digest = pending.get("request_digest")
    if (
        not isinstance(request_digest, str)
        or rollback["request_digest"] != request_digest
        or pending.get("rollback_record_digest") != rollback.get("record_digest")
    ):
        raise AgentStateError("native transition recovery binding is invalid")
    _restore(state_dir, current_state_path, rollback)
    _write_recovery_record(state_dir, request_digest, now)
    _unlink_fsync(state_dir / PENDING_FILE_NAME)


def _restore(state_dir: Path, current_state_path: Path, rollback: dict[str, object]) -> None:
    files = rollback.get("files")
    if not isinstance(files, dict):
        raise AgentStateError("native transition rollback record is invalid")
    _restore_file(NativeStateStore(state_dir).path, files.get("native_state"), required=True)
    _restore_file(current_state_path, files.get("current_state"), required=True)
    _restore_file(state_dir / WORKLOAD_FILE_NAME, files.get("workload_state"), required=False)


def _restore_file(path: Path, record: object, *, required: bool) -> None:
    if record is None and not required:
        path.unlink(missing_ok=True)
        return
    if not isinstance(record, dict) or set(record) != {"sha256", "base64"}:
        raise AgentStateError("native transition rollback file record is invalid")
    try:
        data = base64.b64decode(record["base64"], validate=True)
    except (TypeError, ValueError) as error:
        raise AgentStateError("native transition rollback bytes are invalid") from error
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise AgentStateError("native transition rollback digest is invalid")
    write_bytes_atomically(path, data)


def _write_recovery_record(state_dir: Path, request_digest: str, now: datetime) -> None:
    path = state_dir / RECOVERY_FILE_NAME
    if path.exists():
        return
    _write_new_record(
        path,
        _record(
            {
                "schema_version": "fdai.lifecycle-native-transition-recovery.v1",
                "request_digest": request_digest,
                "outcome": "old-state-restored",
                "recorded_at": now.isoformat(),
            }
        ),
    )


def _validate_completed_retry(
    receipt: dict[str, object],
    *,
    request_digest: str,
    state_dir: Path,
    current_state_path: Path,
) -> dict[str, object]:
    if receipt.get("request_digest") != request_digest:
        raise WorkloadError("native_transition_already_completed")
    state = _require_native_state(NativeStateStore(state_dir).path)
    current = load_current_state(current_state_path)
    workload = WorkloadStore(state_dir).load()
    if (
        state.scope.digest != receipt.get("new_scope_digest")
        or current.digest != receipt.get("new_reported_state_digest")
        or set(current.entities) != {receipt.get("new_entity_id")}
        or workload != WorkloadState()
    ):
        raise WorkloadError("native_transition_completed_state_mismatch")
    pending = state_dir / PENDING_FILE_NAME
    if pending.exists():
        _unlink_fsync(pending)
    return receipt


def _record(document: dict[str, object]) -> dict[str, object]:
    return document | {"record_digest": "sha256:" + canonical_digest(document)}


def _load_record(path: Path, *, required: bool) -> dict[str, Any] | None:
    try:
        raw = read_limited(path, limit=_MAX_RECORD_BYTES, label="native transition record")
    except FileNotFoundError:
        if required:
            raise AgentStateError("native transition record is missing") from None
        return None
    try:
        document = load_json(raw, label="native transition record")
    except ValueError as error:
        raise AgentStateError("native transition record is invalid") from error
    if not isinstance(document, dict):
        raise AgentStateError("native transition record is invalid")
    digest = document.pop("record_digest", None)
    if digest != "sha256:" + canonical_digest(document):
        raise AgentStateError("native transition record digest is invalid")
    document["record_digest"] = digest
    return document


def _write_new_record(path: Path, document: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise AgentStateError("native transition record already exists")
    write_bytes_atomically(path, json.dumps(document, sort_keys=True, indent=2).encode() + b"\n")


def _unlink_fsync(path: Path) -> None:
    path.unlink(missing_ok=True)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
