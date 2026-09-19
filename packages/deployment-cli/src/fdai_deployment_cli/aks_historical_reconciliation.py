"""Validate bounded reconciliation of a historical AKS workload baseline."""

from __future__ import annotations

import copy
import re
from typing import Any

from fdai_deployment_cli.aks_service_update import SERVICES

_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_IMAGE = re.compile(r"[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}")
_IDENTITY_ID = re.compile(
    r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/"
    r"Microsoft[.]ManagedIdentity/userAssignedIdentities/[^/]+",
    re.IGNORECASE,
)
_COMMAND_FIC = "workload-operator-service-command"
_INVENTORY_RESOURCES = {
    "kubernetes_cluster_role_v1.inventory_reader[0]",
    "kubernetes_cluster_role_binding_v1.inventory_reader[0]",
}
_JOBS = {"analyzer", "canary", "inventory", "observation-campaign"}
_EXTERNAL_SERVICES = {"core-control-plane", "document-processing-worker", "isolated-executor"}
_LEGACY_RUNTIME_COMMANDS = {
    "core-control-plane": (
        ["/app/.venv/bin/python"],
        [
            "/opt/fdai-compat/identity_bridge.py",
            "--",
            "/app/.venv/bin/fdai-core-control-plane",
        ],
    ),
    "document-ingestion-api": (
        ["/app/.venv/bin/python"],
        [
            "/opt/fdai-compat/identity_bridge.py",
            "--",
            "/app/.venv/bin/fdai-document-ingestion-api",
        ],
    ),
    "document-processing-worker": (
        ["/app/.venv/bin/python"],
        [
            "/opt/fdai-compat/identity_bridge.py",
            "--",
            "/app/.venv/bin/fdai-document-processing-worker",
        ],
    ),
    "isolated-executor": (
        ["/app/.venv/bin/python"],
        [
            "/opt/fdai-compat/identity_bridge.py",
            "--",
            "/app/.venv/bin/fdai-isolated-executor-service",
        ],
    ),
    "operator-service": (
        ["/app/.venv/bin/python"],
        [
            "/opt/fdai-compat/identity_bridge.py",
            "--",
            "/app/.venv/bin/fdai-operator-service",
        ],
    ),
}


def reconciled_variables(
    *, state: dict[str, Any], variables: dict[str, Any], live: dict[str, Any]
) -> dict[str, Any]:
    """Restore only safety-critical variable values proven by retained state and live AKS."""

    result = copy.deepcopy(variables)
    workloads = _mapping(result.get("workloads"), "historical AKS workloads")
    if set(workloads) != set(SERVICES):
        raise ValueError("historical AKS workload inventory is incomplete")
    deployments = _live_deployments(live)
    identity_bridge = _identity_bridge(state)
    result["identity_bridge"] = identity_bridge

    for name, workload_value in workloads.items():
        workload = _mapping(workload_value, f"historical AKS {name} workload")
        command, arguments = _LEGACY_RUNTIME_COMMANDS[name]
        live_container = _runtime_container(deployments[name], name)
        if (
            live_container.get("command") != command
            or live_container.get("args") != arguments
            or workload.get("command", command) != command
            or workload.get("args", arguments) != arguments
        ):
            raise ValueError(f"historical AKS {name} identity bridge command is invalid")
        if workload.get("identity_bridge_enabled") not in (None, True):
            raise ValueError(f"historical AKS {name} identity bridge binding differs")
        workload["identity_bridge_enabled"] = True

    operator = _mapping(workloads.get("operator-service"), "operator workload")
    operator_live = deployments["operator-service"]
    command_client_id = _environment_value(
        _runtime_container(operator_live, "operator-service"),
        "FDAI_COMMAND_MI_CLIENT_ID",
    )
    if _GUID.fullmatch(command_client_id) is None:
        raise ValueError("historical AKS command identity client id is invalid")
    command_identity = _command_identity(state, variables=variables)
    command_identity["client_id"] = command_client_id
    existing_identities = _mapping(
        operator.get("additional_identities", {}), "operator additional identities"
    )
    if existing_identities not in ({}, {"command": command_identity}):
        raise ValueError("historical AKS operator additional identities differ")
    operator["additional_identities"] = {"command": command_identity}

    worker = _mapping(workloads.get("document-processing-worker"), "document worker")
    clamav, fs_group = _clamav_sidecar(deployments["document-processing-worker"])
    existing_sidecars = _mapping(worker.get("sidecars", {}), "document worker sidecars")
    if existing_sidecars not in ({}, {"clamav": clamav}):
        raise ValueError("historical AKS document worker sidecars differ")
    worker["sidecars"] = {"clamav": clamav}
    if worker.get("fs_group") not in (None, fs_group):
        raise ValueError("historical AKS document worker fs_group differs")
    worker["fs_group"] = fs_group
    return result


