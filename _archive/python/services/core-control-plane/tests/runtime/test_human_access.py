from __future__ import annotations

import json

import httpx
import pytest
from fdai.delivery.identity import HumanAccessDirectApiExecutor
from fdai.runtime.human_access import build_human_access_direct_api
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _environment() -> dict[str, str]:
    return {
        "FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON": json.dumps(
            {
                "Reader": "group-reader",
                "Contributor": "group-contributor",
                "Approver": "group-approver",
                "Owner": "group-owner",
            }
        ),
        "FDAI_HUMAN_ACCESS_MI_CLIENT_ID": "human-access-client",
        "FDAI_MI_CLIENT_ID": "executor-client",
        "IDENTITY_ENDPOINT": "https://identity.example/token",
        "IDENTITY_HEADER": "identity-header",
    }


def test_human_access_runtime_is_absent_without_configuration() -> None:
    assert (
        build_human_access_direct_api(
            audit_store=InMemoryStateStore(),
            http_client=None,
            environment={},
        )
        is None
    )


def test_human_access_runtime_is_absent_when_disabled() -> None:
    assert (
        build_human_access_direct_api(
            audit_store=InMemoryStateStore(),
            http_client=None,
            environment=_environment(),
            enabled=False,
        )
        is None
    )


def test_core_human_access_planning_needs_no_http_or_mutation_identity() -> None:
    environment = {
        "FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON": _environment()["FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON"]
    }
    adapter = build_human_access_direct_api(
        audit_store=InMemoryStateStore(), http_client=None, environment=environment
    )
    assert isinstance(adapter, HumanAccessDirectApiExecutor)
    assert not hasattr(adapter.planner, "provisioner")
    assert not hasattr(adapter.planner, "identity")
    assert not hasattr(adapter.planner, "execute")


async def test_human_access_runtime_ignores_mutation_credentials_and_pins_exact_role_map() -> None:
    environment = _environment()
    async with httpx.AsyncClient() as client:
        executor = build_human_access_direct_api(
            audit_store=InMemoryStateStore(),
            http_client=client,
            environment=environment,
        )

    assert isinstance(executor, HumanAccessDirectApiExecutor)
    assert not hasattr(executor.planner, "provisioner")
    assert set(executor.planner.role_group_ids.values()) == {
        "group-reader",
        "group-contributor",
        "group-approver",
        "group-owner",
    }


@pytest.mark.parametrize(
    "update, message",
    [
        ({"FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON": "{}"}, "MUST define"),
        (
            {
                "FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON": json.dumps(
                    {
                        "Reader": "same-group",
                        "Contributor": "same-group",
                        "Approver": "group-approver",
                        "Owner": "group-owner",
                    }
                )
            },
            "MUST be distinct",
        ),
    ],
)
async def test_human_access_runtime_fails_closed_on_invalid_binding(
    update: dict[str, str],
    message: str,
) -> None:
    environment = {**_environment(), **update}
    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match=message):
            build_human_access_direct_api(
                audit_store=InMemoryStateStore(),
                http_client=client,
                environment=environment,
            )
