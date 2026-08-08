"""Structural, non-executing validation for credential-free shell tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from fdai.shared.providers.command_runner import CommandNetworkProfile
from fdai.shared.providers.shell_task import ShellTaskSpec

_SAFE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,199}$")
_SAFE_SHEBANGS = frozenset({"#!/bin/bash", "#!/usr/bin/env bash"})
_SECRET_MARKERS = (
    "AccountKey=",
    "SharedAccessKey=",
    "-----BEGIN PRIVATE KEY-----",
    "AWS_SECRET_ACCESS_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "AZURE_CLIENT_SECRET",
)
_FORBIDDEN_COMMANDS = frozenset(
    {
        ".",
        "az",
        "aws",
        "docker",
        "env",
        "gcloud",
        "gsutil",
        "kubectl",
        "mount",
        "nsenter",
        "podman",
        "scp",
        "ssh",
        "su",
        "sudo",
        "terraform",
        "tofu",
        "umount",
        "xargs",
    }
)
_FORBIDDEN_PATHS = (
    "/dev/",
    "/etc/",
    "/home/",
    "/proc/",
    "/root/",
    "/run/",
    "/sys/",
    "/var/run/",
)
_METADATA_ENDPOINTS = ("169.254.169.254", "metadata.google.internal")
_COMMAND_WORD = re.compile(r"(?:^|[|;&()])\s*(?:command\s+)?(?P<command>[A-Za-z0-9_./-]+)(?:\s|$)")


@dataclass(frozen=True, slots=True)
class ShellTaskPolicy:
    max_files: int = 32
    max_file_bytes: int = 128 * 1024
    max_total_bytes: int = 64 * 1024


@dataclass(frozen=True, slots=True)
class ShellTaskValidationIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ShellTaskValidationReport:
    artifact_hash: str
    issues: tuple[ShellTaskValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


def validate_shell_task(
    task: ShellTaskSpec,
    *,
    policy: ShellTaskPolicy | None = None,
) -> ShellTaskValidationReport:
    """Validate an inert shell bundle without invoking a shell parser."""

    resolved = policy or ShellTaskPolicy()
    issues: list[ShellTaskValidationIssue] = []
    by_path = {item.path: item for item in task.files}
    if len(by_path) != len(task.files):
        issues.append(_issue("duplicate_path", "files", "file paths MUST be unique"))
    if len(task.files) > resolved.max_files:
        issues.append(_issue("too_many_files", "files", "task exceeds the file-count limit"))
    if task.network_profile is not CommandNetworkProfile.NONE:
        issues.append(
            _issue(
                "network_profile_forbidden",
                "network_profile",
                "shell tasks MUST remain credential-free and offline until promoted",
            )
        )

    total_bytes = 0
    for item in task.files:
        encoded_bytes = len(item.content.encode("utf-8"))
        total_bytes += encoded_bytes
        if not _valid_relative_path(item.path):
            issues.append(
                _issue("invalid_path", item.path, "path MUST be relative and traversal-free")
            )
        if encoded_bytes > resolved.max_file_bytes:
            issues.append(_issue("file_too_large", item.path, "file exceeds the byte limit"))
        if "\x00" in item.content:
            issues.append(_issue("nul_byte", item.path, "shell source MUST be NUL-free"))
        if "\r" in item.content:
            issues.append(_issue("non_lf_line_endings", item.path, "shell source MUST use LF"))
        if any(marker in item.content for marker in _SECRET_MARKERS):
            issues.append(_issue("embedded_secret", item.path, "source contains a secret marker"))
        if item.path.endswith(".sh"):
            _validate_script(item.path, item.content, issues)

    if total_bytes > resolved.max_total_bytes:
        issues.append(_issue("artifact_too_large", "files", "task exceeds the total byte limit"))
    if task.entrypoint not in by_path:
        issues.append(_issue("missing_entrypoint", "entrypoint", "entrypoint is not in files"))
    elif not task.entrypoint.endswith(".sh"):
        issues.append(_issue("invalid_entrypoint", "entrypoint", "entrypoint MUST be a .sh file"))
    return ShellTaskValidationReport(artifact_hash=task.artifact_hash, issues=tuple(issues))


def _validate_script(
    path: str,
    content: str,
    issues: list[ShellTaskValidationIssue],
) -> None:
    lines = content.splitlines()
    if not lines or lines[0] not in _SAFE_SHEBANGS:
        issues.append(_issue("invalid_shebang", path, "script MUST use the pinned bash shebang"))
    effective = [
        line.strip() for line in lines[1:] if line.strip() and not line.lstrip().startswith("#")
    ]
    if not effective or effective[0] != "set -euo pipefail":
        issues.append(
            _issue("strict_mode_required", path, "first command MUST be 'set -euo pipefail'")
        )
    for line in effective:
        if re.search(r"(?:^|\s)set\s+(?:\+|-[^\n]*x)", line):
            issues.append(_issue("unsafe_shell_mode", path, "set +* and xtrace are not allowed"))
        if re.search(r"(?:^|[|;&()]|\s)(?:eval|exec|source)(?:\s|$)", line):
            issues.append(_issue("dynamic_shell", path, "eval, exec, and source are not allowed"))
        if any(root in line for root in _FORBIDDEN_PATHS):
            issues.append(_issue("host_path", path, "script references a protected host path"))
        if any(endpoint in line for endpoint in _METADATA_ENDPOINTS):
            issues.append(_issue("metadata_endpoint", path, "metadata endpoints are not allowed"))
        for match in _COMMAND_WORD.finditer(line):
            command = PurePosixPath(match.group("command")).name
            if command in _FORBIDDEN_COMMANDS:
                issues.append(
                    _issue(
                        "forbidden_command",
                        path,
                        f"command {command!r} requires a registered typed tool",
                    )
                )


def _valid_relative_path(value: str) -> bool:
    if not _SAFE_PATH.fullmatch(value):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def _issue(code: str, path: str, message: str) -> ShellTaskValidationIssue:
    return ShellTaskValidationIssue(code=code, path=path, message=message)


__all__ = [
    "ShellTaskPolicy",
    "ShellTaskValidationIssue",
    "ShellTaskValidationReport",
    "validate_shell_task",
]
