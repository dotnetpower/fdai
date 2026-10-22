"""Independent local policy, identity and explicit native bootstrap composition."""

from __future__ import annotations

import argparse
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

from fdai_lifecycle_agent.journal import HALT_FILE_NAME, WORKLOAD_FILE_NAME
from fdai_lifecycle_agent.native_bootstrap import bootstrap_native_scope
from fdai_lifecycle_agent.native_cluster import NativeCluster, UidCluster
from fdai_lifecycle_agent.native_state import NativeStateStore, load_native_approval
from fdai_lifecycle_agent.runtime_bundle import RuntimeBundle
from fdai_lifecycle_agent.signatures import load_ed25519_public_key
from fdai_lifecycle_agent.state import (
    LOCK_FILE_NAME,
    STATE_FILE_NAME,
    write_json_atomically,
)
from fdai_lifecycle_agent.workload import Cluster, WorkloadError


def register_native_command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    command = commands.add_parser(
        "bootstrap-slot", help="Dry-run creation of a private workload anchor; never deploy an app."
    )
    command.add_argument("--installation-id", required=True)
    command.add_argument("--state-dir", required=True, type=Path)
    command.add_argument("--local-policy", required=True, type=Path)
    command.add_argument("--current-state", required=True, type=Path)
    command.add_argument("--native-approval", required=True, type=Path)
    command.add_argument("--installation-key", required=True, type=Path)
    command.add_argument("--proof-output", type=Path)
    authentication = command.add_mutually_exclusive_group(required=True)
    authentication.add_argument("--kube-context")
    authentication.add_argument("--in-cluster", action="store_true")
    command.add_argument("--timeout-seconds", type=float, default=120)
    command.add_argument("--apply", action="store_true")


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