def _identity_bridge(state: dict[str, Any]) -> dict[str, str]:
    matches: list[dict[str, Any]] = []
    for raw_resource in state.get("resources", []):
        if not isinstance(raw_resource, dict):
            continue
        if (
            raw_resource.get("mode") != "managed"
            or raw_resource.get("type") != "kubernetes_config_map_v1"
            or raw_resource.get("name") != "identity_bridge"
        ):
            continue
        for raw_instance in raw_resource.get("instances", []):
            if isinstance(raw_instance, dict):
                matches.append(_mapping(raw_instance.get("attributes"), "identity bridge"))
    if len(matches) != 1:
        raise ValueError("historical AKS identity bridge state is invalid")
    attributes = matches[0]
    metadata = attributes.get("metadata")
    data = _mapping(attributes.get("data"), "identity bridge data")
    script = data.get("identity_bridge.py")
    if (
        not isinstance(metadata, list)
        or len(metadata) != 1
        or not isinstance(metadata[0], dict)
        or metadata[0].get("name") != "fdai-identity-bridge"
        or set(data) != {"identity_bridge.py"}
        or not isinstance(script, str)
        or not script
        or len(script.encode()) > 65536
    ):
        raise ValueError("historical AKS identity bridge contract is invalid")
    return {
        "config_map_name": "fdai-identity-bridge",
        "script": script,
        "runtime_state_size_limit": "256Mi",
    }


