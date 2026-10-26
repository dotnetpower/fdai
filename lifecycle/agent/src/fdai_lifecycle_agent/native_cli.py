"""Independent local policy, identity and explicit native bootstrap composition."""

from __future__ import annotations

import argparse
import json
import logging
import os
import stat
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fdai_deployment_cli.lifecycle_native import NativeScope
from fdai_deployment_cli.lifecycle_native_reconciliation import (
    NativeScopeTransitionStateReconciliationCompletion,
    NativeScopeTransitionStateReconciliationReceipt,
    SignedNativeScopeTransitionStateReconciliationApproval,
)
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionCompletion,
    NativeScopeTransitionCompletionReceipt,
    NativeScopeTransitionReceipt,
    NativeScopeTransitionReportedState,
    SignedNativeScopeTransitionApproval,
)
from fdai_deployment_cli.private_output import write_private_output

from fdai_lifecycle_agent.hub_client import HttpHubClient
from fdai_lifecycle_agent.journal import HALT_FILE_NAME, WORKLOAD_FILE_NAME
from fdai_lifecycle_agent.native_bootstrap import bootstrap_native_scope
from fdai_lifecycle_agent.native_cluster import NativeCluster, UidCluster
from fdai_lifecycle_agent.native_state import NativeStateStore, load_native_approval
from fdai_lifecycle_agent.native_transition import (
    prepare_native_transition_request,
    transition_native_scope,
)
from fdai_lifecycle_agent.native_transition_reconciliation import (
    prepare_native_transition_state_reconciliation_request,
    reconcile_native_transition_state,
)
from fdai_lifecycle_agent.remote_auth import WorkloadIdentityAuthorization
from fdai_lifecycle_agent.runtime_bundle import RuntimeBundle
from fdai_lifecycle_agent.signatures import load_ed25519_public_key
from fdai_lifecycle_agent.state import (
    LOCK_FILE_NAME,
    STATE_FILE_NAME,
    write_json_atomically,
)
from fdai_lifecycle_agent.strict_json import load_json, read_limited
from fdai_lifecycle_agent.workload import Cluster, WorkloadError

type TransitionCompleter = Callable[
    [argparse.Namespace, NativeScopeTransitionCompletion],
    NativeScopeTransitionCompletionReceipt,
]
type ReconciliationCompleter = Callable[
    [argparse.Namespace, NativeScopeTransitionStateReconciliationCompletion],
    NativeScopeTransitionStateReconciliationReceipt,
]


