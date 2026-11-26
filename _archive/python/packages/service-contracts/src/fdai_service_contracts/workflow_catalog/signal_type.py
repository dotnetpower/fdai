"""Pure SignalType registry contracts shared by Core and Operator."""

from __future__ import annotations

import fnmatch
from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field

from fdai_service_contracts.workflow_catalog.base import WorkflowCatalogBase


class SignalDispatchMode(StrEnum):
    BASELINE = "baseline"
    EXACT = "exact"


class SignalTypeEntry(WorkflowCatalogBase):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$")]
    dispatch_mode: SignalDispatchMode
    event_type_patterns: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...]
    description: Annotated[str, Field(min_length=1, max_length=512)]


class SignalTypeRegistry(WorkflowCatalogBase):
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

    def resolve_declared(self, event_type: str | None) -> frozenset[str]:
        """Resolve only explicitly declared ids or patterns, without baseline fallback."""

        value = (event_type or "").strip().casefold()
        return frozenset(
            item.id
            for item in self.types
            if value == item.id
            or any(
                fnmatch.fnmatchcase(value, pattern.casefold())
                for pattern in item.event_type_patterns
            )
        )

    def resolve(self, event_type: str | None) -> frozenset[str]:
        """Resolve a raw event type to exact semantic types or the baseline."""

        exact = self.resolve_declared(event_type)
        if exact:
            return frozenset(exact)
        return frozenset(
            item.id for item in self.types if item.dispatch_mode is SignalDispatchMode.BASELINE
        )


__all__ = ["SignalDispatchMode", "SignalTypeEntry", "SignalTypeRegistry"]
