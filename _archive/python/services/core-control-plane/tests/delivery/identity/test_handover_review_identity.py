"""Current Core reviewer facts use exact observed people, roles, and private groups only."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.core.human_assignment.scoped_duties import DutyResolution, DutySubject, DutySubjectKind
from fdai.delivery.identity.handover_review_identity import CurrentHandoverIdentityReader
from fdai.shared.providers.human_identity import IdentityRosterEntry

AT = datetime(2026, 9, 14, 12, tzinfo=UTC)
PERSON = "00000000-0000-0000-0000-000000000001"
GROUP = "00000000-0000-0000-0000-000000000002"


def _reader():
    subject = DutySubject(DutySubjectKind.PERSON, PERSON)
    resolution = DutyResolution(
        subject,
        AT,
        (subject,),
        AT,
        AT + timedelta(minutes=5),
        "source:synthetic",
        "a" * 64,
        True,
    )
    entry = IdentityRosterEntry(
        "entra", PERSON, "Example human", "person", ("Reader",), group_ids=(GROUP,)
    )
    return CurrentHandoverIdentityReader(
        SimpleNamespace(resolve=AsyncMock(return_value=resolution)),
        SimpleNamespace(list_role_roster=AsyncMock(return_value=(entry,))),
        {"Reader": GROUP},
        lambda: AT,
    )


async def test_exact_current_observed_groups_remain_private():
    reader = _reader()
    facts = await reader.read(PERSON)
    assert (
        facts.subject_ref == PERSON and facts.roles == ("Reader",) and facts.group_ids == (GROUP,)
    )
    assert facts.expires_at == AT + timedelta(minutes=5)
    assert not facts.current(AT + timedelta(minutes=5))
    assert "group_ids" not in reader.directory.list_role_roster.return_value[0].to_dict()
    reader.directory.list_role_roster.assert_awaited_once_with({"Reader": GROUP}, limit=500)


@pytest.mark.parametrize("change", ["missing", "incomplete", "different_at", "expired", "empty"])
async def test_person_resolution_must_echo_the_current_query(change):
    reader = _reader()
    person = reader.subjects.resolve.return_value
    changes = {
        "incomplete": {"complete": False},
        "different_at": {"at": AT - timedelta(seconds=1)},
        "expired": {"observed_at": AT - timedelta(minutes=5), "valid_until": AT},
        "empty": {"people": ()},
    }
    reader.subjects.resolve.return_value = (
        None if change == "missing" else replace(person, **changes[change])
    )
    assert await reader.read(PERSON) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"roles": ("BreakGlass",)},
        {"provider": "other"},
        {"subject_id": GROUP},
        {"active": False},
        {"active": 1},
        {"principal_type": "group"},
    ],
)
async def test_roster_labels_never_replace_current_ordinary_human_evidence(changes):
    reader = _reader()
    reader.directory.list_role_roster.return_value = (
        replace(reader.directory.list_role_roster.return_value[0], **changes),
    )
    assert await reader.read(PERSON) is None


async def test_role_lookup_expiry_duplicate_and_cancellation_remain_holds():
    reader = _reader()
    reader.directory.list_role_roster.return_value *= 2
    assert await reader.read(PERSON) is None
    reader = _reader()
    clock = {"at": AT}
    reader = replace(reader, clock=lambda: clock["at"])
    entry = reader.directory.list_role_roster.return_value

    async def slow_roles(*args, **kwargs):
        clock["at"] += timedelta(minutes=5)
        return entry

    reader.directory.list_role_roster.side_effect = slow_roles
    assert await reader.read(PERSON) is None
    reader = _reader()
    reader.directory.list_role_roster.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await reader.read(PERSON)


async def test_original_source_expiry_is_never_extended():
    reader = _reader()
    reader.subjects.resolve.return_value = replace(
        reader.subjects.resolve.return_value, valid_until=AT + timedelta(seconds=1)
    )
    assert (await reader.read(PERSON)).expires_at == AT + timedelta(seconds=1)
