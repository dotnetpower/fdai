from __future__ import annotations

from fdai.shared.providers.human_identity import (
    HumanIdentity,
    HumanIdentityDirectory,
    IdentityRosterEntry,
    StaticHumanIdentityDirectory,
)


async def test_static_directory_searches_username_and_display_name() -> None:
    directory = StaticHumanIdentityDirectory(
        (
            HumanIdentity(
                provider="entra",
                subject_id="user-1",
                username="alex@example.com",
                display_name="Alex Kim",
            ),
            HumanIdentity(
                provider="future-provider",
                subject_id="user-2",
                username="casey@example.com",
                display_name="Casey Park",
            ),
        )
    )

    assert isinstance(directory, HumanIdentityDirectory)
    assert [item.subject_id for item in await directory.search("ALEX")] == ["user-1"]
    assert [item.subject_id for item in await directory.search("Park")] == ["user-2"]


async def test_static_directory_validates_query_and_limit() -> None:
    directory = StaticHumanIdentityDirectory()

    for query, limit in (("x", 20), ("valid", 0), ("valid", 51)):
        try:
            await directory.search(query, limit=limit)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid search input was accepted")


async def test_static_directory_returns_people_and_groups_roster() -> None:
    directory = StaticHumanIdentityDirectory(
        roster=(
            IdentityRosterEntry(
                provider="entra",
                subject_id="group-reader",
                display_name="fdai-readers",
                principal_type="group",
                roles=("Reader",),
            ),
            IdentityRosterEntry(
                provider="entra",
                subject_id="user-1",
                display_name="Alex Kim",
                principal_type="person",
                roles=("Reader", "Contributor"),
                username="alex@example.com",
            ),
        )
    )

    roster = await directory.list_role_roster({"Reader": "group-reader"})

    assert [entry.principal_type for entry in roster] == ["group", "person"]
    assert roster[1].roles == ("Reader", "Contributor")
