"""AKS workload rendering for the independent operational evidence verifier."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_OPERATIONAL_EVIDENCE_PORT = 8791
_OPERATIONAL_EVIDENCE_READINESS_PATH = "/v1/operational-evidence/readiness"


def aks_workload(
    component: str,
    refs: dict[str, Any],
    identity: dict[str, Any],
    environment: Mapping[str, object],
    secret_environment: Mapping[str, str],
    readiness_path: str,
    liveness_path: str,
    *,
    external: bool = False,
    service_port: int | None = None,
    fs_group: int | None = None,
    additional_identities: dict[str, dict[str, Any]] | None = None,
    sidecars: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build one runtime-neutral AKS long-running workload specification."""

    image_names = {
        "core": "core-control-plane",
        "operator": "operator-service",
        "executor": "isolated-executor",
        "ingestion": "document-ingestion-api",
        "worker": "document-processing-worker",
    }
    image_name = image_names.get(component)
    if image_name is None or not isinstance(refs.get(image_name), str):
        raise ValueError(f"AKS {component} workload image is unavailable")
    cpu, memory = {
        "core": ("1000m", "2Gi"),
        "operator": ("500m", "1Gi"),
        "executor": ("500m", "1Gi"),
        "ingestion": ("500m", "1Gi"),
        "worker": ("500m", "1Gi"),
    }[component]
    runtime_environment = {name: str(value) for name, value in environment.items()}
    runtime_environment["FDAI_EXECUTION_VENUE"] = "deployed"
    database_role = {
        "operator": "fdai_operator",
        "executor": "fdai_executor",
        "ingestion": "fdai_ingestion_api",
        "worker": "fdai_ingestion_worker",
    }.get(component)
    if database_role is not None:
        runtime_environment["FDAI_DATABASE_ROLE"] = database_role
        runtime_environment["PGOPTIONS"] = f"-c role={database_role}"
    return {
        "component": component,
        "image": refs[image_name],
        "identity_resource_id": identity["resource_id"],
        "identity_client_id": identity["client_id"],
        "additional_identities": additional_identities or {},
        "command": [],
        "args": [],
        "replicas": 2,
        "max_replicas": 4,
        "cpu": cpu,
        "memory": memory,
        "port": 8000,
        "service_port": service_port,
        "external": external,
        "readiness_path": readiness_path,
        "liveness_path": liveness_path,
        "fs_group": fs_group,
        "environment": runtime_environment,
        "secret_environment": secret_environment,
        "sidecars": sidecars or {},
    }


