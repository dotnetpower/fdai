"""Small value types and principal-safe scope hashing for inventory CLI orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InventoryJobResult:
    """Report one promoted attempt after rereading the durable active pointer."""

    attempt_id: str
    source: str
    active: bool


@dataclass(frozen=True, slots=True)
class ChangeStreamDrainResult:
    """Sanitized per-source outcome for one bounded accelerator drain."""

    published: int
    unavailable_sources: tuple[str, ...] = ()

    @property
    def degraded(self) -> bool:
        """Return whether any enabled accelerator was unavailable."""

        return bool(self.unavailable_sources)


class InventoryOntologyProjectionIncompleteError(RuntimeError):
    """A promoted snapshot remains pending after a degraded projection."""


def scope_ref(scopes: tuple[str, ...]) -> str:
    """Hash configured scopes without retaining provider identifiers."""

    encoded = json.dumps(sorted(set(scopes)), separators=(",", ":")).encode("utf-8")
    return "scope-set:sha256:" + hashlib.sha256(encoded).hexdigest()


def generation_digest(generation: str) -> str:
    """Hash one opaque active-generation identifier for progress binding."""

    return "sha256:" + hashlib.sha256(generation.encode("utf-8")).hexdigest()


__all__ = [
    "ChangeStreamDrainResult",
    "InventoryJobResult",
    "InventoryOntologyProjectionIncompleteError",
    "generation_digest",
    "scope_ref",
]
