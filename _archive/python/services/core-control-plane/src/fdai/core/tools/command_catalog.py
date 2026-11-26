"""Deterministic command catalog that renders typed arguments into argv."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from fdai.shared.providers.command_runner import (
    CommandExecutionClass,
    CommandNetworkProfile,
    CommandOutputFormat,
    CommandPlan,
)

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class CommandArgumentKind(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"


class CommandArgumentSource(StrEnum):
    REQUEST = "request"
    TRUSTED = "trusted"


@dataclass(frozen=True, slots=True)
class CommandArgumentSpec:
    name: str
    kind: CommandArgumentKind
    source: CommandArgumentSource = CommandArgumentSource.REQUEST
    flag: str | None = None
    required: bool = True
    pattern: str | None = None
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.name):
            raise ValueError("command argument name MUST be a lowercase identifier")
        if self.flag is not None and not re.fullmatch(r"--[a-z][a-z0-9-]{0,63}", self.flag):
            raise ValueError("command argument flag MUST be a long option")
        if self.kind is CommandArgumentKind.BOOLEAN and self.flag is None:
            raise ValueError("boolean command arguments MUST declare a flag")
        if self.pattern is not None:
            re.compile(self.pattern)
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("command argument minimum MUST NOT exceed maximum")


@dataclass(frozen=True, slots=True)
class CommandSpec:
    command_id: str
    version: int
    executable_ref: str
    fixed_argv: tuple[str, ...]
    arguments: tuple[CommandArgumentSpec, ...]
    execution_class: CommandExecutionClass
    network_profile: CommandNetworkProfile = CommandNetworkProfile.NONE
    output_format: CommandOutputFormat = CommandOutputFormat.TEXT
    timeout_seconds: int = 60
    max_output_bytes: int = 64 * 1024
    credential_profile: str | None = None
    workspace_required: bool = False

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.command_id):
            raise ValueError("command_id MUST be a lowercase dotted identifier")
        if self.version < 1:
            raise ValueError("command version MUST be positive")
        if not _IDENTIFIER.fullmatch(self.executable_ref):
            raise ValueError("executable_ref MUST be a lowercase dotted identifier")
        if any(not value or "\x00" in value for value in self.fixed_argv):
            raise ValueError("fixed_argv entries MUST be non-empty and NUL-free")
        names = [argument.name for argument in self.arguments]
        if len(names) != len(set(names)):
            raise ValueError("command argument names MUST be unique")
        if self.execution_class is CommandExecutionClass.CLOUD_READ:
            if self.credential_profile is None:
                raise ValueError("cloud-read commands MUST declare a credential_profile")


class CommandCatalog:
    """Resolve one registered command without accepting raw argv or env."""

    def __init__(self, specs: tuple[CommandSpec, ...]) -> None:
        by_id = {spec.command_id: spec for spec in specs}
        if len(by_id) != len(specs):
            raise ValueError("command ids MUST be unique")
        self._by_id = by_id

    def resolve(
        self,
        *,
        command_id: str,
        arguments: Mapping[str, object],
        trusted_values: Mapping[str, object],
        idempotency_key: str,
        dry_run: bool = True,
        workspace_ref: str | None = None,
    ) -> CommandPlan:
        try:
            spec = self._by_id[command_id]
        except KeyError as exc:
            raise LookupError(f"unknown command id {command_id!r}") from exc
        declared = {argument.name for argument in spec.arguments}
        unknown = sorted(set(arguments) - declared)
        if unknown:
            raise ValueError(f"unknown command arguments: {unknown}")
        argv = list(spec.fixed_argv)
        for argument in spec.arguments:
            if argument.source is CommandArgumentSource.TRUSTED and argument.name in arguments:
                raise ValueError(
                    f"trusted command argument {argument.name!r} MUST NOT come from the request"
                )
            values = (
                trusted_values if argument.source is CommandArgumentSource.TRUSTED else arguments
            )
            if argument.name not in values:
                if argument.required:
                    raise ValueError(f"missing command argument {argument.name!r}")
                continue
            value = _validated_value(argument, values[argument.name])
            if argument.kind is CommandArgumentKind.BOOLEAN:
                if value is True and argument.flag is not None:
                    argv.append(argument.flag)
                continue
            rendered = str(value)
            if argument.flag is None:
                if rendered.startswith("-"):
                    raise ValueError(
                        f"positional command argument {argument.name!r} MUST NOT start with '-'"
                    )
                argv.append(rendered)
            else:
                argv.extend((argument.flag, rendered))
        if spec.workspace_required and workspace_ref is None:
            raise ValueError("command requires a workspace_ref")
        return CommandPlan(
            command_id=spec.command_id,
            command_version=spec.version,
            idempotency_key=idempotency_key,
            executable_ref=spec.executable_ref,
            argv=tuple(argv),
            execution_class=spec.execution_class,
            network_profile=spec.network_profile,
            output_format=spec.output_format,
            timeout_seconds=spec.timeout_seconds,
            max_output_bytes=spec.max_output_bytes,
            dry_run=dry_run,
            credential_profile=spec.credential_profile,
            workspace_ref=workspace_ref,
        )


def _validated_value(spec: CommandArgumentSpec, value: object) -> str | int | bool:
    if spec.kind is CommandArgumentKind.STRING:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError(f"command argument {spec.name!r} MUST be a non-empty string")
        if spec.pattern is not None and re.fullmatch(spec.pattern, value) is None:
            raise ValueError(f"command argument {spec.name!r} does not match its pattern")
        rendered: str | int | bool = value
    elif spec.kind is CommandArgumentKind.INTEGER:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"command argument {spec.name!r} MUST be an integer")
        if spec.minimum is not None and value < spec.minimum:
            raise ValueError(f"command argument {spec.name!r} is below its minimum")
        if spec.maximum is not None and value > spec.maximum:
            raise ValueError(f"command argument {spec.name!r} exceeds its maximum")
        rendered = value
    else:
        if not isinstance(value, bool):
            raise ValueError(f"command argument {spec.name!r} MUST be a boolean")
        rendered = value
    if spec.choices and str(rendered) not in spec.choices:
        raise ValueError(f"command argument {spec.name!r} is not an allowed choice")
    return rendered


__all__ = [
    "CommandArgumentKind",
    "CommandArgumentSource",
    "CommandArgumentSpec",
    "CommandCatalog",
    "CommandSpec",
]
