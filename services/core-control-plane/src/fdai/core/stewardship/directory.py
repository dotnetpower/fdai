"""Identity-directory seams for stewardship (stale-OID + group expansion).

Two injected Protocols keep `core/stewardship` CSP-neutral: the Graph-backed
implementations live in a fork / the delivery layer, the static ones here are
for tests and upstream defaults. Both are declared **async** because a real
backend (Microsoft Graph) is network I/O; blocking the event loop is not
allowed (see coding-conventions § Provider Protocols).

Neither is on the control-loop hot path: group expansion happens when an
escalation plan is materialized, and stale-OID checks run on a schedule. The
control loop never blocks on either - callers degrade to a best-effort result
and log a warning when the provider is unavailable.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable


@runtime_checkable
class IdentityDirectory(Protocol):
    """Confirms whether an Entra object id still resolves to an active account."""

    async def is_active(self, oid: str) -> bool:
        """Return ``True`` iff ``oid`` is a live, enabled account.

        A fork wraps Microsoft Graph; a missing or disabled account returns
        ``False`` and the person is dropped from live escalation (falling
        through to the next tier / maintainer).
        """
        ...


@runtime_checkable
class GroupMembershipProvider(Protocol):
    """Expands an Entra group object id to its member user object ids."""

    async def members_of(self, group_oid: str) -> tuple[str, ...]:
        """Return the member user object ids of ``group_oid``.

        Best-effort: on failure the caller treats the group as one opaque unit
        rather than blocking. An implementation MUST NOT raise for an unknown
        group - it returns an empty tuple.
        """
        ...


class StaticIdentityDirectory:
    """In-memory :class:`IdentityDirectory` for tests / upstream default.

    Every id passed to the constructor is considered active; anything else is
    stale. An empty set means "directory unknown" - see :attr:`assume_active`.
    """

    def __init__(self, active_oids: Iterable[str] = (), *, assume_active: bool = True) -> None:
        self._active = frozenset(active_oids)
        self._assume_active = assume_active

    async def is_active(self, oid: str) -> bool:
        if not self._active:
            # No directory data configured: do not manufacture stale findings.
            return self._assume_active
        return oid in self._active


class StaticGroupMembershipProvider:
    """In-memory :class:`GroupMembershipProvider` for tests / upstream default."""

    def __init__(self, members: dict[str, tuple[str, ...]] | None = None) -> None:
        self._members = dict(members or {})

    async def members_of(self, group_oid: str) -> tuple[str, ...]:
        return self._members.get(group_oid, ())


__all__ = [
    "GroupMembershipProvider",
    "IdentityDirectory",
    "StaticGroupMembershipProvider",
    "StaticIdentityDirectory",
]