def register_native_command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    command = commands.add_parser(
        "bootstrap-slot",
        help="Dry-run a private workload anchor and exact existing-object inventory.",
    )
    command.add_argument("--installation-id", required=True)
    command.add_argument("--state-dir", required=True, type=Path)
    command.add_argument("--local-policy", required=True, type=Path)
    command.add_argument("--current-state", required=True, type=Path)
    command.add_argument(
        "--native-approval",
        required=True,
        type=Path,
        help="Bounded local creation and exact existing-object adoption approval.",
    )
    command.add_argument("--installation-key", required=True, type=Path)
    command.add_argument("--proof-output", type=Path)
    authentication = command.add_mutually_exclusive_group(required=True)
    authentication.add_argument("--kube-context")
    authentication.add_argument("--in-cluster", action="store_true")
    command.add_argument("--timeout-seconds", type=float, default=120)
    command.add_argument("--apply", action="store_true")
    prepare = commands.add_parser(
        "prepare-native-transition",
        help="Create a recovered-installation proof for one exact legacy-to-native transition.",
    )
    prepare.add_argument("--state-dir", required=True, type=Path)
    prepare.add_argument("--current-state", required=True, type=Path)
    prepare.add_argument("--new-native-state", required=True, type=Path)
    prepare.add_argument("--native-approval", required=True, type=Path)
    prepare.add_argument("--installation-key", required=True, type=Path)
    prepare.add_argument("--recovery-request-digest", required=True)
    prepare.add_argument("--destination", required=True, type=Path)
    transition = commands.add_parser(
        "transition-native-scope",
        help="Atomically activate one Hub-approved native scope and retain legacy rollback state.",
    )
    transition.add_argument("--state-dir", required=True, type=Path)
    transition.add_argument("--current-state", required=True, type=Path)
    transition.add_argument("--new-native-state", required=True, type=Path)
    transition.add_argument("--native-approval", required=True, type=Path)
    transition.add_argument("--hub-approval", required=True, type=Path)
    transition.add_argument("--hub-public-key", required=True, type=Path)
    transition.add_argument("--hub-key-id", required=True)
    transition.add_argument("--hub-key-epoch", required=True, type=int)
    transition.add_argument("--installation-public-key", required=True, type=Path)
    transition.add_argument("--hub-url", required=True)
    transition.add_argument("--hub-scope", required=True)
    transition.add_argument("--timeout-seconds", type=float, default=10.0)
    authentication = transition.add_mutually_exclusive_group(required=True)
    authentication.add_argument("--kube-context")
    authentication.add_argument("--in-cluster", action="store_true")
    prepare_reconciliation = commands.add_parser(
        "prepare-native-transition-reconciliation",
        help="Create one bounded request for a legacy transition timestamp repair.",
    )
    prepare_reconciliation.add_argument("--state-dir", required=True, type=Path)
    prepare_reconciliation.add_argument("--current-state", required=True, type=Path)
    prepare_reconciliation.add_argument("--native-approval", required=True, type=Path)
    prepare_reconciliation.add_argument(
        "--hub-completion-receipt",
        required=True,
        type=Path,
    )
    prepare_reconciliation.add_argument(
        "--installation-public-key",
        required=True,
        type=Path,
    )
    prepare_reconciliation.add_argument("--destination", required=True, type=Path)
    reconcile = commands.add_parser(
        "reconcile-native-transition-state",
        help="Repair only Agent current-state from one audited Hub-authoritative approval.",
    )
    reconcile.add_argument("--state-dir", required=True, type=Path)
    reconcile.add_argument("--current-state", required=True, type=Path)
    reconcile.add_argument("--native-approval", required=True, type=Path)
    reconcile.add_argument("--hub-completion-receipt", required=True, type=Path)
    reconcile.add_argument("--hub-reconciliation-approval", required=True, type=Path)
    reconcile.add_argument("--hub-public-key", required=True, type=Path)
    reconcile.add_argument("--hub-key-id", required=True)
    reconcile.add_argument("--hub-key-epoch", required=True, type=int)
    reconcile.add_argument("--installation-public-key", required=True, type=Path)
    reconcile.add_argument("--hub-url", required=True)
    reconcile.add_argument("--hub-scope", required=True)
    reconcile.add_argument("--timeout-seconds", type=float, default=10.0)
    authentication = reconcile.add_mutually_exclusive_group(required=True)
    authentication.add_argument("--kube-context")
    authentication.add_argument("--in-cluster", action="store_true")


def validate_native_policy(
    scope: NativeScope,
    *,
    installation_id: str,
    namespace: str,
    product: str | None,
    entity_components: Mapping[str, frozenset[str]],
    entity_ids: frozenset[str],
    native_scope_digest: str | None,
    runtime_bundle: RuntimeBundle | None = None,
) -> None:
    if runtime_bundle is not None:
        objects = {
            (item.kind, item.name)
            for item in runtime_bundle.objects
            if item.entity_id == scope.entity_id
        }
        expected = {scope.entity_id: runtime_bundle.components(scope.entity_id)}
        matches = (
            runtime_bundle.namespace == namespace
            and runtime_bundle.product == product
            and objects == scope.resources
            and dict(entity_components) == expected
        )
    else:
        matches = (
            not scope.scheduled_components
            and not scope.autoscaled_components
            and scope.service_components in (None, scope.components)
            and dict(entity_components) == {scope.entity_id: frozenset(scope.components)}
        )
    if (
        scope.installation_id != installation_id
        or scope.namespace != namespace
        or scope.product != product
        or native_scope_digest != scope.digest
        or entity_ids != frozenset({scope.entity_id})
        or not matches
    ):
        raise WorkloadError("native_scope_local_policy_mismatch")


