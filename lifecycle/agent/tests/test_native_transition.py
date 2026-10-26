from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)
from fdai_deployment_cli.lifecycle_native import (
    NativeApproval,
    NativeObjectIdentity,
    NativeScope,
)
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionApproval,
    hub_key_id,
    sign_transition_approval,
)
from lifecycle.agent.tests.test_native_scope import UidProvider

from fdai_lifecycle_agent.cli import main
from fdai_lifecycle_agent.dry_run import (
    EntityState,
    Health,
    load_current_state,
    snapshot_document,
)
from fdai_lifecycle_agent.journal import ApplyJournal, WorkloadState, WorkloadStore
from fdai_lifecycle_agent.native_bootstrap import bootstrap_native_scope
from fdai_lifecycle_agent.native_cluster import NativeCluster
from fdai_lifecycle_agent.native_state import NativeStateStore
from fdai_lifecycle_agent.native_transition import (
    RECEIPT_FILE_NAME,
    RECOVERY_FILE_NAME,
    ROLLBACK_FILE_NAME,
    prepare_native_transition_request,
    transition_native_scope,
)
from fdai_lifecycle_agent.state import write_json_atomically
from fdai_lifecycle_agent.workload import Manifest, WorkloadError, object_key, render


def _deployment_manifests(namespace: str, components: tuple[str, ...]) -> tuple[Manifest, ...]:
    rendered = render(
        namespace,
        {
            ("fdai-workloads", component): (
                f"registry.example.test/{component}@sha256:{index + 1:064x}"
            )
            for index, component in enumerate(components)
        },
    )
    return tuple(item for item in rendered if item["kind"] == "Deployment")


def _foreign(manifest: Manifest, *, uid: str, version: str) -> Manifest:
    value = deepcopy(dict(manifest))
    value["metadata"] = dict(value["metadata"]) | {
        "uid": uid,
        "resourceVersion": version,
        "managedFields": [{"manager": "Terraform"}],
    }
    return value


def _prepare_case(harness, tmp_path: Path):
    now = harness.dependencies().clock()
    state_dir = tmp_path / "active"
    state_dir.mkdir(mode=0o700)
    current_path = state_dir / "current-state.json"
    provider = UidProvider()
    old_key = Ed25519PrivateKey.generate()
    recovered_key = Ed25519PrivateKey.generate()
    old_scope = NativeScope(
        installation_id=harness.settings().installation_id,
        entity_id="operator-hub-canary",
        product="example-web",
        namespace=harness.namespace,
        components=("operator",),
        service_components=(),
    )
    old_approval = NativeApproval(
        schema_version="fdai.lifecycle-native-approval.v1",
        scope=old_scope,
        profile="full-authority-development",
        approved_by="owner",
        approved_at=now - timedelta(minutes=2),
        expires_at=now + timedelta(hours=1),
    )
    write_json_atomically(
        current_path,
        snapshot_document(
            {old_scope.entity_id: EntityState(None, frozenset())},
            schema_revision=15,
            observed_at=now,
        ),
    )
    bootstrap_native_scope(
        provider,
        NativeStateStore(state_dir),
        old_approval,
        old_key,
        current_state_path=current_path,
        clock=lambda: now,
        apply=True,
    )
    old_image = "sha256:" + "a" * 64
    write_json_atomically(
        current_path,
        snapshot_document(
            {
                old_scope.entity_id: EntityState(
                    "1.1.1",
                    frozenset({old_image}),
                    Health.HEALTHY,
                )
            },
            schema_revision=15,
            observed_at=now,
            available_artifact_digests=frozenset({old_image}),
        ),
    )
    old_healthy = _deployment_manifests(harness.namespace, ("operator",))
    WorkloadStore(state_dir).save(WorkloadState(healthy=old_healthy))

    components = tuple(f"component-{index:02d}" for index in range(16))
    desired = _deployment_manifests(harness.namespace, components)
    identities = tuple(
        NativeObjectIdentity(
            kind="Deployment",
            name=component,
            uid=f"uid-existing-{index:02d}",
        )
        for index, component in enumerate(components[:7])
    )
    for index, manifest in enumerate(desired[:7]):
        provider.objects[object_key(manifest)] = _foreign(
            manifest,
            uid=identities[index].uid,
            version=str(index + 1),
        )
    new_scope = NativeScope(
        installation_id=old_scope.installation_id,
        entity_id="fdai-workloads",
        product=old_scope.product,
        namespace=old_scope.namespace,
        components=components,
        service_components=(),
    )
    approval = NativeApproval(
        schema_version="fdai.lifecycle-native-approval.v1",
        scope=new_scope,
        profile="full-authority-development",
        approved_by="owner",
        approved_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        existing_resources=identities,
    )
    staged_dir = tmp_path / "staged"
    staged_dir.mkdir(mode=0o700)
    staged_current = staged_dir / "current-state.json"
    write_json_atomically(
        staged_current,
        snapshot_document(
            {new_scope.entity_id: EntityState(None, frozenset())},
            schema_revision=15,
            observed_at=now,
        ),
    )
    proof = bootstrap_native_scope(
        provider,
        NativeStateStore(staged_dir),
        approval,
        recovered_key,
        current_state_path=staged_current,
        clock=lambda: now,
        apply=True,
    )
    assert proof is not None
    signed_request = prepare_native_transition_request(
        state_dir=state_dir,
        current_state_path=current_path,
        new_native_state_path=NativeStateStore(staged_dir).path,
        approval=approval,
        recovery_request_digest="sha256:" + "b" * 64,
        installation_key=recovered_key,
        now=now,
    )
    hub_key = Ed25519PrivateKey.generate()
    hub_public = hub_key.public_key().public_bytes_raw()
    approval_record = NativeScopeTransitionApproval(
        schema_version="fdai.lifecycle-native-transition-approval.v1",
        request=signed_request,
        profile="full-authority-development",
        approved_by="owner",
        approved_at=now,
        expires_at=signed_request.request.expires_at,
        recovery_audit_digest="sha256:" + "c" * 64,
        ownership_audit_digest="sha256:" + "d" * 64,
        hub_key_id=hub_key_id(hub_public),
        hub_key_epoch=3,
    )
    signed_approval = sign_transition_approval(approval_record, hub_key)
    return SimpleNamespace(
        now=now,
        state_dir=state_dir,
        current_path=current_path,
        staged_path=NativeStateStore(staged_dir).path,
        provider=provider,
        approval=approval,
        proof=proof,
        signed_approval=signed_approval,
        hub_public=hub_public,
        hub_key_id=approval_record.hub_key_id,
        hub_key_epoch=approval_record.hub_key_epoch,
        recovered_public=recovered_key.public_key().public_bytes_raw(),
        desired=desired,
        identities=identities,
        old_scope=old_scope,
        old_healthy=old_healthy,
    )