def aks_operational_evidence_verifier_workload(
    *,
    refs: dict[str, Any],
    verifier_identity: object,
    core_identity: dict[str, Any],
    executor_identity: object,
    deploy_runner_principal: str,
    application_values: dict[str, Any],
    postgres_fqdn: str,
    postgres_database: str,
) -> dict[str, object] | None:
    """Render the optional non-agent verifier workload from deployment-owned bindings."""

    binding = application_values.get("operational_evidence_verifier")
    if binding is None:
        return None
    if not isinstance(binding, dict) or binding.get("enabled") is not True:
        raise ValueError("operational evidence verifier binding is invalid")
    if not isinstance(verifier_identity, dict):
        raise TypeError("operational evidence verifier identity is unavailable")
    if not isinstance(executor_identity, dict):
        raise TypeError("operational evidence verifier requires the isolated executor anchor")

    verifier = _identity_binding(verifier_identity, "operational evidence verifier identity")
    core = _identity_binding(core_identity, "Core runtime identity")
    executor = _identity_binding(executor_identity, "isolated executor identity")
    if verifier["principal_id"] in {
        core["principal_id"],
        executor["principal_id"],
        deploy_runner_principal,
    }:
        raise ValueError("operational evidence verifier identity overlaps an independent anchor")

    json_fields = {
        "anchors_json": "FDAI_OPERATIONAL_EVIDENCE_ANCHORS_JSON",
        "caller_token_jwks_json": "FDAI_OPERATIONAL_EVIDENCE_CALLER_TOKEN_JWKS_JSON",
        "role_readback_scopes_json": "FDAI_OPERATIONAL_EVIDENCE_ROLE_READBACK_SCOPES_JSON",
        "allowed_role_scopes_json": "FDAI_OPERATIONAL_EVIDENCE_ALLOWED_ROLE_SCOPES_JSON",
        "vertical_executor_principals_json": (
            "FDAI_OPERATIONAL_EVIDENCE_VERTICAL_EXECUTOR_PRINCIPALS_JSON"
        ),
        "writer_members_json": "FDAI_OPERATIONAL_EVIDENCE_WRITER_MEMBERS_JSON",
    }
    environment: dict[str, object] = {
        "AZURE_CLIENT_ID": verifier["client_id"],
        "FDAI_MI_CLIENT_ID": verifier["client_id"],
        "POSTGRES_HOST": postgres_fqdn,
        "POSTGRES_DATABASE": postgres_database,
        "FDAI_DATABASE_ROLE": "fdai_operational_evidence_verifier",
        "PGOPTIONS": "-c role=fdai_operational_evidence_verifier",
        "RUNTIME_ENV": application_values["env"],
        "FDAI_OPERATIONAL_EVIDENCE_ENABLED": "1",
        "FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PATH": _optional_text(
            binding,
            "trust_registry_path",
            default="config/operational-evidence-trust-registry.json",
        ),
        "FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PIN": _required_text(
            binding, "trust_registry_pin"
        ),
        "FDAI_OPERATIONAL_EVIDENCE_GRANT_REGISTRY_PATH": _required_text(
            binding, "grant_registry_path"
        ),
        "FDAI_OPERATIONAL_EVIDENCE_GRANT_REGISTRY_PIN": _required_text(
            binding, "grant_registry_pin"
        ),
        "FDAI_OPERATIONAL_EVIDENCE_VERIFIER_URL": (
            f"http://127.0.0.1:{_OPERATIONAL_EVIDENCE_PORT}"
        ),
        "FDAI_OPERATIONAL_EVIDENCE_READER_ROLE": "fdai_core",
        "FDAI_OPERATIONAL_EVIDENCE_CORE_EXECUTOR_PRINCIPAL_ID": core["principal_id"],
        "FDAI_OPERATIONAL_EVIDENCE_ISOLATED_EXECUTOR_PRINCIPAL_ID": executor["principal_id"],
        "FDAI_OPERATIONAL_EVIDENCE_DEV_GATEWAY_EXECUTOR_PRINCIPAL_ID": _required_text(
            binding, "dev_gateway_executor_principal_id"
        ),
        "FDAI_OPERATIONAL_EVIDENCE_DEPLOY_RUNNER_PRINCIPAL_ID": deploy_runner_principal,
        "FDAI_OPERATIONAL_EVIDENCE_CALLER_TOKEN_ISSUER": _required_text(
            binding, "caller_token_issuer"
        ),
        "FDAI_OPERATIONAL_EVIDENCE_CALLER_TOKEN_AUDIENCE": _required_text(
            binding, "caller_token_audience"
        ),
    }
    for key, env_name in json_fields.items():
        environment[env_name] = _required_json_text(binding, key)
    vertical_principals = json.loads(
        str(environment["FDAI_OPERATIONAL_EVIDENCE_VERTICAL_EXECUTOR_PRINCIPALS_JSON"])
    )
    if not isinstance(vertical_principals, list) or not all(
        isinstance(principal, str) and _GUID.fullmatch(principal) is not None
        for principal in vertical_principals
    ):
        raise ValueError("vertical_executor_principals_json must be a JSON list of GUIDs")
    environment["FDAI_OPERATIONAL_EVIDENCE_EXECUTOR_PRINCIPALS_JSON"] = json.dumps(
        sorted(
            {
                str(environment["FDAI_OPERATIONAL_EVIDENCE_CORE_EXECUTOR_PRINCIPAL_ID"]),
                str(environment["FDAI_OPERATIONAL_EVIDENCE_ISOLATED_EXECUTOR_PRINCIPAL_ID"]),
                str(environment["FDAI_OPERATIONAL_EVIDENCE_DEV_GATEWAY_EXECUTOR_PRINCIPAL_ID"]),
                deploy_runner_principal,
                *vertical_principals,
            }
        ),
        separators=(",", ":"),
    )
    image = refs.get("core-control-plane")
    if not isinstance(image, str):
        raise TypeError("AKS operational evidence verifier image is unavailable")
    return {
        "component": "operational-evidence-verifier",
        "image": image,
        "identity_resource_id": verifier["resource_id"],
        "identity_client_id": verifier["client_id"],
        "additional_identities": {},
        "command": ["python", "-m", "fdai.delivery.operational_evidence_server"],
        "args": ["--host", "0.0.0.0", "--port", str(_OPERATIONAL_EVIDENCE_PORT)],
        "replicas": 1,
        "max_replicas": 1,
        "cpu": "500m",
        "memory": "1Gi",
        "port": _OPERATIONAL_EVIDENCE_PORT,
        "service_port": None,
        "external": False,
        "readiness_path": _OPERATIONAL_EVIDENCE_READINESS_PATH,
        "liveness_path": _OPERATIONAL_EVIDENCE_READINESS_PATH,
        "fs_group": None,
        "environment": {
            name: str(value)
            for name, value in {**environment, "FDAI_EXECUTION_VENUE": "deployed"}.items()
        },
        "secret_environment": {"FDAI_OPERATIONAL_EVIDENCE_VERIFIER_DSN": "fdai-state-store-dsn"},
        "sidecars": {},
    }