def compose_native_cluster(
    cluster: Cluster,
    *,
    state_dir: Path,
    approval_path: Path | None,
    public_key_path: Path | None,
    native_scope_digest: str | None,
    installation_id: str,
    namespace: str,
    product: str | None,
    entity_components: Mapping[str, frozenset[str]],
    entity_ids: frozenset[str],
    clock: Callable[[], datetime],
    runtime_bundle: RuntimeBundle | None = None,
) -> Cluster:
    store = NativeStateStore(state_dir)
    if native_scope_digest is None:
        if (
            store.path.exists()
            or store.path.is_symlink()
            or approval_path is not None
            or public_key_path is not None
        ):
            raise WorkloadError("native_scope_local_pin_required")
        return cluster
    if approval_path is None or public_key_path is None:
        raise WorkloadError("native_scope_independent_inputs_required")
    approval = load_native_approval(approval_path)
    validate_native_policy(
        approval.scope,
        installation_id=installation_id,
        namespace=namespace,
        product=product,
        entity_components=entity_components,
        entity_ids=entity_ids,
        native_scope_digest=native_scope_digest,
        runtime_bundle=runtime_bundle,
    )
    if not isinstance(cluster, UidCluster):
        raise WorkloadError("native_scope_uid_provider_required")
    return NativeCluster(
        cluster,
        store,
        approval,
        load_ed25519_public_key(public_key_path).public_bytes_raw(),
        clock,
    )


