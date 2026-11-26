"""Bind a verified Foundation adoption to managed-host kit preparation."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_deployment_cli.deployment_kit import DeploymentKit
from fdai_deployment_cli.foundation_adoption_evidence import (
    validate_foundation_adoption_receipt,
)
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.target import compute_target_binding

_COMMIT = re.compile(r"[0-9a-f]{40}")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


@dataclass(frozen=True, slots=True)
class FoundationHostAdoption:
    """Current application source and optional no-effect adoption evidence."""

    source_commit: str
    digest: str
    receipt: dict[str, Any] | None

    def require_kit(self, kit: DeploymentKit) -> None:
        """Require one verified kit to match the selected application revision."""

        if kit.source_commit != self.source_commit:
            raise ValueError("Foundation and deployment kit source revisions differ")
        if self.receipt is not None and (
            self.receipt.get("kit_manifest_digest") != kit.verification.manifest_digest
            or self.receipt.get("runtime_release_digest") != kit.runtime.digest
        ):
            raise ValueError("Foundation adoption differs from the verified deployment kit")

    def require_context(self, context: dict[str, Any]) -> None:
        """Require retained host preparation to preserve the exact adoption."""

        if (
            context.get("source_commit") != self.source_commit
            or context.get("foundation_adoption_digest", "") != self.digest
            or (
                self.receipt is not None
                and (
                    context.get("kit_manifest_digest") != self.receipt.get("kit_manifest_digest")
                    or context.get("runtime_release_digest")
                    != self.receipt.get("runtime_release_digest")
                )
            )
        ):
            raise ValueError("standalone host retained Foundation adoption differs")


@dataclass(frozen=True, slots=True)
class FoundationHostContext:
    """Verified target, runner identity, and optional adoption."""

    subscription_id: str
    tenant_id: str
    target_binding: str
    client_id: str
    principal_id: str
    adoption: FoundationHostAdoption

    def login(
        self,
        operation: Callable[[str, str, str, str, Path], None],
        work_dir: Path,
    ) -> None:
        """Run the existing managed-identity login with verified target fields."""

        operation(
            self.subscription_id,
            self.tenant_id,
            self.client_id,
            self.principal_id,
            work_dir,
        )


def load_foundation_host_context(
    path: Path | None,
    *,
    handoff: dict[str, Any],
    runner: dict[str, Any],
) -> FoundationHostContext:
    """Load the target and adoption fields needed by managed-host preparation."""

    subscription_id = _guid(handoff, "subscription_id")
    tenant_id = _guid(handoff, "tenant_id")
    target_binding = compute_target_binding(
        tenant_id=tenant_id,
        subscription_id=subscription_id,
    )
    return FoundationHostContext(
        subscription_id=subscription_id,
        tenant_id=tenant_id,
        target_binding=target_binding,
        client_id=_guid(runner, "client_id"),
        principal_id=_guid(runner, "principal_id"),
        adoption=load_foundation_host_adoption(
            path,
            handoff=handoff,
            target_binding=target_binding,
        ),
    )


def load_foundation_host_adoption(
    path: Path | None,
    *,
    handoff: dict[str, Any],
    target_binding: str,
) -> FoundationHostAdoption:
    """Load optional adoption evidence while preserving the original handoff."""

    foundation_source_commit = handoff.get("source_commit")
    if (
        not isinstance(foundation_source_commit, str)
        or _COMMIT.fullmatch(foundation_source_commit) is None
    ):
        raise ValueError("Foundation handoff source revision is invalid")
    if path is None:
        return FoundationHostAdoption(
            source_commit=foundation_source_commit,
            digest="",
            receipt=None,
        )
    raw = read_private_bytes(path, max_bytes=65_536)
    receipt = load_json_object(raw, label="Foundation adoption")
    application_source_commit = str(receipt.get("application_source_commit", ""))
    digest = validate_foundation_adoption_receipt(
        receipt,
        handoff=handoff,
        target_binding=target_binding,
        application_source_commit=application_source_commit,
        kit_manifest_digest=str(receipt.get("kit_manifest_digest", "")),
        runtime_release_digest=str(receipt.get("runtime_release_digest", "")),
    )
    return FoundationHostAdoption(
        source_commit=application_source_commit,
        digest=digest,
        receipt=receipt,
    )


def _guid(value: dict[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or _GUID.fullmatch(item) is None:
        raise ValueError(f"{field} is not a canonical GUID")
    return item
