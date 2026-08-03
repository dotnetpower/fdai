from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from fdai.delivery.operator_api.routes.chat_network_reachability import (
    NetworkReachabilityChatTools,
    needs_network_reachability,
    render_network_reachability_answer,
)
from fdai.delivery.operator_api.routes.chat_verification import verify_answer


class _Provider:
    async def query_reachability(self) -> Mapping[str, Any]:
        return {
            "status": "matched",
            "source": "operations-gateway-active-probe",
            "probe_alias": "app-to-database",
            "reachable": True,
            "http_status": 200,
            "observed_at": "2026-08-03T04:00:00+00:00",
        }


def test_intent_is_specific_to_read_only_application_database_reachability() -> None:
    assert needs_network_reachability("Can the application reach the database end to end?")
    assert needs_network_reachability("앱에서 데이터베이스까지 실제로 통신할 수 있어?")
    assert not needs_network_reachability("Show the database status")
    assert not needs_network_reachability("Open database connectivity from the app")


def test_active_probe_result_is_rendered_and_verified() -> None:
    evidence = asyncio.run(
        NetworkReachabilityChatTools(_Provider()).resolve(
            "Can the application reach the database end to end?",
            principal_id="reader",
        )
    )

    assert evidence is not None
    answer = render_network_reachability_answer(evidence, locale="en")
    assert answer is not None
    assert "path reachable" in answer
    verified = verify_answer("provisional", {"_tool_evidence": evidence}, locale="en")
    assert verified.authority == "server_network_probe"
    assert verified.checks_completed == 1
    assert verified.evidence_refs == (
        "network-reachability:app-to-database@2026-08-03T04:00:00+00:00",
    )


def test_missing_probe_fails_closed_without_configuration_inference() -> None:
    evidence = asyncio.run(
        NetworkReachabilityChatTools().resolve(
            "앱에서 데이터베이스까지 실제로 통신할 수 있어?",
            principal_id="reader",
        )
    )

    assert evidence is not None
    answer = render_network_reachability_answer(evidence, locale="ko")
    assert answer is not None
    assert "NSG" in answer
    verified = verify_answer("provisional", {"_tool_evidence": evidence}, locale="ko")
    assert verified.status == "unverified"
    assert verified.checks_completed == 0
    assert verified.evidence_refs == ()
