"""In-memory :class:`BreakGlassPager` fake.

Two-mode behaviour a test can toggle:

- ``configured=True`` (default) - happy path: :meth:`notify_owners`
  returns a receipt.
- ``configured=False`` - raises :class:`BreakGlassNoChannelError`, used
  to exercise the "no channel configured" refusal branch.

``next_error(exc)`` raises ``exc`` on the very next call, mirroring the
injection hook on the other recording fakes; used to test
:class:`BreakGlassDeliveryError` refusal.
"""

from __future__ import annotations

from datetime import datetime
from itertools import count

from fdai.shared.providers.break_glass_pager import (
    BreakGlassNoChannelError,
    BreakGlassPager,
)


class InMemoryBreakGlassPager(BreakGlassPager):
    """Recording fake for the ``activate_break_glass`` console tool."""

    def __init__(self, *, configured: bool = True) -> None:
        self._configured = configured
        self._calls: list[dict[str, object]] = []
        self._counter = count(1)
        self._next_error: Exception | None = None

    async def notify_owners(
        self,
        *,
        actor_oid: str,
        actor_display: str,
        reason_redacted: str,
        activated_at: datetime,
        expires_at: datetime,
    ) -> str:
        self._calls.append(
            {
                "actor_oid": actor_oid,
                "actor_display": actor_display,
                "reason_redacted": reason_redacted,
                "activated_at": activated_at,
                "expires_at": expires_at,
            }
        )
        if self._next_error is not None:
            err, self._next_error = self._next_error, None
            raise err
        if not self._configured:
            raise BreakGlassNoChannelError()
        return f"pager-{next(self._counter)}"

    # ------------------------------------------------------------------
    # Test-only hooks
    # ------------------------------------------------------------------

    @property
    def calls(self) -> tuple[dict[str, object], ...]:
        return tuple(self._calls)

    def next_error(self, exc: Exception) -> None:
        self._next_error = exc


__all__ = ["InMemoryBreakGlassPager"]
