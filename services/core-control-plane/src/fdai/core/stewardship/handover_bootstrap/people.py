"""Person-directory seam - resolve a mentioned name to an Entra object id.

A document says "Jane Kim owns cost"; the draft needs Jane Kim's Entra object
id. That lookup is Microsoft Graph in a fork, so it sits behind an **async**
Protocol (network I/O; see coding-conventions Provider Protocols) and
``core/`` never imports a cloud SDK. Unresolvable names are flagged, never
guessed into an id (issue #23 safety).

Distinct from :mod:`fdai.core.stewardship.directory`, which resolves the
reverse (an object id -> active/inactive, and a group -> members). This seam is
name -> object id for the bootstrap draft only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fdai.core.stewardship.model import StewardKind


@dataclass(frozen=True, slots=True)
class ResolvedIdentity:
    """A name resolved to an Entra object id and its kind (user or group)."""

    oid: str
    kind: StewardKind = StewardKind.USER


@runtime_checkable
class PersonDirectory(Protocol):
    """Resolve a human-readable name / team to an Entra object id.

    A fork wraps Microsoft Graph (``/users?$search`` / ``/groups``). Returns
    ``None`` for an ambiguous or unknown name so the caller surfaces it for a
    human rather than binding a wrong id. MUST NOT raise for an unknown name.
    """

    async def resolve(self, display_name: str) -> ResolvedIdentity | None:
        """Return the resolved identity for ``display_name``, or ``None``."""
        ...


class StaticPersonDirectory:
    """In-memory :class:`PersonDirectory` for tests / upstream default.

    Backed by a case-insensitive name -> :class:`ResolvedIdentity` map. An
    unknown name resolves to ``None`` (surfaced as unresolved), matching the
    upstream default where no real directory is wired.
    """

    def __init__(self, resolved: dict[str, ResolvedIdentity] | None = None) -> None:
        self._by_name = {name.strip().casefold(): ident for name, ident in (resolved or {}).items()}

    async def resolve(self, display_name: str) -> ResolvedIdentity | None:
        return self._by_name.get(display_name.strip().casefold())


class NullPersonDirectory:
    """A :class:`PersonDirectory` that resolves nothing.

    The upstream default: with no directory wired, every extracted name is
    surfaced as unresolved for a human to fill, never guessed.
    """

    async def resolve(self, display_name: str) -> ResolvedIdentity | None:  # noqa: ARG002
        return None


__all__ = [
    "NullPersonDirectory",
    "PersonDirectory",
    "ResolvedIdentity",
    "StaticPersonDirectory",
]
