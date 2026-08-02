from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fdai.core.readiness import (
    DetectionObservationStatus,
    DetectionReadinessDimension,
    DetectionReadinessObservation,
    detection_readiness_state_key,
    reduce_detection_readiness,
)
from fdai.delivery.operator_api.routes.chat_detection_readiness import (
    DetectionReadinessChatTools,
    needs_detection_readiness,
    render_detection_readiness_answer,
)
from fdai.delivery.operator_api.routes.chat_verification import verify_answer
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)


def _store() -> InMemoryStateStore:
    store = InMemoryStateStore()
    observation = DetectionReadinessObservation(
        resource_ref="cluster/example",
        dimension=DetectionReadinessDimension.DISCOVERED,
        status=DetectionObservationStatus.PASSED,
        observed_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(minutes=4),
        source="azure.monitor",
        evidence_digest="a" * 64,
    )
    snapshot = reduce_detection_readiness(
        (observation,),
        resource_ref="cluster/example",
        generated_at=_NOW,
    )
    asyncio.run(
        store.write_state(
            detection_readiness_state_key(snapshot.resource_ref),
            snapshot.model_dump(mode="json"),
        )
    )
    return store


def test_intent_is_specific_and_does_not_capture_generic_inventory() -> None:
    assert needs_detection_readiness("AKS detection readiness status?")
    assert needs_detection_readiness("쿠버네티스 감지 준비 상태 알려줘")
    assert not needs_detection_readiness("List AKS clusters")
    assert not needs_detection_readiness("Enable AKS monitoring readiness")


def test_tool_reads_muninn_projection_and_renders_grounded_answer() -> None:
    evidence = asyncio.run(
        DetectionReadinessChatTools(_store()).resolve(
            "AKS detection readiness status?",
            principal_id="reader",
        )
    )

    assert evidence is not None
    answer = render_detection_readiness_answer(evidence, locale="en")
    assert answer is not None
    assert "cluster/example: partial" in answer
    verified = verify_answer("provisional", {"_tool_evidence": evidence}, locale="en")
    assert verified.authority == "server_detection_readiness"
    assert verified.checks_completed == 1
    assert verified.evidence_refs == ("detection-readiness:muninn@2026-07-24T01:00:00+00:00",)
