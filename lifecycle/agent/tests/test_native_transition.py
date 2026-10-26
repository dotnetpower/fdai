from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_native import (
    NativeApproval,
    NativeObjectIdentity,
    NativeScope,
)
from fdai_deployment_cli.lifecycle_native_reconciliation import (
    LegacyNativeScopeTransitionReceipt,
    NativeScopeTransitionStateReconciliationApproval,
    NativeScopeTransitionStateReconciliationReceipt,
    canonical_transition_reported_state,
    regenerated_transition_receipt_digest,
    sign_transition_state_reconciliation_approval,
    transition_reported_state_digest,
)
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionApproval,
    NativeScopeTransitionCompletion,
    NativeScopeTransitionCompletionReceipt,
    existing_resources_digest,
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
from fdai_lifecycle_agent.journal import (
    WORKLOAD_FILE_NAME,
    ApplyJournal,
    WorkloadState,
    WorkloadStore,
)
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
from fdai_lifecycle_agent.native_transition_reconciliation import (
    RECONCILIATION_PENDING_FILE_NAME,
    RECONCILIATION_RECEIPT_FILE_NAME,
    RECONCILIATION_ROLLBACK_FILE_NAME,
    _reported_state,
    prepare_native_transition_state_reconciliation_request,
    reconcile_native_transition_state,
)
from fdai_lifecycle_agent.state import (
    AgentState,
    AgentStateError,
    LocalStateStore,
    PlanRecord,
    PlanResult,
    write_json_atomically,
)
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


