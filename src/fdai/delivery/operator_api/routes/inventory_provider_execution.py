"""Strict projection for redacted inventory provider execution receipts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def project_inventory_provider_execution(value: object) -> dict[str, Any] | None:
    """Return one bounded provider receipt or ``None`` when it is not trustworthy."""

    if not isinstance(value, Mapping):
        return None
    if (
        value.get("transport") != "azure_cli"
        or value.get("backend") not in {"azure_resource_graph", "azure_resource_manager"}
        or value.get("executed") is not True
        or value.get("redacted") is not True
        or not isinstance(value.get("page_count"), int)
        or not 1 <= value["page_count"] <= 32
    ):
        return None
    commands = value.get("commands")
    if not isinstance(commands, (list, tuple)) or not 1 <= len(commands) <= 4:
        return None
    safe_commands: list[dict[str, str]] = []
    for command in commands:
        if not isinstance(command, Mapping):
            return None
        label = command.get("label")
        language = command.get("language")
        text = command.get("command")
        if (
            label not in {"resource_groups", "resources"}
            or language != "azure_cli"
            or not isinstance(text, str)
            or not 1 <= len(text) <= 4096
            or "\n" in text
        ):
            return None
        safe_commands.append({"label": label, "language": language, "command": text})
    return {
        "transport": "azure_cli",
        "backend": value["backend"],
        "executed": True,
        "redacted": True,
        "page_count": value["page_count"],
        "commands": safe_commands,
    }


__all__ = ["project_inventory_provider_execution"]