def validate_reconciliation_plan(
    plan: dict[str, Any], *, variables: dict[str, Any]
) -> tuple[str, ...]:
    """Accept only the known legacy normalization while preserving rollout identity."""

    changes = plan.get("resource_changes")
    if plan.get("errored") is not False or plan.get("applyable") is not True:
        raise ValueError("historical AKS reconciliation plan is invalid")
    if not isinstance(changes, list) or not changes:
        raise ValueError("historical AKS reconciliation plan inventory is invalid")
    workloads = _mapping(variables.get("workloads"), "reconciled AKS workloads")
    if set(workloads) != set(SERVICES):
        raise ValueError("reconciled AKS workload inventory is incomplete")

    mutated: list[str] = []
    command_fic_seen = False
    for raw_change in changes:
        change = _mapping(raw_change, "historical AKS reconciliation change")
        address = change.get("address")
        actions = _mapping(change.get("change"), "historical AKS reconciliation actions").get(
            "actions"
        )
        if (
            not isinstance(address, str)
            or not isinstance(actions, list)
            or not all(isinstance(action, str) for action in actions)
        ):
            raise ValueError("historical AKS reconciliation change is invalid")
        if address == f'azurerm_federated_identity_credential.identity["{_COMMAND_FIC}"]':
            command_fic_seen = True
            if set(actions) - {"no-op", "read"}:
                raise ValueError("historical AKS reconciliation changes the command identity")
        if set(actions).issubset({"no-op", "read"}):
            continue
        mutated.append(address)
        before_raw = change["change"].get("before")
        after_raw = change["change"].get("after")
        before = (
            {}
            if before_raw is None and actions == ["create"]
            else _mapping(before_raw, "reconciliation prior value")
        )
        after = (
            {}
            if after_raw is None and actions == ["delete"]
            else _mapping(after_raw, "reconciliation planned value")
        )
        if address in _INVENTORY_RESOURCES and actions == ["create"]:
            if before:
                raise ValueError("historical AKS inventory read role already has prior state")
            continue
        workload = _indexed_name(address, "kubernetes_deployment_v1.workload")
        if workload is not None and workload in SERVICES and actions == ["update"]:
            _validate_workload_update(before, after, name=workload, contract=workloads[workload])
            continue
        job = _indexed_name(address, "kubernetes_cron_job_v1.job")
        if job is not None and job in _JOBS and actions == ["update"]:
            if _normalized_cron_job(before) != _normalized_cron_job(after):
                raise ValueError("historical AKS reconciliation changes a scheduled job contract")
            continue
        service = _indexed_name(address, "kubernetes_service_v1.workload")
        if service is not None and service in _EXTERNAL_SERVICES and actions == ["update"]:
            prior = copy.deepcopy(before)
            planned = copy.deepcopy(after)
            prior.pop("wait_for_load_balancer", None)
            planned.pop("wait_for_load_balancer", None)
            if prior != planned:
                raise ValueError("historical AKS reconciliation changes a Service contract")
            continue
        raise ValueError("historical AKS reconciliation contains an out-of-scope mutation")
    if not command_fic_seen or not mutated:
        raise ValueError("historical AKS reconciliation omits required evidence")
    return tuple(sorted(mutated))


def _command_identity(state: dict[str, Any], *, variables: dict[str, Any]) -> dict[str, str]:
    matches: list[dict[str, Any]] = []
    for raw_resource in state.get("resources", []):
        if not isinstance(raw_resource, dict):
            continue
        if (
            raw_resource.get("mode") != "managed"
            or raw_resource.get("type") != "azurerm_federated_identity_credential"
            or raw_resource.get("name") != "identity"
        ):
            continue
        for raw_instance in raw_resource.get("instances", []):
            if isinstance(raw_instance, dict) and raw_instance.get("index_key") == _COMMAND_FIC:
                matches.append(_mapping(raw_instance.get("attributes"), "command identity"))
    if len(matches) != 1:
        raise ValueError("historical AKS command identity state is invalid")
    attributes = matches[0]
    namespace = variables.get("namespace")
    if (
        attributes.get("audience") != ["api://AzureADTokenExchange"]
        or attributes.get("issuer") != variables.get("oidc_issuer_url")
        or attributes.get("subject") != f"system:serviceaccount:{namespace}:operator-service"
        or not isinstance(attributes.get("parent_id"), str)
        or _IDENTITY_ID.fullmatch(attributes["parent_id"]) is None
    ):
        raise ValueError("historical AKS command identity binding is invalid")
    return {"resource_id": attributes["parent_id"]}


