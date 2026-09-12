#!/usr/bin/env python3
"""Materialize bounded Terraform inputs for the System Knowledge Service."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_DIGEST_IMAGE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}$")
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
_BOT_PROFILE_KEYS = {
    "allowed_service_urls",
    "bot_name",
    "channel_ids",
    "jwks_url",
    "service_name",
    "team_ids",
    "tenant_id",
    "transport",
}
_LEGACY_BOT_PROFILE_KEYS = _BOT_PROFILE_KEYS - {"transport"}
_OUTGOING_PROFILE_KEYS = {
    "channel_ids",
    "service_name",
    "team_ids",
    "tenant_id",
    "transport",
}
_SECRET_NAME = "fdai-system-knowledge-principal-map"  # noqa: S105 - Key Vault key
_OUTGOING_SECRET_NAME = "fdai-system-knowledge-outgoing-hmac"  # noqa: S105 - Key Vault key


class DeploymentInputError(ValueError):
    """Protected deployment inputs are missing, malformed, or inconsistent."""


def build_inputs(
    *,
    platform_outputs: Mapping[str, Any],
    teams_profile_json: str,
    principal_map_json: str,
    subscription_id: str,
    region: str,
    environment: str,
    image_ref: str,
    previous_image_ref: str,
    source_revision: str,
    transition: str,
    outgoing_hmac_secret: str = "",
) -> tuple[dict[str, object], dict[str, object]]:
    """Return sensitive Terraform values and a content-free context receipt."""

    if _GUID.fullmatch(subscription_id) is None:
        raise DeploymentInputError("subscription id must be a canonical lowercase UUID")
    if environment not in {"dev", "staging", "prod"} or transition not in {
        "bootstrap",
        "enable",
        "disable",
    }:
        raise DeploymentInputError("environment or transition is outside the closed contract")
    if not region or len(region) > 64:
        raise DeploymentInputError("region must be bounded and non-empty")
    if (
        _DIGEST_IMAGE.fullmatch(image_ref) is None
        or _DIGEST_IMAGE.fullmatch(previous_image_ref) is None
    ):
        raise DeploymentInputError("service images must be digest-pinned GHCR references")
    if _GIT_REVISION.fullmatch(source_revision) is None:
        raise DeploymentInputError("source revision must be a lowercase Git object id")

    profile = _json_object(teams_profile_json, label="Teams profile")
    transport = profile.get("transport", "bot_framework")
    if transport == "bot_framework":
        if (
            set(profile) not in (_BOT_PROFILE_KEYS, _LEGACY_BOT_PROFILE_KEYS)
            or transition == "bootstrap"
        ):
            raise DeploymentInputError("Bot Framework profile or transition is invalid")
    elif transport == "outgoing_webhook":
        if set(profile) != _OUTGOING_PROFILE_KEYS:
            raise DeploymentInputError("Outgoing Webhook profile fields are invalid")
    else:
        raise DeploymentInputError("Teams transport is outside the closed contract")
    service_name = _name(profile["service_name"], "service name")
    bot_name = (
        _name(profile["bot_name"], "bot name") if transport == "bot_framework" else service_name
    )
    tenant_id = _guid(profile["tenant_id"], "Teams tenant id")
    team_ids = _bounded_string_array(profile["team_ids"], "Teams team ids", maximum=100)
    if transport == "outgoing_webhook" and len(team_ids) != 1:
        raise DeploymentInputError("Outgoing Webhook profile must select exactly one Team")
    channel_ids = _bounded_string_array(
        profile["channel_ids"],
        "Teams channel ids",
        maximum=100,
    )
    service_urls: tuple[str, ...] = ()
    jwks_url = ""
    if transport == "bot_framework":
        service_urls = tuple(
            _https_url(value, "Teams service URL")
            for value in _bounded_string_array(
                profile["allowed_service_urls"],
                "Teams service URLs",
                maximum=32,
            )
        )
        jwks_url = _https_url(profile["jwks_url"], "Teams JWKS URL")
    hmac_secret = (
        _outgoing_hmac_secret(outgoing_hmac_secret, required=True)
        if transport == "outgoing_webhook" and transition == "enable"
        else None
    )
    principal_map = _json_object(principal_map_json, label="Teams principal map")
    if len(principal_map) > 1000 or any(
        not isinstance(sender, str)
        or not sender
        or len(sender) > 200
        or not isinstance(principal, str)
        or not principal
        or len(principal) > 256
        or sender == principal
        for sender, principal in principal_map.items()
    ):
        raise DeploymentInputError("Teams principal map entries are invalid")

    resource_group = _output(platform_outputs, "resource_group_name")
    container_environment = _output(platform_outputs, "container_app_environment_id")
    registry_name = _output(platform_outputs, "container_registry_name")
    registry_server = _output(platform_outputs, "container_registry_login_server")
    vault_uri = _output(platform_outputs, "key_vault_uri")
    storage_name = _output(platform_outputs, "document_storage_account_name")
    if not storage_name:
        raise DeploymentInputError(
            "the platform must expose private document storage for durable claims"
        )
    vault = urlsplit(vault_uri)
    if (
        vault.scheme != "https"
        or vault.hostname is None
        or not vault.hostname.endswith(".vault.azure.net")
        or vault.path not in {"", "/"}
    ):
        raise DeploymentInputError("platform Key Vault URI is invalid")
    vault_name = vault.hostname.removesuffix(".vault.azure.net")
    base_id = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers"
    principal_secret_id = f"{vault_uri.rstrip('/')}/secrets/{_SECRET_NAME}"
    outgoing_secret_id = f"{vault_uri.rstrip('/')}/secrets/{_OUTGOING_SECRET_NAME}"
    tfvars: dict[str, object] = {
        "enabled": transition != "disable",
        "name": service_name,
        "bot_name": bot_name,
        "image": image_ref,
        "source_revision": source_revision,
        "platform": {
            "resource_group_name": resource_group,
            "location": region,
            "container_app_environment_id": container_environment,
            "acr_login_server": registry_server,
            "acr_id": f"{base_id}/Microsoft.ContainerRegistry/registries/{registry_name}",
            "key_vault_id": f"{base_id}/Microsoft.KeyVault/vaults/{vault_name}",
            "claim_storage_account_id": (
                f"{base_id}/Microsoft.Storage/storageAccounts/{storage_name}"
            ),
            "claim_storage_blob_endpoint": f"https://{storage_name}.blob.core.windows.net/",
        },
        "teams": {
            "transport": transport,
            "tenant_id": tenant_id,
            "team_ids": list(team_ids),
            "channel_ids": list(channel_ids),
            "allowed_service_urls": list(service_urls),
            "jwks_url": jwks_url,
            "principal_map_secret_id": principal_secret_id,
            "outgoing_hmac_secret_id": (
                outgoing_secret_id
                if transport == "outgoing_webhook" and transition == "enable"
                else None
            ),
        },
        "claim_store": {"container_name": "system-knowledge-claims"},
        "health": {
            "port": 8015,
            "liveness_path": "/health/live",
            "readiness_path": "/health/ready",
            "startup_path": "/health/ready",
            "interval_seconds": 30,
            "timeout_seconds": 3,
            "failure_count_threshold": 3,
            "startup_failure_count": 60,
        },
        "rollback": {
            "strategy": "previous-revision",
            "previous_image": previous_image_ref,
            "max_unavailable_replicas": 0,
        },
        "runtime_env": environment,
        "scaling": {
            "min_replicas": 1,
            "max_replicas": 1,
            "cpu": 0.5,
            "memory": "1Gi",
        },
        "tags": {
            "fdai:managed": "true",
            "fdai:env": environment,
            "fdai:layer": "system-knowledge",
        },
    }
    context_body: dict[str, object] = {
        "schema_version": "fdai.system-knowledge-deployment.v1",
        "transition": transition,
        "teams_transport": transport,
        "environment": environment,
        "source_revision": source_revision,
        "image_digest": image_ref.rsplit("@", 1)[1],
        "previous_image_digest": previous_image_ref.rsplit("@", 1)[1],
        "tfvars_digest": _digest(tfvars),
        "teams_profile_digest": _digest(profile),
        "principal_map_digest": _digest(principal_map),
        "outgoing_hmac_digest": _digest(hmac_secret) if hmac_secret is not None else None,
    }
    return tfvars, {**context_body, "context_digest": _digest(context_body)}


def write_private_json(path: Path, value: Mapping[str, object]) -> None:
    """Write one owner-only canonical JSON artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, separators=(",", ":"), sort_keys=True)
        stream.write("\n")


