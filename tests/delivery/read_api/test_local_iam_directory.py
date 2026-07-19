from fdai.core.rbac.resolver import GroupMapping
from fdai.delivery.identity import EntraHumanIdentityDirectory
from fdai.delivery.read_api.dev.iam_directory import build_local_iam_directory
from fdai.shared.providers.human_identity import StaticHumanIdentityDirectory


def group_mapping() -> GroupMapping:
    return GroupMapping(
        reader_group_id="reader-group",
        contributor_group_id="contributor-group",
        approver_group_id="approver-group",
        owner_group_id="owner-group",
        break_glass_group_id="break-glass-group",
    )


async def test_anonymous_dev_uses_empty_static_directory() -> None:
    result = build_local_iam_directory(group_mapping(), use_graph=False)

    assert isinstance(result.directory, StaticHumanIdentityDirectory)
    assert await result.directory.list_role_roster(result.role_group_ids) == ()
    assert result.role_group_ids["Owner"] == "owner-group"
    assert result.shutdown_callbacks == ()


async def test_authenticated_local_mode_uses_graph_directory() -> None:
    result = build_local_iam_directory(
        group_mapping(),
        use_graph=True,
        application_id="api-app-id",
    )

    assert isinstance(result.directory, EntraHumanIdentityDirectory)
    assert result.directory.application_id == "api-app-id"
    assert len(result.shutdown_callbacks) == 1

    await result.shutdown_callbacks[0]()
    assert result.directory.client.is_closed
