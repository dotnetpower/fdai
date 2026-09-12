#!/usr/bin/env python3
"""Materialize the knowledge-bot principal map through a VNet-connected runner."""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import json
import os
import subprocess
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

_VAULT_AUDIENCE = "https://vault.azure.net"
_API_VERSION = "7.4"
_SECRET_NAME = "fdai-system-knowledge-principal-map"  # noqa: S105 - Key Vault key
_OUTGOING_SECRET_NAME = "fdai-system-knowledge-outgoing-hmac"  # noqa: S105


class SystemKnowledgeSecretError(RuntimeError):
    """The principal-map materialization request is invalid or unverified."""


def validate_principal_map(value: str) -> str:
    """Return canonical principal-map JSON after structural validation."""

    try:
        parsed = json.loads(value, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as exc:
        raise SystemKnowledgeSecretError(
            "system knowledge principal map must be valid JSON with unique keys"
        ) from exc
    if (
        not isinstance(parsed, dict)
        or not parsed
        or len(parsed) > 1000
        or any(
            not isinstance(sender, str)
            or not sender
            or len(sender) > 200
            or not isinstance(principal, str)
            or not principal
            or len(principal) > 256
            or sender == principal
            for sender, principal in parsed.items()
        )
    ):
        raise SystemKnowledgeSecretError("system knowledge principal map entries are invalid")
    return json.dumps(parsed, separators=(",", ":"), sort_keys=True)


def materialize(
    *,
    vault_uri: str,
    principal_map: str,
    access_token: str,
    transport: httpx.Client,
) -> None:
    """Write and independently read back the fixed principal-map secret."""

    base_uri = _validated_vault_uri(vault_uri)
    url = f"{base_uri}/secrets/{quote(_SECRET_NAME)}?api-version={_API_VERSION}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = transport.put(
        url,
        headers=headers,
        json={
            "value": principal_map,
            "contentType": "application/vnd.fdai.system-knowledge-principal-map+json",
            "attributes": {"enabled": True},
        },
    )
    _success(response, operation="write")
    readback = transport.get(url, headers=headers)
    _success(readback, operation="readback")
    try:
        observed = readback.json().get("value")
    except (AttributeError, ValueError) as exc:
        raise SystemKnowledgeSecretError("Key Vault returned invalid readback JSON") from exc
    if not isinstance(observed, str) or not hmac.compare_digest(observed, principal_map):
        raise SystemKnowledgeSecretError("Key Vault principal-map readback did not match")


def validate_outgoing_hmac(value: str) -> str:
    """Return a validated Teams-issued Base64 HMAC key."""

    normalized = value.strip()
    try:
        decoded = base64.b64decode(normalized, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SystemKnowledgeSecretError(
            "system knowledge Outgoing Webhook HMAC must be valid Base64"
        ) from exc
    if len(decoded) != 32:
        raise SystemKnowledgeSecretError(
            "system knowledge Outgoing Webhook HMAC must decode to 32 bytes"
        )
    return normalized


def materialize_outgoing_hmac(
    *,
    vault_uri: str,
    hmac_secret: str,
    access_token: str,
    transport: httpx.Client,
) -> None:
    """Write and independently read back the fixed Outgoing Webhook HMAC secret."""

    base_uri = _validated_vault_uri(vault_uri)
    url = f"{base_uri}/secrets/{quote(_OUTGOING_SECRET_NAME)}?api-version={_API_VERSION}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = transport.put(
        url,
        headers=headers,
        json={
            "value": hmac_secret,
            "contentType": "application/vnd.fdai.system-knowledge-outgoing-hmac",
            "attributes": {"enabled": True},
        },
    )
    _success(response, operation="outgoing HMAC write")
    readback = transport.get(url, headers=headers)
    _success(readback, operation="outgoing HMAC readback")
    try:
        observed = readback.json().get("value")
    except (AttributeError, ValueError) as exc:
        raise SystemKnowledgeSecretError("Key Vault returned invalid readback JSON") from exc
    if not isinstance(observed, str) or not hmac.compare_digest(observed, hmac_secret):
        raise SystemKnowledgeSecretError("Key Vault Outgoing Webhook HMAC readback did not match")


def _azure_cli_token() -> str:
    result = subprocess.run(  # noqa: S603 - fixed Azure CLI command and arguments
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            _VAULT_AUDIENCE,
            "--query",
            "accessToken",
            "--output",
            "tsv",
            "--only-show-errors",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    token = result.stdout.strip()
    if result.returncode != 0 or token.count(".") != 2 or not token.isprintable():
        raise SystemKnowledgeSecretError("Azure CLI did not return a valid Key Vault token")
    return token


def _validated_vault_uri(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or not parsed.hostname.endswith(".vault.azure.net")
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise SystemKnowledgeSecretError("Key Vault URI is outside the Azure boundary")
    return value.rstrip("/")


def _success(response: httpx.Response, *, operation: str) -> None:
    if response.status_code != 200:
        raise SystemKnowledgeSecretError(
            f"Key Vault principal-map {operation} failed with HTTP {response.status_code}"
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-uri", required=True)
    parser.add_argument("--include-outgoing-hmac", action="store_true")
    arguments = parser.parse_args()
    principal_map = validate_principal_map(
        os.environ.get("SYSTEM_KNOWLEDGE_PRINCIPAL_MAP_JSON", "")
    )
    outgoing_hmac = (
        validate_outgoing_hmac(os.environ.get("SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET", ""))
        if arguments.include_outgoing_hmac
        else None
    )
    token = _azure_cli_token()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0),
            follow_redirects=False,
        ) as client:
            materialize(
                vault_uri=arguments.vault_uri,
                principal_map=principal_map,
                access_token=token,
                transport=client,
            )
            if outgoing_hmac is not None:
                materialize_outgoing_hmac(
                    vault_uri=arguments.vault_uri,
                    hmac_secret=outgoing_hmac,
                    access_token=token,
                    transport=client,
                )
    finally:
        token = ""
        outgoing_hmac = None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
