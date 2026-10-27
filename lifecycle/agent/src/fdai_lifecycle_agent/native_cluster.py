"""Create-only native resources and UID-fenced updates behind the existing Cluster seam."""

from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from typing import Protocol, runtime_checkable

from fdai_deployment_cli.lifecycle_native import NativeApproval, NativeObjectIdentity
from fdai_deployment_cli.lifecycle_plan import LifecyclePlan

from fdai_lifecycle_agent.adoption import AdoptionExpectation, adopt_runtime_objects
from fdai_lifecycle_agent.native_state import NativeState, NativeStateStore
from fdai_lifecycle_agent.workload import (
    COMPONENT_LABEL,
    ENTITY_LABEL,
    FIELD_MANAGER,
    MANAGED_BY_LABEL,
    Cluster,
    CreationRejectedError,
    Manifest,
    MutationNotSubmittedError,
    WorkloadError,
    check_scope,
    object_key,
)

ANCHOR_LABEL = "fdai.io/native-anchor"


@runtime_checkable
class UidCluster(Cluster, Protocol):
    def create(
        self, manifest: Manifest, *, dry_run: bool = False, before_submit: Callable[[], None]
    ) -> Manifest: ...

    def replace_owned(
        self,
        manifest: Manifest,
        uid: str,
        *,
        dry_run: bool = False,
        before_submit: Callable[[], None],
    ) -> None: ...

    def delete_owned(
        self, kind: str, name: str, uid: str, *, before_submit: Callable[[], None]
    ) -> None: ...


@runtime_checkable
class AdoptionUidCluster(UidCluster, Protocol):
    def adopt_terraform_owned(
        self,
        manifest: Manifest,
        *,
        uid: str,
        resource_version: str,
        dry_run: bool = False,
        before_submit: Callable[[], None] | None = None,
    ) -> Manifest: ...


def live_uid(live: Manifest | None) -> str:
    value = (live or {}).get("metadata", {}).get("uid")
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None
    ):
        raise WorkloadError("native_resource_identity_unavailable")
    return value


