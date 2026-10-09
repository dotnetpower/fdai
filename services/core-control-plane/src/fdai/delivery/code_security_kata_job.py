"""Credential-free per-scanner Kata Jobs, with completion observed outside the scanner VM."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from fdai.delivery.code_security_prepared_source import source_tree_digest
from fdai.delivery.kubernetes_quantity import parse_resource_quantity
from fdai.rule_catalog.code_security_scanners import ScannerSpec, resolve_argv

_NAME = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")
_IMAGE = re.compile(r"^[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}$")
_RUNTIME = "kata-vm-isolation"


@dataclass(frozen=True, slots=True)
class KataScanConfig:
    namespace: str
    image: str
    source_pvc: str
    source_mount: Path
    cache_pvc: str | None = None
    cache_subpath: str = "cache"
    network_policy: str = "fdai-code-security-deny-all"
    rules_subpath: str | None = None
    cache_mount: Path | None = None

    def __post_init__(self) -> None:
        if any(
            _NAME.fullmatch(value) is None
            for value in (
                self.namespace,
                self.source_pvc,
                self.network_policy,
            )
        ):
            raise ValueError("Kata namespace, PVC and network policy must be DNS labels")
        if self.cache_pvc is not None and _NAME.fullmatch(self.cache_pvc) is None:
            raise ValueError("Kata cache PVC must be a DNS label")
        if _IMAGE.fullmatch(self.image) is None:
            raise ValueError("Kata scanner image must be pinned by SHA-256 digest")
        if not self.source_mount.is_absolute():
            raise ValueError("Kata source mount must be absolute")
        _subpath(self.cache_subpath)
        if self.rules_subpath is not None:
            _subpath(self.rules_subpath)


def _subpath(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part == ".." for part in path.parts):
        raise ValueError("Kata volume subpath must be relative and cannot traverse")
    return path.as_posix()


def build_scanner_job(
    config: KataScanConfig,
    scanner_id: str,
    spec: ScannerSpec,
    executable: Path,
    source: Path,
    job_name: str,
) -> dict[str, object]:
    """Run only an image-owned binary, with read-only input and no identity/secret mounts.

    Kata supplies the outer kernel isolation. Scanners run directly, avoiding nested namespaces
    and retaining RuntimeDefault seccomp rather than requesting an Unconfined profile.
    """
    if _NAME.fullmatch(job_name) is None:
        raise ValueError("Kata job name is invalid")
    if executable.parent != Path("/opt/scanners/bin") or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,63}", executable.name
    ):
        raise ValueError("Kata executable must be an image-owned scanner")
    try:
        relative_source = source.resolve().relative_to(config.source_mount.resolve())
    except ValueError as exc:
        raise ValueError("Kata source must be within its shared source PVC mount") from exc
    source_subpath = _subpath(relative_source.as_posix())
    mounts: list[dict[str, object]] = [
        {"name": "source", "mountPath": "/source", "subPath": source_subpath, "readOnly": True},
        {"name": "scratch", "mountPath": "/scratch"},
        {"name": "tmp", "mountPath": "/tmp"},  # noqa: S108 - private per-pod emptyDir
    ]
    volumes: list[dict[str, object]] = [
        {
            "name": "source",
            "persistentVolumeClaim": {
                "claimName": config.source_pvc,
                "readOnly": True,
            },
        },
        {"name": "scratch", "emptyDir": {"sizeLimit": "1Gi"}},
        {"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}},
    ]
    if "rules" in spec.mounts:
        if config.rules_subpath is None:
            raise ValueError("Kata scanner requires a digest-bound read-only rule-pack handoff")
        mounts.append(
            {
                "name": "source",
                "mountPath": "/rules",
                "subPath": config.rules_subpath,
                "readOnly": True,
            }
        )
    if "cache" in spec.mounts:
        if config.cache_pvc is None or config.cache_mount is None:
            raise ValueError("Kata scanner requires a bound read-only cache PVC and snapshot mount")
        mounts.append(
            {
                "name": "cache",
                "mountPath": "/cache",
                "subPath": config.cache_subpath,
                "readOnly": True,
            }
        )
        volumes.append(
            {
                "name": "cache",
                "persistentVolumeClaim": {
                    "claimName": config.cache_pvc,
                    "readOnly": True,
                },
            }
        )
    environment = [
        {"name": "HOME", "value": "/scratch"},
        {"name": "TMPDIR", "value": "/tmp"},  # noqa: S108 - private per-pod emptyDir
        {"name": "PATH", "value": "/usr/bin:/bin"},
    ]
    if spec.cache_env:
        environment.append({"name": spec.cache_env, "value": "/cache"})
    memory = spec.address_space_bytes or 4 * 1024**3
    rule_digest = (
        source_tree_digest(config.source_mount / config.rules_subpath)
        if "rules" in spec.mounts and config.rules_subpath is not None
        else ""
    )
    cache_digest = (
        source_tree_digest(config.cache_mount)
        if "cache" in spec.mounts and config.cache_mount is not None
        else ""
    )
    container = {
        "name": "scanner",
        "image": config.image,
        "command": [
            "/bin/sh",
            "-c",
            "/app/.venv/bin/fdai-code-security verify-scanner-input "
            '--path /source --tree-digest "$1" >/dev/null || exit 126; '
            'if [ -n "$2" ]; then /app/.venv/bin/fdai-code-security verify-scanner-input '
            '--path /rules --tree-digest "$2" >/dev/null || exit 126; fi; '
            'if [ -n "$3" ]; then /app/.venv/bin/fdai-code-security verify-scanner-input '
            '--path /cache --tree-digest "$3" >/dev/null || exit 126; fi; '
            'shift 3; exec "$@" 2>/scratch/scanner.stderr',
            "fdai-scanner",
        ],
        "args": [
            source_tree_digest(source),
            rule_digest,
            cache_digest,
            executable.as_posix(),
            *resolve_argv(
                spec,
                {
                    "source": "/source",
                    "rules": "/rules",
                    "cache": "/cache",
                },
            ),
        ],
        "workingDir": "/scratch",
        "env": environment,
        "volumeMounts": mounts,
        "securityContext": {
            "runAsNonRoot": True,
            "runAsUser": 65532,
            "runAsGroup": 65532,
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "resources": {
            "requests": {"cpu": "1", "memory": str(memory)},
            "limits": {"cpu": "2", "memory": str(memory)},
        },
    }
    pod_spec = {
        "runtimeClassName": _RUNTIME,
        "automountServiceAccountToken": False,
        "restartPolicy": "Never",
        "hostNetwork": False,
        "hostPID": False,
        "hostIPC": False,
        "containers": [container],
        "volumes": volumes,
        "nodeSelector": {"fdai.io/code-security-scanner": "true"},
        "tolerations": [
            {
                "key": "fdai.io/code-security-scanner",
                "operator": "Equal",
                "value": "true",
                "effect": "NoSchedule",
            }
        ],
    }
    binding = hashlib.sha256(
        json.dumps(pod_spec, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": config.namespace,
            "labels": {"app.kubernetes.io/name": "fdai-code-security-scanner"},
            "annotations": {"fdai.io/scanner-binding": binding, "fdai.io/scanner-id": scanner_id},
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": spec.timeout_seconds + 300,
            "ttlSecondsAfterFinished": 3600,
            "template": {
                "metadata": {
                    "labels": {"app.kubernetes.io/name": "fdai-code-security-scanner"},
                },
                "spec": pod_spec,
            },
        },
    }


def validate_scanner_pod(expected_job: dict[str, object], pod: dict[str, object], uid: str) -> None:
    """Reject an observed pod that differs from the authorized job's isolation contract."""
    metadata, actual = pod.get("metadata"), pod.get("spec")
    if not isinstance(metadata, dict) or not isinstance(actual, dict):
        raise ValueError("Kata pod has no identity or execution contract")
    owners = metadata.get("ownerReferences")
    if not isinstance(owners, list) or not any(
        isinstance(owner, dict) and owner.get("uid") == uid and owner.get("controller") is True
        for owner in owners
    ):
        raise ValueError("Kata pod is not owned by the observed Job UID")
    spec = expected_job["spec"]
    if not isinstance(spec, dict):
        raise ValueError("expected scanner Job spec is invalid")
    template = spec["template"]
    if not isinstance(template, dict):
        raise ValueError("expected scanner Job template is invalid")
    expected = template["spec"]
    if not isinstance(expected, dict):
        raise ValueError("expected scanner pod spec is invalid")
    if any(
        (
            actual.get(key, False)
            if key in {"hostNetwork", "hostPID", "hostIPC"}
            else actual.get(key)
        )
        != expected[key]
        for key in (
            "runtimeClassName",
            "automountServiceAccountToken",
            "restartPolicy",
            "hostNetwork",
            "hostPID",
            "hostIPC",
        )
    ):
        raise ValueError("Kata pod isolation contract changed")
    if actual.get("initContainers") or actual.get("ephemeralContainers"):
        raise ValueError("Kata scanner pod cannot gain additional containers")
    containers = actual.get("containers")
    desired = expected["containers"]
    if not isinstance(desired, list) or len(desired) != 1 or not isinstance(desired[0], dict):
        raise ValueError("expected scanner container contract is invalid")
    if (
        not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(containers[0], dict)
    ):
        raise ValueError("Kata scanner container identity changed")
    container = containers[0]
    for key in ("name", "image", "command", "args", "env", "volumeMounts", "securityContext"):
        if container.get(key) != desired[0][key]:
            raise ValueError("Kata scanner command, mounts or privilege contract changed")
    if actual.get("volumes") != expected["volumes"] or container.get("envFrom"):
        raise ValueError("Kata scanner cannot receive unbound volumes or credentials")
    selectors = actual.get("nodeSelector")
    if not isinstance(selectors, dict) or selectors.get("fdai.io/code-security-scanner") != "true":
        raise ValueError("Kata scanner must remain bound to its dedicated node pool")
    resources = container.get("resources")
    expected_resources = desired[0].get("resources")
    if not isinstance(resources, dict) or not isinstance(expected_resources, dict):
        raise ValueError("Kata scanner resource constraints are missing")
    for category in ("limits", "requests"):
        values, expected_values = resources.get(category), expected_resources.get(category)
        if not isinstance(values, dict) or not isinstance(expected_values, dict):
            raise ValueError("Kata scanner resource constraints are missing")
        for key in ("cpu", "memory"):
            if parse_resource_quantity(values.get(key)) != parse_resource_quantity(
                expected_values.get(key)
            ):
                raise ValueError("Kata scanner resource constraints changed")


def validate_deny_all_policy(policy: dict[str, object]) -> None:
    spec = policy.get("spec")
    if not isinstance(spec, dict) or (
        spec.get("podSelector") != {}
        or set(spec.get("policyTypes", [])) != {"Ingress", "Egress"}
        or spec.get("ingress", []) != []
        or spec.get("egress", []) != []
    ):
        raise ValueError("Kata scanner namespace requires an enforced deny-all network policy")
