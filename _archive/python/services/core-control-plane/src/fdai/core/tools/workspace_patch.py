"""Pure validation for repository patch proposals against private workspaces."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from fdai.shared.providers.code_workspace import CodePatchSet

_SAFE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,299}$")
_PROTECTED_PATHS = frozenset(
    {
        ".env",
        ".env.local",
        "resolved-models.json",
        "resolved-models-local.json",
    }
)
_PROTECTED_PREFIXES = (
    ".git/",
    ".venv/",
    "console/dist/",
    "infra/dev.plan",
    "infra/terraform.tfstate",
    "security/integrity/",
)


@dataclass(frozen=True, slots=True)
class WorkspacePatchPolicy:
    max_operations: int = 64
    max_file_bytes: int = 256 * 1024
    max_total_bytes: int = 1 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class WorkspacePatchIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class WorkspacePatchReport:
    patch_hash: str
    issues: tuple[WorkspacePatchIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


def validate_workspace_patch(
    patch: CodePatchSet,
    *,
    policy: WorkspacePatchPolicy | None = None,
) -> WorkspacePatchReport:
    """Validate shape and write scope before a workspace provider sees a patch."""

    resolved = policy or WorkspacePatchPolicy()
    issues: list[WorkspacePatchIssue] = []
    seen: set[str] = set()
    total_bytes = 0
    if len(patch.operations) > resolved.max_operations:
        issues.append(_issue("too_many_operations", "operations", "patch exceeds operation limit"))
    for operation in patch.operations:
        if operation.path in seen:
            issues.append(
                _issue("duplicate_path", operation.path, "each path may appear only once")
            )
        seen.add(operation.path)
        if not _valid_path(operation.path):
            issues.append(
                _issue("invalid_path", operation.path, "path MUST be repository-relative")
            )
        if _protected(operation.path):
            issues.append(
                _issue("protected_path", operation.path, "runtime/generated path is read-only")
            )
        if operation.content_after is not None:
            size = len(operation.content_after.encode("utf-8"))
            total_bytes += size
            if size > resolved.max_file_bytes:
                issues.append(
                    _issue("file_too_large", operation.path, "patched file exceeds byte limit")
                )
            if "\x00" in operation.content_after:
                issues.append(_issue("nul_byte", operation.path, "patched text MUST be NUL-free"))
    if total_bytes > resolved.max_total_bytes:
        issues.append(_issue("patch_too_large", "operations", "patch exceeds total byte limit"))
    return WorkspacePatchReport(patch_hash=patch.patch_hash, issues=tuple(issues))


def _valid_path(value: str) -> bool:
    if not _SAFE_PATH.fullmatch(value):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def _protected(value: str) -> bool:
    return value in _PROTECTED_PATHS or any(
        value == prefix.rstrip("/") or value.startswith(prefix) for prefix in _PROTECTED_PREFIXES
    )


def _issue(code: str, path: str, message: str) -> WorkspacePatchIssue:
    return WorkspacePatchIssue(code=code, path=path, message=message)


__all__ = [
    "WorkspacePatchIssue",
    "WorkspacePatchPolicy",
    "WorkspacePatchReport",
    "validate_workspace_patch",
]
