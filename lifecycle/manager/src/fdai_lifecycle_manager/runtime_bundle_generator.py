"""Generate private Hub runtime bundles and native scopes from AKS workload maps."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.lifecycle_native import NativeScope
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_lifecycle_agent.runtime_bundle import RuntimeBundle, RuntimeObject
from pydantic import BaseModel, ConfigDict, Field

_IMAGE = re.compile(r"^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}\Z", re.ASCII)
_MEMORY_GI = re.compile(r"^([1-9][0-9]*)Gi\Z", re.ASCII)
_MEMORY_MI = re.compile(r"^([1-9][0-9]*)Mi\Z", re.ASCII)
_CPU_CORES = re.compile(r"^([1-9][0-9]*)\Z", re.ASCII)
_CPU_MILLIS = re.compile(r"^([1-9][0-9]*)m\Z", re.ASCII)
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}\Z", re.ASCII)
_KV_SECRET_NAME = re.compile(r"^[A-Za-z0-9-]{1,127}\Z", re.ASCII)
_CANARY_UID_FIELD = "metadata.labels['batch.kubernetes.io/controller-uid']"


class PreExistingReferences(BaseModel):
    """Pre-existing Kubernetes and CSI objects required before bundle application."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    service_accounts: tuple[str, ...]
    secret_provider_classes: tuple[str, ...]
    config_maps: tuple[str, ...]
    secrets: tuple[str, ...]
    config_map_data: dict[str, dict[str, str]] = Field(repr=False)
    secret_bindings: dict[str, dict[str, str]] = Field(repr=False)
    identity_bindings: dict[str, dict[str, Any]] = Field(repr=False)


