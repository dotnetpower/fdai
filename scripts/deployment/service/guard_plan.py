#!/usr/bin/env python3
"""Reject unsafe or cross-service actions in a service Terraform plan."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from service_contract import (
    ServiceContract,
    ServiceContractError,
    resolve_service,
)


class PlanGuardError(ValueError):
    """Raised when a Terraform plan exceeds one service's resource boundary."""


_DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")
_ALLOWED_SIDECARS = {
    "document-processing-worker": frozenset({"clamav"}),
}
_OPERATOR_CHANNEL_EDGE_ADDRESS = (
    "module.operator_service.module.channel_edge[0].azurerm_container_app.service"
)
_OPERATOR_CHANNEL_EDGE_CONTRACT_ADDRESS = (
    "module.operator_service.terraform_data.channel_edge_contract[0]"
)
_OPERATOR_CHANNEL_EDGE_REQUIRED_ENVIRONMENT = frozenset(
    {
        "FDAI_DATABASE_URL",
        "FDAI_DATABASE_ROLE",
        "FDAI_EXECUTION_VENUE",
        "RUNTIME_ENV",
        "FDAI_CHANNEL_EDGE_MI_CLIENT_ID",
        "FDAI_CHANNEL_EDGE_ENABLED_CHANNELS",
        "FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON",
        "FDAI_KAFKA_BOOTSTRAP_SERVERS",
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC",
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC",
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC",
        "FDAI_CHANNEL_EDGE_PORT",
    }
)
_OPERATOR_CHANNEL_EDGE_FORBIDDEN_ENVIRONMENT = frozenset(
    {
        "FDAI_COMMAND_MI_CLIENT_ID",
        "FDAI_DEV_OPERATIONS_GATEWAY_URL",
        "FDAI_ISOLATED_EXECUTOR_MI_CLIENT_ID",
        "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER",
    }
)
_MODEL_BINDING_ENVIRONMENT = frozenset(
    {
        "FDAI_LLM_ENDPOINT",
        "FDAI_MODEL_ENDPOINTS_JSON",
        "FDAI_WEB_SEARCH_ALLOWED_DOMAINS",
        "FDAI_WEB_SEARCH_ENABLED",
        "FDAI_WEB_SEARCH_MAX_RESULTS",
        "FDAI_WEB_SEARCH_TIMEOUT_SECONDS",
        "LLM_MODE",
        "LLM_RESOLVED_MODELS_PATH",
        "LLM_RESOLVED_MODELS_SHA256",
    }
)
_OPERATOR_RUNTIME_BINDINGS = {
    "FDAI_HIL_DECISION_TOPIC": "fdai.hil.decisions",
    "FDAI_INCIDENT_INTERVENTION_REQUEST_TOPIC": "operator.incident-intervention.requests",
    "FDAI_NOTIFICATION_RECEIPT_TOPIC": "fdai.notifications.delivery-receipts",
    "FDAI_READ_INVESTIGATION_COMPLETION_CONSUMER_GROUP_ID": (
        "operator-read-investigation-completion-v1"
    ),
    "FDAI_READ_INVESTIGATION_COMPLETION_TOPIC": "core.read-investigation.completions",
    "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": "operator.read-investigation.requests",
    "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "core.semantic-turn.projections",
    "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.semantic-turn.requests",
}
_SHAREPOINT_CONNECTOR_ENVIRONMENT = frozenset(
    {
        "FDAI_SHAREPOINT_ACCESS_DESCRIPTOR_REF",
        "FDAI_SHAREPOINT_CLIENT_ID",
        "FDAI_SHAREPOINT_COLLECTION_ID",
        "FDAI_SHAREPOINT_CONNECTOR_ENABLED",
        "FDAI_SHAREPOINT_CONNECTOR_ID",
        "FDAI_SHAREPOINT_DOWNLOAD_HOST_SUFFIXES",
        "FDAI_SHAREPOINT_DRIVE_ID",
        "FDAI_SHAREPOINT_PURPOSES",
        "FDAI_SHAREPOINT_READER_GROUPS",
        "FDAI_SHAREPOINT_RETENTION_POLICY_VERSION",
        "FDAI_SHAREPOINT_SITE_ID",
        "FDAI_SHAREPOINT_TARGET_TENANT_ID",
    }
)
_SHAREPOINT_PURPOSES = frozenset(
    {
        "handover_bootstrap",
        "handover_evidence",
        "knowledge_base",
        "manual_distillation",
    }
)
_RCA_READER_ENVIRONMENT = frozenset({"FDAI_RCA_AZURE_READER_CLIENT_ID"})
_NOTIFICATION_RECEIPT_TOPIC = "fdai.notifications.delivery-receipts"


def _operator_channel_edge_contract(base: ServiceContract) -> ServiceContract:
    return ServiceContract(
        service="operator-channel-edge",
        environment=base.environment,
        terraform_root=base.terraform_root,
        backend_key=base.backend_key,
        allowed_resource_address=_OPERATOR_CHANNEL_EDGE_ADDRESS,
        image_repository=base.image_repository,
        entrypoint="fdai-operator-channel-edge",
        required_environment=tuple(sorted(_OPERATOR_CHANNEL_EDGE_REQUIRED_ENVIRONMENT)),
    )


def _difference_paths(before: Any, after: Any, *, path: str = "$") -> list[str]:
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        paths: list[str] = []
        for key in sorted(set(before) | set(after)):
            nested = f"{path}.{key}"
            if key not in before or key not in after:
                paths.append(nested)
            else:
                paths.extend(_difference_paths(before[key], after[key], path=nested))
        return paths
    if isinstance(before, list):
        paths = [path] if len(before) != len(after) else []
        for index, (left, right) in enumerate(zip(before, after, strict=False)):
            paths.extend(_difference_paths(left, right, path=f"{path}[{index}]"))
        return paths
    return [] if before == after else [path]


def _actions(change: Any, *, address: str) -> tuple[str, ...]:
    if not isinstance(change, dict) or not isinstance(change.get("actions"), list):
        raise PlanGuardError(f"plan change for {address} has no action list")
    actions = tuple(change["actions"])
    if not all(isinstance(action, str) for action in actions):
        raise PlanGuardError(f"plan change for {address} has an invalid action")
    return actions


