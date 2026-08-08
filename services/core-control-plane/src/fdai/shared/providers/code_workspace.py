"""Provider-neutral contracts for isolated code workspaces and patch proposals."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

_WORKSPACE_REF = re.compile(r"^workspace:sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CodePatchKind(StrEnum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class CodePatchOperation:
    kind: CodePatchKind
    path: str
    expected_before_sha256: str | None = None
    content_after: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.expected_before_sha256 is not None and not _SHA256.fullmatch(
            self.expected_before_sha256
        ):
            raise ValueError("expected_before_sha256 MUST be a lowercase SHA-256")
        if self.kind is CodePatchKind.ADD:
            if self.expected_before_sha256 is not None or self.content_after is None:
                raise ValueError("add requires content_after and no before hash")
        elif self.kind is CodePatchKind.UPDATE:
            if self.expected_before_sha256 is None or self.content_after is None:
                raise ValueError("update requires before hash and content_after")
        elif self.expected_before_sha256 is None or self.content_after is not None:
            raise ValueError("delete requires before hash and no content_after")

    @property
    def content_after_sha256(self) -> str | None:
        if self.content_after is None:
            return None
        return hashlib.sha256(self.content_after.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CodePatchSet:
    """One immutable proposal against a private workspace snapshot."""

    workspace_ref: str
    base_revision: str
    operations: tuple[CodePatchOperation, ...]

    def __post_init__(self) -> None:
        if not _WORKSPACE_REF.fullmatch(self.workspace_ref):
            raise ValueError("workspace_ref MUST be a content-addressed workspace ref")
        if not _REVISION.fullmatch(self.base_revision):
            raise ValueError("base_revision MUST be a bounded revision identifier")
        if not self.operations:
            raise ValueError("operations MUST contain at least one change")

    @property
    def patch_hash(self) -> str:
        payload = {
            "workspace_ref": self.workspace_ref,
            "base_revision": self.base_revision,
            "operations": [
                {
                    "kind": operation.kind.value,
                    "path": operation.path,
                    "expected_before_sha256": operation.expected_before_sha256,
                    "content_after_sha256": operation.content_after_sha256,
                }
                for operation in self.operations
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CodeWorkspaceSnapshot:
    workspace_ref: str
    base_revision: str

    def __post_init__(self) -> None:
        if not _WORKSPACE_REF.fullmatch(self.workspace_ref):
            raise ValueError("workspace_ref MUST be a content-addressed workspace ref")
        if not _REVISION.fullmatch(self.base_revision):
            raise ValueError("base_revision MUST be a bounded revision identifier")


@runtime_checkable
class CodeWorkspaceProvider(Protocol):
    """Prepare and patch only private workspaces, never the runtime checkout."""

    async def prepare(self, *, base_revision: str) -> CodeWorkspaceSnapshot: ...

    async def apply(self, patch: CodePatchSet) -> str: ...


__all__ = [
    "CodePatchKind",
    "CodePatchOperation",
    "CodePatchSet",
    "CodeWorkspaceProvider",
    "CodeWorkspaceSnapshot",
]
