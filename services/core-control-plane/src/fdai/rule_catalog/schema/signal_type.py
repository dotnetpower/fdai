"""Strict catalog for normalized SignalType dispatch semantics."""

from __future__ import annotations

import fnmatch
import json
from collections.abc import Mapping
from enum import StrEnum
from importlib import resources
from typing import Annotated, Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, ValidationError

_SCHEMA_PACKAGE = "fdai.rule_catalog.schema"
_SCHEMA_FILE = "signal_types.schema.json"


class SignalDispatchMode(StrEnum):
    BASELINE = "baseline"
    EXACT = "exact"


class SignalTypeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$")]
    dispatch_mode: SignalDispatchMode
    event_type_patterns: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...]
    description: Annotated[str, Field(min_length=1, max_length=512)]


class SignalTypeRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    types: tuple[SignalTypeEntry, ...]

    def model_post_init(self, __context: Any) -> None:
        ids = tuple(item.id for item in self.types)
        if len(ids) != len(set(ids)):
            raise ValueError("SignalType ids MUST be unique")
        baselines = tuple(
            item.id for item in self.types if item.dispatch_mode is SignalDispatchMode.BASELINE
        )
        if len(baselines) != 1:
            raise ValueError("SignalType registry MUST declare exactly one baseline")

    def ids(self) -> frozenset[str]:
        return frozenset(item.id for item in self.types)

    def resolve(self, event_type: str | None) -> frozenset[str]:
        """Resolve a raw event type to exact semantic types or the baseline."""

        value = (event_type or "").strip().casefold()
        exact = {
            item.id
            for item in self.types
            if value == item.id
            or any(
                fnmatch.fnmatchcase(value, pattern.casefold())
                for pattern in item.event_type_patterns
            )
        }
        if exact:
            return frozenset(exact)
        return frozenset(
            item.id for item in self.types if item.dispatch_mode is SignalDispatchMode.BASELINE
        )


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