def _planned_image(
    change: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> str:
    image = _primary_container(
        _resource(change, side="after", address=address),
        address=address,
        contract=contract,
    ).get("image")
    if not isinstance(image, str):
        raise PlanGuardError(f"resource at {address} has no container image")
    return image


def _resource(change: dict[str, Any], *, side: str, address: str) -> dict[str, Any]:
    resource = change.get(side)
    if not isinstance(resource, dict):
        raise PlanGuardError(f"plan change for {address} has no {side} resource")
    return resource


def _containers(resource: dict[str, Any], *, address: str) -> dict[str, dict[str, Any]]:
    templates = resource.get("template")
    if not isinstance(templates, list) or len(templates) != 1:
        raise PlanGuardError(f"resource at {address} has an invalid template")
    containers = templates[0].get("container") if isinstance(templates[0], dict) else None
    if not isinstance(containers, list) or not containers:
        raise PlanGuardError(f"resource at {address} has no containers")
    result: dict[str, dict[str, Any]] = {}
    for container in containers:
        if not isinstance(container, dict):
            raise PlanGuardError(f"resource at {address} has an invalid container")
        name = container.get("name")
        image = container.get("image")
        if not isinstance(name, str) or not name or name in result:
            raise PlanGuardError(f"resource at {address} has invalid container names")
        if not isinstance(image, str) or not image:
            raise PlanGuardError(f"container {name} at {address} has no image")
        result[name] = container
    return result


def _container_layout(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    containers = _containers(resource, address=address)
    expected_sidecars = _ALLOWED_SIDECARS.get(contract.service, frozenset())
    primary_names = set(containers) - expected_sidecars
    if len(primary_names) != 1 or set(containers) != primary_names | expected_sidecars:
        raise PlanGuardError(
            f"resource at {address} must contain one primary and the exact allowed sidecar set"
        )
    primary = containers[primary_names.pop()]
    sidecars = {name: containers[name] for name in expected_sidecars}
    return primary, sidecars


def _primary_container(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> dict[str, Any]:
    primary, _ = _container_layout(resource, address=address, contract=contract)
    return primary


def _guard_sidecars(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> list[str]:
    _, sidecars = _container_layout(resource, address=address, contract=contract)
    violations: list[str] = []
    for name, sidecar in sidecars.items():
        image = sidecar.get("image")
        if not isinstance(image, str) or _DIGEST_IMAGE.fullmatch(image) is None:
            violations.append(f"sidecar {name} image is not immutable at {address}")
        probes: dict[str, dict[str, Any]] = {}
        for probe_name in ("startup_probe", "liveness_probe", "readiness_probe"):
            raw_probe = sidecar.get(probe_name)
            if (
                not isinstance(raw_probe, list)
                or len(raw_probe) != 1
                or not isinstance(raw_probe[0], dict)
            ):
                violations.append(f"sidecar {name} has invalid {probe_name} at {address}")
                continue
            probes[probe_name] = raw_probe[0]
        if len(probes) != 3:
            continue
        ports = {probe.get("port") for probe in probes.values()}
        if (
            len(ports) != 1
            or not all(
                isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536
                for port in ports
            )
            or not all(probe.get("transport") == "TCP" for probe in probes.values())
            or probes["startup_probe"].get("failure_count_threshold") != 30
        ):
            violations.append(f"sidecar {name} probe contract changed at {address}")
    return violations


def _identity_ids(resource: dict[str, Any], *, address: str) -> frozenset[str]:
    identities = resource.get("identity")
    if not isinstance(identities, list) or len(identities) != 1:
        raise PlanGuardError(f"resource at {address} must contain one identity block")
    identity = identities[0]
    raw_ids = identity.get("identity_ids") if isinstance(identity, dict) else None
    if (
        not isinstance(raw_ids, list)
        or not raw_ids
        or not all(isinstance(identity_id, str) and identity_id for identity_id in raw_ids)
    ):
        raise PlanGuardError(f"resource at {address} has invalid workload identities")
    return frozenset(raw_ids)


def _runtime_contract(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> dict[str, Any]:
    container = _primary_container(resource, address=address, contract=contract)
    return {key: container.get(key) for key in ("name", "command", "args", "env")}


def _runtime_contract_by_name(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> dict[str, Any]:
    container = _primary_container(resource, address=address, contract=contract)
    environment = _environment_by_name(container, address=address)
    return {
        "name": container.get("name"),
        "command": container.get("command"),
        "args": container.get("args"),
        "env": {name: _environment_binding(item) for name, item in sorted(environment.items())},
    }


def _runtime_contract_drift_names(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> tuple[str, ...]:
    before_runtime = _runtime_contract_by_name(before, address=address, contract=contract)
    after_runtime = _runtime_contract_by_name(after, address=address, contract=contract)
    changed = [
        key for key in ("name", "command", "args") if before_runtime[key] != after_runtime[key]
    ]
    before_environment = before_runtime["env"]
    after_environment = after_runtime["env"]
    if not isinstance(before_environment, dict) or not isinstance(after_environment, dict):
        raise PlanGuardError(f"resource at {address} has an invalid normalized environment")
    changed.extend(
        f"env:{name}"
        for name in sorted(set(before_environment) | set(after_environment))
        if before_environment.get(name) != after_environment.get(name)
    )
    return tuple(changed)


def _sort_primary_environment(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> dict[str, Any]:
    normalized = copy.deepcopy(resource)
    container = _primary_container(normalized, address=address, contract=contract)
    environment = container.get("env")
    if not isinstance(environment, list):
        raise PlanGuardError(f"resource at {address} has an invalid environment")
    container["env"] = sorted(
        environment,
        key=lambda item: str(item.get("name")) if isinstance(item, dict) else "",
    )
    return normalized


def _environment_by_name(container: dict[str, Any], *, address: str) -> dict[str, dict[str, Any]]:
    environment = container.get("env")
    if not isinstance(environment, list):
        raise PlanGuardError(f"resource at {address} has an invalid environment")
    result: dict[str, dict[str, Any]] = {}
    for item in environment:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name or name in result:
            raise PlanGuardError(f"resource at {address} has invalid environment names")
        result[name] = item
    return result


def _environment_binding(item: dict[str, Any] | None) -> tuple[Any, Any] | None:
    if item is None:
        return None
    secret_name = item.get("secret_name")
    normalized_secret = None if secret_name in (None, "") else secret_name
    return (
        None if normalized_secret is not None else item.get("value"),
        normalized_secret,
    )


def _sharepoint_connector_bindings_are_valid(
    environment: dict[str, dict[str, Any]],
) -> bool:
    bindings = {
        name: _environment_binding(environment.get(name))
        for name in _SHAREPOINT_CONNECTOR_ENVIRONMENT
    }
    if set(environment) & _SHAREPOINT_CONNECTOR_ENVIRONMENT != _SHAREPOINT_CONNECTOR_ENVIRONMENT:
        return False
    if bindings["FDAI_SHAREPOINT_CONNECTOR_ENABLED"] != ("1", None):
        return False
    values: dict[str, str] = {}
    for name, binding in bindings.items():
        if binding is None or binding[1] is not None or not isinstance(binding[0], str):
            return False
        values[name] = binding[0].strip()
    required = _SHAREPOINT_CONNECTOR_ENVIRONMENT - {"FDAI_SHAREPOINT_READER_GROUPS"}
    if any(not values[name] for name in required):
        return False
    if any(len(value) > 4096 for value in values.values()):
        return False
    try:
        UUID(values["FDAI_SHAREPOINT_TARGET_TENANT_ID"])
        UUID(values["FDAI_SHAREPOINT_CLIENT_ID"])
    except ValueError:
        return False
    purposes = values["FDAI_SHAREPOINT_PURPOSES"].split(",")
    if (
        not purposes
        or len(purposes) != len(set(purposes))
        or any(purpose not in _SHAREPOINT_PURPOSES for purpose in purposes)
    ):
        return False
    suffixes = values["FDAI_SHAREPOINT_DOWNLOAD_HOST_SUFFIXES"].split(",")
    return (
        bool(suffixes)
        and len(suffixes) == len(set(suffixes))
        and all(
            re.fullmatch(r"\.sharepoint\.(?:com|cn|de|us)", suffix) is not None
            for suffix in suffixes
        )
    )


def _guard_sharepoint_connector_transition(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
    transition: str,
) -> list[str]:
    violations: list[str] = []
    before_environment = _environment_by_name(
        _primary_container(before, address=address, contract=contract),
        address=address,
    )
    after_environment = _environment_by_name(
        _primary_container(after, address=address, contract=contract),
        address=address,
    )
    source = before_environment if transition == "enable" else after_environment
    target = after_environment if transition == "enable" else before_environment
    if set(source) & _SHAREPOINT_CONNECTOR_ENVIRONMENT:
        violations.append(f"SharePoint connector {transition} source is not clean at {address}")
    if set(target) & _SHAREPOINT_CONNECTOR_ENVIRONMENT != _SHAREPOINT_CONNECTOR_ENVIRONMENT:
        violations.append(f"SharePoint connector {transition} bindings are incomplete at {address}")
    elif not _sharepoint_connector_bindings_are_valid(target):
        violations.append(f"SharePoint connector {transition} bindings are invalid at {address}")
    source_without_connector = {
        name: _environment_binding(item)
        for name, item in source.items()
        if name not in _SHAREPOINT_CONNECTOR_ENVIRONMENT
    }
    target_without_connector = {
        name: _environment_binding(item)
        for name, item in target.items()
        if name not in _SHAREPOINT_CONNECTOR_ENVIRONMENT
    }
    if source_without_connector != target_without_connector:
        violations.append(f"unrelated environment drift during SharePoint connector {transition}")
    return violations


def _only_rca_reader_runtime_transition(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> bool:
    before_runtime = _runtime_contract(before, address=address, contract=contract)
    after_runtime = _runtime_contract(after, address=address, contract=contract)
    before_environment = before_runtime.get("env")
    after_environment = after_runtime.get("env")
    if not isinstance(before_environment, list) or not isinstance(after_environment, list):
        return False
    normalized_after = [
        item
        for item in after_environment
        if not (isinstance(item, dict) and item.get("name") in _RCA_READER_ENVIRONMENT)
    ]
    return {
        **after_runtime,
        "env": normalized_after,
    } == before_runtime


def _only_notification_receipt_topic_transition(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
    additional_allowed_names: frozenset[str] = frozenset(),
) -> bool:
    if contract.service != "core-control-plane":
        return False
    before_runtime = _runtime_contract(before, address=address, contract=contract)
    after_runtime = _runtime_contract(after, address=address, contract=contract)
    before_environment = before_runtime.get("env")
    after_environment = after_runtime.get("env")
    if not isinstance(before_environment, list) or not isinstance(after_environment, list):
        return False
    before_by_name = _environment_by_name(
        _primary_container(before, address=address, contract=contract),
        address=address,
    )
    after_by_name = _environment_by_name(
        _primary_container(after, address=address, contract=contract),
        address=address,
    )
    if not _has_canonical_notification_receipt_topic(after_by_name):
        return False
    if any(
        before_runtime.get(key) != after_runtime.get(key) for key in ("name", "command", "args")
    ):
        return False
    before_bindings = {
        name: _environment_binding(item)
        for name, item in before_by_name.items()
        if name not in {"FDAI_NOTIFICATION_RECEIPT_TOPIC", *additional_allowed_names}
    }
    after_bindings = {
        name: _environment_binding(item)
        for name, item in after_by_name.items()
        if name not in {"FDAI_NOTIFICATION_RECEIPT_TOPIC", *additional_allowed_names}
    }
    return before_bindings == after_bindings


def _has_canonical_notification_receipt_topic(
    environment: dict[str, dict[str, Any]],
) -> bool:
    return _environment_binding(environment.get("FDAI_NOTIFICATION_RECEIPT_TOPIC")) == (
        _NOTIFICATION_RECEIPT_TOPIC,
        None,
    )


def _valid_https_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip().rstrip("/"))
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and parsed.path == ""
        and parsed.query == ""
        and parsed.fragment == ""
        and port != 0
        and "\\" not in value
        and not any(character.isspace() for character in value)
    )


def _valid_web_search_domains(value: str) -> bool:
    domains = [] if value == "" else value.split(",")
    return (
        len(domains) <= 100
        and len(domains) == len(set(domains))
        and all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", domain) is not None
            and ".." not in domain
            and all(len(label) <= 63 for label in domain.split("."))
            for domain in domains
        )
    )


def _valid_model_endpoints(value: str, *, primary_endpoint: str) -> bool:
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return False
    if not isinstance(raw, dict) or not 1 <= len(raw) <= 16:
        return False
    primary_matches = 0
    for reference, endpoint in raw.items():
        if not isinstance(reference, str) or not isinstance(endpoint, str):
            return False
        if reference.startswith("azure-openai:"):
            prefix = "azure-openai:"
            suffix = ".openai.azure.com"
        elif reference.startswith("azure-foundry:"):
            prefix = "azure-foundry:"
            suffix = ".services.ai.azure.com"
        else:
            return False
        if not _valid_https_origin(endpoint):
            return False
        parsed = urlsplit(endpoint.strip().rstrip("/"))
        hostname = (parsed.hostname or "").lower()
        if not hostname.endswith(suffix):
            return False
        account = hostname.removesuffix(suffix)
        if not account or reference != f"{prefix}{account}":
            return False
        if prefix == "azure-openai:" and endpoint.rstrip("/") == primary_endpoint.rstrip("/"):
            primary_matches += 1
    return primary_matches == 1


def _guard_database_host_binding(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
    additional_allowed_names: frozenset[str] = frozenset(),
) -> list[str]:
    before_primary = _primary_container(before, address=address, contract=contract)
    after_primary = _primary_container(after, address=address, contract=contract)
    if any(
        before_primary.get(key) != after_primary.get(key) for key in ("name", "command", "args")
    ):
        return [f"database host binding changes the service command at {address}"]
    before_environment = _environment_by_name(before_primary, address=address)
    after_environment = _environment_by_name(after_primary, address=address)
    changed_names = {
        name
        for name in set(before_environment) | set(after_environment)
        if _environment_binding(before_environment.get(name))
        != _environment_binding(after_environment.get(name))
    }
    operator_runtime_bindings = {
        name
        for name in changed_names
        if contract.service == "operator-service"
        and _environment_binding(after_environment.get(name))
        == (_OPERATOR_RUNTIME_BINDINGS.get(name), None)
        and name in _OPERATOR_RUNTIME_BINDINGS
    }
    unexpected = sorted(
        changed_names.difference(
            {"POSTGRES_HOST"} | additional_allowed_names | operator_runtime_bindings
        )
    )
    host_binding = _environment_binding(after_environment.get("POSTGRES_HOST"))
    violations: list[str] = []
    if unexpected:
        violations.append(
            f"database host binding changes unapproved environment at {address}: "
            f"unexpected={unexpected}"
        )
    if (
        host_binding is None
        or not isinstance(host_binding[0], str)
        or not host_binding[0].strip()
        or host_binding[1] is not None
    ):
        violations.append(f"database host binding is invalid at {address}")
    return violations


def _guard_model_binding_transition(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
    resolved_models_digest: str,
    additional_allowed_names: frozenset[str] = frozenset(),
) -> list[str]:
    if contract.service != "core-control-plane":
        return ["model binding transition is valid only for the Core control plane"]
    if re.fullmatch(r"[0-9a-f]{64}", resolved_models_digest) is None:
        return ["model binding transition requires one attested resolved-models digest"]
    before_primary = _primary_container(before, address=address, contract=contract)
    after_primary = _primary_container(after, address=address, contract=contract)
    before_environment = _environment_by_name(before_primary, address=address)
    after_environment = _environment_by_name(after_primary, address=address)
    changed = {
        name
        for name in set(before_environment) | set(after_environment)
        if _environment_binding(before_environment.get(name))
        != _environment_binding(after_environment.get(name))
    }
    expected = {
        "LLM_MODE": ("azure", None),
        "LLM_RESOLVED_MODELS_PATH": ("/app/resolved-models.json", None),
        "LLM_RESOLVED_MODELS_SHA256": (resolved_models_digest, None),
    }
    invalid = sorted(
        name
        for name, binding in expected.items()
        if _environment_binding(after_environment.get(name)) != binding
    )
    endpoint_binding = _environment_binding(after_environment.get("FDAI_LLM_ENDPOINT"))
    endpoint, endpoint_secret = endpoint_binding or (None, None)
    model_endpoints_binding = _environment_binding(
        after_environment.get("FDAI_MODEL_ENDPOINTS_JSON")
    )
    model_endpoints, model_endpoints_secret = model_endpoints_binding or (None, None)
    web_enabled_binding = _environment_binding(after_environment.get("FDAI_WEB_SEARCH_ENABLED"))
    web_enabled, web_enabled_secret = web_enabled_binding or (None, None)
    domains_binding = _environment_binding(after_environment.get("FDAI_WEB_SEARCH_ALLOWED_DOMAINS"))
    allowed_domains, domains_secret = domains_binding or (None, None)
    max_results_binding = _environment_binding(after_environment.get("FDAI_WEB_SEARCH_MAX_RESULTS"))
    max_results, max_results_secret = max_results_binding or (None, None)
    timeout_binding = _environment_binding(after_environment.get("FDAI_WEB_SEARCH_TIMEOUT_SECONDS"))
    timeout_seconds, timeout_secret = timeout_binding or (None, None)
    if (
        endpoint_secret is not None
        or endpoint is None
        or not isinstance(endpoint, str)
        or not _valid_https_origin(endpoint)
    ):
        invalid.append("FDAI_LLM_ENDPOINT")
    if (
        model_endpoints_secret is not None
        or not isinstance(model_endpoints, str)
        or not isinstance(endpoint, str)
        or not _valid_model_endpoints(model_endpoints, primary_endpoint=endpoint)
    ):
        invalid.append("FDAI_MODEL_ENDPOINTS_JSON")
    if web_enabled_secret is not None or web_enabled not in {"true", "false"}:
        invalid.append("FDAI_WEB_SEARCH_ENABLED")
    if (
        domains_secret is not None
        or not isinstance(allowed_domains, str)
        or not _valid_web_search_domains(allowed_domains)
    ):
        invalid.append("FDAI_WEB_SEARCH_ALLOWED_DOMAINS")
    elif web_enabled == "true" and not allowed_domains:
        invalid.append("FDAI_WEB_SEARCH_ALLOWED_DOMAINS")
    try:
        valid_max_results = (
            max_results_secret is None and max_results is not None and 1 <= int(max_results) <= 20
        )
    except ValueError:
        valid_max_results = False
    if not valid_max_results:
        invalid.append("FDAI_WEB_SEARCH_MAX_RESULTS")
    try:
        valid_timeout = (
            timeout_secret is None
            and timeout_seconds is not None
            and 0.1 <= float(timeout_seconds) <= 90
        )
    except ValueError:
        valid_timeout = False
    if not valid_timeout:
        invalid.append("FDAI_WEB_SEARCH_TIMEOUT_SECONDS")
    violations: list[str] = []
    if not changed.intersection(_MODEL_BINDING_ENVIRONMENT):
        violations.append("model binding transition does not change a runtime model binding")
    allowed_names = _MODEL_BINDING_ENVIRONMENT | additional_allowed_names
    if changed - allowed_names:
        violations.append(
            f"model binding transition changes unapproved environment at {address}: "
            f"{sorted(changed - allowed_names)!r}"
        )
    if invalid:
        violations.append(
            f"model binding transition has invalid environment at {address}: {invalid!r}"
        )
    return violations


def _authority_cutover(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> str | None:
    environment = _primary_container(resource, address=address, contract=contract).get("env")
    if not isinstance(environment, list):
        raise PlanGuardError(f"resource at {address} has an invalid environment")
    values = {
        item.get("name"): item.get("value")
        for item in environment
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    value = values.get("FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER")
    return value if isinstance(value, str) else None


def _resource_ids(value: Any) -> frozenset[str]:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif isinstance(item, str) and item.lower().startswith("/subscriptions/"):
            found.add(item.lower())

    visit(value)
    return frozenset(found)


def _secret_ids(resource: dict[str, Any]) -> frozenset[str]:
    raw_secrets = resource.get("secret", [])
    if not isinstance(raw_secrets, list):
        raise PlanGuardError("service secret contract is invalid")
    return frozenset(
        secret_id
        for secret in raw_secrets
        if isinstance(secret, dict)
        and isinstance((secret_id := secret.get("key_vault_secret_id")), str)
        and secret_id
    )


def _guard_initial_cutover(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> list[str]:
    violations: list[str] = []
    before_primary, before_sidecars = _container_layout(before, address=address, contract=contract)
    after_primary, after_sidecars = _container_layout(after, address=address, contract=contract)
    before_image = before_primary.get("image")
    if not isinstance(before_image, str) or _DIGEST_IMAGE.fullmatch(before_image) is None:
        violations.append(f"initial cutover rollback image is not immutable at {address}")
    if _runtime_contract(before, address=address, contract=contract) == _runtime_contract(
        after, address=address, contract=contract
    ):
        violations.append(f"initial cutover has no legacy runtime transition at {address}")

    before_resources = {
        key: before_primary.get(key) for key in ("cpu", "memory", "ephemeral_storage")
    }
    after_resources = {
        key: after_primary.get(key) for key in ("cpu", "memory", "ephemeral_storage")
    }
    if before_resources != after_resources:
        violations.append(f"initial cutover changes service resource limits at {address}")

    for name, after_sidecar in after_sidecars.items():
        before_sidecar = before_sidecars[name]
        if before_sidecar.get("image") != after_sidecar.get("image"):
            violations.append(f"initial cutover changes sidecar {name} image at {address}")
        probe_fields = {"startup_probe", "liveness_probe", "readiness_probe"}
        before_config = {
            key: value for key, value in before_sidecar.items() if key not in probe_fields
        }
        after_config = {
            key: value for key, value in after_sidecar.items() if key not in probe_fields
        }
        if before_config != after_config:
            violations.append(f"initial cutover changes sidecar {name} config at {address}")

    before_secret_ids = _secret_ids(before)
    after_secret_ids = _secret_ids(after)
    if not after_secret_ids or not after_secret_ids <= before_secret_ids:
        violations.append(f"initial cutover adds an unbound secret at {address}")

    before_tags = before.get("tags")
    after_tags = after.get("tags")
    if not isinstance(before_tags, dict) or not isinstance(after_tags, dict):
        violations.append(f"initial cutover tags are invalid at {address}")
    else:
        allowed_tag_changes = {
            "fdai:component",
            "fdai:rollback-strategy",
            "fdai:authority-cutover",
        }
        changed_tags = {
            key
            for key in set(before_tags) | set(after_tags)
            if before_tags.get(key) != after_tags.get(key)
        }
        if not changed_tags <= allowed_tag_changes:
            violations.append(f"initial cutover changes unapproved tags at {address}")
        if after_tags.get("fdai:component") != contract.service:
            violations.append(f"initial cutover component tag is invalid at {address}")
        if after_tags.get("fdai:rollback-strategy") not in {
            "previous-revision",
            "image-redeploy",
        }:
            violations.append(f"initial cutover rollback tag is invalid at {address}")

    expected = copy.deepcopy(before)
    expected["tags"] = copy.deepcopy(after.get("tags"))
    expected["secret"] = copy.deepcopy(after.get("secret"))
    expected_primary = _primary_container(expected, address=address, contract=contract)
    expected_primary.clear()
    expected_primary.update(copy.deepcopy(after_primary))
    expected_containers = _containers(expected, address=address)
    for name, sidecar in after_sidecars.items():
        expected_containers[name].clear()
        expected_containers[name].update(copy.deepcopy(sidecar))
    expected_templates = expected.get("template")
    after_templates = after.get("template")
    if (
        isinstance(expected_templates, list)
        and len(expected_templates) == 1
        and isinstance(expected_templates[0], dict)
        and isinstance(after_templates, list)
        and len(after_templates) == 1
        and isinstance(after_templates[0], dict)
    ):
        before_suffix = expected_templates[0].get("revision_suffix")
        after_suffix = after_templates[0].get("revision_suffix")
        if before_suffix != after_suffix:
            if (
                not isinstance(after_suffix, str)
                or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?", after_suffix) is None
            ):
                violations.append(f"planned revision suffix is invalid at {address}")
            else:
                expected_templates[0]["revision_suffix"] = after_suffix
    if expected != after:
        violations.append(
            f"initial cutover changes fields outside its rollback boundary at {address}"
        )
    return violations


def _guard_update(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
    initial_cutover: bool,
    database_host_binding: bool = False,
    model_binding_transition: bool = False,
    resolved_models_digest: str = "",
    sharepoint_connector_transition: str = "none",
) -> list[str]:
    violations: list[str] = []
    for field in ("name", "resource_group_name"):
        if before.get(field) != after.get(field):
            violations.append(f"target resource identity drift at {address}: {field}")
    if before.get("container_app_environment_id") != after.get("container_app_environment_id"):
        violations.append(f"platform or peer resource identity drift at {address}")

    before_identities = _identity_ids(before, address=address)
    after_identities = _identity_ids(after, address=address)
    allowed_rca_reader = False
    if after_identities > before_identities:
        added = after_identities - before_identities
        after_container = _primary_container(after, address=address, contract=contract)
        after_environment = _environment_by_name(
            after_container,
            address=address,
        )
        rca_reader = _environment_binding(after_environment.get("FDAI_RCA_AZURE_READER_CLIENT_ID"))
        allowed_rca_reader = (
            contract.service == "core-control-plane"
            and len(added) == 1
            and next(iter(added)).casefold().endswith("-rca-reader")
            and rca_reader is not None
            and isinstance(rca_reader[0], str)
            and bool(rca_reader[0])
            and rca_reader[1] is None
        )
        if not allowed_rca_reader:
            violations.append(f"identity expansion at {address}")
    elif after_identities != before_identities:
        violations.append(f"workload identity drift at {address}")

    before_authority = _authority_cutover(before, address=address, contract=contract)
    after_authority = _authority_cutover(after, address=address, contract=contract)
    notification_companion_names = (
        _MODEL_BINDING_ENVIRONMENT if model_binding_transition else frozenset()
    )
    if database_host_binding:
        notification_companion_names |= frozenset({"POSTGRES_HOST"})
    if allowed_rca_reader:
        notification_companion_names |= _RCA_READER_ENVIRONMENT
    allowed_notification_topic = _only_notification_receipt_topic_transition(
        before,
        after,
        address=address,
        contract=contract,
        additional_allowed_names=notification_companion_names,
    )
    authority_removed_from_core = (
        initial_cutover
        and contract.service == "core-control-plane"
        and before_authority == "1"
        and after_authority is None
    )
    if before_authority != after_authority and not authority_removed_from_core:
        violations.append(f"authority cutover change at {address}")
    if database_host_binding:
        additional_host_names: frozenset[str] = frozenset()
        if model_binding_transition:
            additional_host_names |= _MODEL_BINDING_ENVIRONMENT
        if allowed_rca_reader:
            additional_host_names |= _RCA_READER_ENVIRONMENT
        violations.extend(
            _guard_database_host_binding(
                before,
                after,
                address=address,
                contract=contract,
                additional_allowed_names=additional_host_names,
            )
        )
    if sharepoint_connector_transition != "none":
        violations.extend(
            _guard_sharepoint_connector_transition(
                before,
                after,
                address=address,
                contract=contract,
                transition=sharepoint_connector_transition,
            )
        )
    if model_binding_transition:
        model_additional_names: frozenset[str] = frozenset()
        if database_host_binding:
            model_additional_names |= frozenset({"POSTGRES_HOST"})
        if allowed_rca_reader:
            model_additional_names |= _RCA_READER_ENVIRONMENT
        after_environment = _environment_by_name(
            _primary_container(after, address=address, contract=contract),
            address=address,
        )
        if allowed_notification_topic or _has_canonical_notification_receipt_topic(
            after_environment
        ):
            model_additional_names |= frozenset({"FDAI_NOTIFICATION_RECEIPT_TOPIC"})
        violations.extend(
            _guard_model_binding_transition(
                before,
                after,
                address=address,
                contract=contract,
                resolved_models_digest=resolved_models_digest,
                additional_allowed_names=model_additional_names,
            )
        )
    runtime_drift_names = _runtime_contract_drift_names(
        before,
        after,
        address=address,
        contract=contract,
    )
    if (
        not initial_cutover
        and not database_host_binding
        and not model_binding_transition
        and sharepoint_connector_transition == "none"
        and not (
            allowed_rca_reader
            and _only_rca_reader_runtime_transition(
                before,
                after,
                address=address,
                contract=contract,
            )
        )
        and not allowed_notification_topic
        and runtime_drift_names
    ):
        violations.append(
            f"command or environment drift at {address}: changed={list(runtime_drift_names)!r}"
        )

    before_resource_ids = _resource_ids(before)
    after_resource_ids = _resource_ids(after)
    if initial_cutover and after_resource_ids <= before_resource_ids:
        pass
    elif before_resource_ids != after_resource_ids and not (
        allowed_rca_reader
        and after_resource_ids - before_resource_ids
        == frozenset(identity.casefold() for identity in added)
    ):
        violations.append(f"platform or peer resource identity drift at {address}")
    before_tags = before.get("tags")
    after_tags = after.get("tags")
    if isinstance(before_tags, dict) and isinstance(after_tags, dict):
        before_authority_tag = before_tags.get("fdai:authority-cutover")
        after_authority_tag = after_tags.get("fdai:authority-cutover")
        aligned_executor_tag = (
            initial_cutover
            and contract.service == "isolated-executor"
            and before_authority == after_authority == "1"
            and before_authority_tag in (None, "true")
            and after_authority_tag == "true"
        )
        if before_authority_tag != after_authority_tag and not aligned_executor_tag:
            violations.append(f"authority cutover tag change at {address}")
    _, before_sidecars = _container_layout(before, address=address, contract=contract)
    _, after_sidecars = _container_layout(after, address=address, contract=contract)
    if before_sidecars != after_sidecars and not initial_cutover:
        violations.append(f"sidecar contract drift at {address}")
    if initial_cutover:
        violations.extend(_guard_initial_cutover(before, after, address=address, contract=contract))
        return violations
    expected_before = copy.deepcopy(before)
    expected_primary = _primary_container(expected_before, address=address, contract=contract)
    after_primary = _primary_container(after, address=address, contract=contract)
    expected_primary["image"] = _planned_image({"after": after}, address=address, contract=contract)
    if (
        database_host_binding
        or model_binding_transition
        or allowed_rca_reader
        or allowed_notification_topic
        or sharepoint_connector_transition != "none"
    ):
        expected_primary["env"] = copy.deepcopy(after_primary.get("env"))
    if allowed_rca_reader:
        expected_before["identity"] = copy.deepcopy(after.get("identity"))
    before_retention = expected_before.get("max_inactive_revisions")
    after_retention = after.get("max_inactive_revisions")
    if before_retention != after_retention:
        if before_retention in (None, 0) and after_retention == 1:
            expected_before["max_inactive_revisions"] = 1
        else:
            violations.append(f"rollback revision retention drift at {address}")
    expected_templates = expected_before.get("template")
    after_templates = after.get("template")
    if (
        not isinstance(expected_templates, list)
        or len(expected_templates) != 1
        or not isinstance(expected_templates[0], dict)
        or not isinstance(after_templates, list)
        or len(after_templates) != 1
        or not isinstance(after_templates[0], dict)
    ):
        raise PlanGuardError(f"resource at {address} has an invalid template")
    before_suffix = expected_templates[0].get("revision_suffix")
    after_suffix = after_templates[0].get("revision_suffix")
    if before_suffix != after_suffix:
        if (
            not isinstance(after_suffix, str)
            or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?", after_suffix) is None
        ):
            violations.append(f"planned revision suffix is invalid at {address}")
        expected_templates[0]["revision_suffix"] = after_suffix
    if _sort_primary_environment(
        expected_before,
        address=address,
        contract=contract,
    ) != _sort_primary_environment(after, address=address, contract=contract):
        violations.append(f"protected update changes fields rollback cannot prove at {address}")
    return violations


def _guard_service_runtime(
    resource: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
) -> list[str]:
    container = _primary_container(resource, address=address, contract=contract)
    violations: list[str] = []
    if container.get("command") != [contract.entrypoint] or container.get("args") not in ([], None):
        violations.append(f"planned command does not match the service entrypoint at {address}")
    environment = container.get("env")
    if not isinstance(environment, list):
        raise PlanGuardError(f"resource at {address} has an invalid environment")
    names = [item.get("name") for item in environment if isinstance(item, dict)]
    if len(names) != len(environment) or not all(isinstance(name, str) for name in names):
        raise PlanGuardError(f"resource at {address} has an invalid environment entry")
    if len(set(names)) != len(names):
        violations.append(f"planned environment contains duplicate names at {address}")
    missing = sorted(set(contract.required_environment) - set(names))
    if missing:
        violations.append(
            f"planned environment is missing required service names at {address}: {missing!r}"
        )
    tags = resource.get("tags")
    if not isinstance(tags, dict) or tags.get("fdai:component") != contract.service:
        violations.append(f"planned component tag does not match the selected service at {address}")
    violations.extend(_guard_sidecars(resource, address=address, contract=contract))
    return violations


def _guard_operator_channel_edge(
    resource: dict[str, Any],
    *,
    address: str,
    image_ref: str,
) -> list[str]:
    """Validate the no-authority public edge companion before protected creation."""
    violations: list[str] = []
    containers = _containers(resource, address=address)
    if set(containers) != {"operator-channel-edge"}:
        violations.append(f"channel edge must contain exactly one owned container at {address}")
        return violations
    container = containers["operator-channel-edge"]
    if container.get("image") != image_ref:
        violations.append(f"channel edge image does not match the attested image at {address}")
    if container.get("command") != ["fdai-operator-channel-edge"] or container.get("args") not in (
        [],
        None,
    ):
        violations.append(f"channel edge command is invalid at {address}")

    environment = container.get("env")
    if not isinstance(environment, list):
        raise PlanGuardError(f"channel edge at {address} has an invalid environment")
    names = [item.get("name") for item in environment if isinstance(item, dict)]
    if len(names) != len(environment) or not all(isinstance(name, str) for name in names):
        raise PlanGuardError(f"channel edge at {address} has an invalid environment entry")
    if len(set(names)) != len(names):
        violations.append(f"channel edge environment contains duplicate names at {address}")
    missing = sorted(_OPERATOR_CHANNEL_EDGE_REQUIRED_ENVIRONMENT - set(names))
    if missing:
        violations.append(f"channel edge environment is missing required names at {address}")
    forbidden = sorted(_OPERATOR_CHANNEL_EDGE_FORBIDDEN_ENVIRONMENT & set(names))
    if forbidden:
        violations.append(f"channel edge environment grants execution authority at {address}")

    identity_ids = _identity_ids(resource, address=address)
    if len(identity_ids) != 1:
        violations.append(f"channel edge must use one dedicated workload identity at {address}")
    else:
        identity_id = next(iter(identity_ids))
        registries = resource.get("registry")
        if (
            not isinstance(registries, list)
            or len(registries) != 1
            or not isinstance(registries[0], dict)
            or registries[0].get("identity") != identity_id
        ):
            violations.append(f"channel edge registry identity is not dedicated at {address}")
        secrets = resource.get("secret")
        if not isinstance(secrets, list) or len(secrets) < 2:
            violations.append(f"channel edge secret references are incomplete at {address}")
        elif any(
            not isinstance(secret, dict)
            or secret.get("identity") != identity_id
            or not isinstance(secret.get("key_vault_secret_id"), str)
            or not secret["key_vault_secret_id"]
            for secret in secrets
        ):
            violations.append(f"channel edge secret identity is not dedicated at {address}")

    ingress = resource.get("ingress")
    if (
        not isinstance(ingress, list)
        or len(ingress) != 1
        or not isinstance(ingress[0], dict)
        or ingress[0].get("external_enabled") is not True
        or ingress[0].get("allow_insecure_connections") is not False
        or ingress[0].get("target_port") != 8014
    ):
        violations.append(f"channel edge ingress contract is invalid at {address}")
    expected_probes = {
        "startup_probe": ("/health/ready", 30),
        "liveness_probe": ("/health/live", 3),
        "readiness_probe": ("/health/ready", 3),
    }
    for probe_name, (path, failure_count) in expected_probes.items():
        probes = container.get(probe_name)
        if (
            not isinstance(probes, list)
            or len(probes) != 1
            or not isinstance(probes[0], dict)
            or probes[0].get("transport") != "HTTP"
            or probes[0].get("port") != 8014
            or probes[0].get("path") != path
            or probes[0].get("failure_count_threshold") != failure_count
        ):
            violations.append(f"channel edge {probe_name} contract is invalid at {address}")
    tags = resource.get("tags")
    if not isinstance(tags, dict) or tags.get("fdai:component") != "operator-channel-edge":
        violations.append(f"channel edge component tag is invalid at {address}")
    return violations


def _guard_initial_worker_drift(
    resource_drift: Any,
    *,
    contract: ServiceContract,
    planned_resource: dict[str, Any],
) -> bool:
    if contract.service != "document-processing-worker":
        return False
    if not isinstance(resource_drift, list) or len(resource_drift) != 1:
        return False
    entry = resource_drift[0]
    if not isinstance(entry, dict) or entry.get("address") != contract.allowed_resource_address:
        return False
    change = entry.get("change")
    if not isinstance(change, dict) or change.get("actions") != ["update"]:
        return False
    before = change.get("before")
    after = change.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    revision_only = copy.deepcopy(before)
    revision_only["latest_revision_name"] = after.get("latest_revision_name")
    if revision_only == after:
        return True
    try:
        before_primary, before_sidecars = _container_layout(
            before,
            address=contract.allowed_resource_address,
            contract=contract,
        )
        after_primary, after_sidecars = _container_layout(
            after,
            address=contract.allowed_resource_address,
            contract=contract,
        )
        _, planned_sidecars = _container_layout(
            planned_resource,
            address=contract.allowed_resource_address,
            contract=contract,
        )
    except PlanGuardError:
        return False
    if before_primary != after_primary:
        return False
    before_sidecar = before_sidecars.get("clamav")
    after_sidecar = after_sidecars.get("clamav")
    planned_sidecar = planned_sidecars.get("clamav")
    if (
        before_sidecar is None
        or after_sidecar is None
        or planned_sidecar is None
        or before_sidecar.get("image") != "clamav/clamav:stable"
        or not isinstance(after_sidecar.get("image"), str)
        or _DIGEST_IMAGE.fullmatch(after_sidecar["image"]) is None
        or after_sidecar.get("image") != planned_sidecar.get("image")
    ):
        return False
    expected = copy.deepcopy(before)
    expected["latest_revision_name"] = after.get("latest_revision_name")
    expected_templates = expected.get("template")
    after_templates = after.get("template")
    if (
        isinstance(expected_templates, list)
        and len(expected_templates) == 1
        and isinstance(expected_templates[0], dict)
        and isinstance(after_templates, list)
        and len(after_templates) == 1
        and isinstance(after_templates[0], dict)
    ):
        expected_templates[0]["revision_suffix"] = after_templates[0].get("revision_suffix")
    expected_sidecars = _container_layout(
        expected,
        address=contract.allowed_resource_address,
        contract=contract,
    )[1]
    expected_sidecars["clamav"]["image"] = after_sidecar["image"]
    return expected == after


def _guard_aligned_transition_drift(
    resource_drift: Any,
    *,
    contract: ServiceContract,
    planned_before: dict[str, Any],
) -> bool:
    if not isinstance(resource_drift, list) or len(resource_drift) != 1:
        return False
    entry = resource_drift[0]
    if not isinstance(entry, dict) or entry.get("address") != contract.allowed_resource_address:
        return False
    change = entry.get("change")
    return (
        isinstance(change, dict)
        and change.get("actions") == ["update"]
        and change.get("after") == planned_before
    )


def _guard_key_vault_secret_value_normalization_drift(
    resource_drift: Any,
    *,
    contract: ServiceContract,
) -> bool:
    """Accept only empty AzureRM value normalization on unchanged Key Vault secrets."""
    if not isinstance(resource_drift, list) or len(resource_drift) != 1:
        return False
    entry = resource_drift[0]
    if not isinstance(entry, dict) or entry.get("address") != contract.allowed_resource_address:
        return False
    change = entry.get("change")
    if not isinstance(change, dict) or change.get("actions") != ["update"]:
        return False
    before = change.get("before")
    after = change.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    paths = _difference_paths(before, after)
    if not paths or not all(re.fullmatch(r"\$\.secret\[\d+\]\.value", path) for path in paths):
        return False
    normalized_before = copy.deepcopy(before)
    normalized_after = copy.deepcopy(after)
    before_secrets = normalized_before.get("secret")
    after_secrets = normalized_after.get("secret")
    if (
        not isinstance(before_secrets, list)
        or not isinstance(after_secrets, list)
        or not before_secrets
        or len(before_secrets) != len(after_secrets)
    ):
        return False
    for before_secret, after_secret in zip(before_secrets, after_secrets, strict=True):
        if not isinstance(before_secret, dict) or not isinstance(after_secret, dict):
            return False
        before_value = before_secret.pop("value", None)
        after_value = after_secret.pop("value", None)
        if before_value not in (None, "") or after_value not in (None, ""):
            return False
        if (
            before_secret != after_secret
            or not isinstance(before_secret.get("key_vault_secret_id"), str)
            or not before_secret["key_vault_secret_id"]
        ):
            return False
    return normalized_before == normalized_after


def _guard_revision_metadata_drift(
    resource_drift: Any,
    *,
    contract: ServiceContract,
    planned_before: dict[str, Any] | None,
) -> bool:
    """Accept only computed revision metadata and an attested-image recovery alignment."""
    if not isinstance(resource_drift, list) or len(resource_drift) != 1:
        return False
    entry = resource_drift[0]
    if not isinstance(entry, dict) or entry.get("address") != contract.allowed_resource_address:
        return False
    change = entry.get("change")
    if not isinstance(change, dict) or change.get("actions") != ["update"]:
        return False
    before = change.get("before")
    after = change.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    paths = set(_difference_paths(before, after))
    allowed_paths = {
        "$.latest_revision_fqdn",
        "$.latest_revision_name",
        "$.template[0].revision_suffix",
    }
    if planned_before is not None:
        allowed_paths.add("$.template[0].container[0].image")
    if not paths or not paths <= allowed_paths:
        return False
    expected = copy.deepcopy(before)
    expected["latest_revision_fqdn"] = after.get("latest_revision_fqdn")
    expected["latest_revision_name"] = after.get("latest_revision_name")
    expected_templates = expected.get("template")
    after_templates = after.get("template")
    if (
        not isinstance(expected_templates, list)
        or len(expected_templates) != 1
        or not isinstance(expected_templates[0], dict)
        or not isinstance(after_templates, list)
        or len(after_templates) != 1
        or not isinstance(after_templates[0], dict)
    ):
        return False
    expected_templates[0]["revision_suffix"] = after_templates[0].get("revision_suffix")
    if "$.template[0].container[0].image" in paths:
        if planned_before is None:
            return False
        try:
            expected_primary = _container_layout(
                expected,
                address=contract.allowed_resource_address,
                contract=contract,
            )[0]
            after_primary = _container_layout(
                after,
                address=contract.allowed_resource_address,
                contract=contract,
            )[0]
            planned_primary = _container_layout(
                planned_before,
                address=contract.allowed_resource_address,
                contract=contract,
            )[0]
        except PlanGuardError:
            return False
        if after_primary.get("image") != planned_primary.get("image"):
            return False
        expected_primary["image"] = after_primary["image"]
    return expected == after


def validate_plan(
    payload: dict[str, Any],
    *,
    service: str,
    environment: str,
    image_ref: str,
    initial_cutover: bool = False,
    database_host_binding: bool = False,
    model_binding_transition: bool = False,
    resolved_models_digest: str = "",
    operator_channel_edge_transition: str = "none",
    sharepoint_connector_transition: str = "none",
) -> None:
    """Allow only bounded actions that deploy the exact attested service image."""
    if operator_channel_edge_transition not in {"none", "enable", "disable"}:
        raise PlanGuardError("operator channel edge transition must be none, enable, or disable")
    if operator_channel_edge_transition != "none" and service != "operator-service":
        raise PlanGuardError("operator channel edge transition is valid only for operator-service")
    if sharepoint_connector_transition not in {"none", "enable", "disable"}:
        raise PlanGuardError("SharePoint connector transition must be none, enable, or disable")
    if sharepoint_connector_transition != "none" and service != "document-ingestion-api":
        raise PlanGuardError(
            "SharePoint connector transitions are valid only for document-ingestion-api"
        )
    if sharepoint_connector_transition != "none" and (
        initial_cutover
        or database_host_binding
        or model_binding_transition
        or operator_channel_edge_transition != "none"
    ):
        raise PlanGuardError("SharePoint connector transition must be applied independently")
    if database_host_binding and (initial_cutover or operator_channel_edge_transition != "none"):
        raise PlanGuardError(
            "database host binding is exclusive with initial cutover and channel-edge transition"
        )
    if model_binding_transition and (
        service != "core-control-plane"
        or initial_cutover
        or operator_channel_edge_transition != "none"
    ):
        raise PlanGuardError(
            "model binding transition is Core-only and exclusive with "
            "initial cutover and channel-edge transition"
        )
    contract = resolve_service(service, environment)
    channel_edge_contract = _operator_channel_edge_contract(contract)
    resource_changes = payload.get("resource_changes", [])
    if not isinstance(resource_changes, list):
        raise PlanGuardError("Terraform plan resource_changes must be an array")
    violations: list[str] = []
    selected_after: dict[str, Any] | None = None
    selected_before: dict[str, Any] | None = None
    channel_edge_actions: dict[str, tuple[str, ...]] = {}
    for entry in resource_changes:
        if not isinstance(entry, dict) or not isinstance(entry.get("address"), str):
            raise PlanGuardError("Terraform plan contains an invalid resource change")
        address = entry["address"]
        change = entry.get("change")
        actions = _actions(change, address=address)
        if actions == ("no-op",):
            continue
        if address in {
            _OPERATOR_CHANNEL_EDGE_ADDRESS,
            _OPERATOR_CHANNEL_EDGE_CONTRACT_ADDRESS,
        }:
            channel_edge_actions[address] = actions
            expected_action = {
                "none": ("update",),
                "enable": ("create",),
                "disable": ("delete",),
            }[operator_channel_edge_transition]
            if address == _OPERATOR_CHANNEL_EDGE_CONTRACT_ADDRESS:
                if operator_channel_edge_transition == "none" or actions != expected_action:
                    violations.append(
                        "operator channel edge contract marker action "
                        f"{actions!r} is not an explicit transition at {address}"
                    )
                continue
            if actions != expected_action:
                violations.append(
                    f"operator channel edge action {actions!r} is not an explicit "
                    f"{operator_channel_edge_transition} at {address}"
                )
                continue
            if not isinstance(change, dict):
                raise PlanGuardError(f"plan change for {address} is invalid")
            if operator_channel_edge_transition == "enable":
                violations.extend(
                    _guard_operator_channel_edge(
                        _resource(change, side="after", address=address),
                        address=address,
                        image_ref=image_ref,
                    )
                )
            elif operator_channel_edge_transition == "disable":
                violations.extend(
                    _guard_operator_channel_edge(
                        _resource(change, side="before", address=address),
                        address=address,
                        image_ref=image_ref,
                    )
                )
            else:
                before = _resource(change, side="before", address=address)
                after = _resource(change, side="after", address=address)
                violations.extend(
                    _guard_operator_channel_edge(after, address=address, image_ref=image_ref)
                )
                violations.extend(
                    _guard_update(
                        before,
                        after,
                        address=address,
                        contract=channel_edge_contract,
                        initial_cutover=False,
                        database_host_binding=False,
                    )
                )
            continue
        if address != contract.allowed_resource_address:
            violations.append(f"cross-service or platform action {actions!r} at {address}")
            continue
        if "delete" in actions:
            violations.append(f"delete or replacement action {actions!r} at {address}")
            continue
        if actions == ("create",):
            violations.append(f"service creation has no automatic recovery at {address}")
            continue
        if actions != ("update",):
            violations.append(f"unsupported action {actions!r} at {address}")
            continue
        if (
            not isinstance(change, dict)
            or _planned_image(change, address=address, contract=contract) != image_ref
        ):
            violations.append(f"planned image at {address} does not match the attested image")
            continue
        after = _resource(change, side="after", address=address)
        selected_after = after
        _identity_ids(after, address=address)
        violations.extend(_guard_service_runtime(after, address=address, contract=contract))
        before = _resource(change, side="before", address=address)
        selected_before = before
        violations.extend(
            _guard_update(
                before,
                after,
                address=address,
                contract=contract,
                initial_cutover=initial_cutover,
                database_host_binding=database_host_binding,
                model_binding_transition=model_binding_transition,
                resolved_models_digest=resolved_models_digest,
                sharepoint_connector_transition=sharepoint_connector_transition,
            )
        )
    if operator_channel_edge_transition in {"enable", "disable"}:
        if set(channel_edge_actions) != {
            _OPERATOR_CHANNEL_EDGE_ADDRESS,
            _OPERATOR_CHANNEL_EDGE_CONTRACT_ADDRESS,
        }:
            violations.append(
                f"operator channel edge {operator_channel_edge_transition} plan is incomplete"
            )
    elif _OPERATOR_CHANNEL_EDGE_CONTRACT_ADDRESS in channel_edge_actions:
        violations.append("operator channel edge standard update changed its contract marker")
    resource_drift = payload.get("resource_drift", [])
    allowed_worker_drift = (
        initial_cutover
        and selected_after is not None
        and _guard_initial_worker_drift(
            resource_drift,
            contract=contract,
            planned_resource=selected_after,
        )
    )
    allowed_aligned_drift = (
        (
            initial_cutover
            or database_host_binding
            or model_binding_transition
            or sharepoint_connector_transition != "none"
        )
        and selected_before is not None
        and _guard_aligned_transition_drift(
            resource_drift,
            contract=contract,
            planned_before=selected_before,
        )
    )
    allowed_secret_normalization_drift = _guard_key_vault_secret_value_normalization_drift(
        resource_drift,
        contract=contract,
    )
    allowed_revision_metadata_drift = _guard_revision_metadata_drift(
        resource_drift,
        contract=contract,
        planned_before=selected_before,
    )
    if (
        resource_drift not in (None, [])
        and not allowed_worker_drift
        and not allowed_aligned_drift
        and not allowed_secret_normalization_drift
        and not allowed_revision_metadata_drift
    ):
        drift_paths: list[str] = []
        if isinstance(resource_drift, list) and len(resource_drift) == 1:
            drift_change = resource_drift[0].get("change")
            if isinstance(drift_change, dict):
                drift_paths = _difference_paths(
                    drift_change.get("before"), drift_change.get("after")
                )
        suffix = f": {drift_paths!r}" if drift_paths else ""
        violations.append(
            f"platform or peer resource drift is not eligible for protected apply{suffix}"
        )
    deferred_changes = payload.get("deferred_changes", [])
    if deferred_changes not in (None, []):
        violations.append("deferred plan changes are not eligible for protected apply")
    if violations:
        raise PlanGuardError("; ".join(violations))


def main() -> int:
    """Validate a Terraform JSON plan from the command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--initial-cutover", action="store_true")
    parser.add_argument("--database-host-binding", action="store_true")
    parser.add_argument("--model-binding-transition", action="store_true")
    parser.add_argument("--resolved-models-digest", default="")
    parser.add_argument(
        "--operator-channel-edge-transition",
        choices=("none", "enable", "disable"),
        default="none",
    )
    parser.add_argument(
        "--sharepoint-connector-transition",
        choices=("none", "enable", "disable"),
        default="none",
    )
    args = parser.parse_args()
    try:
        payload = json.loads(args.plan_json.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise PlanGuardError("Terraform plan must contain a JSON object")
        validate_plan(
            payload,
            service=args.service,
            environment=args.environment,
            image_ref=args.image_ref,
            initial_cutover=args.initial_cutover,
            database_host_binding=args.database_host_binding,
            model_binding_transition=args.model_binding_transition,
            resolved_models_digest=args.resolved_models_digest,
            operator_channel_edge_transition=args.operator_channel_edge_transition,
            sharepoint_connector_transition=args.sharepoint_connector_transition,
        )
    except (OSError, json.JSONDecodeError, ServiceContractError, PlanGuardError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