def load_installation_identity(path: Path) -> Ed25519PrivateKey:
    """Read an existing owner-only key; bootstrap never generates a new identity."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_mode & 0o777 != 0o600
                or metadata.st_uid != os.geteuid()
                or metadata.st_size > 16 * 1024
            ):
                raise ValueError("invalid identity file")
            key = load_pem_private_key(handle.read(16 * 1024 + 1), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("invalid identity type")
        return key
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm) as error:
        raise WorkloadError("native_scope_installation_identity_invalid") from error


def run_native_bootstrap(
    arguments: argparse.Namespace,
    *,
    product: str | None,
    entity_components: Mapping[str, frozenset[str]],
    entity_ids: frozenset[str],
    native_scope_digest: str | None,
    clock: Callable[[], datetime],
    connect: Callable[[str | None, str, bool], Cluster],
    runtime_bundle: RuntimeBundle | None = None,
) -> int:
    approval = load_native_approval(arguments.native_approval)
    validate_native_policy(
        approval.scope,
        installation_id=arguments.installation_id,
        namespace=approval.scope.namespace,
        product=product,
        entity_components=entity_components,
        entity_ids=entity_ids,
        native_scope_digest=native_scope_digest,
        runtime_bundle=runtime_bundle,
    )
    if arguments.apply and arguments.proof_output is None:
        raise WorkloadError("native_scope_private_proof_output_required")
    store = NativeStateStore(arguments.state_dir)
    if arguments.proof_output is not None:
        reserved = [
            arguments.local_policy,
            arguments.current_state,
            arguments.native_approval,
            arguments.installation_key,
            store.path,
            *(
                arguments.state_dir / name
                for name in (STATE_FILE_NAME, LOCK_FILE_NAME, WORKLOAD_FILE_NAME, HALT_FILE_NAME)
            ),
        ]
        if arguments.proof_output.resolve() in {path.resolve() for path in reserved}:
            raise WorkloadError("native_scope_proof_output_conflicts_with_input")
    key = load_installation_identity(arguments.installation_key)
    cluster = connect(arguments.kube_context, approval.scope.namespace, arguments.in_cluster)
    if not isinstance(cluster, UidCluster):
        raise WorkloadError("native_scope_uid_provider_required")
    proof = bootstrap_native_scope(
        cluster,
        store,
        approval,
        key,
        current_state_path=arguments.current_state,
        clock=clock,
        apply=arguments.apply,
        timeout_seconds=arguments.timeout_seconds,
    )
    if proof is not None and arguments.apply:
        write_json_atomically(arguments.proof_output, proof.model_dump(mode="json"))
    logging.info("lifecycle_agent.native_bootstrap complete=true applied=%s", arguments.apply)
    return 0


def run_native_transition_command(
    arguments: argparse.Namespace,
    *,
    clock: Callable[[], datetime],
    connect: Callable[[str | None, str, bool], Cluster],
    complete: TransitionCompleter,
) -> int:
    approval = load_native_approval(arguments.native_approval)
    if arguments.command == "prepare-native-transition":
        request = prepare_native_transition_request(
            state_dir=arguments.state_dir,
            current_state_path=arguments.current_state,
            new_native_state_path=arguments.new_native_state,
            approval=approval,
            recovery_request_digest=arguments.recovery_request_digest,
            installation_key=load_installation_identity(arguments.installation_key),
            now=clock(),
        )
        write_private_output(arguments.destination, request.model_dump_json(indent=2) + "\n")
        print(json.dumps({"prepared": True, "request_digest": request.request.digest}))
        return 0
    try:
        raw = read_limited(arguments.hub_approval, limit=16 * 1024, label="Hub transition approval")
        load_json(raw, label="Hub transition approval")
        hub_approval = SignedNativeScopeTransitionApproval.model_validate_json(raw)
    except (OSError, ValueError) as error:
        raise WorkloadError("native_transition_hub_approval_invalid") from error
    cluster = connect(
        arguments.kube_context,
        approval.scope.namespace,
        arguments.in_cluster,
    )
    if not isinstance(cluster, UidCluster):
        raise WorkloadError("native_scope_uid_provider_required")
    receipt = transition_native_scope(
        cluster,
        state_dir=arguments.state_dir,
        current_state_path=arguments.current_state,
        new_native_state_path=arguments.new_native_state,
        approval=approval,
        signed_approval=hub_approval,
        hub_public_key=load_ed25519_public_key(arguments.hub_public_key).public_bytes_raw(),
        expected_hub_key_id=arguments.hub_key_id,
        expected_hub_key_epoch=arguments.hub_key_epoch,
        installation_public_key=load_ed25519_public_key(
            arguments.installation_public_key
        ).public_bytes_raw(),
        now=clock(),
    )
    try:
        state_document = load_json(
            read_limited(
                arguments.current_state,
                limit=1024 * 1024,
                label="native transition reported state",
            ),
            label="native transition reported state",
        )
        completion = NativeScopeTransitionCompletion(
            schema_version="fdai.lifecycle-native-transition-completion.v1",
            approval=hub_approval,
            transition_receipt=NativeScopeTransitionReceipt.model_validate_json(
                json.dumps(receipt)
            ),
            native_approval=approval,
            reported_state=NativeScopeTransitionReportedState.model_validate_json(
                json.dumps(state_document)
            ),
        )
    except ValueError as error:
        raise WorkloadError("native_transition_completion_invalid") from error
    hub_receipt = complete(arguments, completion)
    print(
        json.dumps(
            {
                "transitioned": True,
                "receipt_digest": receipt["record_digest"],
                "hub_completion_receipt_digest": hub_receipt.receipt_digest,
            }
        )
    )
    return 0


def complete_native_transition(
    arguments: argparse.Namespace,
    completion: NativeScopeTransitionCompletion,
) -> NativeScopeTransitionCompletionReceipt:
    """Submit the committed local receipt under the Agent's workload identity."""

    authorization = WorkloadIdentityAuthorization(arguments.hub_scope)
    try:
        with HttpHubClient(
            arguments.hub_url,
            timeout_seconds=arguments.timeout_seconds,
            authorization=authorization,
        ) as hub:
            return hub.submit_native_transition_completion(
                completion.transition_receipt.installation_id,
                completion,
            )
    finally:
        authorization.close()


