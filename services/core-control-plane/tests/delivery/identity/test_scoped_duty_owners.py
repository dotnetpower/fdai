"""Current Owner evidence never arises from duty, emergency role, or stale directory data."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fdai.core.human_assignment.scoped_duties import DutyResolution, DutySubject, DutySubjectKind
from fdai.delivery.identity.scoped_duty_owners import CurrentScopedDutyOwners
from fdai.shared.providers.human_identity import IdentityRosterEntry

AT = datetime(2026, 9, 14, 12, tzinfo=UTC)
PERSON = "00000000-0000-0000-0000-000000000001"
GROUP = "00000000-0000-0000-0000-000000000002"


def reader(*, roles=("Owner",), active=True, ref=PERSON):
    subject = DutySubject(DutySubjectKind.PERSON, PERSON)
    person = DutyResolution(
        subject, AT, (subject,), AT, AT + timedelta(minutes=5), "source:example", "a" * 64, True
    )
    directory = SimpleNamespace(
        list_role_roster=AsyncMock(
            return_value=(
                IdentityRosterEntry("entra", ref, "Example human", "person", roles, active=active),
            )
        )
    )
    return CurrentScopedDutyOwners(
        SimpleNamespace(resolve=AsyncMock(return_value=person)),
        directory,
        {"Owner": GROUP},
        lambda: AT,
        1.0,
    )


async def test_current_active_person_and_exact_owner_membership_are_both_required():
    source = reader()
    assert await source.is_current_owner(PERSON, at=AT)
    source.directory.list_role_roster.assert_awaited_once_with({"Owner": GROUP}, limit=500)
    source.subjects.resolve.return_value = None
    assert not await source.is_current_owner(PERSON, at=AT)
    assert source.directory.list_role_roster.await_count == 1


@pytest.mark.parametrize("roles", [("Reader",), ("Contributor",), ("Approver",), ("BreakGlass",)])
async def test_duty_or_other_role_is_not_owner(roles):
    assert not await reader(roles=roles).is_current_owner(PERSON, at=AT)


async def test_ambiguous_or_inactive_role_observation_holds():
    for source in (reader(active=False), reader(ref=GROUP)):
        assert not await source.is_current_owner(PERSON, at=AT)
    source = reader()
    source.directory.list_role_roster.return_value *= 2
    assert not await source.is_current_owner(PERSON, at=AT)


async def test_role_lookup_expiry_and_outage_do_not_prove_loss_or_eligibility():
    from dataclasses import replace

    source = replace(reader(), clock=Mock(return_value=AT + timedelta(minutes=5)))
    assert not await source.is_current_owner(PERSON, at=AT)
    source = reader()
    source.directory.list_role_roster.side_effect = RuntimeError("synthetic outage")
    assert not await source.is_current_owner(PERSON, at=AT)
    source.directory.list_role_roster.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await source.is_current_owner(PERSON, at=AT)
