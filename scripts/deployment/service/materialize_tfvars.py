#!/usr/bin/env python3
"""Materialize one service's protected Terraform inputs from stdin."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from service_contract import ServiceContractError, resolve_service


class TfvarsError(ValueError):
    """Raised when protected service tfvars are missing or ambiguous."""


_CHANNEL_EDGE_SECRET_NAMES = {
    "principal_scopes_secret_id": "fdai-channel-edge-principal-scopes",
    "slack_signing_secret_id": "fdai-channel-edge-slack-signing-secret",
    "slack_bot_token_secret_id": "fdai-channel-edge-slack-bot-token",
    "slack_principal_map_secret_id": "fdai-channel-edge-slack-principal-map",
}
_AZURE_GUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SLACK_TEAM_ID = re.compile(r"^[A-Z0-9]{2,64}$")


def _resolved_models_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()


def _https_origin(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TfvarsError("resolved models narrator endpoint is missing")
    endpoint = value.strip().rstrip("/")
    try:
        parsed = urlsplit(endpoint)
        parsed.port  # noqa: B018
    except ValueError as exc:
        raise TfvarsError("resolved models narrator endpoint must be an HTTPS origin") from exc
    if (
        not endpoint.startswith("https://")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path
        or "\\" in endpoint
        or any(character.isspace() for character in endpoint)
    ):
        raise TfvarsError("resolved models narrator endpoint must be an HTTPS origin")
    return endpoint


def _https_container_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TfvarsError("decision evidence container URL is missing")
    url = value.strip().rstrip("/")
    try:
        parsed = urlsplit(url)
        parsed.port  # noqa: B018
    except ValueError as exc:
        raise TfvarsError(
            "decision evidence container URL must identify one HTTPS container"
        ) from exc
    segments = tuple(segment for segment in parsed.path.split("/") if segment)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or len(segments) != 1
        or "\\" in url
        or any(character.isspace() for character in url)
    ):
        raise TfvarsError("decision evidence container URL must identify one HTTPS container")
    return url


def _candidate_endpoints(payload: dict[str, Any], key: str) -> set[str]:
    candidates = payload.get(key, [])
    if not isinstance(candidates, list):
        raise TfvarsError(f"resolved models {key} must be an array")
    endpoints: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise TfvarsError(f"resolved models {key} entries must be objects")
        deployment = candidate.get("deployment")
        if not isinstance(deployment, str) or not deployment.strip():
            raise TfvarsError(f"resolved models {key} deployments must be non-empty")
        endpoints.add(_https_origin(candidate.get("endpoint")))
    return endpoints


def _model_endpoints(
    raw: object,
    *,
    primary_endpoint: str,
    resolved_models: dict[str, Any],
) -> dict[str, str]:
    if not isinstance(raw, dict) or not 1 <= len(raw) <= 16:
        raise TfvarsError("platform model endpoints must contain 1-16 entries")
    endpoints: dict[str, str] = {}
    for reference, endpoint_value in raw.items():
        if not isinstance(reference, str):
            raise TfvarsError("platform model endpoint references must be strings")
        endpoint = _https_origin(endpoint_value)
        parsed = urlsplit(endpoint)
        if reference.startswith("azure-openai:"):
            prefix = "azure-openai:"
            suffix = ".openai.azure.com"
        elif reference.startswith("azure-foundry:"):
            prefix = "azure-foundry:"
            suffix = ".services.ai.azure.com"
        else:
            raise TfvarsError("platform model endpoint reference uses an unsupported provider")
        hostname = (parsed.hostname or "").lower()
        if not hostname.endswith(suffix):
            raise TfvarsError("platform model endpoint provider and hostname do not match")
        account = hostname.removesuffix(suffix)
        if not account or reference != f"{prefix}{account}":
            raise TfvarsError("platform model endpoint reference and account do not match")
        endpoints[reference] = endpoint

    primary_refs = [
        reference
        for reference, endpoint in endpoints.items()
        if reference.startswith("azure-openai:") and endpoint == primary_endpoint
    ]
    if len(primary_refs) != 1:
        raise TfvarsError("platform model endpoints must include the primary OpenAI account")

    bindings = resolved_models.get("endpoint_bindings", [])
    if not isinstance(bindings, list):
        raise TfvarsError("resolved models endpoint_bindings must be an array")
    for binding in bindings:
        if not isinstance(binding, dict):
            raise TfvarsError("resolved models endpoint_bindings entries must be objects")
        endpoint_ref = binding.get("endpoint_ref")
        if (
            isinstance(endpoint_ref, str)
            and endpoint_ref.startswith("azure-foundry:")
            and endpoint_ref not in endpoints
        ):
            raise TfvarsError("platform model endpoints do not cover a Foundry binding")
    return dict(sorted(endpoints.items()))


def _web_search_domains(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        if not isinstance(value, str):
            raise TfvarsError("web search allowed domains must be strings")
        domain = value.strip().lower().rstrip(".")
        try:
            parsed = urlsplit(f"https://{domain}")
            port = parsed.port
        except ValueError as exc:
            raise TfvarsError("web search allowed domains must be valid hosts") from exc
        if (
            not domain
            or parsed.hostname != domain
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or "*" in domain
        ):
            raise TfvarsError("web search allowed domains must be hosts without schemes or paths")
        normalized.append(domain)
    if len(normalized) > 100 or len(normalized) != len(set(normalized)):
        raise TfvarsError("web search allowed domains must contain 100 unique hosts or fewer")
    return normalized


def _channel_edge_name(operator_name: object) -> str:
    if not isinstance(operator_name, str):
        raise TfvarsError("operator service name cannot derive a channel edge name")
    for suffix in ("-operator-api", "-readapi"):
        if operator_name.endswith(suffix):
            name = f"{operator_name[: -len(suffix)]}-channel-edge"
            if len(name) <= 32:
                return name
    raise TfvarsError("operator service name cannot derive a valid channel edge name")


def _container_app_resource_id(value: object, *, label: str) -> tuple[str, str]:
    if not isinstance(value, str) or value != value.strip():
        raise TfvarsError(f"{label} must be an exact Container App Resource ID")
    segments = value.split("/")
    if (
        len(segments) != 9
        or segments[0] != ""
        or segments[1].lower() != "subscriptions"
        or _AZURE_GUID.fullmatch(segments[2]) is None
        or segments[3].lower() != "resourcegroups"
        or not segments[4]
        or segments[5].lower() != "providers"
        or f"{segments[6]}/{segments[7]}".lower() != "microsoft.app/containerapps"
        or not segments[8]
    ):
        raise TfvarsError(f"{label} must be an exact Container App Resource ID")
    return value, segments[8]


def _runtime_call_evidence_binding(
    binding: dict[str, Any],
    *,
    service: str,
    service_name: object,
) -> dict[str, str]:
    if set(binding) != {"caller_resource_id", "target_resource_id"}:
        raise TfvarsError("runtime call evidence binding has unexpected fields")
    caller, caller_name = _container_app_resource_id(
        binding.get("caller_resource_id"),
        label="runtime call caller",
    )
    target, target_name = _container_app_resource_id(
        binding.get("target_resource_id"),
        label="runtime call target",
    )
    if caller.lower() == target.lower():
        raise TfvarsError("runtime call caller and target Resource IDs must be distinct")
    if not isinstance(service_name, str):
        raise TfvarsError("runtime call service name is missing")
    if service == "operator-service":
        if caller_name.lower() != service_name.lower():
            raise TfvarsError("runtime call caller Resource ID does not match the Operator service")
        if not target_name.endswith("-core"):
            raise TfvarsError("runtime call target Resource ID does not identify the Core service")
    elif service == "core-control-plane":
        if target_name.lower() != service_name.lower():
            raise TfvarsError("runtime call target Resource ID does not match the Core service")
        if not caller_name.endswith(("-operator-api", "-readapi")):
            raise TfvarsError(
                "runtime call caller Resource ID does not identify the Operator service"
            )
    else:  # pragma: no cover - guarded by the caller
        raise TfvarsError("runtime call evidence service is unsupported")
    return {
        "caller_resource_id": caller,
        "target_resource_id": target,
    }


def _channel_edge_secret_id(value: object, *, expected_name: str) -> tuple[str, str]:
    if not isinstance(value, str) or not value.isprintable() or value != value.strip():
        raise TfvarsError("operator channel edge secret ids must be non-empty strings")
    segments = value.split("/")
    if (
        len(segments) != 11
        or segments[0] != ""
        or segments[1].lower() != "subscriptions"
        or _AZURE_GUID.fullmatch(segments[2]) is None
        or segments[3].lower() != "resourcegroups"
        or not segments[4]
        or segments[5].lower() != "providers"
        or segments[6].lower() != "microsoft.keyvault"
        or segments[7].lower() != "vaults"
        or re.fullmatch(r"[A-Za-z0-9-]{3,24}", segments[8]) is None
        or segments[9].lower() != "secrets"
        or segments[10] != expected_name
    ):
        raise TfvarsError("operator channel edge secret id is not an approved fixed secret")
    secret_uri = f"https://{segments[8].lower()}.vault.azure.net/secrets/{expected_name}"
    return secret_uri, "/".join(segments[:10])


def materialize_operator_channel_edge(
    provider: dict[str, Any],
    *,
    operator_name: object,
) -> dict[str, Any]:
    """Build the complete Slack edge contract from a bounded provider binding."""
    expected_keys = {*_CHANNEL_EDGE_SECRET_NAMES, "slack_team_id"}
    if set(provider) != expected_keys:
        raise TfvarsError("operator channel edge provider binding has unexpected keys")

    secret_ids: dict[str, str] = {}
    vaults: set[str] = set()
    for key, expected_name in _CHANNEL_EDGE_SECRET_NAMES.items():
        secret_id, vault = _channel_edge_secret_id(provider.get(key), expected_name=expected_name)
        secret_ids[key] = secret_id
        vaults.add(vault.lower())
    if len(vaults) != 1:
        raise TfvarsError("operator channel edge secrets must belong to one Key Vault")

    slack_team_id = provider.get("slack_team_id")
    if not isinstance(slack_team_id, str) or _SLACK_TEAM_ID.fullmatch(slack_team_id) is None:
        raise TfvarsError("operator channel edge Slack workspace id has an invalid shape")

    return {
        "enabled": True,
        "name": _channel_edge_name(operator_name),
        "slack_enabled": True,
        "teams_enabled": False,
        **secret_ids,
        "slack_team_id": slack_team_id,
        "teams_application_id": "",
        "teams_tenant_id": "",
        "teams_principal_map_secret_id": "",
        "teams_allowed_service_urls": "",
        "teams_jwks_url": "",
        "health": {
            "port": 8014,
            "liveness_path": "/health/live",
            "readiness_path": "/health/ready",
            "startup_path": "/health/ready",
            "interval_seconds": 15,
            "timeout_seconds": 3,
            "failure_count_threshold": 3,
            "startup_failure_count": 30,
        },
        "scaling": {
            "min_replicas": 1,
            "max_replicas": 2,
            "cpu": 0.5,
            "memory": "1Gi",
        },
    }


def _operator_channel_edge_identity(binding: dict[str, Any]) -> dict[str, str]:
    if set(binding) != {"client_id", "principal_id", "resource_id"}:
        raise TfvarsError("operator channel edge identity binding has unexpected keys")
    client_id = binding.get("client_id")
    principal_id = binding.get("principal_id")
    resource_id = binding.get("resource_id")
    if (
        not isinstance(client_id, str)
        or _AZURE_GUID.fullmatch(client_id) is None
        or not isinstance(principal_id, str)
        or _AZURE_GUID.fullmatch(principal_id) is None
        or not isinstance(resource_id, str)
        or not resource_id.lower().startswith("/subscriptions/")
        or not resource_id.lower().endswith("-channel-edge")
    ):
        raise TfvarsError("operator channel edge identity binding is invalid")
    return {
        "edge_resource_id": resource_id,
        "edge_client_id": client_id,
    }


def materialize_core_llm(
    resolved_models: dict[str, Any],
    *,
    expected_digest: str,
    model_endpoints: object,
    web_search_requested: bool = False,
    web_search_allowed_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Derive Core LLM inputs only from a digest-bound resolved-model manifest."""
    if len(expected_digest) != 64 or any(
        character not in "0123456789abcdef" for character in expected_digest
    ):
        raise TfvarsError("model binding transition has no attested resolved-models digest")
    if resolved_models.get("schema_version") != "1.0.0":
        raise TfvarsError("resolved models schema_version is unsupported")
    if not isinstance(resolved_models.get("capabilities"), list):
        raise TfvarsError("resolved models capabilities must be an array")
    if _resolved_models_digest(resolved_models) != expected_digest:
        raise TfvarsError("resolved models manifest does not match the attested digest")

    endpoints = _candidate_endpoints(resolved_models, "narrator_candidates")
    narrator = resolved_models.get("narrator")
    if narrator is not None:
        if not isinstance(narrator, dict):
            raise TfvarsError("resolved models narrator must be an object")
        deployment = narrator.get("deployment")
        if not isinstance(deployment, str) or not deployment.strip():
            raise TfvarsError("resolved models narrator deployment must be non-empty")
        endpoints.add(_https_origin(narrator.get("endpoint")))
    if len(endpoints) != 1:
        raise TfvarsError("resolved models must identify exactly one narrator endpoint origin")
    primary_endpoint = next(iter(endpoints))
    endpoint_map = _model_endpoints(
        model_endpoints,
        primary_endpoint=primary_endpoint,
        resolved_models=resolved_models,
    )

    allowed_domains = _web_search_domains(web_search_allowed_domains)
    web_search_endpoints = _candidate_endpoints(resolved_models, "web_search_candidates")
    web_search_available = bool(web_search_endpoints) and web_search_endpoints == endpoints
    web_search_enabled = web_search_requested and web_search_available
    if web_search_enabled and not allowed_domains:
        raise TfvarsError("enabled web search requires an allowed-domain policy")

    return {
        "endpoint": primary_endpoint,
        "model_endpoints": endpoint_map,
        "web_search_enabled": web_search_enabled,
        "web_search_allowed_domains": allowed_domains if web_search_enabled else [],
        "web_search_max_results": 8,
        "web_search_timeout_seconds": 45,
        "resolved_models_digest": expected_digest,
    }


