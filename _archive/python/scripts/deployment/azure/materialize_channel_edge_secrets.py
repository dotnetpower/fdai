"""Materialize approved Slack channel-edge secrets through a VNet-connected runner."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

_VAULT_AUDIENCE = "https://vault.azure.net"
_API_VERSION = "7.4"
_TEAM_ID = re.compile(r"^[A-Z0-9]{2,64}$")
_SECRET_NAMES = {
    "principal_scopes": "fdai-channel-edge-principal-scopes",
    "slack_signing_secret": "fdai-channel-edge-slack-signing-secret",
    "slack_bot_token": "fdai-channel-edge-slack-bot-token",
    "slack_principal_map": "fdai-channel-edge-slack-principal-map",
}


class ChannelEdgeSecretError(RuntimeError):
    """The protected Slack secret materialization request is invalid or unverified."""


@dataclass(frozen=True, slots=True)
class ChannelEdgeSecretInputs:
    """Hold validated Slack provider values supplied by the protected workflow."""

    slack_signing_secret: str
    slack_bot_token: str
    slack_team_id: str
    slack_principal_map: str
    principal_scopes: str

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> ChannelEdgeSecretInputs:
        """Load and cross-check the five protected GitHub Secret inputs."""

        signing_secret = _required(environ, "CHANNEL_EDGE_SLACK_SIGNING_SECRET")
        bot_token = _required(environ, "CHANNEL_EDGE_SLACK_BOT_TOKEN")
        team_id = _required(environ, "CHANNEL_EDGE_SLACK_TEAM_ID")
        principal_map = _required(environ, "CHANNEL_EDGE_SLACK_PRINCIPAL_MAP_JSON")
        principal_scopes = _required(environ, "CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON")

        if len(signing_secret) < 16 or not signing_secret.isprintable():
            raise ChannelEdgeSecretError("Slack signing secret has an invalid shape")
        if (
            not bot_token.startswith("xoxb-")
            or len(bot_token) < 20
            or bot_token != bot_token.strip()
            or not bot_token.isprintable()
        ):
            raise ChannelEdgeSecretError("Slack bot token has an invalid shape")
        if _TEAM_ID.fullmatch(team_id) is None:
            raise ChannelEdgeSecretError("Slack workspace id has an invalid shape")

        scopes = _json_object(principal_scopes, name="principal scopes")
        mapping = _json_object(principal_map, name="Slack principal map")
        if any(
            not isinstance(sender, str)
            or not isinstance(principal, str)
            or sender == principal
            or principal not in scopes
            for sender, principal in mapping.items()
        ):
            raise ChannelEdgeSecretError(
                "Slack principal map must reference distinct configured principals"
            )

        return cls(
            slack_signing_secret=signing_secret,
            slack_bot_token=bot_token,
            slack_team_id=team_id,
            slack_principal_map=principal_map,
            principal_scopes=principal_scopes,
        )

    def vault_values(self) -> dict[str, str]:
        """Return fixed secret names and values for the Key Vault boundary."""

        return {
            _SECRET_NAMES["principal_scopes"]: self.principal_scopes,
            _SECRET_NAMES["slack_signing_secret"]: self.slack_signing_secret,
            _SECRET_NAMES["slack_bot_token"]: self.slack_bot_token,
            _SECRET_NAMES["slack_principal_map"]: self.slack_principal_map,
        }


def materialize_channel_edge_secrets(
    *,
    vault_uri: str,
    inputs: ChannelEdgeSecretInputs,
    access_token: str,
    transport: httpx.Client,
) -> None:
    """Write and independently read back the four fixed channel-edge secrets."""

    base_uri = _validated_vault_uri(vault_uri)
    headers = {"Authorization": f"Bearer {access_token}"}
    for secret_name, secret_value in inputs.vault_values().items():
        url = f"{base_uri}/secrets/{quote(secret_name)}?api-version={_API_VERSION}"
        response = transport.put(
            url,
            headers=headers,
            json={
                "value": secret_value,
                "contentType": "application/vnd.fdai.channel-edge-secret",
                "attributes": {"enabled": True},
            },
        )
        _require_success(response, operation="write")
        readback = transport.get(url, headers=headers)
        _require_success(readback, operation="readback")
        payload = _response_object(readback)
        observed = payload.get("value")
        if not isinstance(observed, str) or not hmac.compare_digest(observed, secret_value):
            raise ChannelEdgeSecretError(
                "Key Vault secret readback did not match the requested value"
            )


def _azure_cli_token() -> str:
    result = subprocess.run(  # noqa: S603 - fixed Azure CLI command and arguments.
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
        raise ChannelEdgeSecretError("Azure CLI did not return a valid Key Vault access token")
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
        raise ChannelEdgeSecretError("Key Vault URI is outside the approved Azure boundary")
    return value.rstrip("/")


def _require_success(response: httpx.Response, *, operation: str) -> None:
    if response.status_code != 200:
        raise ChannelEdgeSecretError(
            f"Key Vault secret {operation} failed with HTTP {response.status_code}"
        )


def _response_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ChannelEdgeSecretError("Key Vault returned an invalid JSON response") from exc
    if not isinstance(payload, dict):
        raise ChannelEdgeSecretError("Key Vault returned a non-object response")
    return payload


def _json_object(value: str, *, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(value, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ChannelEdgeSecretError(f"{name} must be valid JSON with unique keys") from exc
    if not isinstance(payload, dict) or not payload:
        raise ChannelEdgeSecretError(f"{name} must be a non-empty JSON object")
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate JSON key")
        payload[key] = value
    return payload


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "")
    if not value:
        raise ChannelEdgeSecretError(f"{name} must be configured")
    return value


def main() -> int:
    """Run one bounded secret materialization and readback cycle."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-uri", required=True)
    args = parser.parse_args()
    inputs = ChannelEdgeSecretInputs.from_environ(os.environ)
    token = _azure_cli_token()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0),
            follow_redirects=False,
        ) as client:
            materialize_channel_edge_secrets(
                vault_uri=args.vault_uri,
                inputs=inputs,
                access_token=token,
                transport=client,
            )
    finally:
        token = ""
    print("channel-edge secret materialization and readback verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
