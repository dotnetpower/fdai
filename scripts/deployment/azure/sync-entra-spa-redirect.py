#!/usr/bin/env python3
"""Synchronize one deployed console origin into an Entra SPA registration."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

CommandRunner = Callable[[Sequence[str]], str]


class AzureCliError(RuntimeError):
    """Raised when an Azure CLI command fails."""


@dataclass(frozen=True)
class SpaRegistration:
    object_id: str
    redirect_uris: tuple[str, ...]


def normalize_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("origin must be an HTTPS origin without path, query, or fragment")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def run_az(command: Sequence[str]) -> str:
    completed = subprocess.run(
        ["az", *command],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown Azure CLI error"
        raise AzureCliError(detail)
    return completed.stdout


def load_registration(spa_client_id: str, runner: CommandRunner) -> SpaRegistration:
    raw = runner(
        [
            "ad",
            "app",
            "show",
            "--id",
            spa_client_id,
            "--query",
            "{objectId:id,redirectUris:spa.redirectUris}",
            "--output",
            "json",
        ]
    )
    payload: Any = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("objectId"), str):
        raise ValueError("Azure CLI returned an invalid Entra application record")
    redirect_uris = payload.get("redirectUris") or []
    if not isinstance(redirect_uris, list) or not all(
        isinstance(item, str) for item in redirect_uris
    ):
        raise ValueError("Azure CLI returned invalid SPA redirect URIs")
    return SpaRegistration(payload["objectId"], tuple(redirect_uris))


def synchronize_redirect_uri(
    *,
    tenant_id: str,
    spa_client_id: str,
    origin: str,
    runner: CommandRunner = run_az,
) -> bool:
    expected_tenant = tenant_id.strip().lower()
    if not expected_tenant:
        raise ValueError("tenant id must not be empty")
    if not spa_client_id.strip():
        raise ValueError("SPA client id must not be empty")

    active_tenant = runner(["account", "show", "--query", "tenantId", "--output", "tsv"])
    if active_tenant.strip().lower() != expected_tenant:
        raise ValueError("active Azure CLI tenant does not match the deployment tenant")

    normalized_origin = normalize_origin(origin)
    registration = load_registration(spa_client_id, runner)
    if normalized_origin in registration.redirect_uris:
        return False

    redirect_uris = [*registration.redirect_uris, normalized_origin]
    runner(
        [
            "rest",
            "--method",
            "PATCH",
            "--uri",
            "https://graph.microsoft.com/v1.0/applications/"
            + quote(registration.object_id, safe=""),
            "--headers",
            "Content-Type=application/json",
            "--body",
            json.dumps({"spa": {"redirectUris": redirect_uris}}, separators=(",", ":")),
            "--output",
            "none",
        ]
    )

    verified = load_registration(spa_client_id, runner)
    if normalized_origin not in verified.redirect_uris:
        raise AzureCliError("redirect URI update was not visible after the Graph PATCH")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, help="target Entra tenant id")
    parser.add_argument("--spa-client-id", required=True, help="console SPA application client id")
    parser.add_argument("--origin", required=True, help="deployed console HTTPS origin")
    args = parser.parse_args()

    try:
        changed = synchronize_redirect_uri(
            tenant_id=args.tenant_id,
            spa_client_id=args.spa_client_id,
            origin=args.origin,
        )
    except (AzureCliError, json.JSONDecodeError, ValueError) as exc:
        print(f"sync-entra-spa-redirect: FAIL: {exc}", file=sys.stderr)
        return 1

    action = "added" if changed else "already present"
    print(f"sync-entra-spa-redirect: OK ({action})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
