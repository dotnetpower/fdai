"""Fail-closed local configuration for the development diagnostic socket."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_SERVICE = re.compile(r"^[a-z][a-z0-9-]{0,79}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class DevelopmentDiagnosticsConfig:
    """Bind one local process to exact source and owner-only socket identities."""

    service_id: str
    execution_venue: Literal["local"]
    socket_path: Path
    source_root: Path
    source_revision: str
    service_input_digest: str
    worktree_digest: str
    runtime_scope_receipt_digest: str

    def __post_init__(self) -> None:
        if self.execution_venue != "local":
            raise ValueError("development diagnostics require the local execution venue")
        if _SERVICE.fullmatch(self.service_id) is None:
            raise ValueError("development diagnostics service id is invalid")
        if _SHA40.fullmatch(self.source_revision) is None:
            raise ValueError("development diagnostics source revision is invalid")
        if (
            _SHA64.fullmatch(self.service_input_digest) is None
            or _SHA64.fullmatch(self.worktree_digest) is None
        ):
            raise ValueError("development diagnostics input identity is invalid")
        if _RECEIPT.fullmatch(self.runtime_scope_receipt_digest) is None:
            raise ValueError("development diagnostics runtime scope receipt is invalid")
        if len(os.fsencode(self.socket_path)) > 100:
            raise ValueError("development diagnostics socket path exceeds the portable limit")

    @classmethod
    def from_environment(
        cls,
        service_id: str,
        runtime_scope_receipt_digest: str,
        environment: Mapping[str, str] | None = None,
    ) -> DevelopmentDiagnosticsConfig | None:
        values = os.environ if environment is None else environment
        enabled = values.get("FDAI_DEVELOPMENT_DIAGNOSTICS", "").strip().lower()
        if enabled not in {"1", "true"}:
            return None
        if values.get("FDAI_EXECUTION_VENUE", "").strip().lower() != "local":
            raise ValueError("development diagnostics require the local execution venue")
        if _SERVICE.fullmatch(service_id) is None:
            raise ValueError("development diagnostics service id is invalid")
        source_revision = values.get("FDAI_DEVELOPMENT_DIAGNOSTICS_SOURCE_REVISION", "")
        input_digest = values.get("FDAI_DEVELOPMENT_DIAGNOSTICS_INPUT_DIGEST", "")
        worktree_digest = values.get("FDAI_DEVELOPMENT_DIAGNOSTICS_WORKTREE_DIGEST", "")
        if _SHA40.fullmatch(source_revision) is None:
            raise ValueError("development diagnostics source revision is invalid")
        if _SHA64.fullmatch(input_digest) is None or _SHA64.fullmatch(worktree_digest) is None:
            raise ValueError("development diagnostics input identity is invalid")
        if _RECEIPT.fullmatch(runtime_scope_receipt_digest) is None:
            raise ValueError("development diagnostics runtime scope receipt is invalid")
        source_root = Path(
            values.get("FDAI_DEVELOPMENT_DIAGNOSTICS_SOURCE_ROOT", str(Path.cwd()))
        ).resolve()
        socket_root = Path(
            values.get(
                "FDAI_DEVELOPMENT_DIAGNOSTICS_SOCKET_DIR",
                str(source_root / ".fdai" / "r"),
            )
        ).resolve()
        if socket_root == source_root or not socket_root.is_relative_to(source_root / ".fdai"):
            raise ValueError("development diagnostics socket directory escaped private local state")
        socket_identity = hashlib.sha256(
            (
                f"{service_id}:{source_revision}:{input_digest}:{worktree_digest}:"
                f"{runtime_scope_receipt_digest}"
            ).encode("utf-8")
        ).hexdigest()[:12]
        socket_path = socket_root / f"{socket_identity}.sock"
        if len(os.fsencode(socket_path)) > 100:
            raise ValueError("development diagnostics socket path exceeds the portable limit")
        return cls(
            service_id=service_id,
            execution_venue="local",
            socket_path=socket_path,
            source_root=source_root,
            source_revision=source_revision,
            service_input_digest=input_digest,
            worktree_digest=worktree_digest,
            runtime_scope_receipt_digest=runtime_scope_receipt_digest,
        )


__all__ = ["DevelopmentDiagnosticsConfig"]
