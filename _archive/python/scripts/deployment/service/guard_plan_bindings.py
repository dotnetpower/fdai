#!/usr/bin/env python3
"""External runtime binding policies for the independent-service plan guard."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from guard_plan_structure import environment_binding, environment_by_name, primary_container
from service_contract import ServiceContract

MODEL_BINDING_ENVIRONMENT = frozenset(
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
OPERATOR_RUNTIME_BINDINGS = {
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


def valid_https_origin(value: str) -> bool:
    """Return whether one value is an exact credential-free HTTPS origin."""
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


def valid_console_origin(value: str) -> bool:
    """Return whether a value is one exact Static Web Apps HTTPS origin."""
    if not valid_https_origin(value) or value != value.strip().rstrip("/"):
        return False
    parsed = urlsplit(value)
    hostname = parsed.hostname
    return (
        hostname is not None and hostname.endswith(".azurestaticapps.net") and parsed.port is None
    )


def valid_web_search_domains(value: str) -> bool:
    """Validate one bounded comma-separated web-search domain allowlist."""
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


def valid_model_endpoints(value: str, *, primary_endpoint: str) -> bool:
    """Validate the bounded model-reference to exact Azure HTTPS endpoint map."""
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
        if not valid_https_origin(endpoint):
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


def guard_database_host_binding(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    address: str,
    contract: ServiceContract,
    additional_allowed_names: frozenset[str] = frozenset(),
) -> list[str]:
    """Return violations for an exact database-host and companion runtime binding transition."""
    before_primary = primary_container(before, address=address, contract=contract)
    after_primary = primary_container(after, address=address, contract=contract)
    if any(
        before_primary.get(key) != after_primary.get(key) for key in ("name", "command", "args")
    ):
        return [f"database host binding changes the service command at {address}"]
    before_environment = environment_by_name(before_primary, address=address)
    after_environment = environment_by_name(after_primary, address=address)
    changed_names = {
        name
        for name in set(before_environment) | set(after_environment)
        if environment_binding(before_environment.get(name))
        != environment_binding(after_environment.get(name))
    }
    operator_runtime_bindings = {
        name
        for name in changed_names
        if contract.service == "operator-service"
        and environment_binding(after_environment.get(name))
        == (OPERATOR_RUNTIME_BINDINGS.get(name), None)
        and name in OPERATOR_RUNTIME_BINDINGS
    }
    console_origin_binding = environment_binding(
        after_environment.get("FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS")
    )
    console_origin, console_origin_secret = console_origin_binding or (None, None)
    console_origin_changed = "FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS" in changed_names
    valid_origin = (
        contract.service == "operator-service"
        and isinstance(console_origin, str)
        and console_origin_secret is None
        and valid_console_origin(console_origin)
    )
    if console_origin_changed and valid_origin:
        operator_runtime_bindings.add("FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS")
    deployed_venue_binding = {
        name
        for name in changed_names
        if name == "FDAI_EXECUTION_VENUE"
        and environment_binding(after_environment.get(name)) == ("deployed", None)
    }
    unexpected = sorted(
        changed_names.difference(
            {"POSTGRES_HOST"}
            | additional_allowed_names
            | operator_runtime_bindings
            | deployed_venue_binding
        )
    )
    host_binding = environment_binding(after_environment.get("POSTGRES_HOST"))
    violations: list[str] = []
    if unexpected:
        violations.append(
            f"database host binding changes unapproved environment at {address}: "
            f"unexpected={unexpected}"
        )
    if console_origin_changed and not valid_origin:
        violations.append(f"database host binding has invalid Console origin at {address}")
    if (
        host_binding is None
        or not isinstance(host_binding[0], str)
        or not host_binding[0].strip()
        or host_binding[1] is not None
    ):
        violations.append(f"database host binding is invalid at {address}")
    return violations
