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


async def test_heimdall_drift_tool_reads_recorded_code_security_reviews() -> None:
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    store = InMemoryStateStore()
    sourced = {
        **_package(),
        "schema_version": "1.1.0",
        "source": {
            "kind": "local_path",
            "provider": "local",
            "revision_kind": "commit",
            "trigger": "cli",
            "request_id": None,
        },
        "producers": ["Opengrep"],
    }
    older = {**_package(), "revision": "b" * 40}
    await store.write_state(
        f"runtime:code-security-review:example-service:{_REVISION}",
        {"package": sourced, "recorded_at": "2026-10-08T01:00:00+00:00"},
    )
    await store.write_state(
        "runtime:code-security-review:example-service:" + "b" * 40,
        {"package": older, "recorded_at": "2026-10-07T01:00:00+00:00"},
    )
    await store.write_state(
        "runtime:code-security-review:broken:" + "c" * 40,
        {"package": {**_package(), "grants_authority": True}, "recorded_at": "x"},
    )
    heimdall = Heimdall(state_store=store)
    envelope = await heimdall.on_conversation_turn(
        "Did the latest code scan find vulnerabilities?",
        {"conversation_tool": "read_drift_status", "trace_ref": "trace-code"},
    )
    facts = envelope["facts"]
    assert envelope["answer"] is not None and "1 urgent" in envelope["answer"]
    assert "No retained configuration drift finding" in envelope["answer"]
    (latest,) = facts["code_security_latest_decisions"]
    assert latest["revision"] == _REVISION[:12] and latest["source_kind"] == "local_path"
    assert latest["decision"] == "urgent"
    assert facts["code_security_reviews_read"] == 2
    assert "Opengrep" not in str(facts) and "top_issue_ids" not in str(facts)


async def test_heimdall_drift_tool_abstains_without_a_review_store() -> None:
    envelope = await Heimdall().on_conversation_turn(
        "Did the latest code scan find vulnerabilities?",
        {"conversation_tool": "read_drift_status", "trace_ref": "trace-code"},
    )
    assert envelope["answer"] is None