def _live_deployments(live: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = live.get("items")
    if live.get("apiVersion") != "apps/v1" or live.get("kind") != "DeploymentList":
        raise ValueError("historical AKS reconciliation requires a typed DeploymentList")
    if not isinstance(items, list):
        raise ValueError("historical AKS reconciliation Deployment inventory is invalid")
    result: dict[str, dict[str, Any]] = {}
    for raw_item in items:
        item = _mapping(raw_item, "historical AKS live Deployment")
        name = _mapping(item.get("metadata"), "historical AKS Deployment metadata").get("name")
        if not isinstance(name, str) or name not in SERVICES or name in result:
            raise ValueError("historical AKS live Deployment identity is invalid")
        result[name] = item
    if set(result) != set(SERVICES):
        raise ValueError("historical AKS live Deployment inventory is incomplete")
    return result


def _runtime_container(deployment: dict[str, Any], name: str) -> dict[str, Any]:
    containers = _pod_spec(deployment).get("containers")
    if not isinstance(containers, list):
        raise ValueError("historical AKS live containers are invalid")
    selected = [item for item in containers if isinstance(item, dict) and item.get("name") == name]
    if len(selected) != 1:
        raise ValueError("historical AKS live runtime container is invalid")
    return dict(selected[0])


def _environment_value(container: dict[str, Any], name: str) -> str:
    values = [
        item.get("value")
        for item in container.get("env", [])
        if isinstance(item, dict) and item.get("name") == name and set(item) == {"name", "value"}
    ]
    if len(values) != 1 or not isinstance(values[0], str):
        raise ValueError(f"historical AKS live {name} environment is invalid")
    return values[0]


def _clamav_sidecar(deployment: dict[str, Any]) -> tuple[dict[str, object], int]:
    container = _runtime_container(deployment, "clamav")
    image = container.get("image")
    ports = container.get("ports")
    resources = _mapping(container.get("resources"), "ClamAV resources")
    requests = _mapping(resources.get("requests"), "ClamAV requests")
    limits = _mapping(resources.get("limits"), "ClamAV limits")
    security = _mapping(container.get("securityContext"), "ClamAV security context")
    capabilities = _mapping(security.get("capabilities"), "ClamAV capabilities")
    if (
        not isinstance(image, str)
        or _IMAGE.fullmatch(image) is None
        or ports != [{"containerPort": 3310, "protocol": "TCP"}]
        or set(requests) != {"cpu", "memory"}
        or requests != limits
        or not all(isinstance(requests[key], str) and requests[key] for key in requests)
        or security.get("allowPrivilegeEscalation") is not False
        or security.get("readOnlyRootFilesystem") is not True
        or security.get("runAsUser") != 100
        or security.get("runAsGroup") != 101
        or capabilities.get("drop") != ["ALL"]
    ):
        raise ValueError("historical AKS live ClamAV contract is invalid")
    expected_paths = {
        "clamav-database": ("/var/lib/clamav", "1Gi"),
        "clamav-run": ("/run/clamav", "64Mi"),
        "clamav-tmp": ("/tmp", "256Mi"),
    }
    mounts = {
        item.get("name"): item.get("mountPath")
        for item in container.get("volumeMounts", [])
        if isinstance(item, dict)
    }
    volumes = {
        item.get("name"): _mapping(item.get("emptyDir"), "ClamAV volume").get("sizeLimit")
        for item in _pod_spec(deployment).get("volumes", [])
        if isinstance(item, dict) and item.get("name") in expected_paths
    }
    if mounts != {name: path for name, (path, _size) in expected_paths.items()} or volumes != {
        name: size for name, (_path, size) in expected_paths.items()
    }:
        raise ValueError("historical AKS live ClamAV writable paths are invalid")
    pod_security = _mapping(_pod_spec(deployment).get("securityContext"), "worker security")
    init_containers = _pod_spec(deployment).get("initContainers")
    if pod_security.get("fsGroup") != 101 or not isinstance(init_containers, list):
        raise ValueError("historical AKS live ClamAV Pod security is invalid")
    selected_init = [
        item
        for item in init_containers
        if isinstance(item, dict) and item.get("name") == "clamav-database"
    ]
    if len(selected_init) != 1:
        raise ValueError("historical AKS live ClamAV initialization is invalid")
    init = selected_init[0]
    init_security = _mapping(init.get("securityContext"), "ClamAV init security")
    init_mounts = init.get("volumeMounts")
    init_mount = init_mounts[0] if isinstance(init_mounts, list) and len(init_mounts) == 1 else None
    if (
        init.get("image") != image
        or init.get("imagePullPolicy") != "IfNotPresent"
        or init.get("command") != ["/bin/sh", "-c"]
        or init.get("args") != ["cp -a /var/lib/clamav/. /target/"]
        or init_security.get("allowPrivilegeEscalation") is not False
        or init_security.get("readOnlyRootFilesystem") is not True
        or init_security.get("runAsUser") != 100
        or init_security.get("runAsGroup") != 101
        or _mapping(init_security.get("capabilities"), "ClamAV init capabilities").get("drop")
        != ["ALL"]
        or not isinstance(init_mount, dict)
        or init_mount.get("name") != "clamav-database"
        or init_mount.get("mountPath") != "/target"
        or init_mount.get("readOnly") not in (None, False)
        or init_mount.get("mountPropagation") not in (None, "None")
    ):
        raise ValueError("historical AKS live ClamAV initialization is invalid")
    command = container.get("command", [])
    arguments = container.get("args", [])
    if (
        not isinstance(command, list)
        or not isinstance(arguments, list)
        or not all(isinstance(value, str) for value in [*command, *arguments])
    ):
        raise ValueError("historical AKS live ClamAV command is invalid")
    return {
        "image": image,
        "command": command,
        "args": arguments,
        "cpu": requests["cpu"],
        "memory": requests["memory"],
        "port": 3310,
        "run_as_user": 100,
        "run_as_group": 101,
        "init": {
            "name": "clamav-database",
            "command": ["/bin/sh", "-c"],
            "args": ["cp -a /var/lib/clamav/. /target/"],
            "image_pull_policy": "IfNotPresent",
            "run_as_user": 100,
            "run_as_group": 101,
            "writable_path": "database",
            "mount_path": "/target",
        },
        "writable_paths": {
            name.removeprefix("clamav-"): {"mount_path": path, "size_limit": size}
            for name, (path, size) in expected_paths.items()
        },
    }, 101


def _validate_workload_update(
    before: dict[str, Any], after: dict[str, Any], *, name: str, contract: object
) -> None:
    expected = _mapping(contract, f"reconciled workload {name}")
    for value in (before, after):
        container = _terraform_runtime_container(value, name)
        labels = _terraform_template_metadata(value).get("labels")
        if (
            container.get("image") != expected.get("image")
            or not isinstance(labels, dict)
            or labels.get("fdai.io/source-commit") != expected.get("source_commit")
        ):
            raise ValueError("historical AKS reconciliation changes rollout identity")
    if name == "document-processing-worker":
        expected_clamav = _mapping(
            _mapping(expected.get("sidecars"), "reconciled sidecars").get("clamav"),
            "reconciled ClamAV sidecar",
        )
        planned = _terraform_runtime_container(after, "clamav")
        if planned.get("image") != expected_clamav.get("image"):
            raise ValueError("historical AKS reconciliation removes the ClamAV sidecar")
    if _normalized_pod_owner(before) != _normalized_pod_owner(after):
        raise ValueError("historical AKS reconciliation changes a workload contract")


def _normalized_pod_owner(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result.pop("wait_for_rollout", None)
    _normalize_template(_terraform_template(result))
    return result


def _normalized_cron_job(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    try:
        template = result["spec"][0]["job_template"][0]["spec"][0]["template"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("historical AKS planned CronJob template is invalid") from exc
    if not isinstance(template, dict):
        raise ValueError("historical AKS planned CronJob template is invalid")
    _normalize_template(template)
    return result


def _normalize_template(template: dict[str, Any]) -> None:
    metadata = _mapping(template.get("metadata", [{}])[0], "planned Pod metadata")
    annotations = metadata.get("annotations")
    if isinstance(annotations, dict):
        annotations.pop("kubectl.kubernetes.io/restartedAt", None)
    labels = metadata.get("labels")
    if isinstance(labels, dict):
        labels.pop("fdai.io/identity-bridge-sha", None)
    spec = _mapping(template.get("spec", [{}])[0], "planned Pod spec")
    for container_key in ("container", "init_container"):
        containers = spec.get(container_key)
        if not isinstance(containers, list):
            continue
        retained = []
        for container in containers:
            if not isinstance(container, dict):
                retained.append(container)
                continue
            item = copy.deepcopy(container)
            if container_key == "init_container" and item.get("name") == "identity-bridge":
                continue
            legacy_command = _LEGACY_RUNTIME_COMMANDS.get(str(item.get("name")))
            if (
                legacy_command is not None
                and item.get("command") == legacy_command[0]
                and item.get("args") == legacy_command[1]
            ):
                item["command"] = []
                item["args"] = []
            security = item.get("security_context")
            if isinstance(security, list) and len(security) == 1 and isinstance(security[0], dict):
                security[0].pop("run_as_non_root", None)
            mounts = item.get("volume_mount")
            if isinstance(mounts, list):
                item["volume_mount"] = [
                    mount
                    for mount in mounts
                    if not isinstance(mount, dict)
                    or mount.get("name") not in {"identity-bridge", "runtime-state"}
                ]
            retained.append(item)
        spec[container_key] = retained
    volumes = spec.get("volume")
    if isinstance(volumes, list):
        spec["volume"] = [
            volume
            for volume in volumes
            if not isinstance(volume, dict)
            or volume.get("name") not in {"identity-bridge", "runtime-state"}
        ]
        for volume in spec["volume"]:
            if not isinstance(volume, dict):
                continue
            csi = volume.get("csi")
            if (
                isinstance(csi, list)
                and len(csi) == 1
                and isinstance(csi[0], dict)
                and csi[0].get("fs_type") in (None, "")
            ):
                csi[0].pop("fs_type", None)
            empty_dir = volume.get("empty_dir")
            if (
                isinstance(empty_dir, list)
                and len(empty_dir) == 1
                and isinstance(empty_dir[0], dict)
                and empty_dir[0].get("medium") in (None, "")
            ):
                empty_dir[0].pop("medium", None)


def _terraform_runtime_container(value: dict[str, Any], name: str) -> dict[str, Any]:
    containers = _mapping(_terraform_template(value).get("spec", [{}])[0], "planned Pod spec").get(
        "container"
    )
    if not isinstance(containers, list):
        raise ValueError("historical AKS planned containers are invalid")
    selected = [item for item in containers if isinstance(item, dict) and item.get("name") == name]
    if len(selected) != 1:
        raise ValueError("historical AKS planned runtime container is invalid")
    return dict(selected[0])


def _terraform_template(value: dict[str, Any]) -> dict[str, Any]:
    spec = value.get("spec")
    if not isinstance(spec, list) or len(spec) != 1 or not isinstance(spec[0], dict):
        raise ValueError("historical AKS planned workload spec is invalid")
    template = spec[0].get("template")
    if not isinstance(template, list) or len(template) != 1 or not isinstance(template[0], dict):
        raise ValueError("historical AKS planned Pod template is invalid")
    return template[0]


def _terraform_template_metadata(value: dict[str, Any]) -> dict[str, Any]:
    metadata = _terraform_template(value).get("metadata")
    if not isinstance(metadata, list) or len(metadata) != 1 or not isinstance(metadata[0], dict):
        raise ValueError("historical AKS planned Pod metadata is invalid")
    return metadata[0]


def _pod_spec(deployment: dict[str, Any]) -> dict[str, Any]:
    try:
        value = deployment["spec"]["template"]["spec"]
    except (KeyError, TypeError) as exc:
        raise ValueError("historical AKS live Pod spec is invalid") from exc
    return _mapping(value, "historical AKS live Pod spec")


def _indexed_name(address: str, prefix: str) -> str | None:
    match = re.fullmatch(rf'{re.escape(prefix)}\["([^"\\]+)"\]', address)
    return match.group(1) if match is not None else None


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is invalid")
    return value
