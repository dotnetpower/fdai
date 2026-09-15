"""Fresh exact-person and ordinary-role evidence for Core handover admission."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from fdai.core.human_assignment.scoped_duties import (
    DutySubject,
    DutySubjectKind,
    DutySubjectResolver,
)
from fdai.shared.providers.human_identity import HumanIdentityDirectory


@dataclass(frozen=True, slots=True)
class HandoverIdentityFacts:
    """Private current directory facts; group ids never enter a review record or general topic."""

    subject_ref: str
    roles: tuple[str, ...]
    group_ids: tuple[str, ...]
    observed_at: datetime
    expires_at: datetime

    def current(self, at: datetime) -> bool:
        """A caller may only shorten the original five-minute directory evidence window."""
        return self.observed_at <= at < self.expires_at


class HandoverIdentityReader(Protocol):
    """Read only exact current human facts; absence is never ordinary-role authority."""

    async def read(self, subject_ref: str) -> HandoverIdentityFacts | None:
        """Return bounded current facts or None without granting any identity capability."""
        ...


@dataclass(frozen=True, slots=True)
class CurrentHandoverIdentityReader:
    """Join a strict active-person read with uncached observed application roles and groups."""

    subjects: DutySubjectResolver
    directory: HumanIdentityDirectory
    role_group_ids: Mapping[str, str]
    clock: Callable[[], datetime]

    async def read(self, subject_ref: str) -> HandoverIdentityFacts | None:
        """Bound both directory reads; errors hold and cancellation is never swallowed."""
        async with asyncio.timeout(5):
            at = self.clock()
            subject = DutySubject(DutySubjectKind.PERSON, subject_ref)
            person = await self.subjects.resolve(subject, at=at)
            if (
                person is None
                or person.subject != subject
                or person.at != at
                or person.people != (subject,)
                or not person.complete
            ):
                return None
            roster = await self.directory.list_role_roster(self.role_group_ids, limit=500)
            matches = [
                row
                for row in roster
                if (
                    row.subject_id == subject_ref
                    and row.provider == "entra"
                    and row.principal_type == "person"
                    and row.active is True
                )
            ]
            if len(matches) != 1:
                return None
            row = matches[0]
            roles = tuple(sorted(set(row.roles) & {"Reader", "Contributor", "Approver", "Owner"}))
            if (
                not roles
                or len(row.group_ids) > 500
                or any(
                    not isinstance(group, str) or not 1 <= len(group) <= 256
                    for group in row.group_ids
                )
                or not person.is_current(at=self.clock(), max_age=timedelta(minutes=5))
            ):
                return None
            return HandoverIdentityFacts(
                subject_ref,
                roles,
                row.group_ids,
                at,
                min(person.valid_until, person.observed_at + timedelta(minutes=5)),
            )


__all__ = ["CurrentHandoverIdentityReader", "HandoverIdentityFacts", "HandoverIdentityReader"]
