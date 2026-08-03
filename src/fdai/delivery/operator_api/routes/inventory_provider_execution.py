"""Strict projection for bounded inventory provider execution receipts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_RESULT_FIELDS = frozenset({"name", "type", "resource_group", "location", "status"})
_RESULT_PREVIEW_LIMIT = 10
_RESULT_VALUE_CHARS = 512


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
    subscription_id = value.get("subscription_id")
    if subscription_id is not None and (
        not isinstance(subscription_id, str)
        or not 1 <= len(subscription_id) <= 128
        or "\n" in subscription_id
    ):
        return None
    safe_commands: list[dict[str, Any]] = []
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
        result = _project_provider_result(command.get("result"))
        if "result" in command and result is None:
            return None
        safe_commands.append(
            {
                "label": label,
                "language": language,
                "command": text,
                **({"result": result} if result is not None else {}),
            }
        )
    return {
        "transport": "azure_cli",
        "backend": value["backend"],
        "executed": True,
        "redacted": True,
        "page_count": value["page_count"],
        **({"subscription_id": subscription_id} if subscription_id is not None else {}),
        "commands": safe_commands,
    }


def _project_provider_result(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    count = value.get("count")
    preview = value.get("preview")
    truncated = value.get("truncated")
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or not 0 <= count <= 1_000_000
        or not isinstance(preview, (list, tuple))
        or len(preview) > min(count, _RESULT_PREVIEW_LIMIT)
        or not isinstance(truncated, bool)
        or truncated is not (count > len(preview))
    ):
        return None
    safe_preview: list[dict[str, str]] = []
    for item in preview:
        if not isinstance(item, Mapping) or not set(item).issubset(_RESULT_FIELDS):
            return None
        safe_item: dict[str, str] = {}
        for key, item_value in item.items():
            if (
                not isinstance(key, str)
                or not isinstance(item_value, str)
                or not 1 <= len(item_value) <= _RESULT_VALUE_CHARS
                or "\n" in item_value
            ):
                return None
            safe_item[key] = item_value
        safe_preview.append(safe_item)
    return {"count": count, "preview": safe_preview, "truncated": truncated}


__all__ = ["project_inventory_provider_execution"]
