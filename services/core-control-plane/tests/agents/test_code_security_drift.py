"""Heimdall code-security review drift ownership tests."""

from __future__ import annotations

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.saga import Saga
from fdai.core.security.code_findings.review_signal import (
    CodeSecurityReviewError,
    code_security_drift_payload,
)

_REVISION = "a" * 40


def _package() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "kind": "code-security-review",
        "repository_alias": "example-service",
        "revision": _REVISION,
        "review_digest": "4" * 64,
        "issue_count": 1,
        "by_priority": {"P0": 1, "P1": 0, "P2": 0, "P3": 0, "P4": 0},
        "by_severity": {"critical": 1, "high": 0, "medium": 0, "low": 0, "undetermined": 0},
        "by_confidence": {
            "hypothesis": 0,
            "reported": 1,
            "corroborated": 0,
            "verified": 0,
            "proven": 0,
        },
        "known_exploited_count": 1,
        "exposure": "exposed",
        "coverage_complete": True,
        "top_issue_ids": ["FDAI-SEC-0123456789ab"],
        "review_required": True,
        "grants_authority": False,
    }


async def test_heimdall_publishes_code_security_review_on_owned_drift_topic() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    heimdall = Heimdall(bus=bus, code_security_drift_projector=code_security_drift_payload)
    assert await heimdall.publish_code_security_drift(_package()) is True
    message = bus.messages_on("object.drift")[-1]
    assert message.principal == "Heimdall"
    assert message.payload["event_type"] == "code_security.findings_drift"
    assert message.payload["decision"] == "urgent"
    assert message.payload["grants_authority"] is False
    assert heimdall.behavior_snapshot()["code_security_drift:urgent"] == 1


async def test_heimdall_validates_before_transport_and_holds_without_projector() -> None:
    assert await Heimdall().publish_code_security_drift(_package()) is False
    invalid = _package()
    invalid["grants_authority"] = True
    with pytest.raises(CodeSecurityReviewError, match="authority"):
        await Heimdall(
            code_security_drift_projector=code_security_drift_payload
        ).publish_code_security_drift(invalid)


async def test_code_security_drift_reaches_human_approval_verdict_and_saga_audit() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    heimdall = Heimdall(bus=bus, code_security_drift_projector=code_security_drift_payload)
    forseti = Forseti(bus=bus)
    saga = Saga()
    saga.bind_bus(bus)
    bus.subscribe("object.drift", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Saga", saga.on_typed_message)
    assert await heimdall.publish_code_security_drift(_package()) is True
    drift = bus.messages_on("object.drift")[-1].payload
    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["risk_verdict"] == "hil"
    assert verdict["correlation_id"] == drift["correlation_id"]
    entries = saga.audit_chain.entries_for_correlation(str(drift["correlation_id"]))
    assert len(entries) == 1 and entries[0].topic == "object.verdict"
