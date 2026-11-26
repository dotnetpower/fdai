"""Invocation-scope context for measured model usage."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from fdai.core.metering.records import InvocationScope

_INVOCATION_SCOPE: ContextVar[InvocationScope] = ContextVar(
    "fdai_metering_invocation_scope",
    default=InvocationScope.CONTROL_PLANE,
)


def current_invocation_scope() -> InvocationScope:
    """Return the workload scope bound to the current model call."""
    return _INVOCATION_SCOPE.get()


@contextmanager
def with_invocation_scope(scope: InvocationScope) -> Iterator[None]:
    """Bind an explicit workload scope and restore the previous value on exit."""
    token = _INVOCATION_SCOPE.set(scope)
    try:
        yield
    finally:
        _INVOCATION_SCOPE.reset(token)


__all__ = ["current_invocation_scope", "with_invocation_scope"]
