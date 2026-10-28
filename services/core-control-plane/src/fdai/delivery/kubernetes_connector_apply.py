"""Apply, activate, or roll back one approved observer installation through its pinned method.

The preview renderer never touches a cluster. This module is the separate governed step: it
binds one human approval to the exact rendered manifest, checks the cluster identity, requires a
successful server-side dry-run, applies only the fixed observer recipe, and reads the result back.
A successful apply installs a suspended CronJob. Activation is a second approval, and operational
success remains unproven until the gateway admits a fresh snapshot.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from fdai_service_contracts.cluster_connector import ConnectorContract, Digest, connector_time
from fdai_service_contracts.compatibility import canonical_digest
from pydantic import Field, model_validator

from fdai.delivery.kubernetes_connector_claim import MANIFEST_FILE, claim_effect, cluster_lock
from fdai.delivery.kubernetes_connector_installation import (
    PROPOSAL_ANNOTATION,
    ObserverInstallationInput,
    recipe_digest,
    validate_installation_material,
)
from fdai.delivery.kubernetes_connector_kube_transport import (
    AksRunCommandTransport as AksRunCommandTransport,
)
from fdai.delivery.kubernetes_connector_kube_transport import (
    KubectlTransport as KubectlTransport,
)
from fdai.delivery.kubernetes_connector_kube_transport import KubeResult as KubeResult
from fdai.delivery.kubernetes_connector_kube_transport import KubeTransport as KubeTransport
from fdai.delivery.kubernetes_connector_material import MATERIAL_FILES, material_digest
from fdai.delivery.kubernetes_connector_runtime import private_file

FIELD_MANAGER = "fdai-observer-install"
STATE_MANAGER = "fdai-observer-state"
MAX_APPROVAL_SECONDS = 1800
_OWNER_LABEL = "app.kubernetes.io/managed-by"
_AUTHORITY_ANNOTATION = "fdai.dev/execution-authority"
_EXPECTED_KINDS = frozenset(
    {
        "ServiceAccount",
        "ClusterRole",
        "ClusterRoleBinding",
        "PersistentVolumeClaim",
        "CronJob",
        "NetworkPolicy",
    }
)
_CLUSTER_SCOPED = frozenset({"ClusterRole", "ClusterRoleBinding"})
_ROLLBACK_ORDER = (
    "CronJob",
    "NetworkPolicy",
    "ClusterRoleBinding",
    "ClusterRole",
    "PersistentVolumeClaim",
    "ServiceAccount",
)
_HOST_FLAGS = frozenset({"hostNetwork", "hostPID", "hostIPC"})
_TEXT = r"^[A-Za-z0-9][A-Za-z0-9@._:/=+-]*$"

Audit = Callable[[dict[str, object]], None]


class ObserverApplyApproval(ConnectorContract):
    """A short-lived human approval bound to one exact target, plan, and operation."""

    operation: Literal[
        "apply", "activate", "verify", "deactivate", "recover", "rollback", "uninstall"
    ]
    approver_ref: Annotated[str, Field(min_length=1, max_length=256, pattern=_TEXT)]
    target_ref: Annotated[str, Field(min_length=1, max_length=512, pattern=_TEXT)]
    cluster_uid: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9-]+$")]
    method: Literal["existing_host", "managed_host", "run_command"]
    namespace: Annotated[str, Field(min_length=1, max_length=63)]
    name: Annotated[str, Field(min_length=1, max_length=63)]
    inputs_digest: Digest
    recipe_digest: Digest | None = None
    approved_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _window(self) -> ObserverApplyApproval:
        approved, expires = connector_time(self.approved_at), connector_time(self.expires_at)
        if not approved < expires <= approved + timedelta(seconds=MAX_APPROVAL_SECONDS):
            raise ValueError("observer approval must expire within thirty minutes")
        if self.operation in {"apply", "activate", "verify"} and self.recipe_digest is None:
            raise ValueError("observer approval must bind the exact installable recipe")
        return self


def _record(audit: Audit, now: datetime, phase: str, **fields: object) -> None:
    record: dict[str, object] = {
        "event": "observer_install",
        "phase": phase,
        "at": connector_time(now).isoformat(),
    }
    audit(record | fields)


def _checked(result: KubeResult, reason: str, *, secret: bool = False) -> KubeResult:
    if result.exit_code != 0:
        lines = [
            line
            for line in result.output.splitlines()
            if not line.rstrip().endswith(("serverside-applied", "(server dry run)"))
        ]
        detail = "" if secret else f": {' '.join(' '.join(lines or [result.output]).split())[:400]}"
        raise ValueError(f"{reason} (exit {result.exit_code}){detail}")
    return result


def _json(result: KubeResult, reason: str) -> dict[str, Any]:
    try:
        value = json.loads(result.output)
    except ValueError as exc:
        raise ValueError(f"{reason}: the response is not JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{reason}: the response is not an object")
    return value


@contextmanager
def target_lock(directory: Path, key: str) -> Iterator[None]:
    """Hold an owner-only advisory lock so one host serializes operations on one target."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"{hashlib.sha256(key.encode()).hexdigest()[:32]}.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another observer installation operation holds this target") from exc
        yield
    finally:
        os.close(descriptor)


