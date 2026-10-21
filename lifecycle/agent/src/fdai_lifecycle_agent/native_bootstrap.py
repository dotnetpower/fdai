"""Explicit local creation of a workload anchor, without claiming its parent namespace."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_native import (
    NativeApproval,
    NativeScope,
    NativeScopeClaim,
    SignedNativeScope,
    sign_native_scope,
)

from fdai_lifecycle_agent.dry_run import load_current_state
from fdai_lifecycle_agent.journal import WorkloadStore
from fdai_lifecycle_agent.native_cluster import UidCluster, live_uid, require_live_anchor
from fdai_lifecycle_agent.native_state import NativeState, NativeStateStore
from fdai_lifecycle_agent.state import LocalStateStore
from fdai_lifecycle_agent.workload import (
    COMPONENT_LABEL,
    ENTITY_LABEL,
    FIELD_MANAGER,
    MANAGED_BY_LABEL,
    CreationRejectedError,
    Manifest,
    MutationNotSubmittedError,
    WorkloadError,
)


def anchor_manifest(scope: NativeScope) -> Manifest:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "namespace": scope.namespace,
            "name": scope.anchor_name,
            "labels": {
                MANAGED_BY_LABEL: FIELD_MANAGER,
                ENTITY_LABEL: scope.entity_id,
                COMPONENT_LABEL: "scope-anchor",
            },
            "annotations": {"fdai.io/native-scope": scope.digest},
        },
        "spec": {
            "type": "ClusterIP",
            "ports": [{"name": "scope", "port": 65535, "targetPort": 65535}],
        },
    }


def bootstrap_native_scope(
    cluster: UidCluster,
    store: NativeStateStore,
    approval: NativeApproval,
    key: Ed25519PrivateKey,
    *,
    current_state_path: Path,
    clock: Callable[[], datetime],
    apply: bool = False,
    timeout_seconds: float = 120,
    monotonic: Callable[[], float] = time.monotonic,
) -> SignedNativeScope | None:
    """Dry-run by default. Retry only a known created UID; uncertain POSTs require review."""
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 900:
        raise ValueError("native bootstrap timeout must be positive and at most 900 seconds")
    with LocalStateStore(store.path.parent).lock():
        deadline = monotonic() + timeout_seconds

        def require_budget() -> None:
            if monotonic() >= deadline:
                raise WorkloadError("native_bootstrap_deadline")
            try:
                approval.require_current(clock())
            except ValueError as error:
                raise WorkloadError("native_scope_approval_expired") from error

        def before_submit() -> None:
            try:
                require_budget()
            except WorkloadError as error:
                raise MutationNotSubmittedError(error.reason_code) from error

        require_budget()
        state = store.load()
        scope = approval.scope
        current = load_current_state(current_state_path)
        if set(current.entities) - {scope.entity_id} or any(
            entity.release_id is not None for entity in current.entities.values()
        ):
            raise WorkloadError("native_scope_requires_uninstalled_state")
        public = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        if state is not None and state.scope != scope:
            raise WorkloadError("native_scope_approval_mismatch")
        if state is not None and state.proof is not None:
            if not state.proof.verify(public):
                raise WorkloadError("native_scope_proof_invalid")
            require_budget()
            live = cluster.get("Service", scope.anchor_name)
            require_live_anchor(live, state.anchor_uid)
            return state.proof
        if state is not None and state.anchor_uid is None and state.pending is not None:
            raise WorkloadError("native_creation_outcome_unknown")
        if state is None or state.anchor_uid is None:
            workload = WorkloadStore(store.path.parent)
            history = workload.load()
            if (
                history.healthy
                or history.journal is not None
                or workload.halted_plan_id() is not None
                or LocalStateStore(store.path.parent).load().plans
            ):
                raise WorkloadError("native_scope_existing_execution_history")
            for kind, name in sorted(scope.resources | {("Service", scope.anchor_name)}):
                require_budget()
                if cluster.get(kind, name) is not None:
                    raise WorkloadError("native_resource_collision")
            manifest = anchor_manifest(scope)
            require_budget()
            cluster.create(manifest, dry_run=True, before_submit=before_submit)
            if not apply:
                return None
            state = NativeState(
                schema_version="fdai.lifecycle-native-state.v1",
                scope=scope,
                approval_digest=approval.digest,
                pending=f"Service/{scope.anchor_name}",
            )
            store.save(state)
            try:
                require_budget()
            except WorkloadError:
                store.save(state.model_copy(update={"pending": None}))
                raise
            try:
                created = cluster.create(manifest, before_submit=before_submit)
            except (CreationRejectedError, MutationNotSubmittedError):
                store.save(state.model_copy(update={"pending": None}))
                raise
            uid = live_uid(created)
            version = created.get("metadata", {}).get("resourceVersion")
            if not isinstance(version, str) or not 0 < len(version) <= 128:
                raise WorkloadError("native_resource_identity_unavailable")
            state = state.model_copy(update={"anchor_uid": uid, "anchor_resource_version": version})
            store.save(state)
        require_budget()
        live = require_live_anchor(cluster.get("Service", scope.anchor_name), state.anchor_uid)
        if live.get("spec", {}).get("selector"):
            raise WorkloadError("native_scope_anchor_changed")
        if not apply:
            return None
        proof = sign_native_scope(
            NativeScopeClaim(
                schema_version="fdai.lifecycle-native-scope.v1",
                installation_id=scope.installation_id,
                entity_id=scope.entity_id,
                product=scope.product,
                scope_digest=scope.digest,
                approval_digest=state.approval_digest,
                creation_receipt_digest=state.creation_receipt_digest,
            ),
            key,
        )
        store.save(state.model_copy(update={"proof": proof, "pending": None}))
        return proof
