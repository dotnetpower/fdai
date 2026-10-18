"""Pure value validation and projection for standalone deployment checkpoints."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from fdai_deployment_cli.aks_workload_jobs import AKS_CANARY_TOPIC
from fdai_deployment_cli.contracts import canonical_digest

_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def aks_core_environment(
    *,
    context: dict[str, object],
    application_values: dict[str, object],
    substrate_outputs: dict[str, object],
    resource_group: str,
    core_identity: dict[str, object],
    topics: list[object],
    deployment_binding: str,
) -> dict[str, object]:
    """Project the baseline AKS Core environment from verified deployment values."""

    environment: dict[str, object] = {
        "AZURE_TENANT_ID": context["tenant_id"],
        "AZURE_SUBSCRIPTION_ID": context["subscription_id"],
        "AZURE_RESOURCE_GROUP": resource_group,
        "AZURE_REGION": application_values["region"],
        "AZURE_CLIENT_ID": core_identity["client_id"],
        "KAFKA_BOOTSTRAP_SERVERS": substrate_outputs["kafka"],
        "KAFKA_TOPIC_EVENTS": str(topics[0]),
        "FDAI_CANARY_TOPIC": AKS_CANARY_TOPIC,
        "POSTGRES_HOST": substrate_outputs["postgres_fqdn"],
        "POSTGRES_DATABASE": substrate_outputs["postgres_database"],
        "RUNTIME_ENV": application_values["env"],
        "AUTONOMY_MODE_DEFAULT": "shadow",
        "FDAI_MONITOR_WORKSPACE_ID": substrate_outputs["workspace"],
        "FDAI_OPERATING_MODEL_TOPIC": substrate_outputs["operating_model_topic"],
        "FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS": substrate_outputs["operational_kafka"],
        "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER": "1",
        "FDAI_PRODUCT_PROFILE_JSON": str(application_values["product_profile_json"]),
        "FDAI_START_CONSUMER": "1",
        "FDAI_INSTALLATION_BINDING": str(substrate_outputs["installation_binding"]),
        "FDAI_LICENSE_DEPLOYMENT_BINDING": deployment_binding,
    }
    profile = str(application_values.get("development_authority_profile_json", "")).strip()
    executor = str(application_values.get("development_authority_executor_principal", "")).strip()
    if bool(profile) != bool(executor):
        raise ValueError("development authority profile and executor must be selected together")
    if profile:
        environment["FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON"] = profile
        environment["FDAI_FULL_AUTHORITY_DEVELOPMENT_EXECUTOR_PRINCIPAL"] = executor
    return environment


def plan_summary(value: object) -> dict[str, object]:
    """Project one bounded Terraform plan into review-safe action counts and addresses."""
    changes = value.get("resource_changes") if isinstance(value, dict) else None
    if not isinstance(changes, list) or len(changes) > 5000:
        raise ValueError("Terraform plan resource change inventory is invalid")
    counts = {name: 0 for name in ("create", "update", "delete", "replace", "read", "no-op")}
    types: dict[str, int] = {}
    projected: list[dict[str, object]] = []
    for item in changes:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("type"), str)
            or not isinstance(item.get("address"), str)
            or not item["address"]
        ):
            raise ValueError("Terraform plan resource change is invalid")
        change = item.get("change")
        actions = change.get("actions") if isinstance(change, dict) else None
        if not isinstance(actions, list) or not all(isinstance(action, str) for action in actions):
            raise ValueError("Terraform plan action is invalid")
        action_set = set(actions)
        if action_set == {"create", "delete"}:
            counts["replace"] += 1
        else:
            for action in action_set:
                if action in counts:
                    counts[action] += 1
        resource_type = str(item["type"])
        types[resource_type] = types.get(resource_type, 0) + 1
        projected.append({"address": item["address"], "actions": actions})
    return {
        "action_counts": counts,
        "resource_type_counts": dict(sorted(types.items())),
        "resource_changes": projected,
    }


def required_image_digest(records: dict[str, object], name: str) -> str:
    """Return one exact OCI image digest from a validated runtime record."""
    record = records.get(name)
    if not isinstance(record, dict) or any(not isinstance(key, str) for key in record):
        raise ValueError(f"runtime image {name} is invalid")
    digest = record.get("image_digest")
    if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
        raise ValueError("runtime image digest is invalid")
    return digest


def foundation_binding_digest(
    handoff: dict[str, object],
    *,
    runner: dict[str, object],
    state: dict[str, object],
    ops: dict[str, object],
    app: dict[str, object],
) -> str:
    """Bind the selected Foundation resources to the exact source handoff."""
    return canonical_digest(
        {
            "source_commit": handoff.get("source_commit"),
            "run_digest": handoff.get("run_digest"),
            "region": handoff.get("region"),
            "region_short": handoff.get("region_short"),
            "runner": runner,
            "state": state,
            "ops": ops,
            "app_resource_group": app,
        }
    )


def foundation_application_workload(
    app: dict[str, object], *, environment: str, region_short: str
) -> str:
    """Recover the bounded workload token from one reviewed resource-group name."""
    name = app.get("name")
    suffix = f"-{environment}-{region_short}"
    if not isinstance(name, str) or not name.startswith("rg-") or not name.endswith(suffix):
        raise ValueError("Foundation application resource-group name is invalid")
    workload = name[3 : -len(suffix)]
    if re.fullmatch(r"[a-z][a-z0-9]{1,11}", workload) is None:
        raise ValueError("Foundation application workload is invalid")
    return workload


def vault_name(uri: str) -> str:
    """Extract one bounded public-cloud Key Vault name from its exact HTTPS URI."""
    match = re.fullmatch(r"https://([a-z0-9-]{3,24})[.]vault[.]azure[.]net/?", uri)
    if match is None:
        raise ValueError("Terraform Key Vault URI is invalid")
    return match.group(1)


def registry_selector(registry_id: str, expected_name: str) -> tuple[str, ...]:
    """Return ``az acr show`` selectors for a state-owned registry ID of the expected name."""

    match = re.fullmatch(
        r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
        r"Microsoft\.ContainerRegistry/registries/([^/]+)",
        registry_id,
        flags=re.IGNORECASE,
    )
    if match is None or match.group(3) != expected_name:
        raise ValueError("Terraform registry differs from the planned image registry")
    subscription, resource_group, name = match.groups()
    return ("--name", name, "--resource-group", resource_group, "--subscription", subscription)


def planned_container_registry_name(
    *, workload: str, environment: str, region_short: str, resource_suffix: str
) -> str:
    """Return the exact container registry name rendered by the verified Terraform root."""

    if (
        re.fullmatch(r"[a-z][a-z0-9]{1,11}", workload) is None
        or re.fullmatch(r"[a-z][a-z0-9-]{1,15}", environment) is None
        or re.fullmatch(r"[a-z][a-z0-9]{1,7}", region_short) is None
        or re.fullmatch(r"[0-9a-f]{6}", resource_suffix) is None
    ):
        raise ValueError("planned container registry name inputs are invalid")
    return f"cr{workload}{environment.replace('-', '')}{region_short}{resource_suffix}"


def planned_key_vault_name(
    *, workload: str, environment: str, region_short: str, resource_suffix: str
) -> str:
    """Return the exact Key Vault name rendered by the verified Terraform root."""

    if (
        re.fullmatch(r"[a-z][a-z0-9]{1,11}", workload) is None
        or re.fullmatch(r"[a-z][a-z0-9-]{1,15}", environment) is None
        or re.fullmatch(r"[a-z][a-z0-9]{1,7}", region_short) is None
        or re.fullmatch(r"[0-9a-f]{6}", resource_suffix) is None
    ):
        raise ValueError("planned Key Vault name inputs are invalid")
    full_name = f"kv-{workload}-{environment}-{region_short}-{resource_suffix}"
    return (
        full_name
        if len(full_name) <= 24
        else f"kv-aip-{hashlib.sha256(full_name.encode()).hexdigest()[:8]}"
    )


def planned_document_storage_name(
    *, subscription_id: str, workload: str, environment: str, region_short: str
) -> str:
    """Return the exact document-storage name rendered by the verified Terraform root."""

    if (
        re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", subscription_id)
        is None
        or re.fullmatch(r"[a-z][a-z0-9]{1,11}", workload) is None
        or re.fullmatch(r"[a-z][a-z0-9-]{1,15}", environment) is None
        or re.fullmatch(r"[a-z][a-z0-9]{1,7}", region_short) is None
    ):
        raise ValueError("planned document storage name inputs are invalid")
    unique = hashlib.md5(
        f"{subscription_id.casefold()}:{environment}".encode(), usedforsecurity=False
    ).hexdigest()[:6]
    return f"st{workload}doc{environment}{region_short}{unique}"[:24]


def console_origin(hostname: str) -> str:
    """Return the HTTPS origin for one deployed Static Web App hostname."""
    if (
        re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:[.][0-9]+)?[.]azurestaticapps[.]net",
            hostname,
        )
        is None
    ):
        raise ValueError("Console Static Web App hostname is invalid")
    return f"https://{hostname}"


def aks_operator_environment(
    *,
    application_values: dict[str, Any],
    core_environment: dict[str, Any],
    substrate_outputs: dict[str, Any],
    semantic_topics: list[Any],
    operator_identity: dict[str, Any],
    command_identity: dict[str, Any],
    tenant_id: str,
    console_origin: str,
) -> dict[str, object]:
    """Bind the Operator API pod environment selected by the enterprise identity surface."""

    bindings = application_values["stewardship_agent_bindings"]
    if not isinstance(bindings, dict):
        raise ValueError("stewardship bindings are invalid")
    environment: dict[str, object] = {
        "AZURE_CLIENT_ID": operator_identity["client_id"],
        "FDAI_COMMAND_MI_CLIENT_ID": command_identity["client_id"],
        "FDAI_ENTRA_TENANT_ID": tenant_id,
        "FDAI_API_AUDIENCE": application_values["operator_api_audience"],
        "FDAI_RBAC_READERS_GROUP_ID": application_values["rbac_readers_group_id"],
        "FDAI_RBAC_CONTRIBUTORS_GROUP_ID": application_values["rbac_contributors_group_id"],
        "FDAI_RBAC_APPROVERS_GROUP_ID": application_values["rbac_approvers_group_id"],
        "FDAI_RBAC_OWNERS_GROUP_ID": application_values["rbac_owners_group_id"],
        "FDAI_RBAC_BREAK_GLASS_GROUP_ID": application_values["rbac_break_glass_group_id"],
        "FDAI_STEWARDSHIP_REQUIRE_BINDINGS": "1",
        "FDAI_MAINTAINERS": application_values["stewardship_maintainers"],
        "FDAI_KAFKA_BOOTSTRAP_SERVERS": core_environment["KAFKA_BOOTSTRAP_SERVERS"],
        "KAFKA_TOPIC_EVENTS": core_environment["KAFKA_TOPIC_EVENTS"],
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": str(semantic_topics[0]),
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": str(semantic_topics[1]),
        "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC": substrate_outputs["semantic_physical"],
        "FDAI_READ_INVESTIGATION_REQUEST_TOPIC": str(semantic_topics[2]),
        "FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS": console_origin,
    }
    environment.update(
        {f"FDAI_STEWARD_{name.upper()}": binding for name, binding in bindings.items()}
    )
    return environment


# Shared-root Event Hubs startup readiness defaults (`infra/variables.tf`); the AKS
# renderer must supply them because Core's code defaults are too short for a consumer join.
AKS_CORE_STARTUP_READINESS: dict[str, str] = {
    "FDAI_STARTUP_KAFKA_SETTLE_SECONDS": "12",
    "FDAI_STARTUP_PROBE_TIMEOUT_SECONDS": "30",
    "FDAI_STARTUP_PHASE_TIMEOUT_SECONDS": "60",
}

_KEY_VAULT_SECRET_ID = re.compile(
    r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/"
    r"Microsoft[.]KeyVault/vaults/[A-Za-z0-9-]{3,24}/secrets/([A-Za-z0-9-]{1,127})",
    re.IGNORECASE,
)
_KEY_VAULT_SECRET_URL = re.compile(
    r"https://[A-Za-z0-9-]{3,24}[.]vault[.]azure[.]net/"
    r"secrets/([A-Za-z0-9-]{1,127})",
    re.IGNORECASE,
)
_OPERATOR_REQUEST_SEED_NAMES = {
    "core_signing_seed_secret_id": "fdai-operator-request-core-signing-seed",
    "operator_signing_seed_secret_id": "fdai-operator-request-operator-signing-seed",
}


def aks_operator_request_receipts(
    binding: object,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    """Bind Core and Operator to the deployment-owned operator_request receipt seeds.

    Returns Core plain and secret environments, then Operator plain and secret environments.
    Secret environments map variable names to Key Vault secret names.
    """

    if not isinstance(binding, dict):
        raise ValueError("operator_request receipt binding is invalid")
    names: dict[str, str] = {}
    for field, expected_name in _OPERATOR_REQUEST_SEED_NAMES.items():
        reference = str(binding.get(field, ""))
        match = _KEY_VAULT_SECRET_ID.fullmatch(reference) or _KEY_VAULT_SECRET_URL.fullmatch(
            reference
        )
        if match is None or match.group(1) != expected_name:
            raise ValueError("operator_request receipt seed reference is invalid")
        names[field] = match.group(1)
    core_producer = binding.get("core_producer_id")
    operator_producer = binding.get("operator_producer_id")
    if (
        core_producer != "core-control-plane"
        or not isinstance(operator_producer, str)
        or not operator_producer
        or operator_producer == core_producer
        or names["core_signing_seed_secret_id"] == names["operator_signing_seed_secret_id"]
    ):
        raise ValueError("operator_request receipt producers are invalid")
    return (
        {
            "FDAI_OPERATOR_REQUEST_CORE_PRODUCER_ID": core_producer,
            "FDAI_OPERATOR_REQUEST_OPERATOR_PRODUCER_ID": operator_producer,
        },
        {
            "FDAI_OPERATOR_REQUEST_CORE_SIGNING_SEED": names["core_signing_seed_secret_id"],
            "FDAI_OPERATOR_REQUEST_OPERATOR_TRUST_SEED": names["operator_signing_seed_secret_id"],
        },
        {"FDAI_OPERATOR_REQUEST_RECEIPT_PRODUCER_ID": operator_producer},
        {"FDAI_OPERATOR_REQUEST_OPERATOR_SIGNING_SEED": names["operator_signing_seed_secret_id"]},
    )


def selected_identity(identities: dict[str, Any], name: str, selected: bool) -> dict[str, Any]:
    """Return one selected runtime identity or an empty optional binding."""

    if not selected:
        return {}
    return mapping(identities.get(name), f"{name.replace('_', ' ')} runtime identity")


def mapping(value: object, label: str) -> dict[str, Any]:
    """Require one string-keyed mapping."""

    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


def required_guid(value: dict[str, Any], field: str) -> str:
    """Return one required GUID field."""

    item = value.get(field)
    if not isinstance(item, str) or _GUID.fullmatch(item) is None:
        raise ValueError(f"{field} is invalid")
    return item
