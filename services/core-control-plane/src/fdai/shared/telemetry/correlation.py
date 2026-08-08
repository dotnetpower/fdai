"""Correlation-ID context.

Every log line, span, and audit entry that touches an event MUST carry
its ``correlation_id`` so the control loop is reconstructable end-to-end
(see ``goals-and-metrics.md § Data Collection and Telemetry``).

Storage is a :class:`contextvars.ContextVar`, so async tasks and threads
that inherit the same context see the same value; a fresh task gets an
independent copy.

Usage
-----

.. code-block:: python

    from fdai.shared.telemetry import with_correlation, current_correlation_id

    with with_correlation("evt-42"):
        # every log line / span / audit inside this block carries evt-42
        do_work()

    assert current_correlation_id() is None
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_CORRELATION_ID: ContextVar[str | None] = ContextVar("fdai_correlation_id", default=None)


def current_correlation_id() -> str | None:
    """Return the correlation id bound to the current context, or ``None``."""
    return _CORRELATION_ID.get()


@contextmanager
def with_correlation(correlation_id: str) -> Iterator[None]:
    """Bind ``correlation_id`` to the current context for the duration of the block.

    Nested scopes restore the previous value on exit - nothing leaks.
    """
    if not correlation_id:
        raise ValueError("correlation_id MUST be a non-empty string")
    token = _CORRELATION_ID.set(correlation_id)
    try:
        yield
    finally:
        _CORRELATION_ID.reset(token)


__all__ = ["current_correlation_id", "with_correlation"]
