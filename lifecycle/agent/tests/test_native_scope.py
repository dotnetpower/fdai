from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from fdai_deployment_cli.lifecycle_native import NativeApproval, NativeScope

from fdai_lifecycle_agent.native_bootstrap import bootstrap_native_scope
from fdai_lifecycle_agent.native_cluster import ANCHOR_LABEL, NativeCluster
from fdai_lifecycle_agent.native_state import NativeStateStore
from fdai_lifecycle_agent.workload import (
    CreationRejectedError,
    Manifest,
    WorkloadError,
    object_key,
    render,
)

NOW = datetime(2026, 10, 5, tzinfo=UTC)


class UidProvider:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], Manifest] = {}
        self.calls: list[tuple[str, bool]] = []
        self.counter = 0
        self.lose_create_response = False
        self.broken_images: set[str] = set()

    def get(self, kind: str, name: str) -> Manifest | None:
        live = deepcopy(self.objects.get((kind, name)))
        if live is not None and kind == "Deployment":
            image = live["spec"]["template"]["spec"]["containers"][0]["image"]
            replicas = live["spec"].get("replicas", 1)
            live["status"] = {
                "observedGeneration": live["metadata"].get("generation", 0),
                "replicas": replicas if image not in self.broken_images else replicas + 1,
                "updatedReplicas": replicas,
                "readyReplicas": replicas,
                "availableReplicas": replicas,
            }
        return live

    def create(self, manifest: Manifest, *, dry_run: bool = False) -> Manifest:
        self.calls.append(("create", dry_run))
        key = object_key(manifest)
        if key in self.objects:
            raise WorkloadError("kubernetes_request_rejected")
        result = deepcopy(dict(manifest))
        result["metadata"] = dict(result["metadata"]) | {
            "uid": f"uid-{self.counter + 1}",
            "resourceVersion": str(self.counter + 1),
        }
        if not dry_run:
            self.counter += 1
            self.objects[key] = result
            if self.lose_create_response:
                raise WorkloadError("kubernetes_request_failed")
        return deepcopy(result)

    def replace_owned(self, manifest: Manifest, uid: str, *, dry_run: bool = False) -> None:
        self.calls.append(("replace", dry_run))
        key = object_key(manifest)
        current = self.objects.get(key)
        if current is None or current["metadata"]["uid"] != uid:
            raise WorkloadError("native_resource_identity_changed")
        if not dry_run:
            self.counter += 1
            updated = deepcopy(dict(manifest))
            updated["metadata"] = dict(updated["metadata"]) | {
                "uid": uid,
                "resourceVersion": str(self.counter),
            }
            self.objects[key] = updated

    def delete_owned(self, kind: str, name: str, uid: str) -> None:
        self.calls.append(("delete", False))
        current = self.objects.get((kind, name))
        if current is not None and current["metadata"]["uid"] != uid:
            raise WorkloadError("native_resource_identity_changed")
        self.objects.pop((kind, name), None)

    def apply(self, manifest: Manifest, *, dry_run: bool = False) -> None:
        raise AssertionError("native mode must not use legacy apply")

    def delete(self, kind: str, name: str) -> None:
        raise AssertionError("native mode must not use name-only deletion")