def _authorize(
    approval: ObserverApplyApproval,
    *,
    operation: str,
    inputs: ObserverInstallationInput,
    rendered: Mapping[str, Any] | None,
    now: datetime,
) -> None:
    if (
        approval.operation != operation
        or approval.target_ref != inputs.target_ref
        or approval.method != inputs.method
        or (approval.namespace, approval.name) != (inputs.namespace, inputs.name)
        or approval.inputs_digest != canonical_digest(inputs.model_dump(mode="json"))
        or not connector_time(approval.approved_at)
        <= connector_time(now)
        < connector_time(approval.expires_at)
    ):
        raise ValueError("observer approval does not match this operation, target, or time")
    if rendered is not None and (
        approval.recipe_digest != rendered.get("recipe_digest")
        or rendered.get("material_digest") != inputs.material_digest
    ):
        raise ValueError("observer approval does not match the rendered recipe")


def _verified_documents(
    rendered: Mapping[str, Any], inputs: ObserverInstallationInput
) -> list[dict[str, Any]]:
    """Re-derive the fixed observer-only recipe invariants from the bytes about to be applied."""
    documents = rendered.get("documents")
    if (
        not isinstance(documents, list)
        or canonical_digest(documents) != rendered.get("manifest_digest")
        or recipe_digest(documents) != rendered.get("recipe_digest")
        or rendered.get("execution_authority") is not False
        or rendered.get("recommended") is not True
        or rendered.get("missing") != []
    ):
        raise ValueError("observer apply requires a complete, untampered, recommended manifest")
    if sorted(str(item.get("kind")) for item in documents) != sorted(_EXPECTED_KINDS):
        raise ValueError("observer apply manifest is not the fixed observer recipe")
    for item in documents:
        metadata = item["metadata"]
        namespace = None if item["kind"] in _CLUSTER_SCOPED else inputs.namespace
        if (
            metadata.get("name") != inputs.name
            or metadata.get("namespace") != namespace
            or metadata.get("annotations", {}).get(_AUTHORITY_ANNOTATION) != "false"
        ):
            raise ValueError("observer apply manifest identity differs from the approval")
    by_kind = {item["kind"]: item for item in documents}
    rules = by_kind["ClusterRole"]["rules"]
    pod = by_kind["CronJob"]["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    containers = [*pod["initContainers"], *pod["containers"]]
    if (
        any(
            not {"list", "get"} >= set(rule["verbs"])
            or {"*", "secrets", "configmaps"} & set(rule["resources"])
            for rule in rules
        )
        or by_kind["CronJob"]["spec"]["suspend"] is not True
        or any(pod.get(key) is not False for key in ("hostNetwork", "hostPID", "hostIPC"))
        or any(
            item["securityContext"]["privileged"] is not False or item["image"] != inputs.image
            for item in containers
        )
    ):
        raise ValueError("observer apply manifest violates the observer-only safety recipe")
    return [dict(item) for item in documents]


def _labels(inputs: ObserverInstallationInput) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": "fdai-cluster-observer",
        "app.kubernetes.io/instance": inputs.name,
    }