def test_transition_command_reuses_exact_timestamp_across_restart_retry(
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

    arguments = [
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
        "--hub-url",
        "https://hub.example.test",
        "--hub-scope",
        "api://hub.example.test/.default",
        "--kube-context",
        "test-context",
    ]
    transitioned_at = case.now + timedelta(microseconds=619)
    clock_values = iter((transitioned_at, transitioned_at + timedelta(microseconds=619)))
    clock_calls = 0

    def advancing_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return next(clock_values)

    completions: list[NativeScopeTransitionCompletion] = []

    def capture_completion(
        _arguments: object,
        completion: NativeScopeTransitionCompletion,
    ) -> NativeScopeTransitionCompletionReceipt:
        completions.append(completion)
        return cast(
            NativeScopeTransitionCompletionReceipt,
            SimpleNamespace(receipt_digest="sha256:" + "e" * 64),
        )

    def run_transition() -> int:
        return main(
            arguments,
            clock=advancing_clock,
            connect_cluster=lambda _context, _namespace: case.provider,
            complete_transition=capture_completion,
        )

    result = run_transition()
    persisted_after_first_run = (
        (case.state_dir / RECEIPT_FILE_NAME).read_bytes(),
        (case.state_dir / ROLLBACK_FILE_NAME).read_bytes(),
        case.current_path.read_bytes(),
    )
    retry_result = run_transition()

    output = capsys.readouterr()
    assert result == 0
    assert retry_result == 0
    assert clock_calls == 2
    assert '"transitioned": true' in output.out
    assert '"hub_completion_receipt_digest": "sha256:' in output.out
    assert len(completions) == 2
    assert completions[0] == completions[1]
    assert completions[0].reported_state.entities.keys() == {"fdai-workloads"}
    expected_timestamp = transitioned_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    receipt = json.loads((case.state_dir / RECEIPT_FILE_NAME).read_text(encoding="utf-8"))
    rollback = json.loads((case.state_dir / ROLLBACK_FILE_NAME).read_text(encoding="utf-8"))
    state = json.loads(case.current_path.read_text(encoding="utf-8"))
    assert receipt["completed_at"] == expected_timestamp
    assert rollback["created_at"] == expected_timestamp
    assert state["observed_at"] == expected_timestamp
    assert completions[0].transition_receipt.completed_at == transitioned_at
    assert completions[0].reported_state.observed_at == transitioned_at
    assert receipt["record_digest"] == "sha256:" + canonical_digest(
        {key: value for key, value in receipt.items() if key != "record_digest"}
    )
    assert rollback["record_digest"] == "sha256:" + canonical_digest(
        {key: value for key, value in rollback.items() if key != "record_digest"}
    )
    assert state["digest"] == canonical_digest(
        {key: value for key, value in state.items() if key != "digest"}
    )
    serialized_completion = completions[0].model_dump_json()
    assert type(completions[0]).model_validate_json(serialized_completion) == completions[0]
    assert json.loads(serialized_completion)["reported_state"]["observed_at"] == expected_timestamp
    assert (
        (case.state_dir / RECEIPT_FILE_NAME).read_bytes(),
        (case.state_dir / ROLLBACK_FILE_NAME).read_bytes(),
        case.current_path.read_bytes(),
    ) == persisted_after_first_run
    assert case.signed_approval.hub_signature not in output.out + output.err
    assert case.signed_approval.approval.request.installation_proof not in (output.out + output.err)


def _prepare_reconciliation_case(harness, tmp_path: Path):
    case = _prepare_case(harness, tmp_path)
    transitioned_at = case.now.replace(microsecond=787619)
    _transition(case, now=transitioned_at)
    current_document = json.loads(case.current_path.read_text(encoding="utf-8"))
    current_document["observed_at"] = transitioned_at.isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    current_document["digest"] = canonical_digest(
        {key: value for key, value in current_document.items() if key != "digest"}
    )
    write_json_atomically(case.current_path, current_document)
    local_document = json.loads((case.state_dir / RECEIPT_FILE_NAME).read_text(encoding="utf-8"))
    local_document.pop("record_digest")
    local_document["new_reported_state_digest"] = current_document["digest"]
    local_document["record_digest"] = "sha256:" + canonical_digest(local_document)
    (case.state_dir / RECEIPT_FILE_NAME).write_text(
        json.dumps(local_document, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    local = LegacyNativeScopeTransitionReceipt.model_validate(local_document)
    legacy = _reported_state(case.current_path)
    full_precision_digest = transition_reported_state_digest(
        legacy,
        observed_at=local.completed_at,
    )
    hub_completed_at = transitioned_at + timedelta(hours=2)
    completion_document = {
        "schema_version": "fdai.lifecycle-native-transition-completion-receipt.v1",
        "completion_digest": "sha256:" + "1" * 64,
        "request_digest": local.request_digest,
        "hub_approval_digest": local.hub_approval_digest,
        "transition_receipt_digest": regenerated_transition_receipt_digest(
            local,
            new_reported_state_digest=full_precision_digest,
        ),
        "installation_id": local.installation_id,
        "old_entity_id": local.old_entity_id,
        "new_entity_id": local.new_entity_id,
        "old_scope_digest": local.old_scope_digest,
        "new_scope_digest": local.new_scope_digest,
        "old_reported_state_digest": local.old_reported_state_digest,
        "new_reported_state_digest": full_precision_digest,
        "object_scope_digest": "sha256:"
        + canonical_digest(
            [{"kind": kind, "name": name} for kind, name in sorted(case.approval.scope.resources)]
        ),
        "authoritative_uids_digest": existing_resources_digest(
            [item.model_dump(mode="json") for item in case.approval.existing_resources]
        ),
        "source_settings_digest": "0" * 64,
        "agent_principal": "agent-executor",
        "completed_at": hub_completed_at.isoformat().replace("+00:00", "Z"),
    }
    completion = NativeScopeTransitionCompletionReceipt.model_validate(
        {
            **completion_document,
            "receipt_digest": "sha256:" + canonical_digest(completion_document),
        }
    )
    request = prepare_native_transition_state_reconciliation_request(
        state_dir=case.state_dir,
        current_state_path=case.current_path,
        completion_receipt=completion,
        native_approval=case.approval,
        installation_public_key=case.recovered_public,
        now=case.now + timedelta(minutes=3),
    )
    source = request.legacy_reported_state.model_copy(
        update={
            "observed_at": local.completed_at,
            "digest": completion.new_reported_state_digest,
        }
    )
    authoritative = canonical_transition_reported_state(source)
    hub_key = Ed25519PrivateKey.generate()
    hub_public = hub_key.public_key().public_bytes_raw()
    approval = NativeScopeTransitionStateReconciliationApproval(
        schema_version="fdai.lifecycle-native-transition-state-reconciliation-approval.v1",
        request=request,
        source_hub_reported_state=source,
        authoritative_reported_state=authoritative,
        approved_by="owner",
        approved_at=request.requested_at,
        expires_at=request.expires_at,
        completion_audit_digest="sha256:" + "2" * 64,
        hub_key_id=hub_key_id(hub_public),
        hub_key_epoch=4,
    )
    return SimpleNamespace(
        **vars(case),
        completion=completion,
        request=request,
        source=source,
        authoritative=authoritative,
        reconciliation_approval=sign_transition_state_reconciliation_approval(
            approval,
            hub_key,
        ),
        reconciliation_hub_public=hub_public,
        reconciliation_hub_key=hub_key,
    )


def _reconciliation_receipt_for(command, *, completed_at: datetime):
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
        "agent_principal": "agent-executor",
        "authoritative_reported_state": command.reported_state.model_dump(mode="json"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
    }
    return NativeScopeTransitionStateReconciliationReceipt.model_validate_json(
        json.dumps(
            {
                **document,
                "receipt_digest": "sha256:" + canonical_digest(document),
            }
        )
    )


def _reconcile(case, complete, **overrides):
    values = {
        "cluster": case.provider,
        "state_dir": case.state_dir,
        "current_state_path": case.current_path,
        "native_approval": case.approval,
        "completion_receipt": case.completion,
        "signed_approval": case.reconciliation_approval,
        "hub_public_key": case.reconciliation_hub_public,
        "expected_hub_key_id": case.reconciliation_approval.approval.hub_key_id,
        "expected_hub_key_epoch": case.reconciliation_approval.approval.hub_key_epoch,
        "installation_public_key": case.recovered_public,
        "now": case.request.requested_at + timedelta(seconds=1),
        "complete": complete,
    }
    values.update(overrides)
    return reconcile_native_transition_state(**values)


def test_reconciliation_repairs_only_current_state_and_is_idempotent(harness, tmp_path) -> None:
    case = _prepare_reconciliation_case(harness, tmp_path)
    native_before = NativeStateStore(case.state_dir).path.read_bytes()
    workload_before = (case.state_dir / WORKLOAD_FILE_NAME).read_bytes()
    transition_receipt_before = (case.state_dir / RECEIPT_FILE_NAME).read_bytes()
    submissions = []

    def complete(command):
        submissions.append(command)
        return _reconciliation_receipt_for(
            command,
            completed_at=case.request.requested_at + timedelta(seconds=2),
        )

    receipt = _reconcile(case, complete)
    retry = _reconcile(
        case,
        complete,
        now=case.request.expires_at + timedelta(days=1),
    )

    assert retry == receipt
    assert len(submissions) == 1
    assert _reported_state(case.current_path) == case.authoritative
    assert NativeStateStore(case.state_dir).path.read_bytes() == native_before
    assert (case.state_dir / WORKLOAD_FILE_NAME).read_bytes() == workload_before
    assert (case.state_dir / RECEIPT_FILE_NAME).read_bytes() == transition_receipt_before
    assert (case.state_dir / RECONCILIATION_ROLLBACK_FILE_NAME).exists()
    assert (case.state_dir / RECONCILIATION_RECEIPT_FILE_NAME).exists()
    assert not (case.state_dir / RECONCILIATION_PENDING_FILE_NAME).exists()


@pytest.mark.parametrize(
    ("fault", "value"),
    [
        ("state-digest", "f" * 64),
        ("transition-digest", "sha256:" + "f" * 64),
        ("field", "different-entity"),
        ("timestamp", None),
    ],
)
def test_reconciliation_prepare_rejects_wrong_hub_digest_timestamp_or_field(
    fault,
    value,
    harness,
    tmp_path,
) -> None:
    case = _prepare_reconciliation_case(harness, tmp_path)
    completion_document = case.completion.model_dump(mode="json", exclude={"receipt_digest"})
    if fault == "state-digest":
        completion_document["new_reported_state_digest"] = value
    elif fault == "transition-digest":
        completion_document["transition_receipt_digest"] = value
    elif fault == "field":
        completion_document["new_entity_id"] = value
    else:
        completion_document["completed_at"] = (
            case.request.transition_receipt.completed_at - timedelta(microseconds=1)
        ).isoformat()
    completion = NativeScopeTransitionCompletionReceipt.model_validate(
        {
            **completion_document,
            "receipt_digest": "sha256:" + canonical_digest(completion_document),
        }
    )
    transition_receipt_before = (case.state_dir / RECEIPT_FILE_NAME).read_bytes()
    current_state_before = case.current_path.read_bytes()

    with pytest.raises(WorkloadError, match="evidence_mismatch"):
        prepare_native_transition_state_reconciliation_request(
            state_dir=case.state_dir,
            current_state_path=case.current_path,
            completion_receipt=completion,
            native_approval=case.approval,
            installation_public_key=case.recovered_public,
            now=case.request.requested_at,
        )

    assert (case.state_dir / RECEIPT_FILE_NAME).read_bytes() == transition_receipt_before
    assert case.current_path.read_bytes() == current_state_before


def test_reconciliation_cli_submits_and_reads_back_exact_state(
    harness,
    tmp_path,
    capsys,
) -> None:
    case = _prepare_reconciliation_case(harness, tmp_path)
    inputs = tmp_path / "reconciliation-inputs"
    inputs.mkdir(mode=0o700)
    native_approval_path = inputs / "native-approval.json"
    completion_receipt_path = inputs / "hub-completion.json"
    reconciliation_approval_path = inputs / "reconciliation-approval.json"
    request_path = inputs / "reconciliation-request.json"
    hub_public_path = inputs / "hub.pub.pem"
    installation_public_path = inputs / "installation.pub.pem"
    native_approval_path.write_text(case.approval.model_dump_json(), encoding="utf-8")
    completion_receipt_path.write_text(case.completion.model_dump_json(), encoding="utf-8")
    reconciliation_approval_path.write_text(
        case.reconciliation_approval.model_dump_json(),
        encoding="utf-8",
    )
    hub_public_path.write_bytes(
        Ed25519PublicKey.from_public_bytes(case.reconciliation_hub_public).public_bytes(
            Encoding.PEM,
            PublicFormat.SubjectPublicKeyInfo,
        )
    )
    installation_public_path.write_bytes(
        Ed25519PublicKey.from_public_bytes(case.recovered_public).public_bytes(
            Encoding.PEM,
            PublicFormat.SubjectPublicKeyInfo,
        )
    )
    transition_receipt_before = (case.state_dir / RECEIPT_FILE_NAME).read_bytes()
    prepared = main(
        [
            "prepare-native-transition-reconciliation",
            "--state-dir",
            str(case.state_dir),
            "--current-state",
            str(case.current_path),
            "--native-approval",
            str(native_approval_path),
            "--hub-completion-receipt",
            str(completion_receipt_path),
            "--installation-public-key",
            str(installation_public_path),
            "--destination",
            str(request_path),
        ],
        clock=lambda: case.request.requested_at,
    )
    prepared_output = json.loads(capsys.readouterr().out)
    prepared_request = type(case.request).model_validate_json(request_path.read_bytes())
    assert prepared == 0
    assert prepared_output["request_digest"] == prepared_request.digest
    assert (case.state_dir / RECEIPT_FILE_NAME).read_bytes() == transition_receipt_before

    def complete(_arguments, command):
        return _reconciliation_receipt_for(
            command,
            completed_at=case.request.requested_at + timedelta(seconds=2),
        )

    result = main(
        [
            "reconcile-native-transition-state",
            "--state-dir",
            str(case.state_dir),
            "--current-state",
            str(case.current_path),
            "--native-approval",
            str(native_approval_path),
            "--hub-completion-receipt",
            str(completion_receipt_path),
            "--hub-reconciliation-approval",
            str(reconciliation_approval_path),
            "--hub-public-key",
            str(hub_public_path),
            "--hub-key-id",
            case.reconciliation_approval.approval.hub_key_id,
            "--hub-key-epoch",
            str(case.reconciliation_approval.approval.hub_key_epoch),
            "--installation-public-key",
            str(installation_public_path),
            "--hub-url",
            "https://hub.example.test",
            "--hub-scope",
            "api://hub.example.test/.default",
            "--kube-context",
            "test-context",
        ],
        clock=lambda: case.request.requested_at + timedelta(seconds=1),
        connect_cluster=lambda _context, _namespace: case.provider,
        complete_reconciliation=complete,
    )

    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["reconciled"] is True
    assert output["reported_state_digest"] == case.authoritative.digest


def test_reconciliation_restart_retries_and_failure_restores_exact_bytes(harness, tmp_path) -> None:
    case = _prepare_reconciliation_case(harness, tmp_path)
    original = case.current_path.read_bytes()

    def interrupt(stage: str) -> None:
        if stage == "current-state":
            raise SystemExit("simulated restart")

    with pytest.raises(SystemExit, match="simulated restart"):
        _reconcile(
            case,
            lambda command: _reconciliation_receipt_for(
                command,
                completed_at=case.request.requested_at + timedelta(seconds=2),
            ),
            after_write=interrupt,
        )
    assert (case.state_dir / RECONCILIATION_PENDING_FILE_NAME).exists()

    def unavailable(_command):
        raise RuntimeError("Hub unavailable")

    with pytest.raises(WorkloadError, match="failed_restored"):
        _reconcile(case, unavailable)
    assert case.current_path.read_bytes() == original
    assert (case.state_dir / RECONCILIATION_ROLLBACK_FILE_NAME).exists()
    assert not (case.state_dir / RECONCILIATION_RECEIPT_FILE_NAME).exists()

    receipt = _reconcile(
        case,
        lambda command: _reconciliation_receipt_for(
            command,
            completed_at=case.request.requested_at + timedelta(seconds=3),
        ),
    )
    assert receipt.authoritative_reported_state == case.authoritative


def test_reconciliation_restart_after_receipt_keeps_committed_state(
    harness,
    tmp_path,
) -> None:
    case = _prepare_reconciliation_case(harness, tmp_path)
    submissions = 0

    def complete(command):
        nonlocal submissions
        submissions += 1
        return _reconciliation_receipt_for(
            command,
            completed_at=case.request.requested_at + timedelta(seconds=2),
        )

    def interrupt(stage: str) -> None:
        if stage == "receipt":
            raise SystemExit("simulated post-receipt restart")

    with pytest.raises(SystemExit, match="post-receipt restart"):
        _reconcile(case, complete, after_write=interrupt)
    assert _reported_state(case.current_path) == case.authoritative
    assert (case.state_dir / RECONCILIATION_PENDING_FILE_NAME).exists()
    assert (case.state_dir / RECONCILIATION_RECEIPT_FILE_NAME).exists()

    receipt = _reconcile(
        case,
        complete,
        now=case.request.expires_at + timedelta(days=1),
    )
    assert receipt.authoritative_reported_state == case.authoritative
    assert submissions == 1
    assert not (case.state_dir / RECONCILIATION_PENDING_FILE_NAME).exists()


def test_reconciliation_rejects_an_altered_immutable_transition_receipt(
    harness,
    tmp_path,
) -> None:
    case = _prepare_reconciliation_case(harness, tmp_path)
    original_state = case.current_path.read_bytes()
    receipt_path = case.state_dir / RECEIPT_FILE_NAME
    altered = json.loads(receipt_path.read_text(encoding="utf-8"))
    altered["new_entity_id"] = "different-entity"
    receipt_path.write_text(
        json.dumps(altered, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(AgentStateError, match="record digest is invalid"):
        _reconcile(
            case,
            lambda command: _reconciliation_receipt_for(
                command,
                completed_at=case.request.requested_at + timedelta(seconds=2),
            ),
        )

    assert case.current_path.read_bytes() == original_state
    assert not (case.state_dir / RECONCILIATION_ROLLBACK_FILE_NAME).exists()


@pytest.mark.parametrize(
    "fault",
    ["timestamp", "field", "uid", "proof", "plan", "journal"],
)
def test_reconciliation_rejects_non_time_differences_and_open_work(
    fault,
    harness,
    tmp_path,
) -> None:
    case = _prepare_reconciliation_case(harness, tmp_path)
    signed = case.reconciliation_approval
    approval = signed.approval
    overrides = {}
    reason = ""
    if fault == "timestamp":
        source = approval.source_hub_reported_state.model_copy(
            update={
                "observed_at": case.request.legacy_reported_state.observed_at
                + timedelta(milliseconds=1, microseconds=1)
            }
        )
        authoritative = source.model_copy(
            update={"digest": transition_reported_state_digest(source)}
        )
        changed = approval.model_copy(
            update={
                "source_hub_reported_state": source,
                "authoritative_reported_state": authoritative,
            }
        )
        overrides["signed_approval"] = sign_transition_state_reconciliation_approval(
            changed,
            case.reconciliation_hub_key,
        )
        reason = "authoritative_state_invalid"
    elif fault == "field":
        entity = next(iter(approval.source_hub_reported_state.entities.values()))
        source = approval.source_hub_reported_state.model_copy(
            update={
                "entities": {"fdai-workloads": entity.model_copy(update={"health": "degraded"})}
            }
        )
        authoritative = source.model_copy(
            update={"digest": transition_reported_state_digest(source)}
        )
        changed = approval.model_copy(
            update={
                "source_hub_reported_state": source,
                "authoritative_reported_state": authoritative,
            }
        )
        overrides["signed_approval"] = sign_transition_state_reconciliation_approval(
            changed,
            case.reconciliation_hub_key,
        )
        reason = "authoritative_state_invalid"
    elif fault == "uid":
        case.provider.objects[("Deployment", case.identities[0].name)]["metadata"]["uid"] = (
            "uid-replaced"
        )
        reason = "existing_uid_mismatch"
    elif fault == "proof":
        overrides["installation_public_key"] = (
            Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        )
        reason = "native_proof_invalid"
    elif fault == "plan":
        LocalStateStore(case.state_dir).save(
            AgentState(
                last_accepted_sequence=1,
                plans={
                    "open-plan": PlanRecord(
                        sequence=1,
                        payload_digest="a" * 64,
                        result=PlanResult(
                            outcome="dry-run-admitted",
                            reason_code="dry_run_computed",
                            exact_plan_digest="sha256:" + "b" * 64,
                        ),
                        reported=False,
                    )
                },
            )
        )
        reason = "plan_open"
    else:
        WorkloadStore(case.state_dir).save(
            WorkloadState(
                journal=ApplyJournal(
                    plan_id="open-plan",
                    phase="applying",
                    expires_at=case.request.expires_at,
                    target_release_id="1.2.3",
                    entity_images={"fdai-workloads": frozenset()},
                    desired=(),
                    previous=(),
                )
            )
        )
        reason = "journal_open"

    with pytest.raises(WorkloadError, match=reason):
        _reconcile(
            case,
            lambda command: _reconciliation_receipt_for(
                command,
                completed_at=case.request.requested_at + timedelta(seconds=2),
            ),
            **overrides,
        )
    assert not (case.state_dir / RECONCILIATION_RECEIPT_FILE_NAME).exists()
