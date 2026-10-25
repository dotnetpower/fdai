"""``fdai-lifecycle-agent`` command line: ``poll-once``, a dry run unless ``--apply`` is given."""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TypedDict, cast, get_args

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_installation_binding import INSTALLATION_BINDING_FORMAT
from fdai_deployment_cli.lifecycle_native import SignedNativeScope
from fdai_deployment_cli.lifecycle_plan import CapabilityMode, LifecycleEffectEnvelope
from fdai_deployment_cli.lifecycle_release import is_product_id
from fdai_deployment_cli.private_output import read_private_bytes
from pydantic import ValidationError

from fdai_lifecycle_agent.agent import (
    AgentDependencies,
    AgentSettings,
    ApplyMode,
    HubTrust,
    LifecycleAgent,
)
from fdai_lifecycle_agent.configuration_revision import load_full_revision_binding
from fdai_lifecycle_agent.dry_run import load_current_state
from fdai_lifecycle_agent.hub_artifacts import CachedHubArtifactStore
from fdai_lifecycle_agent.hub_client import HttpHubClient, HubProtocolError
from fdai_lifecycle_agent.inputs import (
    MAX_INPUT_BYTES,
    DirectoryArtifactStore,
    InputKind,
    SignedArtifact,
    stage_artifact,
)
from fdai_lifecycle_agent.journal import WorkloadStore
from fdai_lifecycle_agent.native_cli import (
    compose_native_cluster,
    register_native_command,
    run_native_bootstrap,
)
from fdai_lifecycle_agent.polling import PollLimits, poll_bounded
from fdai_lifecycle_agent.reference_cli import register_reference_command, run_reference_command
from fdai_lifecycle_agent.reference_state import ReferenceStatusSource
from fdai_lifecycle_agent.runtime_bundle import RuntimeBundle
from fdai_lifecycle_agent.signatures import (
    Ed25519ArtifactVerifier,
    Ed25519HubKeyring,
    load_ed25519_public_key,
)
from fdai_lifecycle_agent.state import AgentStateError, LocalStateStore, write_json_atomically
from fdai_lifecycle_agent.strict_json import load_json, read_limited
from fdai_lifecycle_agent.workload import (
    Cluster,
    Workload,
    WorkloadError,
    is_dns_label,
    is_repository,
)