def _namespace_document(inputs: ObserverInstallationInput, proposal_digest: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": inputs.namespace,
            "labels": {
                _OWNER_LABEL: FIELD_MANAGER,
                "pod-security.kubernetes.io/enforce": "restricted",
            },
            "annotations": {PROPOSAL_ANNOTATION: proposal_digest, _AUTHORITY_ANNOTATION: "false"},
        },
    }


def _secret_document(
    inputs: ObserverInstallationInput, directory: Path, proposal_digest: str, now: datetime
) -> dict[str, Any]:
    """Build the credential Secret in memory from digest-checked private files."""
    validate_installation_material(inputs, directory=directory, now=now)
    contents = {name: private_file(directory / name) for name in MATERIAL_FILES}
    if material_digest(contents) != inputs.material_digest:
        raise ValueError("observer installation material differs from the approved digest")
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {
            "name": inputs.material_secret,
            "namespace": inputs.namespace,
            "labels": _labels(inputs),
            "annotations": {PROPOSAL_ANNOTATION: proposal_digest, _AUTHORITY_ANNOTATION: "false"},
        },
        "data": {name: base64.b64encode(contents[name]).decode("ascii") for name in contents},
    }


def _bundle(*documents: Mapping[str, Any]) -> bytes:
    return json.dumps({"apiVersion": "v1", "kind": "List", "items": list(documents)}).encode()


def _get(
    transport: KubeTransport, kind: str, name: str, namespace: str | None
) -> dict[str, Any] | None:
    args = ["get", kind.lower(), name, "--output", "json", "--ignore-not-found"]
    if namespace is not None:
        args += ["--namespace", namespace]
    result = _checked(transport.run(args, manifest=None, timeout=90), f"reading {kind} failed")
    return _json(result, f"reading {kind} failed") if result.output.strip() else None


def _cluster_identity(transport: KubeTransport, cluster_uid: str) -> None:
    live = _get(transport, "Namespace", "kube-system", None)
    uid = (live or {}).get("metadata", {}).get("uid")
    if not cluster_uid or uid != cluster_uid:
        raise ValueError("the reachable cluster is not the approved target; nothing was changed")


def _omitted_by_server(key: str, value: object) -> bool:
    """The API server drops empty collections and false host-namespace flags from responses."""
    return value == [] or value == {} or (key in _HOST_FLAGS and value is False)