class GeneratedRuntimeTopology(BaseModel):
    """Complete private runtime bundle, component images, native scope, and prerequisites."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    bundle: RuntimeBundle
    component_images: dict[str, str]
    native_scope: NativeScope
    prerequisites: PreExistingReferences

    @property
    def digest(self) -> str:
        return "sha256:" + canonical_digest(
            {
                "bundle_digest": self.bundle.digest,
                "native_scope_digest": self.native_scope.digest,
                "component_images": self.component_images,
                "prerequisites": self.prerequisites.model_dump(mode="json"),
            }
        )


def _require_str(mapping: Mapping[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}.{key} must be a non-empty string.")
    return value


def _require_int(
    mapping: Mapping[str, Any],
    key: str,
    label: str,
    *,
    default: int | None = None,
    minimum: int = 1,
    maximum: int = 2**31 - 1,
) -> int:
    value = mapping.get(key, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label}.{key} must be an integer between {minimum} and {maximum}.")
    return value


def _require_mapping(mapping: Mapping[str, Any], key: str, label: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}.{key} must be a mapping.")
    return value


def _normalize_cpu(value: str) -> str:
    if _CPU_MILLIS.fullmatch(value):
        return value
    match = _CPU_CORES.fullmatch(value)
    if match is not None:
        return f"{int(match.group(1)) * 1000}m"
    raise ValueError(f"Unsupported CPU quantity: {value}")


def _normalize_memory(value: str) -> str:
    if _MEMORY_MI.fullmatch(value):
        return value
    match = _MEMORY_GI.fullmatch(value)
    if match is not None:
        return f"{int(match.group(1)) * 1024}Mi"
    raise ValueError(f"Unsupported memory quantity: {value}")


def _validate_image(image: object, label: str) -> str:
    if not isinstance(image, str) or not _IMAGE.fullmatch(image):
        raise ValueError(f"{label} requires a digest-pinned image reference.")
    return image


def _record_component_image(
    component_images: dict[str, str],
    component: str,
    image: str,
) -> None:
    existing = component_images.get(component)
    if existing is not None and existing != image:
        raise ValueError(f"Component {component} has conflicting image digests.")
    component_images[component] = image


def _validate_and_record_identity(
    spec: Mapping[str, Any],
    sa_name: str,
    label: str,
    identity_bindings: dict[str, dict[str, Any]],
) -> None:
    client_id = _require_str(spec, "identity_client_id", label)
    resource_id = _require_str(spec, "identity_resource_id", label)
    raw_extra = spec.get("additional_identities") or {}
    if not isinstance(raw_extra, Mapping):
        raise ValueError(f"{label}.additional_identities must be a mapping.")
    extra: dict[str, dict[str, str]] = {}
    for extra_name in sorted(raw_extra):
        extra_spec = raw_extra[extra_name]
        if not isinstance(extra_spec, Mapping):
            raise ValueError(f"{label}.additional_identities.{extra_name} must be a mapping.")
        extra[str(extra_name)] = {
            "client_id": _require_str(extra_spec, "client_id", f"{label}.{extra_name}"),
            "resource_id": _require_str(extra_spec, "resource_id", f"{label}.{extra_name}"),
        }
    identity_bindings[sa_name] = {
        "client_id": client_id,
        "resource_id": resource_id,
        **({"additional_identities": extra} if extra else {}),
    }


def _validate_env_contracts(
    *,
    label: str,
    component: str,
    environment: Mapping[str, Any],
    secret_environment: Mapping[str, Any],
    field_environment: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    env_out: dict[str, str] = {}
    for key, val in sorted(environment.items()):
        if not isinstance(key, str) or not _ENV_NAME.fullmatch(key) or not isinstance(val, str):
            raise ValueError(f"{label} environment entry {key!r} is invalid.")
        env_out[key] = val
    sec_out: dict[str, str] = {}
    for key, val in sorted(secret_environment.items()):
        if (
            not isinstance(key, str)
            or not _ENV_NAME.fullmatch(key)
            or not isinstance(val, str)
            or not _KV_SECRET_NAME.fullmatch(val)
        ):
            raise ValueError(f"{label} secret_environment entry {key!r} is invalid.")
        sec_out[key] = val
    field_out: dict[str, str] = {}
    for key, val in sorted(field_environment.items()):
        if not isinstance(key, str) or not _ENV_NAME.fullmatch(key) or not isinstance(val, str):
            raise ValueError(f"{label} field_environment entry {key!r} is invalid.")
        field_out[key] = val
    if field_out and (
        component != "canary" or field_out != {"FDAI_CANARY_JOB_UID": _CANARY_UID_FIELD}
    ):
        raise ValueError(f"{label} field_environment is supported only for canary Job UID.")
    if (set(env_out) & set(sec_out)) or (set(field_out) & (set(env_out) | set(sec_out))):
        raise ValueError(f"{label} environment keys overlap across environment maps.")
    return env_out, sec_out, field_out


def _build_env_references(
    *,
    secret_ref_name: str,
    secret_environment: Mapping[str, str],
    field_environment: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    env: list[dict[str, Any]] = [
        {
            "name": env_name,
            "valueFrom": {
                "secretKeyRef": {"name": secret_ref_name, "key": env_name, "optional": False}
            },
        }
        for env_name in sorted(secret_environment)
    ]
    for env_name in sorted(field_environment or {}):
        env.append(
            {
                "name": env_name,
                "valueFrom": {
                    "fieldRef": {"apiVersion": "v1", "fieldPath": field_environment[env_name]}  # type: ignore[index]
                },
            }
        )
    return env


def _build_base_volumes(
    *,
    ref_name: str,
    tmp_size: str,
    has_secrets: bool,
    identity_bridge_enabled: bool,
    identity_bridge_config_map: str | None,
    identity_bridge_size_limit: str | None,
    config_maps: set[str],
    secret_provider_classes: set[str],
    secrets: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    volumes: list[dict[str, Any]] = [
        {"name": "tmp", "emptyDir": {"sizeLimit": _normalize_memory(tmp_size)}}
    ]
    mounts: list[dict[str, Any]] = [
        {"name": "tmp", "mountPath": "/tmp"}  # noqa: S108 - Pod-local emptyDir
    ]
    if identity_bridge_enabled:
        if not identity_bridge_config_map:
            raise ValueError(f"{ref_name} requires identity_bridge_config_map.")
        config_maps.add(identity_bridge_config_map)
        volumes.append(
            {
                "name": "identity-bridge",
                "configMap": {"name": identity_bridge_config_map, "defaultMode": 292},
            }
        )
        mounts.append(
            {"name": "identity-bridge", "mountPath": "/opt/fdai-compat", "readOnly": True}
        )
        if identity_bridge_size_limit is not None:
            volumes.append(
                {
                    "name": "runtime-state",
                    "emptyDir": {"sizeLimit": _normalize_memory(identity_bridge_size_limit)},
                }
            )
            mounts.append({"name": "runtime-state", "mountPath": "/app/.fdai", "readOnly": False})
    if has_secrets:
        secret_provider_classes.add(ref_name)
        secrets.add(ref_name)
        volumes.append(
            {
                "name": "secrets",
                "csi": {
                    "driver": "secrets-store.csi.k8s.io",
                    "readOnly": True,
                    "volumeAttributes": {"secretProviderClass": ref_name},
                },
            }
        )
        mounts.append({"name": "secrets", "mountPath": "/mnt/secrets-store", "readOnly": True})
    return volumes, mounts


def _build_sidecars(
    *,
    name: str,
    sidecars: Mapping[str, Any],
    component_images: dict[str, str],
    volumes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    containers: list[dict[str, Any]] = []
    init_containers: list[dict[str, Any]] = []
    for sidecar_name in sorted(sidecars):
        sc_raw = sidecars[sidecar_name]
        if not isinstance(sc_raw, Mapping):
            raise ValueError(f"workload {name}.sidecars.{sidecar_name} must be a mapping.")
        sc_label = f"sidecar {sidecar_name}"
        _record_component_image(
            component_images, sidecar_name, _validate_image(sc_raw.get("image"), sc_label)
        )
        sc_cpu = _normalize_cpu(str(sc_raw.get("cpu", "500m")))
        sc_memory = _normalize_memory(str(sc_raw.get("memory", "1Gi")))
        sc_port = _require_int(sc_raw, "port", sc_label, minimum=1, maximum=65535)
        writable = (
            _require_mapping(sc_raw, "writable_paths", sc_label)
            if "writable_paths" in sc_raw
            else {}
        )
        sc_mounts: list[dict[str, Any]] = []
        for vol_key in sorted(writable):
            vol_spec = writable[vol_key]
            if not isinstance(vol_spec, Mapping):
                raise ValueError(f"{sc_label}.writable_paths.{vol_key} must be a mapping.")
            vol_name = f"{sidecar_name}-{vol_key}"
            volumes.append(
                {
                    "name": vol_name,
                    "emptyDir": {
                        "sizeLimit": _normalize_memory(
                            _require_str(vol_spec, "size_limit", f"{sc_label}.{vol_key}")
                        )
                    },
                }
            )
            sc_mounts.append(
                {
                    "name": vol_name,
                    "mountPath": _require_str(vol_spec, "mount_path", f"{sc_label}.{vol_key}"),
                }
            )
        sc_sec: dict[str, Any] = {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
            "capabilities": {"drop": ["ALL"]},
        }
        if sc_raw.get("run_as_user") is not None:
            sc_sec["runAsUser"] = _require_int(sc_raw, "run_as_user", sc_label)
        if sc_raw.get("run_as_group") is not None:
            sc_sec["runAsGroup"] = _require_int(sc_raw, "run_as_group", sc_label)
        sc_container: dict[str, Any] = {
            "name": sidecar_name,
            "image_component": sidecar_name,
            "imagePullPolicy": "Always",
            "resources": {
                "requests": {"cpu": sc_cpu, "memory": sc_memory},
                "limits": {"cpu": sc_cpu, "memory": sc_memory},
            },
            "securityContext": sc_sec,
            "ports": [{"containerPort": sc_port, "protocol": "TCP"}],
            "readinessProbe": {
                "tcpSocket": {"port": sc_port},
                "initialDelaySeconds": 5,
                "periodSeconds": 10,
                "timeoutSeconds": 3,
                "failureThreshold": 3,
            },
            "livenessProbe": {
                "tcpSocket": {"port": sc_port},
                "initialDelaySeconds": 10,
                "periodSeconds": 30,
                "timeoutSeconds": 3,
                "failureThreshold": 3,
            },
            "volumeMounts": sc_mounts,
        }
        if sc_raw.get("command"):
            sc_container["command"] = [str(x) for x in sc_raw["command"]]
        if sc_raw.get("args"):
            sc_container["args"] = [str(x) for x in sc_raw["args"]]
        containers.append(sc_container)

        init_spec = sc_raw.get("init")
        if init_spec is not None:
            if not isinstance(init_spec, Mapping):
                raise ValueError(f"{sc_label}.init must be a mapping.")
            init_label = f"{sc_label}.init"
            writable_key = _require_str(init_spec, "writable_path", init_label)
            if writable_key not in writable:
                raise ValueError(f"{init_label}.writable_path must reference a declared volume.")
            init_cmd = list(init_spec.get("command") or [])
            if not init_cmd:
                raise ValueError(f"{init_label}.command must be non-empty.")
            init_c: dict[str, Any] = {
                "name": _require_str(init_spec, "name", init_label),
                "image_component": sidecar_name,
                "imagePullPolicy": str(init_spec.get("image_pull_policy", "Always")),
                "command": [str(x) for x in init_cmd],
                "resources": {
                    "requests": {"cpu": sc_cpu, "memory": sc_memory},
                    "limits": {"cpu": sc_cpu, "memory": sc_memory},
                },
                "securityContext": {
                    "allowPrivilegeEscalation": False,
                    "readOnlyRootFilesystem": True,
                    "runAsNonRoot": True,
                    "runAsUser": _require_int(init_spec, "run_as_user", init_label),
                    "runAsGroup": _require_int(init_spec, "run_as_group", init_label),
                    "capabilities": {"drop": ["ALL"]},
                },
                "volumeMounts": [
                    {
                        "name": f"{sidecar_name}-{writable_key}",
                        "mountPath": _require_str(init_spec, "mount_path", init_label),
                    }
                ],
            }
            if init_spec.get("args"):
                init_c["args"] = [str(x) for x in init_spec["args"]]
            init_containers.append(init_c)
    return containers, init_containers


def _build_deployment_and_service(
    *,
    name: str,
    workload: Mapping[str, Any],
    entity_id: str,
    namespace: str,
    canary_scheduled: bool,
    identity_bridge_config_map: str | None,
    identity_bridge_size_limit: str,
    component_images: dict[str, str],
    service_accounts: set[str],
    secret_provider_classes: set[str],
    config_maps: set[str],
    secrets: set[str],
    config_map_data: dict[str, dict[str, str]],
    secret_bindings: dict[str, dict[str, str]],
    identity_bindings: dict[str, dict[str, Any]],
) -> tuple[RuntimeObject, RuntimeObject]:
    label = f"workload {name}"
    _record_component_image(component_images, name, _validate_image(workload.get("image"), label))
    _validate_and_record_identity(workload, name, label, identity_bindings)
    replicas = _require_int(workload, "replicas", label, default=2, minimum=1, maximum=3)
    port = _require_int(workload, "port", label, default=8000, minimum=1, maximum=65535)
    raw_svc_port = workload.get("service_port")
    service_port = (
        port
        if raw_svc_port is None
        else _require_int(workload, "service_port", label, minimum=1, maximum=65535)
    )
    raw_env = dict(
        _require_mapping(workload, "environment", label) if "environment" in workload else {}
    )
    if name == "core-control-plane" and canary_scheduled:
        for obs_key, obs_val in (
            ("FDAI_CANARY_OBSERVER_NAMESPACE", namespace),
            ("FDAI_CANARY_OBSERVER_CRONJOB", "canary"),
        ):
            if obs_key in raw_env and raw_env[obs_key] != obs_val:
                raise ValueError(f"Core canary observer {obs_key} conflicts with namespace/job.")
            raw_env[obs_key] = obs_val
    raw_sec = (
        _require_mapping(workload, "secret_environment", label)
        if "secret_environment" in workload
        else {}
    )
    env_map, sec_map, _ = _validate_env_contracts(
        label=label,
        component=str(workload.get("component", name)),
        environment=raw_env,
        secret_environment=raw_sec,
        field_environment={},
    )
    service_accounts.add(name)
    env_cm_name = f"{name}-env"
    config_maps.add(env_cm_name)
    config_map_data[env_cm_name] = env_map
    if sec_map:
        secret_bindings[name] = sec_map
    volumes, volume_mounts = _build_base_volumes(
        ref_name=name,
        tmp_size="1Gi",
        has_secrets=bool(sec_map),
        identity_bridge_enabled=bool(workload.get("identity_bridge_enabled", False)),
        identity_bridge_config_map=identity_bridge_config_map,
        identity_bridge_size_limit=identity_bridge_size_limit,
        config_maps=config_maps,
        secret_provider_classes=secret_provider_classes,
        secrets=secrets,
    )
    cpu = _normalize_cpu(str(workload.get("cpu", "500m")))
    memory = _normalize_memory(str(workload.get("memory", "1Gi")))
    readiness_path = _require_str(workload, "readiness_path", label)
    liveness_path = str(workload.get("liveness_path", readiness_path))
    primary: dict[str, Any] = {
        "name": name,
        "image_component": name,
        "imagePullPolicy": "Always",
        "resources": {
            "requests": {"cpu": cpu, "memory": memory},
            "limits": {"cpu": cpu, "memory": memory},
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
            "capabilities": {"drop": ["ALL"]},
        },
        "ports": [{"name": "http", "containerPort": port, "protocol": "TCP"}],
        "readinessProbe": {
            "httpGet": {"path": readiness_path, "port": port, "scheme": "HTTP"},
            "initialDelaySeconds": 5,
            "periodSeconds": 10,
            "timeoutSeconds": 3,
            "failureThreshold": 3,
        },
        "livenessProbe": {
            "httpGet": {"path": liveness_path, "port": port, "scheme": "HTTP"},
            "initialDelaySeconds": 10,
            "periodSeconds": 30,
            "timeoutSeconds": 3,
            "failureThreshold": 3,
        },
        "envFrom": [{"configMapRef": {"name": env_cm_name, "optional": False}}],
        "volumeMounts": volume_mounts,
    }
    if workload.get("command"):
        primary["command"] = [str(x) for x in workload["command"]]
    if workload.get("args"):
        primary["args"] = [str(x) for x in workload["args"]]
    if sec_map:
        primary["env"] = _build_env_references(secret_ref_name=name, secret_environment=sec_map)

    sidecar_map = (
        _require_mapping(workload, "sidecars", label)
        if "sidecars" in workload and workload["sidecars"] is not None
        else {}
    )
    sc_containers, init_containers = _build_sidecars(
        name=name,
        sidecars=sidecar_map,
        component_images=component_images,
        volumes=volumes,
    )
    pod_sec: dict[str, Any] = {
        "runAsNonRoot": True,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    if workload.get("fs_group") is not None:
        pod_sec["fsGroup"] = _require_int(workload, "fs_group", label)
    pod_spec: dict[str, Any] = {
        "serviceAccountName": name,
        "automountServiceAccountToken": True,
        "terminationGracePeriodSeconds": 30,
        "nodeSelector": {"fdai.io/pool": "runtime"},
        "securityContext": pod_sec,
        "containers": [primary, *sc_containers],
        "volumes": volumes,
        **({"initContainers": init_containers} if init_containers else {}),
    }
    deployment_obj = RuntimeObject(
        entity_id=entity_id,
        name=name,
        kind="Deployment",
        spec={
            "replicas": replicas,
            "strategy": {
                "type": "RollingUpdate",
                "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0},
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/name": name,
                        "app.kubernetes.io/component": str(workload.get("component", name)),
                        "fdai.io/runtime": "aks",
                        "azure.workload.identity/use": "true",
                    }
                },
                "spec": pod_spec,
            },
        },
    )
    service_obj = RuntimeObject(
        entity_id=entity_id,
        name=name,
        kind="Service",
        spec={
            "type": "ClusterIP",
            "ports": [
                {"name": "http", "port": service_port, "targetPort": port, "protocol": "TCP"}
            ],
        },
    )
    return deployment_obj, service_obj


def _build_cron_job(
    *,
    name: str,
    job: Mapping[str, Any],
    entity_id: str,
    image_component: str,
    identity_bridge_config_map: str | None,
    component_images: dict[str, str],
    service_accounts: set[str],
    secret_provider_classes: set[str],
    config_maps: set[str],
    secrets: set[str],
    config_map_data: dict[str, dict[str, str]],
    secret_bindings: dict[str, dict[str, str]],
    identity_bindings: dict[str, dict[str, Any]],
) -> RuntimeObject:
    label = f"scheduled job {name}"
    _record_component_image(
        component_images, image_component, _validate_image(job.get("image"), label)
    )
    sa_name = f"{name}-job"
    _validate_and_record_identity(job, sa_name, label, identity_bindings)
    service_accounts.add(sa_name)
    env_cm_name = f"{name}-job-env"
    component = str(job.get("component", name))
    env_map, sec_map, field_map = _validate_env_contracts(
        label=label,
        component=component,
        environment=_require_mapping(job, "environment", label) if "environment" in job else {},
        secret_environment=_require_mapping(job, "secret_environment", label)
        if "secret_environment" in job
        else {},
        field_environment=_require_mapping(job, "field_environment", label)
        if "field_environment" in job
        else {},
    )
    config_maps.add(env_cm_name)
    config_map_data[env_cm_name] = env_map
    if sec_map:
        secret_bindings[sa_name] = sec_map
    volumes, volume_mounts = _build_base_volumes(
        ref_name=sa_name,
        tmp_size="256Mi",
        has_secrets=bool(sec_map),
        identity_bridge_enabled=bool(job.get("identity_bridge_enabled", False)),
        identity_bridge_config_map=identity_bridge_config_map,
        identity_bridge_size_limit=None,
        config_maps=config_maps,
        secret_provider_classes=secret_provider_classes,
        secrets=secrets,
    )
    cpu = _normalize_cpu(str(job.get("cpu", "500m")))
    memory = _normalize_memory(str(job.get("memory", "1Gi")))
    command = [str(item) for item in (job.get("command") or [])]
    if not command:
        raise ValueError(f"Scheduled job {name} requires a non-empty command.")
    container: dict[str, Any] = {
        "name": name,
        "image_component": image_component,
        "command": command,
        "resources": {
            "requests": {"cpu": cpu, "memory": memory},
            "limits": {"cpu": cpu, "memory": memory},
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
            "capabilities": {"drop": ["ALL"]},
        },
        "envFrom": [{"configMapRef": {"name": env_cm_name, "optional": False}}],
        "volumeMounts": volume_mounts,
    }
    if job.get("args"):
        container["args"] = [str(item) for item in job["args"]]
    env_refs = _build_env_references(
        secret_ref_name=sa_name,
        secret_environment=sec_map,
        field_environment=field_map,
    )
    if env_refs:
        container["env"] = env_refs
    deadline_seconds = _require_int(
        job, "deadline_seconds", label, default=240, minimum=1, maximum=900
    )
    job_labels = {
        "app.kubernetes.io/name": name,
        "app.kubernetes.io/component": component,
        "fdai.io/runtime": "aks",
    }
    return RuntimeObject(
        entity_id=entity_id,
        name=name,
        kind="CronJob",
        spec={
            "schedule": _require_str(job, "schedule", label),
            "suspend": bool(job.get("suspend", False)),
            "concurrencyPolicy": "Forbid",
            "timeZone": "Etc/UTC",
            "successfulJobsHistoryLimit": 3,
            "failedJobsHistoryLimit": 3,
            "jobTemplate": {
                "metadata": {"labels": dict(job_labels)},
                "spec": {
                    "completions": 1,
                    "parallelism": 1,
                    "backoffLimit": 0,
                    "activeDeadlineSeconds": deadline_seconds,
                    "ttlSecondsAfterFinished": 3600,
                    "template": {
                        "metadata": {
                            "labels": {
                                **job_labels,
                                "azure.workload.identity/use": "true",
                            }
                        },
                        "spec": {
                            "serviceAccountName": sa_name,
                            "automountServiceAccountToken": True,
                            "restartPolicy": "Never",
                            "nodeSelector": {"fdai.io/pool": "runtime"},
                            "securityContext": {
                                "runAsNonRoot": True,
                                "seccompProfile": {"type": "RuntimeDefault"},
                            },
                            "containers": [container],
                            "volumes": volumes,
                        },
                    },
                },
            },
        },
    )


def generate_fdai_runtime_bundle(
    *,
    workloads: Mapping[str, Mapping[str, Any]],
    scheduled_jobs: Mapping[str, Mapping[str, Any]],
    installation_id: str,
    entity_id: str = "fdai-workloads",
    product: str = "fdai",
    namespace: str = "fdai-runtime",
    scheduled_job_image_component: str = "core-control-plane",
    identity_bridge_config_map: str | None = None,
    identity_bridge_size_limit: str = "256Mi",
) -> GeneratedRuntimeTopology:
    """Convert AKS workload maps into a verified Hub runtime bundle and native scope."""

    if not workloads:
        raise ValueError("At least one AKS workload is required.")

    objects: list[RuntimeObject] = []
    component_images: dict[str, str] = {}
    service_accounts: set[str] = set()
    secret_provider_classes: set[str] = set()
    config_maps: set[str] = set()
    secrets: set[str] = set()
    config_map_data: dict[str, dict[str, str]] = {}
    secret_bindings: dict[str, dict[str, str]] = {}
    identity_bindings: dict[str, dict[str, Any]] = {}
    canary_scheduled = "canary" in scheduled_jobs

    for name in sorted(workloads):
        deployment_obj, service_obj = _build_deployment_and_service(
            name=name,
            workload=workloads[name],
            entity_id=entity_id,
            namespace=namespace,
            canary_scheduled=canary_scheduled,
            identity_bridge_config_map=identity_bridge_config_map,
            identity_bridge_size_limit=identity_bridge_size_limit,
            component_images=component_images,
            service_accounts=service_accounts,
            secret_provider_classes=secret_provider_classes,
            config_maps=config_maps,
            secrets=secrets,
            config_map_data=config_map_data,
            secret_bindings=secret_bindings,
            identity_bindings=identity_bindings,
        )
        objects.extend((deployment_obj, service_obj))

    for job_name in sorted(scheduled_jobs):
        cron_obj = _build_cron_job(
            name=job_name,
            job=scheduled_jobs[job_name],
            entity_id=entity_id,
            image_component=scheduled_job_image_component,
            identity_bridge_config_map=identity_bridge_config_map,
            component_images=component_images,
            service_accounts=service_accounts,
            secret_provider_classes=secret_provider_classes,
            config_maps=config_maps,
            secrets=secrets,
            config_map_data=config_map_data,
            secret_bindings=secret_bindings,
            identity_bindings=identity_bindings,
        )
        objects.append(cron_obj)

    bundle = RuntimeBundle(
        format="fdai.application-runtime-bundle.v1",
        product=product,
        namespace=namespace,
        objects=tuple(objects),
    )
    if product == "fdai" and "core-control-plane" in workloads:
        service_accounts.add("fdai-schema-migration")
    deployments = tuple(sorted(item.name for item in bundle.objects if item.kind == "Deployment"))
    services = tuple(sorted(item.name for item in bundle.objects if item.kind == "Service"))
    schedules = tuple(sorted(item.name for item in bundle.objects if item.kind == "CronJob"))
    native_scope = NativeScope(
        installation_id=installation_id,
        entity_id=entity_id,
        product=product,
        namespace=namespace,
        components=deployments,
        service_components=services,
        scheduled_components=schedules,
    )
    prerequisites = PreExistingReferences(
        service_accounts=tuple(sorted(service_accounts)),
        secret_provider_classes=tuple(sorted(secret_provider_classes)),
        config_maps=tuple(sorted(config_maps)),
        secrets=tuple(sorted(secrets)),
        config_map_data=config_map_data,
        secret_bindings=dict(sorted(secret_bindings.items())),
        identity_bindings=dict(sorted(identity_bindings.items())),
    )
    return GeneratedRuntimeTopology(
        bundle=bundle,
        component_images=dict(sorted(component_images.items())),
        native_scope=native_scope,
        prerequisites=prerequisites,
    )


def write_generated_runtime_bundle(
    *,
    topology_input_path: Path,
    destination: Path,
    installation_id: str,
    entity_id: str = "fdai-workloads",
    product: str = "fdai",
    namespace: str = "fdai-runtime",
) -> dict[str, Any]:
    """Read a private AKS topology JSON file and write bundle, image, scope, and reference files."""

    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Runtime bundle destination must not exist.")
    raw = load_json_object(
        read_private_bytes(topology_input_path.absolute(), max_bytes=256 * 1024),
        label="AKS topology input",
        strict=True,
    )
    workloads = raw.get("workloads")
    scheduled_jobs = raw.get("scheduled_jobs", {})
    if not isinstance(workloads, Mapping) or not isinstance(scheduled_jobs, Mapping):
        raise ValueError("AKS topology input requires workloads and scheduled_jobs mappings.")
    generated = generate_fdai_runtime_bundle(
        workloads=workloads,
        scheduled_jobs=scheduled_jobs,
        installation_id=installation_id,
        entity_id=entity_id,
        product=product,
        namespace=namespace,
        identity_bridge_config_map=(
            str(raw["identity_bridge_config_map"])
            if raw.get("identity_bridge_config_map") is not None
            else None
        ),
    )
    destination.mkdir(mode=0o700, parents=True)
    write_private_bytes(
        destination / "runtime-bundle.json",
        canonical_bytes(generated.bundle.model_dump(mode="json")) + b"\n",
    )
    write_private_bytes(
        destination / "component-images.json",
        canonical_bytes(generated.component_images) + b"\n",
    )
    write_private_bytes(
        destination / "native-scope.json",
        canonical_bytes(generated.native_scope.model_dump(mode="json")) + b"\n",
    )
    write_private_bytes(
        destination / "prerequisites.json",
        canonical_bytes(generated.prerequisites.model_dump(mode="json")) + b"\n",
    )
    return {
        "schema_version": "fdai.generated-runtime-topology.v1",
        "runtime_bundle_digest": generated.bundle.digest,
        "native_scope_digest": generated.native_scope.digest,
        "topology_digest": generated.digest,
        "deployments": list(generated.native_scope.components),
        "services": list(generated.native_scope.service_components or ()),
        "scheduled_jobs": list(generated.native_scope.scheduled_components),
        "components": sorted(generated.component_images),
        "destination": str(destination),
    }
