"""Stage protocol for the future ControlLoop pipeline (G-2 phase 2).

Not yet consumed by the orchestrator - see :file:`__init__.py` for the
follow-up scope declaration. Defined here so downstream forks can begin
subclassing / composing against a stable Protocol identity while phase
2 is designed.

Every stage MUST be:
  * async (control-plane I/O is async by default per the coding
    conventions)
  * side-effect-scoped (auditable via the passed-in ctx; no reaching
    into module globals)
  * idempotent (re-delivery of the same event MUST NOT double-apply)

The Protocol is intentionally minimal; concrete stages own their own
constructor injection.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Stage(Protocol):
    """One pipeline step of the future stage-based ControlLoop."""

    name: str

    async def handle(self, ctx: Any) -> Any:  # pragma: no cover - scaffold
        """Execute this stage against ``ctx`` and return a result.

        ``ctx`` type will be pinned to ``PipelineContext`` when phase 2
        lands. Kept ``Any`` here so the scaffold does not force a
        premature type on the follow-up work.
        """
        ...


__all__ = ["Stage"]
