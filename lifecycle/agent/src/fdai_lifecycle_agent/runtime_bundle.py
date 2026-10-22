"""Installation-local workload templates pinned independently of vendor image publication."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Annotated, Any, Literal, Self

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from fdai_lifecycle_agent.workload import (
    COMPONENT_LABEL,
    ENTITY_LABEL,
    FIELD_MANAGER,
    MANAGED_BY_LABEL,
    Manifest,
    WorkloadError,
    is_dns_label,
)

type Name = Annotated[str, StringConstraints(pattern=r"^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$")]
type EntityId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")]


class RuntimeObject(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    entity_id: EntityId
    name: Name
    kind: Literal["Deployment", "Service", "CronJob"]
    spec: dict[str, Any] = Field(repr=False)

    @model_validator(mode="after")
    def validate_specification(self) -> Self:
        if self.kind == "Service":
            _fields(self.spec, {"ports"}, {"type"})
            if self.spec.get("type", "ClusterIP") != "ClusterIP":
                raise ValueError("runtime Service must be internal")
            ports = self.spec["ports"]
            if not isinstance(ports, list) or not 1 <= len(ports) <= 16:
                raise ValueError("runtime Service ports are invalid")
            for port in ports:
                _fields(port, {"port", "targetPort"}, {"name", "protocol"})
                _integer(port["port"], 1, 65535)
                target = port["targetPort"]
                if isinstance(target, str):
                    _name(target)
                else:
                    _integer(target, 1, 65535)
                if port.get("protocol", "TCP") != "TCP":
                    raise ValueError("runtime Service protocol is unsupported")
        elif self.kind == "Deployment":
            _fields(self.spec, {"replicas", "template"}, {"strategy", "progressDeadlineSeconds"})
            _integer(self.spec["replicas"], 1, 3)
            _integer(self.spec.get("progressDeadlineSeconds", 600), 1, 900)
            if "strategy" in self.spec and self.spec["strategy"] != {
                "type": "RollingUpdate",
                "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0},
            }:
                raise ValueError("runtime Deployment strategy is unsupported")
            _pod_template(self.spec["template"], scheduled=False)
        else:
            _fields(
                self.spec,
                {"schedule", "suspend", "concurrencyPolicy", "jobTemplate"},
                {
                    "timeZone",
                    "startingDeadlineSeconds",
                    "successfulJobsHistoryLimit",
                    "failedJobsHistoryLimit",
                },
            )
            if not isinstance(self.spec["suspend"], bool):
                raise ValueError("runtime schedule suspension is invalid")
            schedule = self.spec["schedule"]
            if (
                not isinstance(schedule, str)
                or not re.fullmatch(r"[0-9*/,-]+(?: [0-9*/,-]+){4}", schedule)
                or len(schedule) > 128
            ):
                raise ValueError("runtime schedule is invalid")
            if self.spec.get("timeZone", "Etc/UTC") != "Etc/UTC":
                raise ValueError("runtime schedules require an explicit UTC time base")
            if self.spec["concurrencyPolicy"] != "Forbid":
                raise ValueError("runtime scheduled tasks cannot overlap")
            _integer(self.spec.get("startingDeadlineSeconds", 60), 1, 300)
            for key in ("successfulJobsHistoryLimit", "failedJobsHistoryLimit"):
                _integer(self.spec.get(key, 1), 0, 3)
            _fields(self.spec["jobTemplate"], {"spec"}, set())
            job = self.spec["jobTemplate"]["spec"]
            _fields(
                job,
                {"template", "activeDeadlineSeconds", "backoffLimit"},
                {"parallelism", "completions", "ttlSecondsAfterFinished"},
            )
            _integer(job["activeDeadlineSeconds"], 1, 900)
            if any(
                type(job.get(key, default)) is not int or job.get(key, default) != default
                for key, default in (("backoffLimit", 0), ("parallelism", 1), ("completions", 1))
            ):
                raise ValueError("runtime scheduled task attempts are unbounded")
            _integer(job.get("ttlSecondsAfterFinished", 3600), 60, 86400)
            _pod_template(job["template"], scheduled=True)
        return self

    @property
    def pod(self) -> dict[str, Any] | None:
        if self.kind == "Service":
            return None
        spec = self.spec if self.kind == "Deployment" else self.spec["jobTemplate"]["spec"]
        pod: dict[str, Any] = spec["template"]["spec"]
        return pod


class RuntimeBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    format: Literal["fdai.application-runtime-bundle.v1"]
    product: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,62}$")]
    namespace: Name
    objects: Annotated[tuple[RuntimeObject, ...], Field(min_length=1, max_length=192)] = Field(
        repr=False
    )

    @model_validator(mode="after")
    def validate_inventory(self) -> Self:
        keys = [(item.kind, item.name) for item in self.objects]
        if len(set(keys)) != len(keys):
            raise ValueError("runtime objects must be unique")
        deployments = {
            (item.entity_id, item.name): item for item in self.objects if item.kind == "Deployment"
        }
        for item in self.objects:
            if item.kind == "Service" and (item.entity_id, item.name) not in deployments:
                raise ValueError("runtime Service requires its own Entity's named Deployment")
        if len(canonical_bytes(self.model_dump(mode="json"))) > 64 * 1024:
            raise ValueError("runtime bundle exceeds its byte limit")
        return self

    @property
    def digest(self) -> str:
        return "sha256:" + canonical_digest(self.model_dump(mode="json"))

    def components(self, entity_id: str) -> frozenset[str]:
        return frozenset(
            container["image_component"]
            for item in self.objects
            if item.entity_id == entity_id and item.pod is not None
            for key in ("containers", "initContainers")
            for container in item.pod.get(key, [])
        )

    def render(
        self,
        namespace: str,
        entities: frozenset[str],
        images: Mapping[tuple[str, str], str],
    ) -> tuple[Manifest, ...]:
        if namespace != self.namespace:
            raise WorkloadError("runtime_bundle_namespace_mismatch")
        desired: list[Manifest] = []
        for item in self.objects:
            if item.entity_id not in entities:
                continue
            labels = {
                MANAGED_BY_LABEL: FIELD_MANAGER,
                ENTITY_LABEL: item.entity_id,
                COMPONENT_LABEL: item.name,
            }
            spec = deepcopy(item.spec)
            selector = {COMPONENT_LABEL: item.name}
            if item.kind == "Service":
                spec["selector"] = selector
            else:
                workload = spec if item.kind == "Deployment" else spec["jobTemplate"]["spec"]
                template = workload["template"]
                template.setdefault("metadata", {}).setdefault("labels", {}).update(labels)
                if item.kind == "Deployment":
                    spec["selector"] = {"matchLabels": selector}
                for key in ("containers", "initContainers"):
                    for container in template["spec"].get(key, []):
                        component = container.pop("image_component")
                        try:
                            container["image"] = images[item.entity_id, component]
                        except KeyError:
                            raise WorkloadError("runtime_bundle_component_mismatch") from None
            desired.append(
                {
                    "apiVersion": "v1"
                    if item.kind == "Service"
                    else "apps/v1"
                    if item.kind == "Deployment"
                    else "batch/v1",
                    "kind": item.kind,
                    "metadata": {"name": item.name, "namespace": namespace, "labels": labels},
                    "spec": spec,
                }
            )
        if not desired:
            raise WorkloadError("runtime_bundle_entity_mismatch")
        return tuple(desired)


def _fields(value: Any, required: set[str], optional: set[str]) -> None:
    if not isinstance(value, dict) or not required <= value.keys() <= required | optional:
        raise ValueError("runtime specification fields are invalid")


def _integer(value: Any, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("runtime numeric bound is invalid")


def _name(value: Any) -> None:
    if not isinstance(value, str) or not is_dns_label(value):
        raise ValueError("runtime reference name is invalid")


def _security(value: Any, *, container: bool) -> None:
    required = (
        {"runAsNonRoot", "allowPrivilegeEscalation", "readOnlyRootFilesystem", "capabilities"}
        if container
        else {"runAsNonRoot", "seccompProfile"}
    )
    optional = {"runAsUser", "runAsGroup"} | (
        set() if container else {"fsGroup", "fsGroupChangePolicy"}
    )
    _fields(value, required, optional)
    if value["runAsNonRoot"] is not True:
        raise ValueError("runtime containers cannot run as root")
    for key in ("runAsUser", "runAsGroup", "fsGroup"):
        if key in value:
            _integer(value[key], 1, 2**31 - 1)
    if container:
        if (
            value["allowPrivilegeEscalation"] is not False
            or value["readOnlyRootFilesystem"] is not True
        ):
            raise ValueError("runtime container isolation is insufficient")
        if value["capabilities"] != {"drop": ["ALL"]}:
            raise ValueError("runtime capabilities are unsupported")
    elif value["seccompProfile"] != {"type": "RuntimeDefault"}:
        raise ValueError("runtime seccomp profile is unsupported")
    if "fsGroupChangePolicy" in value and value["fsGroupChangePolicy"] not in (
        "Always",
        "OnRootMismatch",
    ):
        raise ValueError("runtime filesystem group policy is invalid")


def _pod_template(template: Any, *, scheduled: bool) -> None:
    _fields(template, {"spec"}, {"metadata"})
    metadata = template.get("metadata", {})
    _fields(metadata, set(), {"labels"})
    if not isinstance(metadata.get("labels", {}), dict):
        raise ValueError("runtime Pod labels are invalid")
    if any(
        not isinstance(key, str) or not isinstance(value, str) or len(key) > 253 or len(value) > 63
        for key, value in metadata.get("labels", {}).items()
    ):
        raise ValueError("runtime Pod labels are invalid")
    pod = template["spec"]
    _fields(
        pod,
        {"containers", "securityContext", "serviceAccountName", "automountServiceAccountToken"},
        {
            "initContainers",
            "volumes",
            "nodeSelector",
            "terminationGracePeriodSeconds",
            "restartPolicy",
        },
    )
    _security(pod["securityContext"], container=False)
    _name(pod["serviceAccountName"])
    if (
        pod["serviceAccountName"] == "default"
        or type(pod["automountServiceAccountToken"]) is not bool
    ):
        raise ValueError("runtime identity must be independently bound")
    if pod.get("restartPolicy", "Always") != ("Never" if scheduled else "Always"):
        raise ValueError("runtime restart policy is invalid")
    _integer(pod.get("terminationGracePeriodSeconds", 30), 1, 120)
    if not isinstance(pod.get("nodeSelector", {}), dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in pod.get("nodeSelector", {}).items()
    ):
        raise ValueError("runtime node selector is invalid")
    volumes = pod.get("volumes", [])
    if not isinstance(volumes, list) or len(volumes) > 16:
        raise ValueError("runtime volumes are unbounded")
    names: set[str] = set()
    for volume in volumes:
        _fields(volume, {"name"}, {"emptyDir", "configMap", "persistentVolumeClaim", "csi"})
        _name(volume["name"])
        if volume["name"] in names or len(volume) != 2:
            raise ValueError("runtime volumes must be unique and typed")
        names.add(volume["name"])
        _volume(volume)
    container_names: set[str] = set()
    for key, maximum in (("containers", 8), ("initContainers", 4)):
        containers = pod.get(key, [])
        if (
            not isinstance(containers, list)
            or not (1 if key == "containers" else 0) <= len(containers) <= maximum
        ):
            raise ValueError("runtime containers are unbounded")
        for item in containers:
            _container(item, names, initializing=key == "initContainers", scheduled=scheduled)
            if item["name"] in container_names:
                raise ValueError("runtime container names must be unique")
            container_names.add(item["name"])


def _quantity(value: Any, unit: str, maximum: int) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*" + unit, value):
        raise ValueError("runtime resource quantity is invalid")
    number = int(value[: -len(unit)])
    _integer(number, 1, maximum)
    return number


def _container(item: Any, volumes: set[str], *, initializing: bool, scheduled: bool) -> None:
    _fields(
        item,
        {"name", "image_component", "resources", "securityContext"},
        {
            "command",
            "args",
            "ports",
            "readinessProbe",
            "livenessProbe",
            "startupProbe",
            "env",
            "envFrom",
            "volumeMounts",
            "imagePullPolicy",
        },
    )
    _name(item["name"])
    _name(item["image_component"])
    _security(item["securityContext"], container=True)
    if initializing and any(
        key in item for key in ("readinessProbe", "livenessProbe", "startupProbe")
    ):
        raise ValueError("runtime initialization cannot declare service probes")
    if not initializing and not scheduled and "readinessProbe" not in item:
        raise ValueError("runtime service containers require a readiness check")
    _fields(item["resources"], {"requests", "limits"}, set())
    for tier in ("requests", "limits"):
        _fields(item["resources"][tier], {"cpu", "memory"}, set())
    for resource, unit, maximum in (("cpu", "m", 16000), ("memory", "Mi", 65536)):
        request = _quantity(item["resources"]["requests"][resource], unit, maximum)
        limit = _quantity(item["resources"]["limits"][resource], unit, maximum)
        if request > limit:
            raise ValueError("runtime resource request exceeds its limit")
    for key in ("command", "args"):
        if key in item and (
            not isinstance(item[key], list)
            or not 1 <= len(item[key]) <= 64
            or not all(
                isinstance(arg, str) and 0 < len(arg) <= 4096 and "\0" not in arg
                for arg in item[key]
            )
        ):
            raise ValueError("runtime arguments are unbounded")
    if item.get("imagePullPolicy", "IfNotPresent") not in ("Always", "IfNotPresent"):
        raise ValueError("runtime image pull policy is invalid")
    for variable in _sequence(item.get("env", []), 128):
        _fields(variable, {"name", "valueFrom"}, set())
        if not isinstance(variable["name"], str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]{0,127}", variable["name"]
        ):
            raise ValueError("runtime environment name is invalid")
        reference = variable["valueFrom"]
        _fields(reference, set(), {"secretKeyRef", "configMapKeyRef", "fieldRef"})
        if len(reference) != 1:
            raise ValueError("runtime environment requires one reference")
        if "fieldRef" in reference:
            _fields(reference["fieldRef"], {"fieldPath"}, {"apiVersion"})
            if (
                reference["fieldRef"]["fieldPath"]
                not in (
                    "metadata.name",
                    "metadata.namespace",
                    "spec.nodeName",
                )
                or reference["fieldRef"].get("apiVersion", "v1") != "v1"
            ):
                raise ValueError("runtime field reference is unsupported")
        else:
            value = next(iter(reference.values()))
            _fields(value, {"name", "key"}, {"optional"})
            _name(value["name"])
            if not isinstance(value["key"], str) or not re.fullmatch(
                r"[A-Za-z0-9._-]{1,253}", value["key"]
            ):
                raise ValueError("runtime environment key is invalid")
            if value.get("optional", False) is not False:
                raise ValueError("runtime references cannot be optional")
    for reference in _sequence(item.get("envFrom", []), 16):
        _fields(reference, {"configMapRef"}, set())
        _fields(reference["configMapRef"], {"name"}, {"optional"})
        _name(reference["configMapRef"]["name"])
        if reference["configMapRef"].get("optional", False) is not False:
            raise ValueError("runtime references cannot be optional")
    for mount in _sequence(item.get("volumeMounts", []), 16):
        _fields(mount, {"name", "mountPath"}, {"readOnly"})
        if not isinstance(mount["name"], str) or mount["name"] not in volumes:
            raise ValueError("runtime volume mount has no declared volume")
        path = mount["mountPath"]
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or ".." in path.split("/")
            or "\0" in path
        ):
            raise ValueError("runtime mount path is invalid")
        if type(mount.get("readOnly", False)) is not bool:
            raise ValueError("runtime mount access is invalid")
    for port in _sequence(item.get("ports", []), 16):
        _fields(port, {"containerPort"}, {"name", "protocol"})
        _integer(port["containerPort"], 1, 65535)
        if "name" in port:
            _name(port["name"])
        if port.get("protocol", "TCP") != "TCP":
            raise ValueError("runtime container protocol is unsupported")
    for key in ("readinessProbe", "livenessProbe", "startupProbe"):
        if key in item:
            _probe(item[key])


def _sequence(value: Any, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("runtime list is invalid or unbounded")
    return value


def _probe(value: Any) -> None:
    _fields(
        value,
        set(),
        {
            "httpGet",
            "tcpSocket",
            "initialDelaySeconds",
            "periodSeconds",
            "timeoutSeconds",
            "failureThreshold",
            "successThreshold",
        },
    )
    if len({"httpGet", "tcpSocket"} & value.keys()) != 1:
        raise ValueError("runtime probe requires one bounded network check")
    if "httpGet" in value:
        _fields(value["httpGet"], {"path", "port"}, {"scheme"})
        path = value["httpGet"]["path"]
        if (
            not isinstance(path, str)
            or not re.fullmatch(r"/[A-Za-z0-9/._~-]{0,255}", path)
            or path.startswith("//")
        ):
            raise ValueError("runtime probe path is invalid")
        if value["httpGet"].get("scheme", "HTTP") not in ("HTTP", "HTTPS"):
            raise ValueError("runtime probe scheme is invalid")
    else:
        _fields(value["tcpSocket"], {"port"}, set())
    port = value.get("httpGet", value.get("tcpSocket"))["port"]
    if isinstance(port, str):
        _name(port)
    else:
        _integer(port, 1, 65535)
    for key in (
        "initialDelaySeconds",
        "periodSeconds",
        "timeoutSeconds",
        "failureThreshold",
        "successThreshold",
    ):
        if key in value:
            _integer(value[key], 0 if key == "initialDelaySeconds" else 1, 300)


def _volume(volume: dict[str, Any]) -> None:
    if "emptyDir" in volume:
        _fields(volume["emptyDir"], {"sizeLimit"}, set())
        _quantity(volume["emptyDir"]["sizeLimit"], "Mi", 16384)
    elif "persistentVolumeClaim" in volume:
        claim = volume["persistentVolumeClaim"]
        _fields(claim, {"claimName"}, {"readOnly"})
        _name(claim["claimName"])
        if type(claim.get("readOnly", False)) is not bool:
            raise ValueError("runtime claim access is invalid")
    elif "configMap" in volume:
        _fields(volume["configMap"], {"name"}, {"defaultMode"})
        _name(volume["configMap"]["name"])
        if "defaultMode" in volume["configMap"]:
            _integer(volume["configMap"]["defaultMode"], 0, 0o444)
    else:
        csi = volume["csi"]
        _fields(csi, {"driver", "readOnly", "volumeAttributes"}, set())
        if csi["driver"] != "secrets-store.csi.k8s.io" or csi["readOnly"] is not True:
            raise ValueError("runtime CSI provider is unsupported")
        _fields(csi["volumeAttributes"], {"secretProviderClass"}, set())
        _name(csi["volumeAttributes"]["secretProviderClass"])
