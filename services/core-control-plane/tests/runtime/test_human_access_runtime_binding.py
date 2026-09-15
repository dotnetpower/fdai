"""Production human-access composition never creates a mutation identity or bypasses
missing inputs.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.core.risk_gate.gate import RiskGate
from fdai.delivery.persistence.state_store_action_promotion import StateStoreActionPromotionRegistry
from fdai.runtime.human_access_runtime import build_human_access_workflow
from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
from fdai.runtime.safeguard_isolated_executor import SafeguardBoundEventBusDirectApiExecutionClient
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.core.executor.test_safeguard_lifecycle_coordinator import _coordinator


@pytest.fixture
async def binding():
    store = InMemoryStateStore()
    coordinator, _ = _coordinator(store)
    client = EventBusDirectApiExecutionClient(InMemoryEventBus(), store, "core:binding-test")
    registry = StateStoreActionPromotionRegistry(store=store)
    loop = SimpleNamespace(
        _direct_api_executor=SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator),
        _risk_gate=RiskGate(registry=registry),
        _risk_table=object(),
        _action_builder=object(),
        _kill_switch=None,
        _degradation=None,
        _kill_switch_refresher=AsyncMock(),
    )
    env = {
        "FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON": json.dumps(
            {r: "group:" + r.lower() for r in ("Reader", "Contributor", "Approver", "Owner")}
        ),
        "FDAI_STATE_STORE_DSN": "postgresql://example",
        "FDAI_MI_CLIENT_ID": "identity:reader",
        "FDAI_HUMAN_ACCESS_MI_CLIENT_ID": "identity:writer",
        "FDAI_PANTHEON_APPROVER_ACTIONS_JSON": '{"person:reviewer":["ops.apply-human-access"]}',
    }
    identity = SimpleNamespace(
        get_token=AsyncMock(side_effect=AssertionError("no provider I/O at composition"))
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(AssertionError("no HTTP at composition"))
        )
    ) as http:
        yield dict(
            loop=loop,
            store=store,
            environment=env,
            http_client=http,
            identity=identity,
            enforce_ready=lambda: False,
        )


def test_complete_binding_retains_read_identity_and_all_owned_recovery_callbacks(binding):
    runtime = build_human_access_workflow(**binding)
    assert runtime is not None and runtime.agent_bindings().execution_bound
    assert runtime.observer.identity is binding["identity"]
    assert runtime.approvals.can_approve("person:reviewer", "ops.apply-human-access")
    assert not runtime.approvals.can_approve("person:reviewer", "ops.revoke-human-access")
    assert runtime.enforce_ready() is False
    binding["identity"].get_token.assert_not_awaited()


@pytest.mark.parametrize(
    "missing",
    ["FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON", "FDAI_STATE_STORE_DSN", "FDAI_MI_CLIENT_ID"],
)
def test_missing_owned_runtime_source_does_not_bind_an_executor(binding, missing):
    binding["environment"].pop(missing)
    assert build_human_access_workflow(**binding) is None


def test_case_changed_same_identity_cannot_impersonate_separate_reader(binding):
    binding["environment"]["FDAI_HUMAN_ACCESS_MI_CLIENT_ID"] = "IDENTITY:READER"
    with pytest.raises(ValueError, match="MUST NOT share"):
        build_human_access_workflow(**binding)


@pytest.mark.parametrize("change", ["duplicate", "case", "unknown", "nonstring"])
def test_core_and_executor_use_same_strict_role_group_configuration(binding, change):
    from fdai_service_contracts.human_access import parse_human_access_role_groups

    original = binding["environment"]["FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON"]
    if change == "duplicate":
        raw = original[:-1] + ',"Reader":"group:reader"}'
    else:
        data = json.loads(original)
        if change == "case":
            data["Reader"] = "GROUP:READER"
        elif change == "unknown":
            data["BreakGlass"] = "group:breakglass"
        else:
            data["Reader"] = 1
        raw = json.dumps(data)
    binding["environment"]["FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON"] = raw
    with pytest.raises(ValueError):
        parse_human_access_role_groups(raw)
    with pytest.raises(ValueError):
        build_human_access_workflow(**binding)
