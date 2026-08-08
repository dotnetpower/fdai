"""In-memory :class:`RunbookRegistry` for tests + upstream Day-1 wiring.

Registers named runbooks as callables and records every invocation for
assertion. Fork replaces this with a registry that dispatches to the
real ``core.verticals.*`` runbook adapters.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from fdai.shared.providers.runbook_registry import (
    RunbookExecutionError,
    RunbookNotFoundError,
    RunbookRegistry,
    RunbookResult,
)

# A runbook callable receives (params, dry_run) and returns a
# RunbookResult synchronously; the fake wraps it in the async
# execute() method to match the Protocol.
RunbookCallable = Callable[[Mapping[str, object], bool], RunbookResult]


class InMemoryRunbookRegistry(RunbookRegistry):
    """Registry that dispatches to plain Python callables.

    ``register(name, fn)`` associates a name with a callable that takes
    ``(params, dry_run)`` and returns a :class:`RunbookResult`. The
    tool's dry_run vs live branching is preserved verbatim - the
    registry never overrides ``dry_run``.
    """

    def __init__(self) -> None:
        self._table: dict[str, RunbookCallable] = {}
        self._invocations: list[tuple[str, Mapping[str, object], bool]] = []
        self._next_error: Exception | None = None

    def register(self, name: str, fn: RunbookCallable) -> None:
        if not name:
            raise ValueError("runbook name MUST be non-empty")
        self._table[name] = fn

    def names(self) -> Sequence[str]:
        return tuple(sorted(self._table))

    async def execute(
        self,
        *,
        name: str,
        params: Mapping[str, object],
        dry_run: bool,
    ) -> RunbookResult:
        self._invocations.append((name, dict(params), dry_run))
        if self._next_error is not None:
            err, self._next_error = self._next_error, None
            raise err
        fn = self._table.get(name)
        if fn is None:
            raise RunbookNotFoundError(name)
        try:
            return fn(params, dry_run)
        except RunbookExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - wrap uncontrolled errors
            raise RunbookExecutionError(name, str(exc)) from exc

    # ------------------------------------------------------------------
    # Test-only hooks
    # ------------------------------------------------------------------

    @property
    def invocations(self) -> tuple[tuple[str, Mapping[str, object], bool], ...]:
        """Every ``execute`` call the tool made, in order."""
        return tuple(self._invocations)

    def next_error(self, exc: Exception) -> None:
        """Raise ``exc`` on the very next ``execute`` call."""
        self._next_error = exc


__all__ = ["InMemoryRunbookRegistry", "RunbookCallable"]
