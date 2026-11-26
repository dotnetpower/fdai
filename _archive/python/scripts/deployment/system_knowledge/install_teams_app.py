#!/usr/bin/env python3
"""Upload the knowledge-bot Teams package and install it in one approved team."""

from __future__ import annotations

import argparse
import json
import subprocess
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx

_GRAPH = "https://graph.microsoft.com/v1.0"
_MAX_PACKAGE_BYTES = 1_048_576


class TeamsAppInstallError(RuntimeError):
    """Microsoft Graph app-catalog or team installation failed safely."""


def install_package(
    *,
    package: Path,
    team_id: str,
    access_token: str,
    transport: httpx.Client,
) -> dict[str, str | bool]:
    """Upload one validated package if needed and install it in one exact team."""

    external_id = _manifest_id(package)
    team = _guid(team_id, "team id")
    headers = {"Authorization": f"Bearer {access_token}"}
    catalog = transport.get(
        f"{_GRAPH}/appCatalogs/teamsApps",
        headers=headers,
        params={
            "$filter": f"externalId eq '{external_id}'",
            "$select": "id,externalId,displayName",
        },
    )
    _success(catalog, expected={200}, operation="read app catalog")
    catalog_items = _items(catalog, label="app catalog")
    if len(catalog_items) > 1:
        raise TeamsAppInstallError("more than one Teams app has the package external id")
    uploaded = not catalog_items
    if uploaded:
        created = transport.post(
            f"{_GRAPH}/appCatalogs/teamsApps",
            headers={**headers, "Content-Type": "application/zip"},
            content=package.read_bytes(),
        )
        _success(created, expected={200, 201}, operation="upload app package")
        app_id = _required_string(created.json(), "id", label="uploaded Teams app")
    else:
        app_id = _required_string(catalog_items[0], "id", label="existing Teams app")

    installed = transport.get(
        f"{_GRAPH}/teams/{team}/installedApps",
        headers=headers,
        params={
            "$expand": "teamsApp",
            "$filter": f"teamsApp/externalId eq '{external_id}'",
        },
    )
    _success(installed, expected={200}, operation="read team app installations")
    installations = _items(installed, label="team installations")
    if len(installations) > 1:
        raise TeamsAppInstallError("the Teams app is installed more than once")
    installed_now = not installations
    if installed_now:
        response = transport.post(
            f"{_GRAPH}/teams/{team}/installedApps",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "teamsApp@odata.bind": f"{_GRAPH}/appCatalogs/teamsApps/{app_id}",
            },
        )
        _success(response, expected={200, 201, 204}, operation="install app in team")
    return {
        "external_id": external_id,
        "catalog_app_id": app_id,
        "uploaded": uploaded,
        "installed": installed_now,
    }


def _manifest_id(package: Path) -> str:
    if package.is_symlink() or not package.is_file() or package.stat().st_size > _MAX_PACKAGE_BYTES:
        raise TeamsAppInstallError("Teams app package is unavailable or exceeds the size bound")
    try:
        with zipfile.ZipFile(package) as archive:
            if set(archive.namelist()) != {"manifest.json", "color.png", "outline.png"}:
                raise TeamsAppInstallError("Teams app package files do not match the contract")
            manifest = json.loads(archive.read("manifest.json"))
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise TeamsAppInstallError("Teams app package is invalid") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("manifestVersion") != "1.30"
        or not isinstance(manifest.get("bots"), list)
        or len(manifest["bots"]) != 1
        or manifest["bots"][0].get("scopes") != ["team"]
        or "authorization" in manifest
    ):
        raise TeamsAppInstallError("Teams app package exceeds the mention-only contract")
    return _guid(manifest.get("id"), "Teams app id")


def _graph_token() -> str:
    result = subprocess.run(  # noqa: S603 - fixed Azure CLI command and arguments
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://graph.microsoft.com",
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
        raise TeamsAppInstallError("Azure CLI did not return a valid Microsoft Graph token")
    return token


def _items(response: httpx.Response, *, label: str) -> list[dict[str, Any]]:
    try:
        value = response.json()
    except ValueError as exc:
        raise TeamsAppInstallError(f"{label} returned invalid JSON") from exc
    items = value.get("value") if isinstance(value, dict) else None
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise TeamsAppInstallError(f"{label} returned an invalid collection")
    return items


def _required_string(value: Any, key: str, *, label: str) -> str:
    item = value.get(key) if isinstance(value, dict) else None
    if not isinstance(item, str) or not item or len(item) > 256:
        raise TeamsAppInstallError(f"{label} has no bounded {key}")
    return item


def _guid(value: Any, label: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except ValueError as exc:
        raise TeamsAppInstallError(f"{label} MUST be a UUID") from exc
    rendered = str(parsed)
    if value != rendered:
        raise TeamsAppInstallError(f"{label} MUST use canonical lowercase UUID form")
    return rendered


def _success(response: httpx.Response, *, expected: set[int], operation: str) -> None:
    if response.status_code not in expected:
        try:
            payload = response.json()
            code = payload.get("error", {}).get("code", "unknown")
        except (AttributeError, ValueError):
            code = "invalid_response"
        raise TeamsAppInstallError(
            f"Microsoft Graph {operation} failed with HTTP {response.status_code} ({code})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--team-id", required=True)
    arguments = parser.parse_args()
    token = _graph_token()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
            follow_redirects=False,
        ) as client:
            result = install_package(
                package=arguments.package,
                team_id=arguments.team_id,
                access_token=token,
                transport=client,
            )
    finally:
        token = ""
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