LOCAL_POLICY_SCHEMA = "fdai.lifecycle-local-policy.v1"
_LOCAL_POLICY_KEYS = frozenset(
    {
        "schema",
        "entity_ids",
        "regions",
        "capability_modes",
        "destructive_allowed",
        "max_duration_minutes",
        "entity_components",
    }
)
_OPTIONAL_LOCAL_POLICY_KEYS = frozenset(
    {"component_images", "product", "native_scope_digest", "runtime_bundle", "installation_binding"}
)
_MAX_LOCAL_POLICY_BYTES = 64 * 1024
_EXIT_OK = 0
_EXIT_FAILED = 1
_EXIT_CONFIGURATION = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fdai-lifecycle-agent",
        description="Hub-managed lifecycle agent. Dry-runs a Plan unless --apply is given.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    register_reference_command(commands)
    register_native_command(commands)
    submit = commands.add_parser(
        "submit-native-proof", help="Deliver a private signed proof without accepting ownership."
    )
    submit.add_argument("--installation-id", required=True)
    submit.add_argument("--proof", type=Path, required=True)
    submit.add_argument("--hub-url", required=True)
    submit.add_argument("--hub-scope", required=True)
    submit.add_argument("--timeout-seconds", type=float, default=10.0)
    poll = commands.add_parser(
        "poll-once", help="Fetch one Plan, admit it, dry-run it, and report the result."
    )
    poll.add_argument("--hub-url", required=True, help="Hub base URL (http only on loopback).")
    poll.add_argument("--installation-id", required=True, help="This installation's Plan audience.")
    poll.add_argument(
        "--state-dir", required=True, type=Path, help="Durable agent state directory."
    )
    poll.add_argument("--hub-public-key", required=True, type=Path, help="Hub Ed25519 PEM key.")
    poll.add_argument("--hub-key-id", required=True, help="Key id the Hub uses in Plans.")
    poll.add_argument("--hub-key-epoch", required=True, type=int, help="Current Hub key epoch.")
    poll.add_argument(
        "--revoked-hub-key-id", action="append", default=[], help="Revoked Hub key id."
    )
    poll.add_argument("--fencing-generation", required=True, type=int)
    poll.add_argument("--release-public-key", required=True, type=Path)
    poll.add_argument("--configuration-public-key", required=True, type=Path)
    poll.add_argument(
        "--configuration-binding",
        type=Path,
        help="Independent private active revision/Entity/history binding.",
    )
    poll.add_argument(
        "--installation-encryption-key",
        type=Path,
        help="Independent private X25519 installation key; never an identity key.",
    )
    poll.add_argument(
        "--inputs-dir",
        type=Path,
        help="Directory source or private cache for signed Release/configuration documents.",
    )
    poll.add_argument(
        "--artifact-source",
        choices=("directory", "hub"),
        default="directory",
        help="Read pre-staged files, or fetch exact current-Plan artifacts from the Hub.",
    )
    poll.add_argument("--current-state", required=True, type=Path, help="Current-state fixture.")
    poll.add_argument(
        "--local-policy",
        required=True,
        type=Path,
        help="Local hard policy: maximum effect envelope and the components each Entity runs.",
    )
    poll.add_argument("--timeout-seconds", type=float, default=10.0)
    poll.add_argument("--hub-auth", choices=["none", "workload-identity"], default="none")
    poll.add_argument("--hub-scope", help="Exact api:// Hub application /.default scope.")
    poll.add_argument(
        "--apply",
        action="store_true",
        help="Apply an admitted Plan to one namespace, verify it, and roll back on failure.",
    )
    poll.add_argument("--kube-context", help="kubeconfig context; required with --apply.")
    poll.add_argument(
        "--in-cluster", action="store_true", help="Use the projected Kubernetes identity."
    )
    poll.add_argument("--namespace", help="The only namespace to change; required with --apply.")
    poll.add_argument("--native-approval", type=Path, help="Independent local creation approval.")
    poll.add_argument("--installation-public-key", type=Path, help="Enrolled identity PEM key.")
    poll.add_argument(
        "--health-timeout-seconds",
        type=float,
        default=180.0,
        help="Time each Deployment rollout and each rollback has to complete.",
    )
    continuous = commands.add_parser("poll", parents=[poll], add_help=False)
    continuous.add_argument("--max-polls", type=int, default=30)
    continuous.add_argument("--poll-interval-seconds", type=float, default=15)
    continuous.add_argument("--max-duration-seconds", type=float, default=900)
    stage = commands.add_parser(
        "stage-input", help="Verify and stage one independently pinned input."
    )
    stage.add_argument("--kind", choices=["release", "configuration"], required=True)
    stage.add_argument("--digest", required=True)
    stage.add_argument("--document", type=Path, required=True)
    stage.add_argument("--signature", type=Path, required=True)
    stage.add_argument("--public-key", type=Path, required=True)
    stage.add_argument("--inputs-dir", type=Path, required=True)
    return parser


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _connect_hub(url: str, timeout_seconds: float) -> HttpHubClient:
    return HttpHubClient(url, timeout_seconds=timeout_seconds)


def _connect_cluster(context: str, namespace: str) -> Cluster:
    # Imported here so that a dry run never loads a Kubernetes client.
    from fdai_lifecycle_agent.kube import KubernetesCluster

    return KubernetesCluster(context=context, namespace=namespace)


def _connect_in_cluster(namespace: str) -> Cluster:
    from fdai_lifecycle_agent.kube import KubernetesCluster

    return KubernetesCluster(in_cluster=True, namespace=namespace)