def _output(outputs: Mapping[str, Any], name: str) -> str:
    record = outputs.get(name)
    value = record.get("value") if isinstance(record, Mapping) else None
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise DeploymentInputError(f"platform output {name} is unavailable")
    return value


def _json_object(value: str, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as exc:
        raise DeploymentInputError(f"{label} must be valid JSON with unique keys") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise DeploymentInputError(f"{label} must be a non-empty object")
    return parsed


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _bounded_string_array(value: Any, label: str, *, maximum: int) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > maximum
        or any(not isinstance(item, str) or not item or len(item) > 512 for item in value)
        or len(value) != len(set(value))
    ):
        raise DeploymentInputError(f"{label} must be a bounded unique string array")
    return tuple(value)


def _guid(value: Any, label: str) -> str:
    if not isinstance(value, str) or _GUID.fullmatch(value) is None:
        raise DeploymentInputError(f"{label} must be a canonical lowercase UUID")
    return value


def _name(value: Any, label: str) -> str:
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise DeploymentInputError(f"{label} must be lowercase kebab-case")
    return value


def _https_url(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise DeploymentInputError(f"{label} must be an HTTPS URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise DeploymentInputError(f"{label} must be an HTTPS URL")
    return value


def _outgoing_hmac_secret(value: str, *, required: bool) -> str | None:
    normalized = value.strip() or None
    if normalized is None:
        if required:
            raise DeploymentInputError("Outgoing Webhook enable requires an HMAC key")
        return None
    try:
        decoded = base64.b64decode(normalized, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DeploymentInputError("Outgoing Webhook HMAC key must be valid Base64") from exc
    if len(decoded) != 32:
        raise DeploymentInputError("Outgoing Webhook HMAC key must decode to 32 bytes")
    return normalized


def _digest(value: object) -> str:
    body = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(body).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform-outputs", type=Path, required=True)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--environment", choices=("dev", "staging", "prod"), required=True)
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--previous-image-ref", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument(
        "--transition",
        choices=("bootstrap", "enable", "disable"),
        required=True,
    )
    parser.add_argument("--tfvars-output", type=Path, required=True)
    parser.add_argument("--context-output", type=Path, required=True)
    arguments = parser.parse_args()
    outputs = json.loads(arguments.platform_outputs.read_text(encoding="utf-8"))
    if not isinstance(outputs, dict):
        raise DeploymentInputError("platform outputs must be a JSON object")
    tfvars, context = build_inputs(
        platform_outputs=outputs,
        teams_profile_json=os.environ.get("SYSTEM_KNOWLEDGE_TEAMS_PROFILE_JSON", ""),
        principal_map_json=os.environ.get("SYSTEM_KNOWLEDGE_PRINCIPAL_MAP_JSON", ""),
        subscription_id=arguments.subscription_id,
        region=arguments.region,
        environment=arguments.environment,
        image_ref=arguments.image_ref,
        previous_image_ref=arguments.previous_image_ref,
        source_revision=arguments.source_revision,
        transition=arguments.transition,
        outgoing_hmac_secret=os.environ.get(
            "SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET",
            "",
        ),
    )
    write_private_json(arguments.tfvars_output, tfvars)
    write_private_json(arguments.context_output, context)
    print(context["context_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
