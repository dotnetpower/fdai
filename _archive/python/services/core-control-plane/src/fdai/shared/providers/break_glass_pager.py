"""BreakGlass pager - Protocol for the ``activate_break_glass`` console tool.

Chat invariant 7 (operator-console.md 7.2) requires BreakGlass grants to
be **fail-closed on notification**: if no pager channel confirms
delivery, the grant is refused. The tool depends on this Protocol; a
fork wires the real Teams / Slack / PagerDuty adapter, upstream ships
an in-memory fake with success + failure hooks.

The Protocol is deliberately narrower than the full notifications router
(:mod:`fdai.shared.providers.notifications`): break-glass has one
audience (every configured Owner), one severity (critical), one flow
(succeed or refuse). Keeping this seam thin lets a fork use whichever
underlying channel makes sense without the tool depending on the full
matrix.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


class BreakGlassPagerError(RuntimeError):
    """Base class for pager delivery failures.

    A raise from :meth:`BreakGlassPager.notify_owners` causes the tool
    to refuse the grant (chat invariant 7). The refusal is itself
    audited.
    """

    __slots__ = ("kind",)

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class BreakGlassNoChannelError(BreakGlassPagerError):
    """No pager channel is configured for BreakGlass in this deployment.

    Chat invariant 7 refuses to grant when no channel exists at all
    (an unwitnessed emergency elevation is more dangerous than a
    delayed emergency).
    """

    def __init__(self) -> None:
        super().__init__(
            kind="no_channel",
            message="no BreakGlass pager channel configured; grant refused",
        )


class BreakGlassDeliveryError(BreakGlassPagerError):
    """The pager attempted delivery but no channel confirmed.

    Adapters that fan out to multiple channels (Teams primary + Slack
    fallback) raise this when both fail. Message text is pre-redacted
    and truncated.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(
            kind="delivery",
            message=f"BreakGlass pager delivery failed: {detail}",
        )


@runtime_checkable
class BreakGlassPager(Protocol):
    """Fan out one page to every configured Owner-tier channel.

    Implementations MUST:

    - target the **Owner** audience only (BreakGlass is Owner-visible,
      never Reader / Contributor);
    - return an opaque ``pager_receipt`` string on **at-least-one**
      confirmed delivery (the caller records it verbatim in audit);
    - raise :class:`BreakGlassDeliveryError` when NO channel confirms
      - the tool refuses the grant in that case, per chat invariant 7;
    - raise :class:`BreakGlassNoChannelError` when the deployment has
      no BreakGlass channels configured at all.
    """

    async def notify_owners(
        self,
        *,
        actor_oid: str,
        actor_display: str,
        reason_redacted: str,
        activated_at: datetime,
        expires_at: datetime,
    ) -> str: ...


__all__ = [
    "BreakGlassDeliveryError",
    "BreakGlassNoChannelError",
    "BreakGlassPager",
    "BreakGlassPagerError",
]