def _connect_reference_source(context: str, namespace: str) -> ReferenceStatusSource:
    from fdai_lifecycle_agent.kube import KubernetesCluster

    return KubernetesCluster(context=context, namespace=namespace)


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], datetime] = _utc_now,
    connect_hub: Callable[[str, float], HttpHubClient] = _connect_hub,
    connect_cluster: Callable[[str, str], Cluster] = _connect_cluster,
    connect_reference_source: Callable[
        [str, str], ReferenceStatusSource
    ] = _connect_reference_source,
) -> int:
    """Run the command. ``clock``, ``connect_hub``, and ``connect_cluster`` are seams for tests;
    defaults are real."""

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    # Keep stderr to the agent's structured events; httpx logs every request URL at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "submit-native-proof":
        from fdai_lifecycle_agent.remote_auth import WorkloadIdentityAuthorization

        try:
            body = read_limited(arguments.proof, limit=8192, label="native proof")
            load_json(body, label="native proof")
            proof = SignedNativeScope.model_validate_json(body)
            if proof.claim.installation_id != arguments.installation_id:
                raise ValueError("Native proof installation binding does not match.")
            with ExitStack() as resources:
                authorization = WorkloadIdentityAuthorization(arguments.hub_scope)
                resources.callback(authorization.close)
                hub = resources.enter_context(
                    HttpHubClient(
                        arguments.hub_url,
                        timeout_seconds=arguments.timeout_seconds,
                        authorization=authorization,
                    )
                )
                hub.submit_native_proof(arguments.installation_id, proof)
        except (ValueError, OSError, HubProtocolError) as error:
            logging.error("lifecycle_agent.native_proof_failed error_type=%s", type(error).__name__)
            print(
                "Native proof delivery failed; verify identity and private inputs.", file=sys.stderr
            )
            return _EXIT_CONFIGURATION
        logging.info("lifecycle_agent.native_proof_submitted")
        return _EXIT_OK
    if arguments.command == "reference-status":
        return run_reference_command(arguments, clock=clock, connect=connect_reference_source)
    if arguments.command == "bootstrap-slot":

        def connect_native(context: str | None, namespace: str, in_cluster: bool) -> Cluster:
            if in_cluster:
                return _connect_in_cluster(namespace)
            if context is None:
                raise ValueError("Native bootstrap requires an explicit Kubernetes context.")
            return connect_cluster(context, namespace)

        try:
            policy = load_local_policy(arguments.local_policy)
            return run_native_bootstrap(
                arguments,
                product=policy["product"],
                entity_components=policy["entity_components"],
                entity_ids=policy["maximum_envelope"].entity_ids,
                native_scope_digest=policy["native_scope_digest"],
                clock=clock,
                connect=connect_native,
                runtime_bundle=policy["runtime_bundle"],
            )
        except (ValueError, OSError, WorkloadError, AgentStateError) as error:
            logging.error(
                "lifecycle_agent.native_bootstrap_failed error_type=%s", type(error).__name__
            )
            print(
                "Native bootstrap failed; verify local approval, policy, identity and state.",
                file=sys.stderr,
            )
            return _EXIT_CONFIGURATION
    if arguments.command == "stage-input":
        try:
            stage_artifact(
                arguments.inputs_dir,
                cast(InputKind, arguments.kind),
                arguments.digest,
                SignedArtifact(
                    read_limited(arguments.document, limit=MAX_INPUT_BYTES, label="signed input"),
                    read_limited(arguments.signature, limit=64, label="input signature"),
                ),
                Ed25519ArtifactVerifier.from_file(arguments.public_key),
            )
        except (OSError, ValueError) as error:
            logging.error("lifecycle_agent.staging_failed error_type=%s", type(error).__name__)
            print(
                "Verify the approved digest, detached signature, public key and input paths.",
                file=sys.stderr,
            )
            return _EXIT_CONFIGURATION
        logging.info("lifecycle_agent.input_staged")
        return _EXIT_OK
    if arguments.apply and (
        not arguments.namespace or arguments.in_cluster == bool(arguments.kube_context)
    ):
        parser.error(
            "--apply requires --namespace and exactly one of --kube-context or --in-cluster"
        )
    if not arguments.apply and (
        arguments.in_cluster or arguments.kube_context or arguments.namespace
    ):
        parser.error("Kubernetes connection options require --apply")
    if (arguments.hub_auth == "workload-identity") != bool(arguments.hub_scope):
        parser.error("--hub-scope is required only with --hub-auth workload-identity")
    if arguments.artifact_source == "directory" and arguments.inputs_dir is None:
        parser.error("--inputs-dir is required with --artifact-source directory")
    if arguments.artifact_source == "hub" and arguments.hub_auth != "workload-identity":
        parser.error("--artifact-source hub requires --hub-auth workload-identity")
    limits = None
    try:
        if arguments.command == "poll":
            limits = PollLimits(
                arguments.max_polls, arguments.poll_interval_seconds, arguments.max_duration_seconds
            )
        settings = AgentSettings(
            installation_id=arguments.installation_id,
            trust=HubTrust(
                hub_key_epochs={arguments.hub_key_id: arguments.hub_key_epoch},
                revoked_hub_key_ids=frozenset(arguments.revoked_hub_key_id),
                current_hub_key_epoch=arguments.hub_key_epoch,
                fencing_generation=arguments.fencing_generation,
            ),
            **load_local_policy(arguments.local_policy),
        )
        hub_keyring = Ed25519HubKeyring(
            {arguments.hub_key_id: load_ed25519_public_key(arguments.hub_public_key)}
        )
        release_verifier = Ed25519ArtifactVerifier.from_file(arguments.release_public_key)
        configuration_verifier = Ed25519ArtifactVerifier.from_file(
            arguments.configuration_public_key
        )
        binding = None
        if arguments.configuration_binding and arguments.installation_encryption_key:
            binding = load_full_revision_binding(
                arguments.configuration_binding,
                arguments.installation_encryption_key,
                arguments.configuration_public_key,
            )
        # Fail fast as a configuration error; each poll then reads the current state again.
        load_current_state(arguments.current_state)
        if arguments.apply:
            _check_apply_settings(settings, arguments.namespace, arguments.health_timeout_seconds)
    except ValueError as error:
        print(f"fdai-lifecycle-agent: configuration error: {error}", file=sys.stderr)
        return _EXIT_CONFIGURATION
    with ExitStack() as resources:
        try:
            if arguments.hub_auth == "workload-identity":
                from fdai_lifecycle_agent.remote_auth import WorkloadIdentityAuthorization

                authorization = WorkloadIdentityAuthorization(arguments.hub_scope)
                resources.callback(authorization.close)
                hub = HttpHubClient(
                    arguments.hub_url,
                    timeout_seconds=arguments.timeout_seconds,
                    authorization=authorization,
                )
            else:
                hub = connect_hub(arguments.hub_url, arguments.timeout_seconds)
        except ValueError as error:
            print(f"fdai-lifecycle-agent: configuration error: {error}", file=sys.stderr)
            return _EXIT_CONFIGURATION
        resources.enter_context(hub)
        apply = None
        if arguments.apply:
            try:
                cluster = (
                    _connect_in_cluster(arguments.namespace)
                    if arguments.in_cluster
                    else connect_cluster(arguments.kube_context, arguments.namespace)
                )
                cluster = compose_native_cluster(
                    cluster,
                    state_dir=arguments.state_dir,
                    approval_path=arguments.native_approval,
                    public_key_path=arguments.installation_public_key,
                    native_scope_digest=settings.native_scope_digest,
                    installation_id=settings.installation_id,
                    namespace=arguments.namespace,
                    product=settings.product,
                    entity_components=settings.entity_components,
                    entity_ids=settings.maximum_envelope.entity_ids,
                    clock=clock,
                    runtime_bundle=settings.runtime_bundle,
                )
            except (ValueError, WorkloadError) as error:
                print(f"fdai-lifecycle-agent: configuration error: {error}", file=sys.stderr)
                return _EXIT_CONFIGURATION
            apply = ApplyMode(
                workload=Workload(
                    cluster=cluster,
                    namespace=arguments.namespace,
                    health_timeout_seconds=arguments.health_timeout_seconds,
                ),
                store=WorkloadStore(arguments.state_dir),
                write_current_state=partial(write_json_atomically, arguments.current_state),
            )
        artifact_store = (
            CachedHubArtifactStore(
                arguments.inputs_dir or arguments.state_dir / "artifact-cache",
                hub,
                arguments.installation_id,
                release_verifier=release_verifier,
                configuration_verifier=configuration_verifier,
            )
            if arguments.artifact_source == "hub"
            else DirectoryArtifactStore(arguments.inputs_dir)
        )
        dependencies = AgentDependencies(
            hub=hub,
            state_store=LocalStateStore(arguments.state_dir),
            artifact_store=artifact_store,
            verify_plan_signature=hub_keyring,
            verify_release_signature=release_verifier,
            verify_configuration_signature=configuration_verifier,
            read_current_state=partial(load_current_state, arguments.current_state),
            clock=clock,
            apply=apply,
            configuration_binding=binding,
        )
        agent = LifecycleAgent(settings, dependencies)

        def poll_once() -> int:
            try:
                result = agent.poll_once()
            except (HubProtocolError, AgentStateError) as error:
                print(f"fdai-lifecycle-agent: poll failed: {error}", file=sys.stderr)
                return _EXIT_FAILED
            if limits is None:
                print(json.dumps(result.to_json(), sort_keys=True))
            else:
                logging.info("lifecycle_agent.poll outcome=%s", result.outcome)
            if result.outcome in {"malformed-plan", "halted"}:
                return _EXIT_FAILED
            if limits is not None and result.outcome in {"rejected", "rolled-back"}:
                return _EXIT_FAILED
            if result.outcome not in {"no-plan", "already-reported"} and not result.reported:
                return _EXIT_FAILED
            return _EXIT_OK

        if limits is None:
            return poll_once()
        status = poll_bounded(poll_once, limits)
        logging.info("lifecycle_agent.polling_complete exit_code=%s", status)
        return status


