#!/usr/bin/env python3
"""Materialize one service's protected Terraform inputs from stdin."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from service_contract import ServiceContractError, event_bus_topic_migration, resolve_service


class TfvarsError(ValueError):
    """Raised when protected service tfvars are missing or ambiguous."""


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


def materialize_core_llm(
    resolved_models: dict[str, Any],
    *,
    expected_digest: str,
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

    allowed_domains = _web_search_domains(web_search_allowed_domains)
    web_search_endpoints = _candidate_endpoints(resolved_models, "web_search_candidates")
    web_search_available = bool(web_search_endpoints) and web_search_endpoints == endpoints
    web_search_enabled = web_search_requested and web_search_available
    if web_search_enabled and not allowed_domains:
        raise TfvarsError("enabled web search requires an allowed-domain policy")

    return {
        "endpoint": endpoints.pop(),
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
    migrate_event_bus_topics: bool = False,
    resolved_models: dict[str, Any] | None = None,
    resolved_models_digest: str = "",
    web_search_requested: bool = False,
    web_search_allowed_domains: list[str] | None = None,
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
    materialized = copy.deepcopy(selected)
    if operator_channel_edge_enabled is not None:
        if service != "operator-service":
            raise TfvarsError("operator channel edge override is valid only for operator-service")
        channel_edge = materialized.get("channel_edge")
        if not isinstance(channel_edge, dict):
            raise TfvarsError("operator tfvars must contain a channel_edge object")
        channel_edge["enabled"] = operator_channel_edge_enabled
    if migrate_event_bus_topics:
        event_topics = materialized.get("event_topics")
        if not isinstance(event_topics, dict):
            raise TfvarsError("service tfvars must contain an event_topics object")
        event_topics.update(event_bus_topic_migration(service, surface="tfvars"))
    if resolved_models is not None:
        if service != "core-control-plane":
            raise TfvarsError("resolved model binding is valid only for core-control-plane")
        materialized["llm"] = materialize_core_llm(
            resolved_models,
            expected_digest=resolved_models_digest,
            web_search_requested=web_search_requested,
            web_search_allowed_domains=web_search_allowed_domains,
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
    parser.add_argument("--event-bus-topic-migration", action="store_true")
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
            migrate_event_bus_topics=args.event_bus_topic_migration,
            resolved_models=resolved_models,
            resolved_models_digest=os.environ.get("RESOLVED_MODELS_DIGEST", ""),
            web_search_requested=web_search_requested,
            web_search_allowed_domains=web_search_allowed_domains,
        )
        write_tfvars(args.output, selected)
    except (OSError, json.JSONDecodeError, ServiceContractError, TfvarsError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