def _contains(expected: object, live: object) -> bool:
    if isinstance(expected, dict):
        return isinstance(live, dict) and all(
            _contains(value, live[key]) if key in live else _omitted_by_server(key, value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(live, list)
            and len(live) == len(expected)
            and all(_contains(a, b) for a, b in zip(expected, live, strict=True))
        )
    return bool(expected == live and type(expected) is type(live))


def _verify_installed(
    transport: KubeTransport,
    documents: Sequence[Mapping[str, Any]],
    *,
    suspended: bool,
) -> list[dict[str, str]]:
    verified: list[dict[str, str]] = []
    drift: list[str] = []
    for item in documents:
        metadata = item["metadata"]
        live = _get(transport, item["kind"], metadata["name"], metadata.get("namespace"))
        expected = {
            key: value
            for key, value in item.items()
            if key not in {"apiVersion", "kind", "metadata"}
        }
        if item["kind"] == "CronJob":
            expected["spec"] = {**expected["spec"], "suspend": suspended}
        meta = {"annotations": metadata["annotations"], "labels": metadata["labels"]}
        if (
            live is None
            or not _contains(expected, live)
            or not _contains(meta, live.get("metadata", {}))
        ):
            drift.append(str(item["kind"]))
        else:
            verified.append({"kind": str(item["kind"]), "name": str(metadata["name"])})
    if drift:
        raise ValueError(f"observer installation differs from the approved plan: {sorted(drift)}")
    return verified


def _guarded_namespace(transport: KubeTransport, inputs: ObserverInstallationInput) -> bool:
    """Return whether the namespace must be created; refuse a namespace this tool does not own."""
    live = _get(transport, "Namespace", inputs.namespace, None)
    if live is None:
        return True
    if live.get("metadata", {}).get("labels", {}).get(_OWNER_LABEL) != FIELD_MANAGER:
        raise ValueError(
            "the observer namespace exists and is not owned by this installer; "
            f"label it {_OWNER_LABEL}={FIELD_MANAGER} to adopt it after review"
        )
    return False


def _apply_args(*, dry_run: bool) -> list[str]:
    return [
        "apply",
        "--server-side",
        f"--field-manager={FIELD_MANAGER}",
        *(["--dry-run=server"] if dry_run else []),
        "--filename",
        MANIFEST_FILE,
    ]


def apply_observer_installation(
    rendered: Mapping[str, Any],
    inputs: ObserverInstallationInput,
    approval: ObserverApplyApproval | None,
    *,
    transport: KubeTransport,
    material_directory: Path,
    cluster_uid: str,
    lock_directory: Path,
    audit: Audit,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Install the suspended observer. Without an approval, only identity and dry-run run."""
    documents = _verified_documents(rendered, inputs)
    proposal_digest = str(rendered["proposal_digest"])
    if approval is not None:
        _authorize(approval, operation="apply", inputs=inputs, rendered=rendered, now=now())
        cluster_uid = approval.cluster_uid
    key = canonical_digest([approval.model_dump(mode="json") if approval else None, documents])
    common: dict[str, object] = {
        "operation": "apply",
        "target_ref": inputs.target_ref,
        "manifest_digest": rendered["manifest_digest"],
        "recipe_digest": rendered["recipe_digest"],
        "proposal_digest": proposal_digest,
        "idempotency_key": key,
        "executor": transport.name,
        "approver_ref": approval.approver_ref if approval else None,
    }

    def dry_run(*items: Mapping[str, Any], reason: str, secret: bool = False) -> None:
        _checked(
            transport.run(_apply_args(dry_run=True), manifest=_bundle(*items), timeout=120),
            reason,
            secret=secret,
        )

    def apply(*items: Mapping[str, Any], reason: str, secret: bool = False) -> None:
        _checked(
            transport.run(_apply_args(dry_run=False), manifest=_bundle(*items), timeout=180),
            reason,
            secret=secret,
        )

    with (
        target_lock(lock_directory, f"{inputs.target_ref}/{inputs.namespace}/{inputs.name}"),
        (
            cluster_lock(
                transport,
                namespace=inputs.namespace,
                name=inputs.name,
                holder=f"{transport.name}:{key[7:23]}",
                now=now(),
            )
            if approval is not None
            else nullcontext("none")
        ) as lock_scope,
    ):
        common = common | {"lock_scope": lock_scope}
        _cluster_identity(transport, cluster_uid)
        live_job = _get(transport, "CronJob", inputs.name, inputs.namespace)
        if live_job is not None and live_job.get("spec", {}).get("suspend") is False:
            raise ValueError(
                "the observer is active; run deactivate before applying a changed or repeated plan"
            )
        create_namespace = _guarded_namespace(transport, inputs)
        secret = _secret_document(inputs, material_directory, proposal_digest, now())
        namespace_document = _namespace_document(inputs, proposal_digest)
        _record(audit, now(), "intent", step="dry-run", **common)
        if create_namespace:
            dry_run(namespace_document, reason="namespace dry-run was rejected")
        else:
            dry_run(*documents, reason="observer dry-run was rejected")
            dry_run(secret, reason="observer material dry-run was rejected", secret=True)
        _record(audit, now(), "result", step="dry-run", outcome="succeeded", **common)
        if approval is None:
            return {
                "schema_version": "1.0.0",
                "operation": "apply",
                "state": "dry_run_passed",
                "manifest_digest": rendered["manifest_digest"],
                "recipe_digest": rendered["recipe_digest"],
                "dry_run_scope": "namespace_only" if create_namespace else "complete",
                "approval_required": True,
                "operational_success": False,
            }
        claim = claim_effect(lock_directory, key, operation="apply", at=now())
        _record(audit, now(), "intent", step="apply", **common)
        try:
            if create_namespace:
                apply(namespace_document, reason="namespace apply failed")
                dry_run(*documents, reason="observer dry-run was rejected")
                dry_run(secret, reason="observer material dry-run was rejected", secret=True)
            apply(secret, reason="observer material apply failed", secret=True)
            apply(*documents, reason="observer apply failed")
            verified = _verify_installed(transport, documents, suspended=True)
            _cluster_identity(transport, cluster_uid)
        except ValueError as exc:
            claim.settle("unknown", at=now())
            _record(audit, now(), "result", step="apply", outcome="unknown", **common)
            raise ValueError(
                f"{exc}; the outcome is unknown, so run verify against the cluster, then request "
                "a fresh approval or run the approved rollback"
            ) from exc
        claim.settle("installed_suspended", at=now())
        _record(audit, now(), "result", step="apply", outcome="installed_suspended", **common)
    return {
        "schema_version": "1.0.0",
        "operation": "apply",
        "state": "installed_suspended",
        "manifest_digest": rendered["manifest_digest"],
        "recipe_digest": rendered["recipe_digest"],
        "idempotency_key": key,
        "resources": verified,
        "activation_required": True,
        "operational_success": False,
    }


def activate_observer(
    rendered: Mapping[str, Any],
    inputs: ObserverInstallationInput,
    approval: ObserverApplyApproval,
    *,
    transport: KubeTransport,
    lock_directory: Path,
    audit: Audit,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Resume the CronJob only when the live installation still equals the approved plan."""
    documents = _verified_documents(rendered, inputs)
    _authorize(approval, operation="activate", inputs=inputs, rendered=rendered, now=now())
    common: dict[str, object] = {
        "operation": "activate",
        "target_ref": inputs.target_ref,
        "manifest_digest": rendered["manifest_digest"],
        "recipe_digest": rendered["recipe_digest"],
        "proposal_digest": rendered["proposal_digest"],
        "executor": transport.name,
        "approver_ref": approval.approver_ref,
    }
    key = canonical_digest([approval.model_dump(mode="json"), documents])
    with (
        target_lock(lock_directory, f"{inputs.target_ref}/{inputs.namespace}/{inputs.name}"),
        cluster_lock(
            transport,
            namespace=inputs.namespace,
            name=inputs.name,
            holder=f"{transport.name}:{key[7:23]}",
            now=now(),
        ) as lock_scope,
    ):
        common = common | {"lock_scope": lock_scope}
        _cluster_identity(transport, approval.cluster_uid)
        _verify_installed_either(transport, documents)
        claim = claim_effect(lock_directory, key, operation="activate", at=now())
        _record(audit, now(), "intent", step="activate", **common)
        try:
            _set_suspend(transport, inputs, suspend=False, reason="observer activation failed")
            _verify_installed(transport, documents, suspended=False)
        except ValueError:
            claim.settle("unknown", at=now())
            raise
        claim.settle("activated", at=now())
        _record(audit, now(), "result", step="activate", outcome="activated", **common)
    return {
        "schema_version": "1.0.0",
        "operation": "activate",
        "state": "activated_pending_observation",
        "manifest_digest": rendered["manifest_digest"],
        "observation_required": True,
        "operational_success": False,
    }


def _verify_installed_either(
    transport: KubeTransport, documents: Sequence[Mapping[str, Any]]
) -> None:
    try:
        _verify_installed(transport, documents, suspended=True)
    except ValueError:
        _verify_installed(transport, documents, suspended=False)


def _set_suspend(
    transport: KubeTransport, inputs: ObserverInstallationInput, *, suspend: bool, reason: str
) -> None:
    """Own only spec.suspend under a separate field manager.

    A partial apply under the install manager would delete the fields that it omits. Forcing is
    limited to this single field, so stopping never waits on another manager's ownership.
    """
    document = {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {"name": inputs.name, "namespace": inputs.namespace},
        "spec": {"suspend": suspend},
    }
    arguments = [
        "apply",
        "--server-side",
        f"--field-manager={STATE_MANAGER}",
        "--force-conflicts",
        "--validate=false",
        "--filename",
        MANIFEST_FILE,
    ]
    _checked(transport.run(arguments, manifest=_bundle(document), timeout=120), reason)


def deactivate_observer(
    inputs: ObserverInstallationInput,
    approval: ObserverApplyApproval,
    *,
    transport: KubeTransport,
    lock_directory: Path,
    audit: Audit,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Stop collection by suspending the CronJob; this is the observer's stop condition."""
    _authorize(approval, operation="deactivate", inputs=inputs, rendered=None, now=now())
    common: dict[str, object] = {
        "operation": "deactivate",
        "target_ref": inputs.target_ref,
        "executor": transport.name,
        "approver_ref": approval.approver_ref,
    }
    with target_lock(lock_directory, f"{inputs.target_ref}/{inputs.namespace}/{inputs.name}"):
        _cluster_identity(transport, approval.cluster_uid)
        _record(audit, now(), "intent", step="deactivate", **common)
        _set_suspend(transport, inputs, suspend=True, reason="observer deactivation failed")
        live = _get(transport, "CronJob", inputs.name, inputs.namespace)
        if live is None or live.get("spec", {}).get("suspend") is not True:
            raise ValueError("observer deactivation was not confirmed by readback")
        _record(audit, now(), "result", step="deactivate", outcome="suspended", **common)
    return {"schema_version": "1.0.0", "operation": "deactivate", "state": "installed_suspended"}


def _remove_owned_resources(
    transport: KubeTransport, inputs: ObserverInstallationInput
) -> list[str]:
    """Delete only this observer's labeled resources, in reverse dependency order."""
    targets: list[tuple[str, str, str | None]] = [
        (kind, inputs.name, None if kind in _CLUSTER_SCOPED else inputs.namespace)
        for kind in _ROLLBACK_ORDER
    ]
    targets.append(("Secret", inputs.material_secret, inputs.namespace))
    removed: list[str] = []
    for kind, name, namespace in targets:
        live = _get(transport, kind, name, namespace)
        if live is None:
            continue
        if live.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/instance") != (
            inputs.name
        ):
            raise ValueError(f"{kind} {name} is not owned by this observer; rollback stopped")
        args = ["delete", kind.lower(), name, "--ignore-not-found", "--wait=false"]
        if namespace is not None:
            args += ["--namespace", namespace]
        _checked(transport.run(args, manifest=None, timeout=90), f"deleting {kind} failed")
        removed.append(kind)
    return removed


def rollback_observer_installation(
    inputs: ObserverInstallationInput,
    approval: ObserverApplyApproval,
    *,
    transport: KubeTransport,
    lock_directory: Path,
    audit: Audit,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Delete only this installer's labeled observer resources; the namespace is retained."""
    _authorize(approval, operation="rollback", inputs=inputs, rendered=None, now=now())
    common: dict[str, object] = {
        "operation": "rollback",
        "target_ref": inputs.target_ref,
        "executor": transport.name,
        "approver_ref": approval.approver_ref,
    }
    with target_lock(lock_directory, f"{inputs.target_ref}/{inputs.namespace}/{inputs.name}"):
        _cluster_identity(transport, approval.cluster_uid)
        _record(audit, now(), "intent", step="rollback", **common)
        removed = _remove_owned_resources(transport, inputs)
        _record(audit, now(), "result", step="rollback", outcome="removed", **common)
    return {
        "schema_version": "1.0.0",
        "operation": "rollback",
        "state": "removed",
        "removed": removed,
        "namespace_retained": True,
    }


async def await_first_observation(
    observing: Callable[[str], Awaitable[bool]],
    target_ref: str,
    *,
    timeout_s: float,
    interval_s: float,
    sleep: Callable[[float], Awaitable[None]],
    monotonic: Callable[[], float],
) -> bool:
    """Wait for the gateway's authenticated fresh snapshot; this is the effect observation."""
    deadline = monotonic() + timeout_s
    while True:
        if await observing(target_ref):
            return True
        if monotonic() + interval_s > deadline:
            return False
        await sleep(interval_s)


__all__ = [
    "AksRunCommandTransport",
    "KubeResult",
    "KubeTransport",
    "KubectlTransport",
    "ObserverApplyApproval",
    "activate_observer",
    "apply_observer_installation",
    "deactivate_observer",
    "await_first_observation",
    "rollback_observer_installation",
    "target_lock",
]