def select_tfvars(
    payload: dict[str, Any],
    *,
    service: str,
    environment: str,
    operator_channel_edge_enabled: bool | None = None,
    operator_channel_edge_identity: dict[str, Any] | None = None,
    operator_channel_edge_provider: dict[str, Any] | None = None,
    resolved_models: dict[str, Any] | None = None,
    resolved_models_digest: str = "",
    model_endpoints: object = None,
    web_search_requested: bool = False,
    web_search_allowed_domains: list[str] | None = None,
    stewardship_gitops: dict[str, Any] | None = None,
    decision_evidence_container_url: str = "",
    runtime_call_evidence: dict[str, Any] | None = None,
    source_revision: str | None = None,
) -> dict[str, Any]:
    """Select exactly one environment/service object and reserve image for the workflow."""
    resolve_service(service, environment)
    environments = payload.get("environments")
    if not isinstance(environments, dict):
        raise TfvarsError("tfvars payload must contain an environments object")
    services = environments.get(environment)
    if not isinstance(services, dict):
        raise TfvarsError(f"tfvars payload has no {environment} environment object")
    selected = services.get(service)
    if not isinstance(selected, dict) or not selected:
        raise TfvarsError(f"tfvars payload has no non-empty entry for {service}")
    if "image" in selected:
        raise TfvarsError("tfvars payload must not set image; the attested workflow input owns it")
    if "source_revision" in selected:
        raise TfvarsError(
            "tfvars payload must not set source_revision; the attested workflow input owns it"
        )
    if "runtime_call_evidence" in selected:
        raise TfvarsError(
            "tfvars payload must not set runtime_call_evidence; platform state owns it"
        )
    materialized = copy.deepcopy(selected)
    if source_revision is not None:
        if service != "core-control-plane":
            if source_revision:
                raise TfvarsError("source revision binding is valid only for core-control-plane")
        elif re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", source_revision) is None:
            raise TfvarsError("Core source revision must be a full lowercase Git SHA-1 or SHA-256")
        else:
            materialized["source_revision"] = source_revision
    if operator_channel_edge_enabled is not None:
        if service != "operator-service":
            raise TfvarsError("operator channel edge override is valid only for operator-service")
        channel_edge = materialized.get("channel_edge")
        if operator_channel_edge_enabled and operator_channel_edge_provider is not None:
            channel_edge = materialize_operator_channel_edge(
                operator_channel_edge_provider,
                operator_name=materialized.get("name"),
            )
            materialized["channel_edge"] = channel_edge
        elif channel_edge is None and not operator_channel_edge_enabled:
            pass
        elif not isinstance(channel_edge, dict):
            raise TfvarsError("operator tfvars must contain a channel_edge object")
        else:
            channel_edge["enabled"] = operator_channel_edge_enabled
        if operator_channel_edge_enabled:
            identity = materialized.get("identity")
            if not isinstance(identity, dict):
                raise TfvarsError("operator tfvars must contain an identity object")
            if operator_channel_edge_identity is not None:
                identity.update(_operator_channel_edge_identity(operator_channel_edge_identity))
            if not identity.get("edge_resource_id") or not identity.get("edge_client_id"):
                raise TfvarsError("operator channel edge identity binding is missing")
    if resolved_models is not None:
        if service != "core-control-plane":
            raise TfvarsError("resolved model binding is valid only for core-control-plane")
        materialized["llm"] = materialize_core_llm(
            resolved_models,
            expected_digest=resolved_models_digest,
            model_endpoints=model_endpoints,
            web_search_requested=web_search_requested,
            web_search_allowed_domains=web_search_allowed_domains,
        )
    if service in {"core-control-plane", "document-ingestion-api"}:
        materialized["stewardship_gitops"] = _stewardship_gitops_binding(
            stewardship_gitops,
            service=service,
        )
    elif stewardship_gitops is not None:
        raise TfvarsError("stewardship GitOps binding is valid only for Core or document ingestion")
    if decision_evidence_container_url:
        if service != "core-control-plane":
            raise TfvarsError(
                "decision evidence container binding is valid only for core-control-plane"
            )
        materialized["decision_evidence_container_url"] = _https_container_url(
            decision_evidence_container_url
        )
    if service in {"core-control-plane", "operator-service"} and runtime_call_evidence is not None:
        materialized["runtime_call_evidence"] = _runtime_call_evidence_binding(
            runtime_call_evidence,
            service=service,
            service_name=materialized.get("name"),
        )
    elif runtime_call_evidence is not None:
        raise TfvarsError("runtime call evidence binding is valid only for operator-service")
    return materialized