def require_live_anchor(live: Manifest | None, uid: str | None) -> Manifest:
    if (
        live is None
        or live_uid(live) != uid
        or live.get("metadata", {}).get("deletionTimestamp") is not None
    ):
        raise WorkloadError("native_scope_anchor_changed")
    return live


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

    def _require_current(self) -> None:
        try:
            self._approval.require_current(self._clock())
        except ValueError as error:
            raise MutationNotSubmittedError(
                "native_scope_approval_expired", retryable=True
            ) from error

    def _guard(self, *, mutation: bool = False) -> NativeState:
        state = self._load()
        if state.scope != self._approval.scope:
            raise WorkloadError("native_scope_approval_mismatch")
        if mutation:
            self._require_current()
            if state.pending is not None:
                raise WorkloadError("native_creation_outcome_unknown")
        anchor = self._cluster.get("Service", state.scope.anchor_name)
        require_live_anchor(anchor, state.anchor_uid)
        return state

    @staticmethod
    def _resource(state: NativeState, kind: str, name: str) -> str:
        if (kind, name) not in state.scope.resources:
            raise WorkloadError("native_resource_outside_scope")
        return f"{kind}/{name}"

    def _approved_existing(self) -> dict[tuple[str, str], NativeObjectIdentity]:
        return {item.key: item for item in self._approval.existing_resources}

    @staticmethod
    def _selector(state: NativeState, name: str) -> dict[str, str]:
        return {
            COMPONENT_LABEL: name,
            ENTITY_LABEL: state.scope.entity_id,
            ANCHOR_LABEL: state.creation_receipt_digest.removeprefix("sha256:")[:32],
        }

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
        if key not in state.deleting and live["metadata"].get("deletionTimestamp") is not None:
            raise WorkloadError("native_resource_terminating")
        selector = self._selector(state, name)
        spec = live.get("spec", {})
        if kind == "Deployment":
            template_labels = spec.get("template", {}).get("metadata", {}).get("labels", {})
            isolated = spec.get("selector") == {"matchLabels": selector} and all(
                template_labels.get(label) == value for label, value in selector.items()
            )
        elif kind == "CronJob":
            template_labels = (
                spec.get("jobTemplate", {})
                .get("spec", {})
                .get("template", {})
                .get("metadata", {})
                .get("labels", {})
            )
            isolated = all(template_labels.get(label) == value for label, value in selector.items())
        elif kind == "HorizontalPodAutoscaler":
            isolated = spec.get("scaleTargetRef") == {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "name": name,
            }
        else:
            isolated = spec.get("selector") == selector
        if not isolated:
            raise WorkloadError("native_resource_isolation_changed")
        return live

    def prepare_adoptions(
        self,
        plan: LifecyclePlan,
        desired: tuple[Manifest, ...],
        *,
        recorded: frozenset[tuple[str, str]] = frozenset(),
    ) -> tuple[tuple[AdoptionExpectation, ...], tuple[Manifest, ...]]:
        """Pin exact existing objects for the admitted Plan without changing them."""

        state = self._guard()
        proof = state.proof
        if proof is None:
            raise WorkloadError("native_scope_proof_invalid")
        expected_ownership = {state.scope.entity_id: proof.claim.digest}
        if self._approval.existing_resources and dict(plan.ownership_digests) != expected_ownership:
            raise WorkloadError("native_ownership_plan_mismatch")
        if not self._approval.existing_resources and dict(plan.ownership_digests) not in (
            {},
            expected_ownership,
        ):
            raise WorkloadError("native_ownership_plan_mismatch")
        approved = self._approved_existing()
        desired_by_key = {object_key(item): item for item in desired}
        if not set(approved) <= desired_by_key.keys():
            raise WorkloadError("native_adoption_scope_mismatch")
        if approved and not isinstance(self._cluster, AdoptionUidCluster):
            raise WorkloadError("native_adoption_provider_required")
        expectations: list[AdoptionExpectation] = []
        previous: list[Manifest] = []
        for key, _manifest in sorted(desired_by_key.items()):
            resource = self._resource(state, *key)
            live = self._cluster.get(*key)
            owned_uid = state.resources.get(resource)
            identity = approved.get(key)
            if owned_uid is not None:
                if live is None:
                    raise WorkloadError("native_owned_resource_missing")
                if live_uid(live) != owned_uid:
                    raise WorkloadError("native_resource_identity_changed")
                if identity is not None and identity.uid != owned_uid:
                    raise WorkloadError("native_adoption_uid_conflict")
                if identity is not None and key not in recorded:
                    previous.append(deepcopy(dict(live)))
                continue
            if identity is None:
                if live is not None:
                    raise WorkloadError("native_resource_collision")
                continue
            if live is None:
                raise WorkloadError("native_adoption_object_missing")
            metadata = live.get("metadata", {})
            if live_uid(live) != identity.uid:
                raise WorkloadError("native_adoption_uid_conflict")
            if metadata.get("deletionTimestamp") is not None:
                raise WorkloadError("native_resource_terminating")
            version = metadata.get("resourceVersion")
            if not isinstance(version, str) or not version:
                raise WorkloadError("native_resource_identity_unavailable")
            expectations.append(AdoptionExpectation(key[0], key[1], identity.uid, version))
            previous.append(deepcopy(dict(live)))
        return tuple(expectations), tuple(previous)

    def adopt_existing(
        self,
        desired: tuple[Manifest, ...],
        expectations: tuple[AdoptionExpectation, ...],
        *,
        plan_id: str,
    ) -> None:
        """Adopt the journaled exact objects and retain a per-object transition receipt."""

        if not expectations:
            return
        desired_by_key = {object_key(item): item for item in desired}
        manifests = tuple(desired_by_key[item.key] for item in expectations)
        receipt_id = sha256(plan_id.encode("ascii")).hexdigest()[:24]
        proof = self._load().proof
        if proof is None:
            raise WorkloadError("native_scope_proof_invalid")
        adopt_runtime_objects(
            _NativeAdoptionAdapter(self),
            manifests,
            expectations,
            installation_id=self._approval.scope.installation_id,
            release_id=plan_id,
            destination=self._store.path.parent / f"lifecycle-native-adoption-{receipt_id}.json",
            authorization_digest=self._approval.digest,
            ownership_digest=proof.claim.digest,
        )

    def adopt_terraform_owned(
        self,
        manifest: Manifest,
        *,
        uid: str,
        resource_version: str,
    ) -> Manifest:
        """Transfer one independently approved object and retain its UID before continuing."""

        state = self._guard(mutation=True)
        if not isinstance(self._cluster, AdoptionUidCluster):
            raise WorkloadError("native_adoption_provider_required")
        kind, name = object_key(manifest)
        key = self._resource(state, kind, name)
        identity = self._approved_existing().get((kind, name))
        if identity is None or identity.uid != uid or key in state.deleting:
            raise WorkloadError("native_adoption_not_approved")
        live = self._cluster.get(kind, name)
        metadata = (live or {}).get("metadata", {})
        if metadata.get("uid") != uid or metadata.get("resourceVersion") != resource_version:
            raise WorkloadError("adoption_resource_drifted")
        owned = self._owned_manifest(state, manifest)
        adopted = self._cluster.adopt_terraform_owned(
            owned,
            uid=uid,
            resource_version=resource_version,
            before_submit=self._require_current,
        )
        if live_uid(adopted) != uid:
            raise WorkloadError("adoption_receipt_invalid")
        self._store.save(state.model_copy(update={"resources": state.resources | {key: uid}}))
        return adopted

    def recover_adoptions(self, expectations: tuple[AdoptionExpectation, ...]) -> None:
        """Recover a confirmed SSA whose response or local UID write was interrupted."""

        state = self._load()
        resources = dict(state.resources)
        changed = False
        for expectation in expectations:
            key = f"{expectation.kind}/{expectation.name}"
            if resources.get(key) == expectation.uid:
                continue
            live = self._cluster.get(expectation.kind, expectation.name)
            if live is None or live_uid(live) != expectation.uid:
                continue
            if self._has_ownership_marker(state, live, expectation.name):
                resources[key] = expectation.uid
                changed = True
        if changed:
            self._store.save(state.model_copy(update={"resources": resources}))

    def transition_owned(self, kind: str, name: str, uid: str) -> bool:
        state = self._load()
        return state.resources.get(f"{kind}/{name}") == uid

    def transition_live(self, kind: str, name: str, uid: str) -> Manifest | None:
        state = self._load()
        live = self._cluster.get(kind, name)
        if live is None or live_uid(live) != uid:
            return None
        if state.resources.get(f"{kind}/{name}") is None and self._has_ownership_marker(
            state, live, name
        ):
            raise WorkloadError("native_adoption_outcome_unknown")
        return live

    def apply(self, manifest: Manifest, *, dry_run: bool = False) -> None:
        state = self._guard(mutation=True)
        kind, name = object_key(manifest)
        key = self._resource(state, kind, name)
        owned_uid = state.resources.get(key)
        check_scope(
            (manifest,),
            state.scope.namespace,
            unmanaged_adoptions=frozenset({(kind, name)}) if owned_uid is not None else frozenset(),
        )
        labels = manifest["metadata"]["labels"]
        if (
            labels.get(ENTITY_LABEL) != state.scope.entity_id
            or labels.get(COMPONENT_LABEL) != name
            or key in state.deleting
        ):
            raise WorkloadError("native_resource_outside_scope")
        owned_manifest = self._owned_manifest(state, manifest)
        identity = self._approved_existing().get((kind, name))
        if owned_uid is None and identity is not None:
            if not isinstance(self._cluster, AdoptionUidCluster):
                raise WorkloadError("native_adoption_provider_required")
            live = self._cluster.get(kind, name)
            metadata = (live or {}).get("metadata", {})
            if metadata.get("uid") != identity.uid:
                raise WorkloadError("native_adoption_uid_conflict")
            version = metadata.get("resourceVersion")
            if not isinstance(version, str) or not version:
                raise WorkloadError("native_resource_identity_unavailable")
            if not dry_run:
                raise WorkloadError("native_adoption_required")
            self._cluster.adopt_terraform_owned(
                owned_manifest,
                uid=identity.uid,
                resource_version=version,
                dry_run=True,
                before_submit=self._require_current,
            )
            return
        live = self.get(kind, name)
        if owned_uid is not None:
            if live is None:
                raise WorkloadError("native_owned_resource_missing")
            self._cluster.replace_owned(
                owned_manifest, owned_uid, dry_run=dry_run, before_submit=self._require_current
            )
        else:
            if not dry_run:
                self._store.save(state.model_copy(update={"pending": key}))
            try:
                created = self._cluster.create(
                    owned_manifest, dry_run=dry_run, before_submit=self._require_current
                )
            except (CreationRejectedError, MutationNotSubmittedError):
                if not dry_run:
                    self._store.save(state.model_copy(update={"pending": None}))
                raise
            if not dry_run:
                uid = live_uid(created)
                self._store.save(
                    state.model_copy(
                        update={"resources": state.resources | {key: uid}, "pending": None}
                    )
                )
        self._guard()

    def _owned_manifest(self, state: NativeState, manifest: Manifest) -> Manifest:
        kind, name = object_key(manifest)
        labels = manifest["metadata"]["labels"]
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
        selector = self._selector(state, name)
        owned_manifest["metadata"]["labels"] = (
            dict(labels) | {MANAGED_BY_LABEL: FIELD_MANAGER} | selector
        )
        if kind == "Deployment":
            owned_manifest["spec"]["selector"]["matchLabels"] = selector
            owned_manifest["spec"]["template"]["metadata"]["labels"].update(selector)
        elif kind == "CronJob":
            owned_manifest["spec"]["jobTemplate"]["spec"]["template"]["metadata"]["labels"].update(
                selector
            )
        elif kind == "Service":
            owned_manifest["spec"]["selector"] = selector
        return owned_manifest

    def _has_ownership_marker(self, state: NativeState, live: Manifest, name: str) -> bool:
        metadata = live.get("metadata", {})
        expected_owner = {
            "apiVersion": "v1",
            "kind": "Service",
            "name": state.scope.anchor_name,
            "uid": state.anchor_uid,
            "controller": True,
            "blockOwnerDeletion": False,
        }
        return (
            metadata.get("annotations", {}).get("fdai.io/adopted-from") == "Terraform"
            and expected_owner in metadata.get("ownerReferences", [])
            and all(
                metadata.get("labels", {}).get(label) == value
                for label, value in self._selector(state, name).items()
            )
        )

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
        try:
            self._cluster.delete_owned(kind, name, uid, before_submit=self._require_current)
        except MutationNotSubmittedError:
            self._store.save(state)
            raise
        self._guard()
        self.get(kind, name)


class _NativeAdoptionAdapter:
    """Expose raw reads while routing the exact adoption effect through NativeCluster."""

    def __init__(self, owner: NativeCluster) -> None:
        self._owner = owner

    def get(self, kind: str, name: str) -> Manifest | None:
        return self._owner._cluster.get(kind, name)

    def adopt_terraform_owned(
        self,
        manifest: Manifest,
        *,
        uid: str,
        resource_version: str,
    ) -> Manifest:
        return self._owner.adopt_terraform_owned(
            manifest,
            uid=uid,
            resource_version=resource_version,
        )