def _check_apply_settings(settings: AgentSettings, namespace: str, timeout: float) -> None:
    if not is_dns_label(namespace):
        raise ValueError("--namespace is not a valid Kubernetes namespace")
    if settings.runtime_bundle is not None and settings.runtime_bundle.namespace != namespace:
        raise ValueError("--namespace differs from the independent local runtime bundle")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("--health-timeout-seconds MUST be positive and finite")
    components = set().union(*settings.entity_components.values())
    if missing := components - settings.component_repositories.keys():
        raise ValueError(f"local policy component_images lacks {sorted(missing)}")


class LocalPolicy(TypedDict):
    maximum_envelope: LifecycleEffectEnvelope
    entity_components: dict[str, frozenset[str]]
    component_repositories: dict[str, str]
    product: str | None
    native_scope_digest: str | None
    runtime_bundle: RuntimeBundle | None


def load_local_policy(path: Path) -> LocalPolicy:
    """Load local hard policy. A Hub Plan and the signed inputs can only narrow its envelope."""

    try:
        raw = read_limited(path, limit=_MAX_LOCAL_POLICY_BYTES, label="local policy")
    except OSError as error:
        raise ValueError(f"local policy is unreadable: {type(error).__name__}") from error
    document = load_json(raw, label="local policy")
    if not isinstance(document, dict) or not (
        _LOCAL_POLICY_KEYS <= set(document) <= _LOCAL_POLICY_KEYS | _OPTIONAL_LOCAL_POLICY_KEYS
    ):
        raise ValueError("local policy fields are invalid")
    if document["schema"] != LOCAL_POLICY_SCHEMA:
        raise ValueError("local policy schema is unsupported")
    runtime_bundle = None
    if "installation_binding" in document and "runtime_bundle" not in document:
        raise ValueError("an installation binding requires a private runtime bundle")
    if "runtime_bundle" in document:
        try:
            private = read_private_bytes(path, max_bytes=_MAX_LOCAL_POLICY_BYTES)
        except OSError:
            raise ValueError("private runtime policy requires owner-only regular storage") from None
        if private != raw:
            raise ValueError("private local runtime policy changed while reading")
        try:
            runtime_bundle = RuntimeBundle.model_validate_json(
                canonical_bytes(document["runtime_bundle"])
            )
        except ValidationError:
            raise ValueError("private local runtime bundle is invalid") from None
        runtime_bundle = _bind_installation(runtime_bundle, document.get("installation_binding"))
    product = document.get("product")
    if product is not None and not is_product_id(product):
        raise ValueError("local policy product must be an application identifier")
    native_pin = document.get("native_scope_digest")
    if native_pin is not None and (
        product is None
        or not isinstance(native_pin, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", native_pin) is None
    ):
        raise ValueError("native local policy requires a product and exact scope digest")
    modes = document["capability_modes"]
    if not isinstance(modes, dict) or not set(modes.values()) <= set(get_args(CapabilityMode)):
        raise ValueError("local policy capability mode is unsupported")
    components = document["entity_components"]
    if not isinstance(components, dict):
        raise ValueError("local policy entity_components MUST be an object")
    repositories = document.get("component_images", {})
    if not isinstance(repositories, dict) or not all(
        isinstance(repository, str) and is_repository(repository)
        for repository in repositories.values()
    ):
        raise ValueError(
            "local policy component_images MUST map components to repositories without a tag"
        )
    try:
        envelope = LifecycleEffectEnvelope(
            entity_ids=_strings(document["entity_ids"], "entity_ids"),
            regions=_strings(document["regions"], "regions"),
            capability_modes=cast(dict[str, CapabilityMode], modes),
            destructive_allowed=document["destructive_allowed"],
            max_duration_minutes=document["max_duration_minutes"],
        )
    except TypeError as error:
        raise ValueError(f"local policy is invalid: {error}") from error
    return LocalPolicy(
        maximum_envelope=envelope,
        entity_components={
            str(entity_id): _strings(names, "entity_components")
            for entity_id, names in components.items()
        },
        component_repositories={str(name): str(repo) for name, repo in repositories.items()},
        product=product,
        native_scope_digest=native_pin,
        runtime_bundle=runtime_bundle,
    )


def _bind_installation(bundle: RuntimeBundle, binding: object) -> RuntimeBundle:
    if binding is None:
        if bundle.referenced_binding_keys():
            raise ValueError("the runtime bundle references an installation binding that is absent")
        return bundle
    if (
        not isinstance(binding, dict)
        or set(binding) != {"format", "values"}
        or binding["format"] != INSTALLATION_BINDING_FORMAT
        or not isinstance(binding["values"], dict)
    ):
        raise ValueError("installation binding is invalid")
    try:
        return bundle.with_installation_binding(binding["values"])
    except ValueError as error:
        # The messages are fixed text; a value is never echoed.
        raise ValueError(str(error)) from None


def _strings(value: object, label: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"local policy {label} MUST be a list of strings")
    return frozenset(value)


if __name__ == "__main__":
    raise SystemExit(main())
