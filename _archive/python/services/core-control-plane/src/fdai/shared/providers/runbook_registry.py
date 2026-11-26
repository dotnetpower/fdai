"""Runbook registry - Protocol for the ``run_runbook`` console tool.

The console's `run_runbook` tool routes an operator's runbook request
to the concrete adapter registered under ``docs/runbooks/`` (e.g.
``db_dr_drill_cli``). ``core/`` MUST NOT know which runbooks exist -
that is composition-root territory. This module ships the Protocol
plus the small result / error types the tool consumes.

Wave scope

- **This module (W1.1)** - Protocol + result types.
- **In-memory fake** at
  :mod:`fdai.shared.providers.testing.runbook_registry`.
- **Concrete adapters** (the actual runbook wrappers) already live
  under :mod:`fdai.core.verticals` and their CLI counterparts;
  a fork registers them at the composition root.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RunbookResult:
    """One-line summary the tool renders + records in audit.

    ``ok`` decides the tool status; ``summary`` is the short human
    readable line (no secrets, no customer-identifying values); the
    optional ``detail`` block is auxiliary structured data audit MAY
    quote.
    """

    ok: bool
    summary: str
    detail: Mapping[str, object] = field(default_factory=dict)


class RunbookError(RuntimeError):
    """Base class for runbook-registry failures.

    Subclasses carry a distinct ``kind`` so the audit record classifies
    without parsing the message.
    """

    __slots__ = ("kind",)

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class RunbookNotFoundError(RunbookError):
    """Raised when ``execute`` targets an unknown name."""

    def __init__(self, name: str) -> None:
        super().__init__(
            kind="not_found",
            message=f"no runbook registered under name {name!r}",
        )


class RunbookExecutionError(RunbookError):
    """Raised when an otherwise-registered runbook fails at dispatch.

    Adapters MUST truncate any vendor error to a short, secret-free
    summary before wrapping.
    """

    def __init__(self, name: str, detail: str) -> None:
        super().__init__(
            kind="execution",
            message=f"runbook {name!r} failed: {detail}",
        )


@runtime_checkable
class RunbookRegistry(Protocol):
    """Dispatch table from runbook name to adapter.

    Implementations MUST:

    - report a stable set via :meth:`names` (used by the tool's
      unknown-name fail-close path);
    - treat ``dry_run=True`` as a **read-only pass** - it MUST NOT
      mutate substrate state, MUST NOT call a privileged API, and
      MUST return a :class:`RunbookResult` that reflects the plan
      only;
    - treat ``dry_run=False`` as a live invocation and let the
      calling tool enforce the Owner-role gate before dispatch.

    ``execute`` is async because real adapters call substrate SDKs
    (Azure Chaos / Site Recovery). The fake shipped upstream is sync
    under the hood but still exposes an async method to keep the
    Protocol uniform.
    """

    def names(self) -> Sequence[str]: ...

    async def execute(
        self,
        *,
        name: str,
        params: Mapping[str, object],
        dry_run: bool,
    ) -> RunbookResult: ...


__all__ = [
    "RunbookError",
    "RunbookExecutionError",
    "RunbookNotFoundError",
    "RunbookRegistry",
    "RunbookResult",
]
