"""Strict catalog loader for normalized SignalType dispatch semantics."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from typing import Any

from fdai_service_contracts.workflow_catalog import (
    SignalDispatchMode,
    SignalTypeEntry,
    SignalTypeRegistry,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "signal_types.schema.json"


class SignalTypeRegistryError(ValueError):
    """Raised when the SignalType catalog is malformed."""


def load_signal_type_registry_from_mapping(raw: Mapping[str, Any]) -> SignalTypeRegistry:
    schema = json.loads(
        resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(dict(raw)), key=lambda e: list(e.path))
    if errors:
        preview = "; ".join(
            f"{'.'.join(str(item) for item in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors[:5]
        )
        raise SignalTypeRegistryError(f"signal-type registry validation failed: {preview}")
    try:
        return SignalTypeRegistry.model_validate(raw)
    except ValidationError as exc:
        raise SignalTypeRegistryError(f"signal-type registry validation failed: {exc}") from exc


__all__ = [
    "SignalDispatchMode",
    "SignalTypeEntry",
    "SignalTypeRegistry",
    "SignalTypeRegistryError",
    "load_signal_type_registry_from_mapping",
]
