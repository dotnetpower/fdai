"""Create-only native resources and UID-fenced updates behind the existing Cluster seam."""

from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai_deployment_cli.lifecycle_native import NativeApproval

from fdai_lifecycle_agent.native_state import NativeState, NativeStateStore
from fdai_lifecycle_agent.workload import (
    COMPONENT_LABEL,
    ENTITY_LABEL,
    Cluster,
    Manifest,
    WorkloadError,
    check_scope,
    object_key,
)

ANCHOR_LABEL = "fdai.io/native-anchor"


@runtime_checkable
class UidCluster(Cluster, Protocol):
    def create(self, manifest: Manifest, *, dry_run: bool = False) -> Manifest: ...

    def replace_owned(self, manifest: Manifest, uid: str, *, dry_run: bool = False) -> None: ...

    def delete_owned(self, kind: str, name: str, uid: str) -> None: ...


def live_uid(live: Manifest | None) -> str:
    value = (live or {}).get("metadata", {}).get("uid")
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None
    ):
        raise WorkloadError("native_resource_identity_unavailable")
    return value


class NativeCluster:
    """The customer namespace stays unmanaged; only retained object UIDs can be changed."""

    def __init__(
        self,
        cluster: UidCluster,
        store: NativeStateStore,
        approval: NativeApproval,
        public_key: bytes,
        clock: Callable[[], datetime],
    ) -> None:
        self._cluster = cluster
        self._store = store
        self._approval = approval
        self._public_key = public_key
        self._clock = clock
        state = self._load()
        if state.proof is None or not state.proof.verify(public_key):
            raise WorkloadError("native_scope_proof_invalid")
        if state.scope != approval.scope:
            raise WorkloadError("native_scope_approval_mismatch")

    def _load(self) -> NativeState:
        state = self._store.load()
        if state is None:
            raise WorkloadError("native_scope_state_missing")
        if state.proof is None or not state.proof.verify(self._public_key):
            raise WorkloadError("native_scope_proof_invalid")
        return state

    def _guard(self, *, mutation: bool = False) -> NativeState:
        state = self._load()
        if state.scope != self._approval.scope:
            raise WorkloadError("native_scope_approval_mismatch")
        if mutation:
            try:
                self._approval.require_current(self._clock())
            except ValueError as error:
                raise WorkloadError("native_scope_approval_expired") from error
            if state.pending is not None:
                raise WorkloadError("native_creation_outcome_unknown")
        anchor = self._cluster.get("Service", state.scope.anchor_name)
        if anchor is None or live_uid(anchor) != state.anchor_uid:
            raise WorkloadError("native_scope_anchor_changed")
        return state

    @staticmethod
    def _resource(state: NativeState, kind: str, name: str) -> str:
        if (kind, name) not in state.scope.resources:
            raise WorkloadError("native_resource_outside_scope")
        return f"{kind}/{name}"

    def get(self, kind: str, name: str) -> Manifest | None:
        state = self._guard()
        key = self._resource(state, kind, name)
        live = self._cluster.get(kind, name)
        if live is None:
            if key in state.deleting:
                self._store.save(
                    state.model_copy(
                        update={
                            "resources": {k: v for k, v in state.resources.items() if k != key},
                            "deleting": state.deleting - {key},
                        }
                    )
                )
            return None
        if state.pending == key:
            raise WorkloadError("native_creation_outcome_unknown")
        if live_uid(live) != state.resources.get(key):
            raise WorkloadError("native_resource_not_owned")
        return live

    def apply(self, manifest: Manifest, *, dry_run: bool = False) -> None:
        state = self._guard(mutation=True)
        check_scope((manifest,), state.scope.namespace)
        kind, name = object_key(manifest)
        key = self._resource(state, kind, name)
        labels = manifest["metadata"]["labels"]
        if (
            labels.get(ENTITY_LABEL) != state.scope.entity_id
            or labels.get(COMPONENT_LABEL) != name
            or key in state.deleting
        ):
            raise WorkloadError("native_resource_outside_scope")
        live = self.get(kind, name)
        owned_uid = state.resources.get(key)
        owned_manifest = deepcopy(dict(manifest)) | {
            "metadata": dict(manifest["metadata"])
            | {
                "ownerReferences": [
                    {
                        "apiVersion": "v1",
                        "kind": "Service",
                        "name": state.scope.anchor_name,
                        "uid": state.anchor_uid,
                        "controller": True,
                        "blockOwnerDeletion": False,
                    }
                ]
            }
        }
        anchor_label = state.creation_receipt_digest.removeprefix("sha256:")[:32]
        owned_manifest["metadata"]["labels"] = dict(labels) | {ANCHOR_LABEL: anchor_label}
        selector = {
            COMPONENT_LABEL: name,
            ENTITY_LABEL: state.scope.entity_id,
            ANCHOR_LABEL: anchor_label,
        }
        if kind == "Deployment":
            owned_manifest["spec"]["selector"]["matchLabels"] = selector
            owned_manifest["spec"]["template"]["metadata"]["labels"].update(selector)
        else:
            owned_manifest["spec"]["selector"] = selector
        if owned_uid is not None:
            if live is None:
                raise WorkloadError("native_owned_resource_missing")
            self._cluster.replace_owned(owned_manifest, owned_uid, dry_run=dry_run)
        else:
            if not dry_run:
                self._store.save(state.model_copy(update={"pending": key}))
            created = self._cluster.create(owned_manifest, dry_run=dry_run)
            if not dry_run:
                uid = live_uid(created)
                self._store.save(
                    state.model_copy(
                        update={"resources": state.resources | {key: uid}, "pending": None}
                    )
                )
        self._guard()

    def delete(self, kind: str, name: str) -> None:
        state = self._guard(mutation=True)
        key = self._resource(state, kind, name)
        live = self.get(kind, name)
        if live is None:
            return
        uid = state.resources.get(key)
        if uid is None:
            raise WorkloadError("native_resource_not_owned")
        self._store.save(state.model_copy(update={"deleting": state.deleting | {key}}))
        self._cluster.delete_owned(kind, name, uid)
        self._guard()
        self.get(kind, name)
