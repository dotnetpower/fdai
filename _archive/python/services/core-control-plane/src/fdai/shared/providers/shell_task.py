"""Inert, content-addressed shell task artifacts for a credential-free sandbox."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from fdai.shared.providers.command_runner import CommandNetworkProfile

_TASK_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ShellTaskFile:
    path: str
    content: str = field(repr=False)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ShellTaskSpec:
    """One shell bundle that carries no executable path or credential selection."""

    task_id: str
    version: str
    entrypoint: str
    files: tuple[ShellTaskFile, ...]
    required_command_ids: tuple[str, ...] = ()
    timeout_seconds: int = 300
    network_profile: CommandNetworkProfile = CommandNetworkProfile.NONE

    def __post_init__(self) -> None:
        if not _TASK_ID.fullmatch(self.task_id):
            raise ValueError("task_id MUST be a lowercase dotted identifier")
        if not self.version or len(self.version) > 64:
            raise ValueError("version MUST be a non-empty string of at most 64 characters")
        if not self.files:
            raise ValueError("files MUST contain at least one file")
        if not 1 <= self.timeout_seconds <= 900:
            raise ValueError("timeout_seconds MUST be in [1, 900]")
        if any(not _COMMAND_ID.fullmatch(value) for value in self.required_command_ids):
            raise ValueError("required_command_ids MUST contain dotted command identifiers")
        if len(set(self.required_command_ids)) != len(self.required_command_ids):
            raise ValueError("required_command_ids MUST be unique")

    @property
    def artifact_hash(self) -> str:
        payload = {
            "task_id": self.task_id,
            "version": self.version,
            "entrypoint": self.entrypoint,
            "files": [
                {"path": item.path, "sha256": item.sha256}
                for item in sorted(self.files, key=lambda item: item.path)
            ],
            "required_command_ids": sorted(self.required_command_ids),
            "timeout_seconds": self.timeout_seconds,
            "network_profile": self.network_profile.value,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def artifact_ref(self) -> str:
        return f"shell-task:{self.task_id}@{self.version}#{self.artifact_hash}"


__all__ = ["ShellTaskFile", "ShellTaskSpec"]
