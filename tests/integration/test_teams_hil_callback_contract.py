"""Cross-service proof that the Teams card matches the Operator receiver.

The Core Teams adapter renders the approval card; the Operator service owns the
receiver that authenticates the resulting Bot activity. If the two drift, a
click either fails closed or - worse - carries a field the receiver was not
designed to refuse. This check pins the shared verb and the exact action-data
field set from both sides.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fdai.delivery.chatops.teams_adapter import (
    HIL_DECISION_ACTION as CORE_HIL_DECISION_ACTION,
)
from fdai.delivery.chatops.teams_adapter import (
    TeamsHilAdapter,
    TeamsHilAdapterConfig,
)
from fdai.shared.providers.hil_channel import HilApprovalRequest
from fdai_operator_service.families.iam.hil_teams_callback import (
    HIL_DECISION_ACTION as OPERATOR_HIL_DECISION_ACTION,
)
from fdai_operator_service.families.iam.hil_teams_callback import (
    TEAMS_ACTION_DATA_FIELDS as OPERATOR_ACTION_FIELDS,
)

_AUDIENCE = "teams:approval-team:approval-channel"


def test_core_and_operator_agree_on_the_approval_action_verb() -> None:
    assert CORE_HIL_DECISION_ACTION == OPERATOR_HIL_DECISION_ACTION == "fdai.hil.decision"


@pytest.mark.asyncio
async def test_rendered_card_data_matches_the_operator_receiver_contract() -> None:
    card = await _render_card()
    actions = card["actions"]

    assert [action["type"] for action in actions] == ["Action.Execute", "Action.Execute"]
    assert {action["verb"] for action in actions} == {OPERATOR_HIL_DECISION_ACTION}
    inputs = {block["id"] for block in card["body"] if block.get("type") == "Input.Text"}
    for action in actions:
        # Adaptive Cards merge gathered inputs into ``action.data`` before the
        # activity leaves the client, so declared data plus inputs MUST equal
        # the receiver's exact field set.
        assert set(action["data"]) | inputs == OPERATOR_ACTION_FIELDS
        assert "provider_actor_id" not in action["data"]
        assert "roles" not in action["data"]
        assert action["data"]["audience"] == _AUDIENCE


async def _render_card() -> dict[str, Any]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = TeamsHilAdapter(
            config=TeamsHilAdapterConfig(
                webhook_url="https://example.invalid/webhook",
                approval_audience=_AUDIENCE,
            ),
            http_client=client,
        )
        await adapter.send(
            HilApprovalRequest(
                approval_id="approval-1",
                correlation_id="correlation-1",
                action_id="00000000-0000-0000-0000-000000000042",
                action_type="remediate.tag-missing-owner",
                rule_ids=("example.tag.owner-required",),
                target_resource_ref="resource:example/rg/vm-1",
                blast_radius_summary="1 resource in rg-example",
                reasons=("Owner tag is missing.",),
                ttl_seconds=1_800,
                action_hash="action-hash-1",
                metadata={"idempotency_key": "hil-key-1"},
            )
        )

    body = json.loads(seen[0].content)
    card: dict[str, Any] = body["attachments"][0]["content"]
    return card