def add_aks_operational_evidence_verifier_workload(
    workloads: dict[str, dict[str, object]],
    *,
    refs: dict[str, Any],
    identities: dict[str, Any],
    substrate_outputs: Mapping[str, object],
    context: Mapping[str, object],
    application_values: dict[str, Any],
) -> None:
    """Add the optional verifier workload to ``workloads`` when its binding is present."""

    if application_values.get("operational_evidence_verifier") is None:
        return
    verifier_workload = aks_operational_evidence_verifier_workload(
        refs=refs,
        verifier_identity=substrate_outputs["operational_evidence_verifier_identity"],
        core_identity=_mapping(identities.get("core"), "Core runtime identity"),
        executor_identity=identities.get("executor"),
        deploy_runner_principal=_required_text(context, "principal_id"),
        application_values=application_values,
        postgres_fqdn=_required_text(substrate_outputs, "postgres_fqdn"),
        postgres_database=_required_text(substrate_outputs, "postgres_database"),
    )
    if verifier_workload is not None:
        workloads["operational-evidence-verifier"] = verifier_workload


def runtime_principal_ids_with_operational_evidence_verifier(
    identities: Mapping[str, Any], names: tuple[str, ...]
) -> set[str]:
    """Return runtime principal ids, including the optional verifier identity."""

    principals = {
        str(_mapping(identities.get(name), f"{name} runtime identity")["principal_id"])
        for name in names
    }
    verifier_identity = identities.get("operational_evidence_verifier")
    if verifier_identity is not None:
        principals.add(
            str(
                _mapping(verifier_identity, "operational evidence verifier runtime identity")[
                    "principal_id"
                ]
            )
        )
    return principals


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


def _identity_binding(value: dict[str, Any], label: str) -> dict[str, str]:
    result = {
        "resource_id": _required_text(value, "resource_id"),
        "client_id": _required_text(value, "client_id"),
        "principal_id": _required_text(value, "principal_id"),
    }
    if any(_GUID.fullmatch(result[key]) is None for key in ("client_id", "principal_id")):
        raise ValueError(f"{label} is invalid")
    return result


def _required_text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} is required")
    return item.strip()


def _optional_text(value: Mapping[str, Any], key: str, *, default: str) -> str:
    item = value.get(key, default)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} is required")
    return item.strip()


def _required_json_text(value: Mapping[str, Any], key: str) -> str:
    item = _required_text(value, key)
    try:
        json.loads(item)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{key} must be valid JSON") from exc
    return item
