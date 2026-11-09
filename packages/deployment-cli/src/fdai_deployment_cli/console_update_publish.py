"""Publish one approved existing-Console update."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from fdai_deployment_cli.standalone_console_publish import publish_verified_console


class ConsoleUpdatePublicationTarget(Protocol):
    @property
    def subscription_id(self) -> str: ...

    @property
    def tenant_id(self) -> str: ...

    @property
    def console_hostname(self) -> str: ...

    @property
    def console_static_web_app_id(self) -> str: ...

    @property
    def operator_api_base_url(self) -> str: ...

    @property
    def ingestion_api_base_url(self) -> str: ...

    @property
    def entra_console_spa_client_id(self) -> str: ...

    @property
    def entra_console_api_scope(self) -> str: ...

    @property
    def stencil_feature_flags(self) -> dict[str, object]: ...


def publish_console_update(
    *,
    source_root: Path,
    work_dir: Path,
    archive: Path,
    archive_digest: str,
    target: ConsoleUpdatePublicationTarget,
    scripts: Path,
    timeout_seconds: int,
    verify_only: bool,
    verify_service_contracts: bool = True,
) -> dict[str, object]:
    work_dir.mkdir(mode=0o700, exist_ok=True)
    if work_dir.is_symlink() or not work_dir.is_dir():
        raise ValueError("Console publication work directory is invalid")
    work_dir.chmod(0o700)
    return publish_verified_console(
        console_archive=archive,
        console_archive_sha256=archive_digest,
        bundle_root=source_root,
        prepared_root=work_dir,
        entra_bindings={
            "ENTRA_CONSOLE_SPA_CLIENT_ID": target.entra_console_spa_client_id,
            "ENTRA_CONSOLE_API_SCOPE": target.entra_console_api_scope,
        },
        browser_console={
            "console_hostname": target.console_hostname,
            "console_origin": f"https://{target.console_hostname}",
            "console_static_web_app_id": target.console_static_web_app_id,
            "operator_api_base_url": target.operator_api_base_url,
            "ingestion_api_base_url": target.ingestion_api_base_url,
        },
        scripts=scripts,
        subscription_id=target.subscription_id,
        tenant_id=target.tenant_id,
        timeout_seconds=timeout_seconds,
        redirect_changed=False,
        verify_only=verify_only,
        verify_service_contracts=verify_service_contracts,
        stencil_feature_flags=target.stencil_feature_flags,
    )


__all__ = ["publish_console_update"]
