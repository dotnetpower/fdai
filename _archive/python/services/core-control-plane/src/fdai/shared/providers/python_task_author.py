"""Draft-generation seam for governed Python task artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fdai.shared.providers.vm_task import PythonTaskCapability, PythonTaskSpec


@dataclass(frozen=True, slots=True)
class PythonTaskAuthorRequest:
    intent: str
    task_id_hint: str
    target_capabilities: frozenset[PythonTaskCapability]
    allowed_modules: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.intent or len(self.intent) > 4_000:
            raise ValueError("intent MUST be a bounded non-empty string")
        if not self.task_id_hint or len(self.task_id_hint) > 80:
            raise ValueError("task_id_hint MUST be a bounded non-empty string")
        if len(self.allowed_modules) > 64:
            raise ValueError("allowed_modules MUST contain at most 64 entries")


@runtime_checkable
class PythonTaskAuthor(Protocol):
    """Generate an inert PythonTask draft; never stage or execute it."""

    async def author(self, request: PythonTaskAuthorRequest) -> PythonTaskSpec: ...


__all__ = ["PythonTaskAuthor", "PythonTaskAuthorRequest"]
