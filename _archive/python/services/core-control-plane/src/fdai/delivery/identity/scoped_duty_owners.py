"""Current scoped-plan Owner eligibility over separate person and role observations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType

from fdai.core.human_assignment.scoped_duties import (
    DutySubject,
    DutySubjectKind,
    DutySubjectResolver,
    utc_instant,
)
from fdai.shared.providers.human_identity import HumanIdentityDirectory


@dataclass(frozen=True, slots=True)
class CurrentScopedDutyOwners:
    """Require an active exact person and current ordinary Owner group membership.

    The role directory is composed uncached. Its bounded projection can prove positive
    membership only; a missing, ambiguous, or partial result denies eligibility. This
    adapter receives no role writer and never treats backup duty as a role grant.
    """

    subjects: DutySubjectResolver
    directory: HumanIdentityDirectory
    role_group_ids: Mapping[str, str]
    clock: Callable[[], datetime]
    timeout_seconds: float

    def __post_init__(self) -> None:
        if (
            set(self.role_group_ids) != {"Owner"}
            or not isinstance(self.role_group_ids["Owner"], str)
            or not self.role_group_ids["Owner"]
            or isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or not 0 < self.timeout_seconds <= 30
        ):
            raise ValueError("scoped Owner reader requires one configured role group and deadline")
        object.__setattr__(self, "role_group_ids", MappingProxyType(dict(self.role_group_ids)))

    async def is_current_owner(self, person_ref: str, *, at: datetime) -> bool:
        """Read person and role independently; failure holds and cancellation propagates."""
        try:
            async with asyncio.timeout(self.timeout_seconds):
                subject = DutySubject(DutySubjectKind.PERSON, person_ref)
                person = await self.subjects.resolve(subject, at=at)
                if (
                    person is None
                    or person.subject != subject
                    or person.people != (subject,)
                    or not person.complete
                ):
                    return False
                rows = await self.directory.list_role_roster(self.role_group_ids, limit=500)
                matches = [
                    row
                    for row in rows
                    if row.provider == "entra"
                    and row.subject_id == person_ref
                    and row.principal_type == "person"
                    and row.active is True
                    and "Owner" in row.roles
                ]
                return len(matches) == 1 and person.is_current(
                    at=utc_instant(self.clock()), max_age=timedelta(minutes=5)
                )
        except Exception:  # noqa: BLE001 - unavailable evidence is not a negative role-change event.
            return False


__all__ = ["CurrentScopedDutyOwners"]