def _stewardship_gitops_binding(
    binding: dict[str, Any] | None,
    *,
    service: str,
) -> dict[str, Any]:
    if not binding:
        return {}
    materialized = copy.deepcopy(binding)
    if "auth_mode" not in materialized:
        if service == "document-ingestion-api":
            return {}
        materialized.update(
            {
                "auth_mode": "static_token",
                "app_client_id": "",
                "app_installation_id": "",
                "app_private_key_secret_id": "",
                "webhook_secret_id": "",
            }
        )
    return materialized


def write_tfvars(path: Path, payload: dict[str, Any]) -> None:
    """Write selected deployment inputs with owner-only permissions."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(json.dumps(payload, sort_keys=True) + "\n")


def main() -> int:
    """Read the repository secret from stdin and write one temporary tfvars file."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--operator-channel-edge-enabled",
        choices=("true", "false"),
    )
    parser.add_argument("--model-binding-transition", action="store_true")
    args = parser.parse_args()
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise TfvarsError("tfvars payload must be a JSON object")
        edge_enabled = (
            args.operator_channel_edge_enabled == "true"
            if args.operator_channel_edge_enabled is not None
            else None
        )
        resolved_models = None
        web_search_requested = False
        web_search_allowed_domains = None
        if args.model_binding_transition:
            resolved_models = json.loads(os.environ.get("RESOLVED_MODELS_JSON", ""))
            if not isinstance(resolved_models, dict):
                raise TfvarsError("RESOLVED_MODELS_JSON must contain a JSON object")
            web_search_value = os.environ.get("WEB_SEARCH_ENABLED", "false")
            if web_search_value not in {"true", "false"}:
                raise TfvarsError("WEB_SEARCH_ENABLED must be true or false")
            web_search_requested = web_search_value == "true"
            web_search_allowed_domains = json.loads(
                os.environ.get("WEB_SEARCH_ALLOWED_DOMAINS_JSON", "[]")
            )
            if not isinstance(web_search_allowed_domains, list):
                raise TfvarsError("WEB_SEARCH_ALLOWED_DOMAINS_JSON must contain a JSON array")
        selected = select_tfvars(
            raw,
            service=args.service,
            environment=args.environment,
            operator_channel_edge_enabled=edge_enabled,
            operator_channel_edge_identity=(
                _optional_object_environment("OPERATOR_CHANNEL_EDGE_IDENTITY_JSON")
                if edge_enabled
                else None
            ),
            operator_channel_edge_provider=(
                _optional_object_environment("OPERATOR_CHANNEL_EDGE_PROVIDER_JSON")
                if edge_enabled
                else None
            ),
            resolved_models=resolved_models,
            resolved_models_digest=os.environ.get("RESOLVED_MODELS_DIGEST", ""),
            model_endpoints=json.loads(os.environ.get("MODEL_ENDPOINTS_JSON", "{}")),
            web_search_requested=web_search_requested,
            web_search_allowed_domains=web_search_allowed_domains,
            stewardship_gitops=_optional_object_environment("STEWARDSHIP_GITOPS_JSON"),
            decision_evidence_container_url=os.environ.get(
                "DECISION_EVIDENCE_CONTAINER_URL",
                "",
            ),
            runtime_call_evidence=_optional_object_environment("RUNTIME_CALL_EVIDENCE_JSON"),
            source_revision=os.environ.get("SOURCE_REVISION"),
        )
        write_tfvars(args.output, selected)
    except (OSError, json.JSONDecodeError, ServiceContractError, TfvarsError) as exc:
        parser.error(str(exc))
    return 0


def _optional_object_environment(name: str) -> dict[str, Any] | None:
    raw = os.environ.get(name, "null")
    value = json.loads(raw)
    if value is not None and not isinstance(value, dict):
        raise TfvarsError(f"{name} must contain a JSON object or null")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