def _transition(case, **overrides):
    values = {
        "cluster": case.provider,
        "state_dir": case.state_dir,
        "current_state_path": case.current_path,
        "new_native_state_path": case.staged_path,
        "approval": case.approval,
        "signed_approval": case.signed_approval,
        "hub_public_key": case.hub_public,
        "expected_hub_key_id": case.hub_key_id,
        "expected_hub_key_epoch": case.hub_key_epoch,
        "installation_public_key": case.recovered_public,
        "now": case.now,
    }
    return transition_native_scope(**(values | overrides))


def test_live_legacy_shape_transitions_then_adopts_seven_and_creates_nine(
    harness, tmp_path
) -> None:
    case = _prepare_case(harness, tmp_path)

    receipt = _transition(case)

    active = NativeStateStore(case.state_dir).load()
    current = load_current_state(case.current_path)
    assert active is not None and active.scope.entity_id == "fdai-workloads"
    assert active.resources == {}
    assert set(current.entities) == {"fdai-workloads"}
    assert current.entities["fdai-workloads"].release_id is None
    assert WorkloadStore(case.state_dir).load() == WorkloadState()
    assert (case.state_dir / ROLLBACK_FILE_NAME).exists()
    assert (case.state_dir / RECEIPT_FILE_NAME).exists()

    cluster = NativeCluster(
        case.provider,
        NativeStateStore(case.state_dir),
        case.approval,
        case.recovered_public,
        lambda: case.now,
    )
    plan = SimpleNamespace(
        plan_id="mixed-scope-adoption",
        ownership_digests={"fdai-workloads": case.proof.claim.digest},
    )
    expectations, _previous = cluster.prepare_adoptions(plan, case.desired)
    cluster.adopt_existing(case.desired, expectations, plan_id=plan.plan_id)
    for manifest in case.desired:
        cluster.apply(manifest)

    assert len(case.provider.adopted) == 7
    assert len(NativeStateStore(case.state_dir).load().resources) == 16
    before = (
        NativeStateStore(case.state_dir).path.read_bytes(),
        case.current_path.read_bytes(),
        WorkloadStore(case.state_dir).load(),
    )
    with pytest.raises(WorkloadError, match="recovered_proof_invalid"):
        _transition(
            case,
            installation_public_key=(Ed25519PrivateKey.generate().public_key().public_bytes_raw()),
        )
    assert _transition(case) == receipt
    assert (
        NativeStateStore(case.state_dir).path.read_bytes(),
        case.current_path.read_bytes(),
        WorkloadStore(case.state_dir).load(),
    ) == before


