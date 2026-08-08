"""Cloud-neutral human identity directory contract for operator IAM.

The core and console consume stable provider subjects without importing an
Azure, AWS, or Google SDK. Delivery adapters translate their directory records
into :class:`HumanIdentity`. The implemented upstream adapter targets Microsoft
Entra ID; future providers implement the same async search contract.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class HumanIdentity:
    """One searchable human account from an external identity provider."""

    provider: str
    subject_id: str
    username: str
    display_name: str
    user_type: str = "member"
    active: bool = True

    def __post_init__(self) -> None:
        for name in ("provider", "subject_id", "username", "display_name", "user_type"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"HumanIdentity.{name} MUST be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "subject_id": self.subject_id,
            "username": self.username,
            "display_name": self.display_name,
            "user_type": self.user_type,
            "active": self.active,
        }


@dataclass(frozen=True, slots=True)
class IdentityRosterEntry:
    """One person or group with its effective FDAI role bindings."""

    provider: str
    subject_id: str
    display_name: str
    principal_type: str
    roles: tuple[str, ...]
    username: str | None = None
    active: bool = True

    def __post_init__(self) -> None:
        for name in ("provider", "subject_id", "display_name", "principal_type"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"IdentityRosterEntry.{name} MUST be non-empty")
        if not self.roles or any(not role.strip() for role in self.roles):
            raise ValueError("IdentityRosterEntry.roles MUST contain non-empty roles")

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "subject_id": self.subject_id,
            "display_name": self.display_name,
            "principal_type": self.principal_type,
            "roles": list(self.roles),
            "username": self.username,
            "active": self.active,
        }


@runtime_checkable
class HumanIdentityDirectory(Protocol):
    """Search human accounts without exposing provider credentials to callers."""

    async def search(self, query: str, *, limit: int = 20) -> tuple[HumanIdentity, ...]:
        """Return up to ``limit`` matching identities in provider-defined order."""
        ...

    async def get_by_subject_id(self, subject_id: str) -> HumanIdentity | None:
        """Return one exact human subject, or ``None`` when it does not exist."""
        ...

    async def list_role_roster(
        self,
        role_group_ids: Mapping[str, str],
        *,
        limit: int = 200,
    ) -> tuple[IdentityRosterEntry, ...]:
        """Return role groups and their person members as one bounded projection."""
        ...


class StaticHumanIdentityDirectory:
    """In-memory directory for tests and the local console harness."""

    def __init__(
        self,
        identities: Iterable[HumanIdentity] = (),
        roster: Iterable[IdentityRosterEntry] = (),
    ) -> None:
        self._identities = tuple(identities)
        self._roster = tuple(roster)

    async def search(self, query: str, *, limit: int = 20) -> tuple[HumanIdentity, ...]:
        normalized = _validate_search(query, limit=limit)
        matches = (
            identity
            for identity in self._identities
            if normalized in identity.username.casefold()
            or normalized in identity.display_name.casefold()
        )
        return tuple(matches)[:limit]

    async def get_by_subject_id(self, subject_id: str) -> HumanIdentity | None:
        normalized = subject_id.strip()
        if not normalized:
            raise ValueError("identity subject_id MUST be non-empty")
        return next(
            (identity for identity in self._identities if identity.subject_id == normalized),
            None,
        )

    async def list_role_roster(
        self,
        role_group_ids: Mapping[str, str],
        *,
        limit: int = 200,
    ) -> tuple[IdentityRosterEntry, ...]:
        del role_group_ids
        if limit < 1 or limit > 500:
            raise ValueError("identity roster limit MUST be between 1 and 500")
        return self._roster[:limit]


def _validate_search(query: str, *, limit: int) -> str:
    normalized = query.strip().casefold()
    if len(normalized) < 2:
        raise ValueError("identity search query MUST contain at least 2 characters")
    if len(normalized) > 128:
        raise ValueError("identity search query MUST contain at most 128 characters")
    if limit < 1 or limit > 50:
        raise ValueError("identity search limit MUST be between 1 and 50")
    return normalized


__all__ = [
    "HumanIdentity",
    "HumanIdentityDirectory",
    "IdentityRosterEntry",
    "StaticHumanIdentityDirectory",
]
