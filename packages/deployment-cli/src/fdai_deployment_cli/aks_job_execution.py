"""Materialize exact, replay-safe AKS Jobs from reviewed CronJob templates."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_IMAGE = re.compile(r"^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$")
_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_MAX_ACTIVE_DEADLINE_SECONDS = 1_800
_SENSITIVE_ENVIRONMENT_MARKERS = ("KEY", "PASSWORD", "SECRET", "TOKEN")
_CONTROLLED_LABEL_PREFIXES = (
    "app.kubernetes.io/",
    "azure.workload.identity/",
    "fdai.io/",
)
_SERVER_ANNOTATIONS = frozenset({"batch.kubernetes.io/job-tracking"})


@dataclass(frozen=True, slots=True)
class AksOneShotJob:
    """One immutable Job derived from a reviewed AKS CronJob."""

    name: str
    execution_digest: str
    manifest: dict[str, Any]


def protected_cronjob_template_digest(
    scheduled_job: object,
    *,
    template_name: str,
    namespace: str,
    source_revision: str,
) -> str:
    """Derive the complete controlled CronJob contract from protected Terraform input."""

    if (
        _DNS_LABEL.fullmatch(template_name) is None
        or _DNS_LABEL.fullmatch(namespace) is None
        or _SOURCE_REVISION.fullmatch(source_revision) is None
    ):
        raise ValueError("protected AKS CronJob identity is invalid")
    value = _mapping(scheduled_job, "protected AKS scheduled job")
    component = _required_text(value, "component", "protected AKS Job component")
    image = _required_text(value, "image", "protected AKS Job image")
    command = _text_sequence(value.get("command"), "protected AKS Job command", required=True)
    args = _text_sequence(value.get("args", []), "protected AKS Job arguments")
    schedule = _required_text(value, "schedule", "protected AKS Job schedule")
    suspend = value.get("suspend", False)
    deadline = _strict_integer(value.get("deadline_seconds"), "protected AKS Job deadline")
    retry_limit = _strict_integer(value.get("retry_limit"), "protected AKS Job retry limit")
    cpu = _required_text(value, "cpu", "protected AKS Job CPU")
    memory = _required_text(value, "memory", "protected AKS Job memory")
    environment = _string_mapping(value.get("environment"), "protected AKS Job environment")
    secret_environment = _string_mapping(
        value.get("secret_environment", {}),
        "protected AKS Job secret environment",
    )
    env_from = value.get("env_from", [])
    if not isinstance(env_from, list) or any(
        not isinstance(item, dict) or any(not isinstance(key, str) for key in item)
        for item in env_from
    ):
        raise ValueError("protected AKS Job envFrom contract is invalid")
    protected_env_from = copy.deepcopy(env_from)
    if (
        _DNS_LABEL.fullmatch(component) is None
        or _IMAGE.fullmatch(image) is None
        or not isinstance(suspend, bool)
        or not 1 <= deadline <= _MAX_ACTIVE_DEADLINE_SECONDS
        or not 0 <= retry_limit <= 10
        or not _safe_argument(schedule)
        or not _safe_argument(cpu)
        or not _safe_argument(memory)
        or any(_ENVIRONMENT_NAME.fullmatch(name) is None for name in environment)
        or any(_ENVIRONMENT_NAME.fullmatch(name) is None for name in secret_environment)
        or set(environment) & set(secret_environment)
    ):
        raise ValueError("protected AKS scheduled job contract is invalid")
    labels = {
        "app.kubernetes.io/name": template_name,
        "app.kubernetes.io/component": component,
        "app.kubernetes.io/managed-by": "terraform",
        "fdai.io/runtime": "aks",
        "fdai.io/source-commit": source_revision,
    }
    pod_labels = {**labels, "azure.workload.identity/use": "true"}
    environment_entries: list[dict[str, Any]] = [
        {"name": name, "value": environment[name]} for name in sorted(environment)
    ]
    environment_entries.extend(
        {
            "name": name,
            "valueFrom": {
                "secretKeyRef": {
                    "name": f"{template_name}-job",
                    "key": name,
                }
            },
        }
        for name in sorted(secret_environment)
    )
    environment_entries.sort(key=lambda entry: str(entry["name"]))
    has_secrets = bool(secret_environment)
    contract = {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {
            "name": template_name,
            "namespace": namespace,
            "labels": labels,
            "annotations": {},
        },
        "spec": {
            "schedule": schedule,
            "timeZone": None,
            "suspend": suspend,
            "concurrencyPolicy": "Forbid",
            "startingDeadlineSeconds": None,
            "successfulJobsHistoryLimit": 3,
            "failedJobsHistoryLimit": 3,
            "jobTemplate": {
                "metadata": {"labels": labels, "annotations": {}},
                "spec": {
                    "completions": 1,
                    "parallelism": 1,
                    "backoffLimit": retry_limit,
                    "activeDeadlineSeconds": deadline,
                    "ttlSecondsAfterFinished": 3600,
                    "completionMode": "NonIndexed",
                    "backoffLimitPerIndex": None,
                    "maxFailedIndexes": None,
                    "podFailurePolicy": None,
                    "template": {
                        "metadata": {"labels": pod_labels, "annotations": {}},
                        "spec": {
                            "serviceAccountName": f"{template_name}-job",
                            "automountServiceAccountToken": True,
                            "restartPolicy": "Never",
                            "nodeSelector": {"fdai.io/pool": "runtime"},
                            "securityContext": {
                                "runAsNonRoot": True,
                                "seccompProfile": {"type": "RuntimeDefault"},
                            },
                            "containers": [
                                {
                                    "name": template_name,
                                    "image": image,
                                    "imagePullPolicy": "IfNotPresent",
                                    "command": command,
                                    "args": args,
                                    "env": environment_entries,
                                    "envFrom": protected_env_from,
                                    "resources": {
                                        "requests": {"cpu": cpu, "memory": memory},
                                        "limits": {"cpu": cpu, "memory": memory},
                                    },
                                    "securityContext": {
                                        "allowPrivilegeEscalation": False,
                                        "runAsNonRoot": True,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                    "volumeMounts": (
                                        [
                                            {
                                                "name": "secrets",
                                                "mountPath": "/mnt/secrets-store",
                                                "readOnly": True,
                                            }
                                        ]
                                        if has_secrets
                                        else []
                                    ),
                                    "volumeDevices": [],
                                    "resizePolicy": [],
                                    "restartPolicy": None,
                                    "restartPolicyRules": None,
                                    "workingDir": None,
                                    "ports": [],
                                    "livenessProbe": None,
                                    "readinessProbe": None,
                                    "startupProbe": None,
                                    "lifecycle": None,
                                    "terminationMessagePath": "/dev/termination-log",
                                    "terminationMessagePolicy": "File",
                                    "stdin": False,
                                    "stdinOnce": False,
                                    "tty": False,
                                }
                            ],
                            "initContainers": [],
                            "volumes": (
                                [
                                    {
                                        "name": "secrets",
                                        "csi": {
                                            "driver": "secrets-store.csi.k8s.io",
                                            "readOnly": True,
                                            "volumeAttributes": {
                                                "secretProviderClass": f"{template_name}-job"
                                            },
                                        },
                                    }
                                ]
                                if has_secrets
                                else []
                            ),
                            "affinity": None,
                            "tolerations": [],
                            "topologySpreadConstraints": [],
                            "hostNetwork": None,
                            "hostPID": None,
                            "hostIPC": None,
                            "runtimeClassName": None,
                            "priorityClassName": None,
                            "imagePullSecrets": [],
                        },
                    },
                },
            },
        },
    }
    return _digest(contract)


def materialize_cronjob_execution(
    cronjob: object,
    *,
    purpose: str,
    source_revision: str,
    target_binding: str,
    expected_template_name: str,
    expected_container_name: str,
    expected_image: str,
    expected_command: tuple[str, ...],
    expected_service_account: str,
    args: tuple[str, ...],
    environment: Mapping[str, str] | None = None,
    require_suspended: bool | None = None,
    protected_template_digest: str,
    protected_identity_binding_digest: str,
) -> AksOneShotJob:
    """Derive one content-addressed Job without copying credential values."""

    _validate_identity(
        purpose=purpose,
        source_revision=source_revision,
        target_binding=target_binding,
        expected_template_name=expected_template_name,
        expected_container_name=expected_container_name,
        expected_image=expected_image,
        expected_command=expected_command,
        expected_service_account=expected_service_account,
        args=args,
    )
    overrides = dict(environment or {})
    _validate_environment(overrides)
    value = _mapping(cronjob, "AKS CronJob")
    if value.get("apiVersion") != "batch/v1" or value.get("kind") != "CronJob":
        raise ValueError("AKS one-shot source MUST be one batch/v1 CronJob")
    if (
        _DIGEST.fullmatch(protected_template_digest) is None
        or _DIGEST.fullmatch(protected_identity_binding_digest) is None
        or _digest(_cronjob_contract(value)) != protected_template_digest
    ):
        raise ValueError("AKS one-shot CronJob differs from the protected template digest")
    metadata = _mapping(value.get("metadata"), "AKS CronJob metadata")
    namespace = metadata.get("namespace")
    if metadata.get("name") != expected_template_name or not isinstance(namespace, str):
        raise ValueError("AKS one-shot CronJob identity differs from the reviewed template")
    if _DNS_LABEL.fullmatch(namespace) is None:
        raise ValueError("AKS one-shot CronJob namespace is invalid")
    labels = _string_mapping(metadata.get("labels"), "AKS CronJob labels")
    if labels.get("fdai.io/source-commit") != source_revision:
        raise ValueError("AKS one-shot CronJob source revision is not exact")

    cron_spec = _mapping(value.get("spec"), "AKS CronJob spec")
    if require_suspended is not None and cron_spec.get("suspend", False) is not require_suspended:
        raise ValueError("AKS one-shot CronJob suspension contract changed")
    job_template = _mapping(cron_spec.get("jobTemplate"), "AKS CronJob Job template")
    template_metadata = _mapping(job_template.get("metadata"), "AKS CronJob Job template metadata")
    template_labels = _string_mapping(
        template_metadata.get("labels"), "AKS CronJob Job template labels"
    )
    if template_labels.get("fdai.io/source-commit") != source_revision:
        raise ValueError("AKS one-shot Job template source revision is not exact")
    job_spec = copy.deepcopy(_mapping(job_template.get("spec"), "AKS CronJob Job spec"))
    _validate_job_bounds(job_spec)
    pod_template = _mapping(job_spec.get("template"), "AKS one-shot Pod template")
    pod_metadata = _mapping(pod_template.get("metadata"), "AKS one-shot Pod metadata")
    pod_labels = _string_mapping(pod_metadata.get("labels"), "AKS one-shot Pod labels")
    if pod_labels.get("fdai.io/source-commit") != source_revision:
        raise ValueError("AKS one-shot Pod source revision is not exact")
    pod_spec = _mapping(pod_template.get("spec"), "AKS one-shot Pod spec")
    if pod_spec.get("serviceAccountName") != expected_service_account:
        raise ValueError("AKS one-shot Job does not use the reviewed workload identity")
    containers = pod_spec.get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        raise ValueError("AKS one-shot Job MUST have exactly one container")
    container = _mapping(containers[0], "AKS one-shot container")
    if (
        container.get("name") != expected_container_name
        or container.get("image") != expected_image
        or container.get("command") != list(expected_command)
    ):
        raise ValueError("AKS one-shot container differs from the reviewed runtime contract")
    container["args"] = list(args)
    container["env"] = _environment_with_overrides(container.get("env"), overrides)
    containers[0] = container
    pod_spec["containers"] = containers
    pod_template["spec"] = pod_spec
    job_spec["template"] = pod_template

    material = {
        "purpose": purpose,
        "source_revision": source_revision,
        "target_binding": target_binding,
        "template_name": expected_template_name,
        "template_namespace": namespace,
        "protected_template_digest": protected_template_digest,
        "protected_identity_binding_digest": protected_identity_binding_digest,
        "template_spec": job_spec,
    }
    execution_digest = _digest(material)
    name = f"fdai-{purpose}-{execution_digest[:16]}"
    if len(name) > 63 or _DNS_LABEL.fullmatch(name) is None:
        raise ValueError("AKS one-shot purpose produces an invalid Job name")
    job_labels = {
        **template_labels,
        "fdai.io/one-shot": purpose,
        "fdai.io/source-commit": source_revision,
    }
    pod_metadata["labels"] = {
        **pod_labels,
        "fdai.io/one-shot": purpose,
        "fdai.io/source-commit": source_revision,
    }
    pod_template["metadata"] = pod_metadata
    job_spec["template"] = pod_template
    manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": job_labels,
            "annotations": {
                "fdai.io/execution-digest": execution_digest,
                "fdai.io/identity-binding-digest": protected_identity_binding_digest,
                "fdai.io/template-digest": protected_template_digest,
                "fdai.io/target-binding": target_binding,
            },
        },
        "spec": job_spec,
    }
    return AksOneShotJob(
        name=name,
        execution_digest=execution_digest,
        manifest=manifest,
    )


def validate_existing_job(job: object, *, expected: AksOneShotJob) -> None:
    """Fail closed unless an existing Job is the same content-addressed attempt."""

    value = _mapping(job, "existing AKS Job")
    if value.get("apiVersion") != "batch/v1" or value.get("kind") != "Job":
        raise ValueError("existing AKS one-shot object is not a batch/v1 Job")
    if aks_job_contract_digest(value) != aks_job_contract_digest(expected.manifest):
        raise ValueError("existing AKS one-shot Job controlled contract changed")


def aks_job_contract_digest(job: object) -> str:
    """Digest every controlled Job field while excluding server-owned runtime metadata."""

    value = _mapping(job, "AKS Job")
    if value.get("apiVersion") != "batch/v1" or value.get("kind") != "Job":
        raise ValueError("AKS one-shot object is not a batch/v1 Job")
    spec = _mapping(value.get("spec"), "AKS Job spec")
    _validate_job_bounds(spec)
    return _digest(_job_contract(value))


def job_terminal_state(job: object) -> Literal["running", "succeeded", "failed"]:
    """Return one bounded terminal projection from Kubernetes Job status."""

    value = _mapping(job, "AKS Job")
    status_value = value.get("status", {})
    status = _mapping(status_value, "AKS Job status")
    conditions = status.get("conditions", [])
    if not isinstance(conditions, list):
        raise ValueError("AKS Job conditions are invalid")
    complete = False
    failed = False
    for item in conditions:
        condition = _mapping(item, "AKS Job condition")
        if condition.get("status") != "True":
            continue
        if condition.get("type") == "Complete":
            complete = True
        elif condition.get("type") == "Failed":
            failed = True
    failed_count = status.get("failed", 0)
    succeeded_count = status.get("succeeded", 0)
    if (
        isinstance(failed_count, bool)
        or not isinstance(failed_count, int)
        or isinstance(succeeded_count, bool)
        or not isinstance(succeeded_count, int)
        or failed_count < 0
        or succeeded_count < 0
    ):
        raise ValueError("AKS Job counters are invalid")
    if complete and failed:
        raise ValueError("AKS Job terminal conditions conflict")
    if complete and succeeded_count == 1:
        return "succeeded"
    if complete or succeeded_count > 1:
        raise ValueError("AKS Job completion evidence is inconsistent")
    if failed:
        return "failed"
    spec_value = value.get("spec")
    if spec_value is not None:
        spec = _mapping(spec_value, "AKS Job spec")
        backoff_limit = spec.get("backoffLimit")
        if (
            isinstance(backoff_limit, bool)
            or not isinstance(backoff_limit, int)
            or backoff_limit < 0
        ):
            raise ValueError("AKS Job backoff limit is invalid")
        if failed_count > backoff_limit:
            return "failed"
    return "running"


def _cronjob_contract(value: Mapping[str, Any]) -> dict[str, object]:
    metadata = _mapping(value.get("metadata"), "AKS CronJob metadata")
    spec = _mapping(value.get("spec"), "AKS CronJob spec")
    job_template = _mapping(spec.get("jobTemplate"), "AKS CronJob Job template")
    job_metadata = _mapping(job_template.get("metadata"), "AKS CronJob Job template metadata")
    job_spec = _mapping(job_template.get("spec"), "AKS CronJob Job spec")
    return {
        "apiVersion": value.get("apiVersion"),
        "kind": value.get("kind"),
        "metadata": _top_level_metadata_contract(metadata, "AKS CronJob metadata"),
        "spec": {
            "schedule": spec.get("schedule"),
            "timeZone": spec.get("timeZone"),
            "suspend": spec.get("suspend", False),
            "concurrencyPolicy": spec.get("concurrencyPolicy"),
            "startingDeadlineSeconds": spec.get("startingDeadlineSeconds"),
            "successfulJobsHistoryLimit": spec.get("successfulJobsHistoryLimit"),
            "failedJobsHistoryLimit": spec.get("failedJobsHistoryLimit"),
            "jobTemplate": {
                "metadata": _nested_metadata_contract(
                    job_metadata, "AKS CronJob Job template metadata"
                ),
                "spec": _job_spec_contract(job_spec),
            },
        },
    }


def _job_contract(value: Mapping[str, Any]) -> dict[str, object]:
    metadata = _mapping(value.get("metadata"), "AKS Job metadata")
    spec = _mapping(value.get("spec"), "AKS Job spec")
    return {
        "apiVersion": value.get("apiVersion"),
        "kind": value.get("kind"),
        "metadata": _top_level_metadata_contract(metadata, "AKS Job metadata"),
        "spec": _job_spec_contract(spec),
    }


def _job_spec_contract(value: Mapping[str, Any]) -> dict[str, object]:
    template = _mapping(value.get("template"), "AKS Job Pod template")
    metadata = _mapping(template.get("metadata"), "AKS Job Pod metadata")
    pod_spec = _mapping(template.get("spec"), "AKS Job Pod spec")
    return {
        "completions": value.get("completions"),
        "parallelism": value.get("parallelism"),
        "backoffLimit": value.get("backoffLimit"),
        "activeDeadlineSeconds": value.get("activeDeadlineSeconds"),
        "ttlSecondsAfterFinished": value.get("ttlSecondsAfterFinished"),
        "completionMode": value.get("completionMode") or "NonIndexed",
        "backoffLimitPerIndex": value.get("backoffLimitPerIndex"),
        "maxFailedIndexes": value.get("maxFailedIndexes"),
        "podFailurePolicy": copy.deepcopy(value.get("podFailurePolicy")),
        "template": {
            "metadata": _nested_metadata_contract(metadata, "AKS Job Pod metadata"),
            "spec": _pod_spec_contract(pod_spec),
        },
    }


def _pod_spec_contract(value: Mapping[str, Any]) -> dict[str, object]:
    return {
        "serviceAccountName": value.get("serviceAccountName"),
        "automountServiceAccountToken": value.get("automountServiceAccountToken"),
        "restartPolicy": value.get("restartPolicy"),
        "nodeSelector": _optional_mapping(value.get("nodeSelector"), "AKS node selector"),
        "securityContext": _optional_mapping(
            value.get("securityContext"), "AKS Pod security context"
        ),
        "containers": [_container_contract(_only_container(value))],
        "initContainers": _object_sequence(value.get("initContainers", []), "AKS init containers"),
        "volumes": _named_object_sequence(value.get("volumes", []), "AKS volumes"),
        "affinity": copy.deepcopy(value.get("affinity")),
        "tolerations": _object_sequence(value.get("tolerations", []), "AKS tolerations"),
        "topologySpreadConstraints": _object_sequence(
            value.get("topologySpreadConstraints", []),
            "AKS topology spread constraints",
        ),
        "hostNetwork": value.get("hostNetwork"),
        "hostPID": value.get("hostPID"),
        "hostIPC": value.get("hostIPC"),
        "runtimeClassName": value.get("runtimeClassName"),
        "priorityClassName": value.get("priorityClassName"),
        "imagePullSecrets": _named_object_sequence(
            value.get("imagePullSecrets", []), "AKS image pull secrets"
        ),
    }


def _container_contract(value: Mapping[str, Any]) -> dict[str, object]:
    return {
        "name": value.get("name"),
        "image": value.get("image"),
        "imagePullPolicy": value.get("imagePullPolicy"),
        "command": _text_sequence(value.get("command", []), "AKS container command"),
        "args": _text_sequence(value.get("args", []), "AKS container arguments"),
        "env": _environment_entries(value.get("env")),
        "envFrom": _object_sequence(value.get("envFrom", []), "AKS container envFrom"),
        "resources": _optional_mapping(value.get("resources"), "AKS container resources"),
        "securityContext": _optional_mapping(
            value.get("securityContext"), "AKS container security context"
        ),
        "volumeMounts": _named_object_sequence(value.get("volumeMounts", []), "AKS volume mounts"),
        "volumeDevices": _named_object_sequence(
            value.get("volumeDevices", []), "AKS volume devices"
        ),
        "resizePolicy": _object_sequence(
            value.get("resizePolicy", []), "AKS container resize policy"
        ),
        "restartPolicy": value.get("restartPolicy"),
        "restartPolicyRules": copy.deepcopy(value.get("restartPolicyRules")),
        "workingDir": value.get("workingDir"),
        "ports": _object_sequence(value.get("ports", []), "AKS container ports"),
        "livenessProbe": copy.deepcopy(value.get("livenessProbe")),
        "readinessProbe": copy.deepcopy(value.get("readinessProbe")),
        "startupProbe": copy.deepcopy(value.get("startupProbe")),
        "lifecycle": copy.deepcopy(value.get("lifecycle")),
        "terminationMessagePath": _defaulted(
            value, "terminationMessagePath", "/dev/termination-log"
        ),
        "terminationMessagePolicy": _defaulted(value, "terminationMessagePolicy", "File"),
        "stdin": _defaulted(value, "stdin", False),
        "stdinOnce": _defaulted(value, "stdinOnce", False),
        "tty": _defaulted(value, "tty", False),
    }


def _top_level_metadata_contract(value: Mapping[str, Any], label: str) -> dict[str, object]:
    name = value.get("name")
    namespace = value.get("namespace")
    if not isinstance(name, str) or not isinstance(namespace, str):
        raise ValueError(f"{label} identity is invalid")
    return {
        "name": name,
        "namespace": namespace,
        **_nested_metadata_contract(value, label),
    }


def _nested_metadata_contract(value: Mapping[str, Any], label: str) -> dict[str, object]:
    labels = _string_mapping(value.get("labels", {}), f"{label} labels")
    annotations = _string_mapping(value.get("annotations", {}), f"{label} annotations")
    return {
        "labels": {
            key: labels[key] for key in sorted(labels) if key.startswith(_CONTROLLED_LABEL_PREFIXES)
        },
        "annotations": {
            key: annotations[key] for key in sorted(annotations) if key not in _SERVER_ANNOTATIONS
        },
    }


def _environment_entries(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("AKS one-shot container environment MUST be an array")
    entries: dict[str, dict[str, Any]] = {}
    for item in value:
        entry = copy.deepcopy(_mapping(item, "AKS one-shot environment entry"))
        name = entry.get("name")
        if (
            not isinstance(name, str)
            or _ENVIRONMENT_NAME.fullmatch(name) is None
            or name in entries
        ):
            raise ValueError("AKS one-shot container environment is invalid")
        entries[name] = entry
    return [entries[name] for name in sorted(entries)]


def _named_object_sequence(value: object, label: str) -> list[object]:
    items = _object_sequence(value, label)
    named: dict[str, object] = {}
    for item in items:
        mapping = _mapping(item, f"{label} entry")
        name = mapping.get("name")
        if not isinstance(name, str) or not name or name in named:
            raise ValueError(f"{label} is invalid")
        named[name] = mapping
    return [named[name] for name in sorted(named)]


def _object_sequence(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} MUST be an array")
    return copy.deepcopy(value)


def _optional_mapping(value: object, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return copy.deepcopy(_mapping(value, label))


def _required_text(value: Mapping[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not _safe_argument(item):
        raise ValueError(f"{label} is invalid")
    return item


def _text_sequence(value: object, label: str, *, required: bool = False) -> list[str]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or any(not isinstance(item, str) or not _safe_argument(item) for item in value)
        or (required and not value)
    ):
        raise ValueError(f"{label} is invalid")
    return list(value)


def _strict_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} is invalid")
    return value


def _defaulted(value: Mapping[str, Any], key: str, default: object) -> object:
    return value[key] if key in value else default


def _validate_identity(
    *,
    purpose: str,
    source_revision: str,
    target_binding: str,
    expected_template_name: str,
    expected_container_name: str,
    expected_image: str,
    expected_command: tuple[str, ...],
    expected_service_account: str,
    args: tuple[str, ...],
) -> None:
    for value, label in (
        (purpose, "purpose"),
        (expected_template_name, "template name"),
        (expected_container_name, "container name"),
        (expected_service_account, "service account"),
    ):
        if _DNS_LABEL.fullmatch(value) is None:
            raise ValueError(f"AKS one-shot {label} is invalid")
    if _SOURCE_REVISION.fullmatch(source_revision) is None:
        raise ValueError("AKS one-shot source revision MUST be an exact git SHA")
    if _DIGEST.fullmatch(target_binding) is None:
        raise ValueError("AKS one-shot target binding MUST be SHA-256")
    if _IMAGE.fullmatch(expected_image) is None:
        raise ValueError("AKS one-shot image MUST be digest-pinned")
    if not expected_command or any(not _safe_argument(value) for value in expected_command):
        raise ValueError("AKS one-shot command is invalid")
    if any(not _safe_argument(value) for value in args):
        raise ValueError("AKS one-shot arguments are invalid")


def _validate_environment(environment: Mapping[str, str]) -> None:
    for name, value in environment.items():
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or not name
            or not _safe_environment_value(value)
            or any(marker in name.upper() for marker in _SENSITIVE_ENVIRONMENT_MARKERS)
        ):
            raise ValueError("AKS one-shot environment overrides MUST be non-secret text")


def _validate_job_bounds(job_spec: dict[str, Any]) -> None:
    deadline = job_spec.get("activeDeadlineSeconds")
    if (
        isinstance(deadline, bool)
        or not isinstance(deadline, int)
        or not 1 <= deadline <= _MAX_ACTIVE_DEADLINE_SECONDS
        or job_spec.get("completions") != 1
        or job_spec.get("parallelism") != 1
    ):
        raise ValueError("AKS one-shot Job bounds differ from the reviewed contract")


def _environment_with_overrides(
    value: object,
    overrides: Mapping[str, str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("AKS one-shot container environment MUST be an array")
    retained: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        environment = copy.deepcopy(_mapping(item, "AKS one-shot environment entry"))
        name = environment.get("name")
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError("AKS one-shot container environment is invalid")
        seen.add(name)
        if name not in overrides:
            retained.append(environment)
    retained.extend({"name": name, "value": overrides[name]} for name in sorted(overrides))
    retained.sort(key=lambda entry: str(entry["name"]))
    return retained


def _only_container(pod_spec: Mapping[str, Any]) -> dict[str, Any]:
    containers = pod_spec.get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        raise ValueError("AKS one-shot Job MUST have exactly one container")
    return _mapping(containers[0], "AKS one-shot container")


def _safe_argument(value: str) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 4_096
        and "\x00" not in value
        and "\r" not in value
        and "\n" not in value
    )


def _safe_environment_value(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 4_096
        and "\x00" not in value
        and "\r" not in value
        and "\n" not in value
    )


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} MUST be an object")
    return {str(key): item for key, item in value.items()}


def _string_mapping(value: object, label: str) -> dict[str, str]:
    mapping = _mapping(value, label)
    if any(not isinstance(item, str) for item in mapping.values()):
        raise ValueError(f"{label} MUST contain string values")
    return {key: str(item) for key, item in mapping.items()}


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "AksOneShotJob",
    "aks_job_contract_digest",
    "job_terminal_state",
    "materialize_cronjob_execution",
    "protected_cronjob_template_digest",
    "validate_existing_job",
]