def test_interrupted_transition_restores_exact_old_state_then_retries(harness, tmp_path) -> None:
    case = _prepare_case(harness, tmp_path)
    old_native = NativeStateStore(case.state_dir).path.read_bytes()
    old_current = case.current_path.read_bytes()
    old_workload = (case.state_dir / "lifecycle-agent-workload.json").read_bytes()

    def interrupt(stage: str) -> None:
        if stage == "current-state":
            raise SystemExit("simulated interruption")

    with pytest.raises(SystemExit, match="simulated interruption"):
        _transition(case, after_write=interrupt)
    with pytest.raises(WorkloadError, match="interrupted_restored"):
        _transition(case)

    assert NativeStateStore(case.state_dir).path.read_bytes() == old_native
    assert case.current_path.read_bytes() == old_current
    assert (case.state_dir / "lifecycle-agent-workload.json").read_bytes() == old_workload
    assert (case.state_dir / RECOVERY_FILE_NAME).exists()
    assert _transition(case)["new_entity_id"] == "fdai-workloads"


@pytest.mark.parametrize("fault", ["wrong-uid", "wrong-proof", "expired"])
def test_wrong_uid_proof_or_expiry_never_changes_old_state(fault, harness, tmp_path) -> None:
    case = _prepare_case(harness, tmp_path)
    old_native = NativeStateStore(case.state_dir).path.read_bytes()
    old_current = case.current_path.read_bytes()
    if fault == "wrong-uid":
        case.provider.objects[("Deployment", case.identities[0].name)]["metadata"]["uid"] = (
            "uid-replaced"
        )
        overrides = {}
        reason = "existing_uid_mismatch"
    elif fault == "wrong-proof":
        overrides = {
            "installation_public_key": (
                Ed25519PrivateKey.generate().public_key().public_bytes_raw()
            )
        }
        reason = "recovered_proof_invalid"
    else:
        overrides = {"now": case.signed_approval.approval.expires_at}
        reason = "approval_expired"

    with pytest.raises(WorkloadError, match=reason):
        _transition(case, **overrides)

    assert NativeStateStore(case.state_dir).path.read_bytes() == old_native
    assert case.current_path.read_bytes() == old_current
    assert not (case.state_dir / RECEIPT_FILE_NAME).exists()


def test_applying_journal_blocks_transition_before_any_state_change(harness, tmp_path) -> None:
    case = _prepare_case(harness, tmp_path)
    old_native = NativeStateStore(case.state_dir).path.read_bytes()
    old_current = case.current_path.read_bytes()
    WorkloadStore(case.state_dir).save(
        WorkloadState(
            healthy=case.old_healthy,
            journal=ApplyJournal(
                plan_id="legacy-open-plan",
                phase="applying",
                expires_at=case.now + timedelta(minutes=10),
                target_release_id="1.1.1",
                entity_images={"operator-hub-canary": frozenset({"sha256:" + "a" * 64})},
                desired=case.old_healthy,
                previous=case.old_healthy,
            ),
        )
    )

    with pytest.raises(WorkloadError, match="journal_open"):
        _transition(case)

    assert NativeStateStore(case.state_dir).path.read_bytes() == old_native
    assert case.current_path.read_bytes() == old_current
    assert not (case.state_dir / ROLLBACK_FILE_NAME).exists()


def test_transition_command_wires_verified_inputs_without_printing_proofs(
    harness, tmp_path, capsys
) -> None:
    case = _prepare_case(harness, tmp_path)
    inputs = tmp_path / "private-inputs"
    inputs.mkdir(mode=0o700)
    approval_path = inputs / "approval.json"
    hub_approval_path = inputs / "hub-approval.json"
    hub_public_path = inputs / "hub.pub.pem"
    installation_public_path = inputs / "installation.pub.pem"
    approval_path.write_text(case.approval.model_dump_json(), encoding="utf-8")
    hub_approval_path.write_text(
        case.signed_approval.model_dump_json(),
        encoding="utf-8",
    )
    hub_key = case.signed_approval.approval
    # Public inputs are independently provisioned PEM files; no private key reaches this command.
    hub_public_path.write_bytes(
        Ed25519PublicKey.from_public_bytes(case.hub_public).public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        )
    )
    installation_public_path.write_bytes(
        Ed25519PublicKey.from_public_bytes(case.recovered_public).public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        )
    )

    result = main(
        [
            "transition-native-scope",
            "--state-dir",
            str(case.state_dir),
            "--current-state",
            str(case.current_path),
            "--new-native-state",
            str(case.staged_path),
            "--native-approval",
            str(approval_path),
            "--hub-approval",
            str(hub_approval_path),
            "--hub-public-key",
            str(hub_public_path),
            "--hub-key-id",
            hub_key.hub_key_id,
            "--hub-key-epoch",
            str(hub_key.hub_key_epoch),
            "--installation-public-key",
            str(installation_public_path),
            "--kube-context",
            "test-context",
        ],
        clock=lambda: case.now,
        connect_cluster=lambda _context, _namespace: case.provider,
    )

    output = capsys.readouterr()
    assert result == 0
    assert '"transitioned": true' in output.out
    assert case.signed_approval.hub_signature not in output.out + output.err
    assert case.signed_approval.approval.request.installation_proof not in (output.out + output.err)
