#!/usr/bin/env python3
"""Private-descriptor lookup for the profile-approved Entra executor."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fdai_deployment_cli.entra_profiles import EntraTargetProfile
from genesis_checks import trusted_tool

_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def executor_identity(target: EntraTargetProfile) -> tuple[str, bool, bool]:
    """Return object identity, managed-identity type, and exact profile match."""

    value = graph_objects_by_id((target.executor_object_id,))
    rows = value.get("value")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("executor identity readback is incomplete")
    principal = rows[0]
    object_id = principal.get("id")
    profile_match = (
        object_id == target.executor_object_id
        and principal.get("appId") == target.executor_client_id
        and principal.get("displayName") == target.executor_display_name
    )
    if not isinstance(object_id, str) or _GUID.fullmatch(object_id) is None:
        raise ValueError("executor identity readback is invalid")
    return object_id, principal.get("servicePrincipalType") == "ManagedIdentity", profile_match


@contextmanager
def executor_execution_context(target: EntraTargetProfile) -> Iterator[str]:
    """Select and prove the separately authenticated profile executor."""

    path = target.executor_azure_config_dir
    if path.is_symlink():
        raise PermissionError("executor Azure CLI context MUST NOT be a symbolic link")
    details = path.stat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise PermissionError("executor Azure CLI context MUST be current-UID mode 0700")
    previous = os.environ.get("AZURE_CONFIG_DIR")
    os.environ["AZURE_CONFIG_DIR"] = str(path)
    try:
        object_id, client_id = _current_graph_token_identity()
        if (
            object_id.casefold() != target.executor_object_id.casefold()
            or client_id.casefold() != target.executor_client_id.casefold()
        ):
            raise ValueError("authenticated Entra executor does not match the target profile")
        yield hashlib.sha256(object_id.casefold().encode()).hexdigest()
    finally:
        if previous is None:
            os.environ.pop("AZURE_CONFIG_DIR", None)
        else:
            os.environ["AZURE_CONFIG_DIR"] = previous


def _current_graph_token_identity() -> tuple[str, str]:
    az = trusted_tool("az")
    completed = subprocess.run(
        [
            az,
            "account",
            "get-access-token",
            "--resource-type",
            "ms-graph",
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
    if completed.returncode != 0:
        raise ValueError("executor Graph token acquisition failed")
    token = completed.stdout.strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("executor Graph token shape is invalid")
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("executor Graph token claims are invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("executor Graph token claims are invalid")
    object_id = payload.get("oid")
    client_id = payload.get("appid")
    if (
        not isinstance(object_id, str)
        or _GUID.fullmatch(object_id) is None
        or not isinstance(client_id, str)
        or _GUID.fullmatch(client_id) is None
        or payload.get("idtyp") not in {None, "app"}
    ):
        raise ValueError("executor Graph token identity is invalid")
    return object_id, client_id


def graph_objects_by_id(object_ids: tuple[str, ...]) -> dict[str, Any]:
    """Send private object IDs through an inherited pipe, never process arguments."""

    az = trusted_tool("az")
    read_descriptor, write_descriptor = os.pipe()
    try:
        os.write(
            write_descriptor,
            json.dumps({"ids": list(object_ids), "types": ["servicePrincipal"]}).encode(),
        )
    finally:
        os.close(write_descriptor)
    try:
        completed = subprocess.run(
            [
                az,
                "rest",
                "--method",
                "POST",
                "--uri",
                "https://graph.microsoft.com/v1.0/directoryObjects/getByIds",
                "--headers",
                "Content-Type=application/json",
                "--body",
                f"@/proc/self/fd/{read_descriptor}",
                "--output",
                "json",
                "--only-show-errors",
            ],
            pass_fds=(read_descriptor,),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        os.close(read_descriptor)
    if completed.returncode != 0:
        raise ValueError("executor identity provider read failed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("executor identity provider response is invalid")
    return value