def run_native_reconciliation_command(
    arguments: argparse.Namespace,
    *,
    clock: Callable[[], datetime],
    connect: Callable[[str | None, str, bool], Cluster],
    complete: ReconciliationCompleter,
) -> int:
    approval = load_native_approval(arguments.native_approval)
    completion_receipt = _load_transition_completion_receipt(arguments.hub_completion_receipt)
    installation_public_key = load_ed25519_public_key(
        arguments.installation_public_key
    ).public_bytes_raw()
    if arguments.command == "prepare-native-transition-reconciliation":
        destination = arguments.destination.resolve()
        if destination.is_relative_to(arguments.state_dir.resolve()) or destination in {
            arguments.current_state.resolve(),
            arguments.native_approval.resolve(),
            arguments.hub_completion_receipt.resolve(),
            arguments.installation_public_key.resolve(),
        }:
            raise WorkloadError("native_transition_reconciliation_output_conflict")
        request = prepare_native_transition_state_reconciliation_request(
            state_dir=arguments.state_dir,
            current_state_path=arguments.current_state,
            completion_receipt=completion_receipt,
            native_approval=approval,
            installation_public_key=installation_public_key,
            now=clock(),
        )
        write_private_output(destination, request.model_dump_json(indent=2) + "\n")
        print(json.dumps({"prepared": True, "request_digest": request.digest}))
        return 0
    signed_approval = _load_reconciliation_approval(arguments.hub_reconciliation_approval)
    cluster = connect(
        arguments.kube_context,
        approval.scope.namespace,
        arguments.in_cluster,
    )
    if not isinstance(cluster, UidCluster):
        raise WorkloadError("native_scope_uid_provider_required")
    receipt = reconcile_native_transition_state(
        cluster,
        state_dir=arguments.state_dir,
        current_state_path=arguments.current_state,
        native_approval=approval,
        completion_receipt=completion_receipt,
        signed_approval=signed_approval,
        hub_public_key=load_ed25519_public_key(arguments.hub_public_key).public_bytes_raw(),
        expected_hub_key_id=arguments.hub_key_id,
        expected_hub_key_epoch=arguments.hub_key_epoch,
        installation_public_key=installation_public_key,
        now=clock(),
        complete=lambda command: complete(arguments, command),
    )
    print(
        json.dumps(
            {
                "reconciled": True,
                "reported_state_digest": receipt.new_reported_state_digest,
                "reconciliation_receipt_digest": receipt.receipt_digest,
            }
        )
    )
    return 0


def complete_native_transition_reconciliation(
    arguments: argparse.Namespace,
    completion: NativeScopeTransitionStateReconciliationCompletion,
) -> NativeScopeTransitionStateReconciliationReceipt:
    """Submit corrected state and consume the exact committed Hub readback."""

    authorization = WorkloadIdentityAuthorization(arguments.hub_scope)
    try:
        with HttpHubClient(
            arguments.hub_url,
            timeout_seconds=arguments.timeout_seconds,
            authorization=authorization,
        ) as hub:
            return hub.submit_native_transition_state_reconciliation(
                completion.approval.approval.request.installation_id,
                completion,
            )
    finally:
        authorization.close()


def _load_transition_completion_receipt(
    path: Path,
) -> NativeScopeTransitionCompletionReceipt:
    try:
        raw = read_limited(path, limit=64 * 1024, label="Hub transition completion receipt")
        load_json(raw, label="Hub transition completion receipt")
        return NativeScopeTransitionCompletionReceipt.model_validate_json(raw)
    except (OSError, ValueError) as error:
        raise WorkloadError("native_transition_completion_receipt_invalid") from error


def _load_reconciliation_approval(
    path: Path,
) -> SignedNativeScopeTransitionStateReconciliationApproval:
    try:
        raw = read_limited(path, limit=192 * 1024, label="Hub reconciliation approval")
        load_json(raw, label="Hub reconciliation approval")
        return SignedNativeScopeTransitionStateReconciliationApproval.model_validate_json(raw)
    except (OSError, ValueError) as error:
        raise WorkloadError("native_transition_reconciliation_approval_invalid") from error
