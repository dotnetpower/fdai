"""Publish the verified standalone Console artifact."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fdai_deployment_cli.bundle import extract_bundle_archive
from fdai_deployment_cli.console_config import (
    configure_console,
    validate_console_stencil_flags,
)
from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.private_output import write_private_output
from fdai_deployment_cli.standalone_host_state import replace_private_json

_DIGEST = re.compile(r"[0-9a-f]{64}")
_PUBLISHER_FIXED_REASON = re.compile(r'echo "([^"$`\\]+)" >&2')
_MAX_STENCIL_STATE_BYTES = 16_384


def _fetch_operator_stencil_state(url: str, timeout_seconds: float) -> bytes:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise ValueError("Operator Stencil state endpoint is unavailable")
            raw = bytes(response.read(_MAX_STENCIL_STATE_BYTES + 1))
    except (HTTPError, URLError, TimeoutError) as error:
        raise ValueError("Operator Stencil state endpoint is unavailable") from error
    if len(raw) > _MAX_STENCIL_STATE_BYTES:
        raise ValueError("Operator Stencil state response is too large")
    return raw


def verify_operator_stencil_contract(
    operator_api_base_url: str,
    stencil_feature_flags: Mapping[str, object],
    *,
    timeout_seconds: float,
    fetch: Callable[[str, float], bytes] = _fetch_operator_stencil_state,
) -> None:
    """Require the deployed Operator to expose the exact selected Stencil before Console publish."""

    expected = validate_console_stencil_flags(stencil_feature_flags)
    expected_panels = expected.get("enabled_panel_ids")
    if not isinstance(expected_panels, list):
        raise TypeError("Selected Release Stencil enabled panels are required")
    endpoint = operator_api_base_url.rstrip("/") + "/system/stencil-feature-flags"
    payload = load_json_object(
        fetch(endpoint, min(max(timeout_seconds, 1.0), 10.0)),
        label="Operator Stencil state",
        max_bytes=_MAX_STENCIL_STATE_BYTES,
        strict=True,
    )
    if (
        payload.get("active") is not True
        or payload.get("stencil_id") != expected.get("stencil_id")
        or payload.get("enforcement_mode") != "fail-closed"
        or payload.get("enabled_panel_ids") != sorted(expected_panels)
    ):
        raise ValueError("Operator Stencil state differs from the selected Release")


def publish_verified_console(
    *,
    console_archive: Path,
    console_archive_sha256: str,
    bundle_root: Path,
    prepared_root: Path,
    entra_bindings: dict[str, str],
    browser_console: dict[str, Any],
    scripts: Path,
    subscription_id: str,
    tenant_id: str,
    timeout_seconds: int,
    redirect_changed: bool,
    verify_only: bool = False,
    verify_service_contracts: bool = True,
    stencil_feature_flags: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Configure a verified Console artifact, publish it, and read back exact bytes."""

    validated_stencil_flags: dict[str, object] | None = None
    if stencil_feature_flags is not None:
        validated_stencil_flags = validate_console_stencil_flags(stencil_feature_flags)
        if not isinstance(validated_stencil_flags.get("stencil_id"), str):
            raise ValueError("Console publication Stencil id is required")
        verify_operator_stencil_contract(
            str(browser_console["operator_api_base_url"]),
            validated_stencil_flags,
            timeout_seconds=timeout_seconds,
        )
    _require_archive_digest(console_archive, console_archive_sha256)
    extraction = prepared_root / "console-publish"
    # A retained extraction may contain a prior release, not the just-verified archive.
    _remove_retained_extraction(extraction)
    console_directory = extract_bundle_archive(console_archive, extraction)
    console_directory.chmod(0o700)
    settings: dict[str, object] = {
        "schema_version": "fdai.console-runtime.v1",
        "operator_api_base_url": str(browser_console["operator_api_base_url"]),
        "ingestion_api_base_url": str(browser_console["ingestion_api_base_url"]),
        "tenant_id": tenant_id,
        "spa_client_id": str(entra_bindings["ENTRA_CONSOLE_SPA_CLIENT_ID"]),
        "api_scope": str(entra_bindings["ENTRA_CONSOLE_API_SCOPE"]),
    }
    if validated_stencil_flags is not None:
        settings["stencil_feature_flags"] = validated_stencil_flags
    settings_path = prepared_root / "console-runtime-settings.json"
    replace_private_json(settings_path, settings)
    configured = configure_console(
        console_directory,
        settings_path,
        manual_studio_url=f"{browser_console['console_origin']}/manuals",
    )
    summary = prepared_root / "console-publish-summary.txt"
    if not summary.exists():
        write_private_output(summary, "")
    environment: dict[str, str] = {
        **os.environ,
        "EXPECTED_AZURE_TENANT_ID": str(settings["tenant_id"]),
        "ENTRA_CONSOLE_SPA_CLIENT_ID": str(settings["spa_client_id"]),
        "ENTRA_CONSOLE_API_SCOPE": str(settings["api_scope"]),
        "ARM_SUBSCRIPTION_ID": subscription_id,
        "CONSOLE_DEFAULT_HOSTNAME": str(browser_console["console_hostname"]),
        "CONSOLE_STATIC_WEB_APP_ID": str(browser_console["console_static_web_app_id"]),
        "BROWSER_GATEWAY_OPERATOR_URL": str(settings["operator_api_base_url"]),
        "BROWSER_GATEWAY_INGESTION_URL": str(settings["ingestion_api_base_url"]),
        "CONSOLE_PREBUILT_DIRECTORY": str(console_directory),
        "FDAI_CONSOLE_VERIFY_ONLY": "1" if verify_only else "0",
        "FDAI_CONSOLE_VERIFY_SERVICE_CONTRACTS": "1" if verify_service_contracts else "0",
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    completed = subprocess.run(
        (
            "/bin/bash",
            str(scripts / "publish-console.sh"),
            str(bundle_root / "infra/runtimes/aks/workloads"),
        ),
        cwd=bundle_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        reason = _publisher_failure_reason(scripts / "publish-console.sh", completed.stderr)
        raise ValueError(
            "prebuilt Console publication or browser verification failed"
            + (f": {reason}" if reason else "")
        )
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-console-publication.v1",
        "state": "verified" if verify_only else "published",
        "console_origin": browser_console["console_origin"],
        "console_archive_sha256": console_archive_sha256,
        "runtime_config_digest": configured["runtime_config_digest"],
        "entra_redirect_changed": redirect_changed,
        "artifact_hash_verified": True,
        "spa_fallback_verified": True,
        "api_health_verified": verify_service_contracts,
        "authorization_preflight_verified": verify_service_contracts,
        "unauthenticated_denial_verified": verify_service_contracts,
        "entra_redirect_verified": verify_service_contracts,
        "mutation_performed": not verify_only,
        "subscription_ready": False,
    }
    if validated_stencil_flags is not None:
        receipt["operator_stencil_verified"] = True
        receipt["stencil_id"] = validated_stencil_flags["stencil_id"]
        receipt["stencil_feature_flags_digest"] = canonical_digest(validated_stencil_flags)
    receipt["receipt_digest"] = canonical_digest(receipt)
    replace_private_json(prepared_root / "console-publication-receipt.json", receipt)
    return receipt


def _publisher_failure_reason(publisher: Path, stderr: str | None) -> str | None:
    """Return the publisher's final literal failure reason, never a variable diagnostic."""

    try:
        fixed_reasons = set(_PUBLISHER_FIXED_REASON.findall(publisher.read_text(encoding="utf-8")))
    except OSError:
        return None
    for line in reversed((stderr or "").splitlines()):
        if line.strip():
            return line.strip() if line.strip() in fixed_reasons else None
    return None


def _remove_retained_extraction(extraction: Path) -> None:
    """Remove a prior Console extraction without following a substituted link."""

    try:
        status = extraction.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(status.st_mode) or status.st_uid != os.getuid():
        raise ValueError("retained Console extraction is not a private directory")
    shutil.rmtree(extraction)


def _require_archive_digest(path: Path, expected_digest: str) -> None:
    if _DIGEST.fullmatch(expected_digest) is None:
        raise ValueError("Console archive digest is invalid")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Console archive is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            observed = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Console archive changed while it was read")
        if observed != expected_digest:
            raise ValueError("Console archive digest does not match the signed release")
    finally:
        os.close(descriptor)