@pytest.fixture
def native(tmp_path: Path):
    approval = NativeApproval(
        schema_version="fdai.lifecycle-native-approval.v1",
        scope=NativeScope(
            installation_id="installation-alpha",
            entity_id="application",
            product="example-app",
            namespace="example-test",
            components=("frontend",),
        ),
        profile="full-authority-development",
        approved_by="operator",
        approved_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    provider = UidProvider()
    store = NativeStateStore(tmp_path)
    key = Ed25519PrivateKey.generate()
    return provider, store, approval, key


def bootstrap(native, *, apply=True):
    provider, store, approval, key = native
    return bootstrap_native_scope(provider, store, approval, key, clock=lambda: NOW, apply=apply)


def wrapper(native, *, clock=lambda: NOW):
    provider, store, approval, key = native
    return NativeCluster(provider, store, approval, key.public_key().public_bytes_raw(), clock)


def manifests():
    return render(
        "example-test",
        {("application", "frontend"): "example.test/frontend@sha256:" + "a" * 64},
    )


def test_default_bootstrap_only_dry_runs_and_does_not_persist(native):
    provider, store, *_ = native
    assert bootstrap(native, apply=False) is None
    assert provider.calls == [("create", True)]
    assert provider.objects == {}
    assert not store.path.exists()


@pytest.mark.parametrize("operation", ["get", "apply", "delete", "bootstrap"])
def test_terminating_anchor_stops_reads_writes_and_proof_resume(native, operation):
    provider, _, approval, _ = native
    bootstrap(native)
    cluster = wrapper(native)
    cluster.apply(manifests()[0])
    provider.objects[("Service", approval.scope.anchor_name)]["metadata"]["deletionTimestamp"] = (
        NOW.isoformat()
    )
    before = list(provider.calls)
    with pytest.raises(WorkloadError, match="native_scope_anchor_changed"):
        if operation == "get":
            cluster.get("Deployment", "frontend")
        elif operation == "apply":
            cluster.apply(manifests()[0])
        elif operation == "delete":
            cluster.delete("Deployment", "frontend")
        else:
            bootstrap(native)
    assert provider.calls == before


def test_confirmed_anchor_create_rejection_can_retry_without_claiming_creation(native, monkeypatch):
    provider, store, _, _ = native
    create = provider.create

    def reject(manifest, *, dry_run=False):
        if not dry_run:
            raise CreationRejectedError("kubernetes_request_rejected")
        return create(manifest, dry_run=dry_run)

    monkeypatch.setattr(provider, "create", reject)
    with pytest.raises(CreationRejectedError):
        bootstrap(native)
    assert store.load().pending is None
    assert store.load().anchor_uid is None
    assert not provider.objects
    monkeypatch.setattr(provider, "create", create)
    assert bootstrap(native) is not None


def test_native_selectors_exclude_foreign_labels_and_retain_anchor_identity(native):
    provider, store, approval, _ = native
    bootstrap(native)
    cluster = wrapper(native)
    rendered = manifests()
    original = deepcopy(rendered)
    for manifest in rendered:
        cluster.apply(manifest)
    deployment = provider.objects[("Deployment", "frontend")]
    service = provider.objects[("Service", "frontend")]
    selector = deployment["spec"]["selector"]["matchLabels"]
    assert selector == service["spec"]["selector"]
    assert (
        selector[ANCHOR_LABEL] == store.load().creation_receipt_digest.removeprefix("sha256:")[:32]
    )
    assert selector.items() <= deployment["spec"]["template"]["metadata"]["labels"].items()
    for foreign in (
        original[0]["spec"]["template"]["metadata"]["labels"],
        dict(selector) | {ANCHOR_LABEL: "another-anchor"},
        dict(selector) | {"fdai.io/entity": "another-entity"},
    ):
        assert not selector.items() <= foreign.items()
    cluster.apply(rendered[0])
    assert (
        provider.objects[("Deployment", "frontend")]["spec"]["selector"]["matchLabels"] == selector
    )
    assert rendered == original
    assert (
        store.load().anchor_uid
        == provider.objects[("Service", approval.scope.anchor_name)]["metadata"]["uid"]
    )


def test_proof_binds_actual_anchor_and_does_not_disclose_private_scope(native):
    provider, store, approval, key = native
    proof = bootstrap(native)
    assert proof is not None and proof.verify(key.public_key().public_bytes_raw())
    state = store.load()
    assert state is not None
    anchor = provider.objects[("Service", approval.scope.anchor_name)]
    assert state.anchor_uid == anchor["metadata"]["uid"]
    assert state.anchor_resource_version == anchor["metadata"]["resourceVersion"]
    assert "selector" not in anchor["spec"]
    assert proof.claim.creation_receipt_digest == state.creation_receipt_digest
    assert approval.scope.namespace not in proof.model_dump_json()
    assert state.anchor_uid not in proof.model_dump_json()
    writes = list(provider.calls)
    assert bootstrap(native) == proof
    assert provider.calls == writes
    assert store.path.stat().st_mode & 0o777 == 0o600


def test_collision_is_never_adopted_even_with_matching_labels(native):
    provider, store, *_ = native
    provider.create(manifests()[0])
    before = deepcopy(provider.objects)
    with pytest.raises(WorkloadError, match="native_resource_collision"):
        bootstrap(native)
    assert provider.objects == before
    assert not store.path.exists()


def test_unknown_anchor_creation_is_not_retried(native):
    provider, store, *_ = native
    provider.lose_create_response = True
    with pytest.raises(WorkloadError, match="kubernetes_request_failed"):
        bootstrap(native)
    calls = list(provider.calls)
    with pytest.raises(WorkloadError, match="native_creation_outcome_unknown"):
        bootstrap(native)
    assert provider.calls == calls
    assert store.load().proof is None


def test_known_anchor_uid_can_finish_proof_without_recreating(native):
    provider, store, *_ = native
    bootstrap(native)
    state = store.load()
    store.save(state.model_copy(update={"proof": None}))
    calls = list(provider.calls)
    assert bootstrap(native) is not None
    assert provider.calls == calls


def test_create_update_delete_use_retained_uid_and_preserve_anchor(native):
    provider, store, approval, *_ = native
    bootstrap(native)
    cluster = wrapper(native)
    for manifest in manifests():
        cluster.apply(manifest, dry_run=True)
    assert store.load().resources == {}
    for manifest in manifests():
        cluster.apply(manifest)
    retained = dict(store.load().resources)
    for manifest in manifests():
        cluster.apply(manifest)
        live = cluster.get(*object_key(manifest))
        assert live["metadata"]["uid"] == retained["/".join(object_key(manifest))]
        assert live["metadata"]["ownerReferences"][0]["uid"] == store.load().anchor_uid
    for manifest in manifests():
        cluster.delete(*object_key(manifest))
    assert store.load().resources == {}
    assert store.load().deleting == frozenset()
    assert set(provider.objects) == {("Service", approval.scope.anchor_name)}


@pytest.mark.parametrize("change", ["anchor", "workload", "missing"])
def test_replaced_or_lost_resource_is_not_changed(native, change):
    provider, store, approval, *_ = native
    bootstrap(native)
    cluster = wrapper(native)
    deployment = manifests()[0]
    cluster.apply(deployment)
    key = object_key(deployment)
    if change == "anchor":
        provider.objects[("Service", approval.scope.anchor_name)]["metadata"]["uid"] = "foreign"
    elif change == "workload":
        provider.objects[key]["metadata"]["uid"] = "foreign"
    else:
        del provider.objects[key]
    before = deepcopy(provider.objects)
    with pytest.raises(WorkloadError, match="native_"):
        cluster.apply(deployment)
    assert provider.objects == before


def test_unknown_workload_creation_blocks_all_later_mutations(native):
    provider, store, *_ = native
    bootstrap(native)
    cluster = wrapper(native)
    provider.lose_create_response = True
    with pytest.raises(WorkloadError, match="kubernetes_request_failed"):
        cluster.apply(manifests()[0])
    calls = list(provider.calls)
    restarted = wrapper(native)
    for manifest in manifests():
        with pytest.raises(WorkloadError, match="native_creation_outcome_unknown"):
            restarted.apply(manifest)
    assert provider.calls == calls
    assert store.load().pending == "Deployment/frontend"


def test_expired_approval_blocks_mutations_without_writes(native):
    provider, _, approval, *_ = native
    bootstrap(native)
    cluster = wrapper(native, clock=lambda: approval.expires_at)
    calls = list(provider.calls)
    with pytest.raises(WorkloadError, match="native_scope_approval_expired"):
        cluster.apply(manifests()[0])
    assert provider.calls == calls


def test_corrupt_or_missing_private_state_never_falls_back(native):
    _, store, *_ = native
    bootstrap(native)
    cluster = wrapper(native)
    store.path.write_text('{"scope":', encoding="utf-8")
    with pytest.raises(WorkloadError, match="native_scope_state_invalid"):
        cluster.apply(manifests()[0])
    store.path.unlink()
    with pytest.raises(WorkloadError, match="native_scope_state_missing"):
        cluster.apply(manifests()[0])


def test_wrong_installation_key_and_tampered_scope_are_rejected(native):
    provider, store, approval, *_ = native
    bootstrap(native)
    foreign = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    with pytest.raises(WorkloadError, match="native_scope_proof_invalid"):
        NativeCluster(provider, store, approval, foreign, lambda: NOW)
    document = store.path.read_text()
    store.path.write_text(document.replace('"example-test"', '"another-test"'))
    with pytest.raises(WorkloadError, match="native_scope_state_invalid"):
        wrapper(native)


@pytest.mark.parametrize("pin", [False, True])
def test_native_composition_never_silently_uses_legacy_mode(native, pin, tmp_path):
    from fdai_lifecycle_agent.native_cli import compose_native_cluster

    provider, _, approval, _ = native
    bootstrap(native)
    with pytest.raises(WorkloadError, match="native_scope_"):
        compose_native_cluster(
            provider,
            state_dir=tmp_path,
            approval_path=None,
            public_key_path=None,
            native_scope_digest=approval.scope.digest if pin else None,
            installation_id=approval.scope.installation_id,
            namespace=approval.scope.namespace,
            product=approval.scope.product,
            entity_components={"application": frozenset({"frontend"})},
            entity_ids=frozenset({"application"}),
            clock=lambda: NOW,
        )


def test_bootstrap_cli_defaults_to_dry_run_then_writes_private_proof(native, tmp_path, capsys):
    from fdai_lifecycle_agent.cli import main
    from fdai_lifecycle_agent.dry_run import EntityState, snapshot_document

    provider, store, approval, key = native
    policy = {
        "schema": "fdai.lifecycle-local-policy.v1",
        "entity_ids": ["application"],
        "regions": ["test-region"],
        "capability_modes": {},
        "destructive_allowed": False,
        "max_duration_minutes": 30,
        "entity_components": {"application": ["frontend"]},
        "product": approval.scope.product,
        "native_scope_digest": approval.scope.digest,
    }
    (tmp_path / "policy.json").write_text(json.dumps(policy))
    (tmp_path / "approval.json").write_text(approval.model_dump_json())
    (tmp_path / "identity.pem").write_bytes(
        key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    )
    (tmp_path / "identity.pem").chmod(0o600)
    (tmp_path / "current.json").write_text(
        json.dumps(
            snapshot_document(
                {"application": EntityState(None, frozenset())},
                schema_revision=0,
                observed_at=NOW,
            )
        )
    )
    arguments = [
        "bootstrap-slot",
        "--installation-id",
        "installation-alpha",
        "--state-dir",
        str(tmp_path),
        "--local-policy",
        str(tmp_path / "policy.json"),
        "--current-state",
        str(tmp_path / "current.json"),
        "--native-approval",
        str(tmp_path / "approval.json"),
        "--installation-key",
        str(tmp_path / "identity.pem"),
        "--kube-context",
        "kind-test",
        "--proof-output",
        str(tmp_path / "proof.json"),
    ]

    def connect(_context, _namespace):
        return provider

    assert main(arguments, clock=lambda: NOW, connect_cluster=connect) == 0
    assert not store.path.exists()
    assert not (tmp_path / "proof.json").exists()
    unsafe = list(arguments)
    unsafe[-1] = str(tmp_path / "identity.pem")
    identity = (tmp_path / "identity.pem").read_bytes()
    assert main([*unsafe, "--apply"], clock=lambda: NOW, connect_cluster=connect) == 2
    assert (tmp_path / "identity.pem").read_bytes() == identity
    assert not store.path.exists()
    assert main([*arguments, "--apply"], clock=lambda: NOW, connect_cluster=connect) == 0
    assert store.load().proof is not None
    assert (tmp_path / "proof.json").stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr()
    assert output.out == ""
    assert store.load().proof.signature not in output.err


def test_bootstrap_deadline_is_enforced_before_cluster_access(native):
    provider, store, approval, key = native
    ticks = iter((0.0, 121.0))
    with pytest.raises(WorkloadError, match="native_bootstrap_deadline"):
        bootstrap_native_scope(
            provider, store, approval, key, clock=lambda: NOW, monotonic=lambda: next(ticks)
        )
    assert provider.calls == []
