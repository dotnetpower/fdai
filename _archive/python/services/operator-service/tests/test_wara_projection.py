from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest
from fdai_operator_service.wara_projection import (
    WaraAssessmentProjectionBridge,
    WaraAssessmentProjectionConsumer,
    WaraProjectionError,
    project_wara_assessment,
)
from fdai_service_contracts.wara_assessment import (
    WARA_ASSESSMENT_CONSUMER_GROUP,
    WARA_ASSESSMENT_TOPIC,
)


def _catalog() -> dict[str, object]:
    return {
        "_revision": "catalog-revision",
        "source_revision": "1" * 40,
        "crosswalk_digest": "sha256:" + "a" * 64,
        "evaluation_source": "not_connected",
        "controls": [
            {
                "id": "active-guid",
                "lifecycle": "active",
                "applicability": "unknown",
                "evaluation_status": "not_evaluated",
                "satisfaction": "unknown",
                "execution_authority": False,
            },
            {
                "id": "disabled-guid",
                "lifecycle": "disabled",
                "applicability": "unknown",
                "evaluation_status": "not_evaluated",
                "satisfaction": "unknown",
                "execution_authority": False,
            },
        ],
    }


def _assessment() -> dict[str, object]:
    return {
        "assessment_id": "assessment-1",
        "mode": "shadow",
        "execution_authority": False,
        "framework_revision": "1" * 40,
        "crosswalk_digest": "sha256:" + "a" * 64,
        "scope_digest": "sha256:" + "b" * 64,
        "evaluated_at": "2026-09-01T00:00:00+00:00",
        "result_digest": "sha256:" + "c" * 64,
        "controls": [
            {
                "recommendation_id": "active-guid",
                "mapping_state": "unmapped",
                "applicability": "applicable",
                "evaluation": "evaluated",
                "satisfaction": "failed",
                "evidence_refs": ["evidence-1"],
                "evidence_digests": ["sha256:" + "d" * 64],
                "evidence_complete": True,
                "limitations": [],
            }
        ],
    }


def test_shadow_result_merges_without_changing_disabled_history() -> None:
    projected = project_wara_assessment(_catalog(), _assessment())
    controls = {item["id"]: item for item in projected["controls"]}  # type: ignore[index]

    assert projected["evaluation_source"] == "wara-shadow-assessment"
    assert controls["active-guid"]["satisfaction"] == "failed"
    assert controls["active-guid"]["evidence_complete"] is True
    assert controls["active-guid"]["execution_authority"] is False
    assert controls["disabled-guid"]["evaluation_status"] == "not_evaluated"


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "enforce"},
        {"execution_authority": True},
        {"framework_revision": "2" * 40},
        {"crosswalk_digest": "sha256:" + "e" * 64},
        {"controls": []},
    ],
)
def test_projection_rejects_authority_pin_or_coverage_drift(
    change: dict[str, object],
) -> None:
    with pytest.raises(WaraProjectionError):
        project_wara_assessment(_catalog(), {**_assessment(), **change})


@pytest.mark.asyncio
async def test_consumer_writes_only_validated_projection() -> None:
    class Store:
        def __init__(self) -> None:
            self.written: dict[str, object] | None = None

        async def read_wara_catalog(self) -> dict[str, object]:
            return _catalog()

        async def write_wara_projection(self, value: Any) -> None:
            self.written = dict(value)

    store = Store()
    await WaraAssessmentProjectionConsumer(store).handle(_assessment())

    assert store.written is not None
    assert store.written["last_assessment_id"] == "assessment-1"


@pytest.mark.asyncio
async def test_bridge_subscribes_to_wara_topic_and_projects_event() -> None:
    class Store:
        def __init__(self) -> None:
            self.written: dict[str, object] | None = None

        async def read_wara_catalog(self) -> dict[str, object]:
            return _catalog()

        async def write_wara_projection(self, value: Mapping[str, object]) -> None:
            self.written = dict(value)

    class Source:
        topic: str | None = None
        group_id: str | None = None

        async def probe_readiness(self) -> bool:
            return True

        def subscribe(
            self,
            topic: str,
            group_id: str,
        ) -> AsyncIterator[Mapping[str, object]]:
            self.topic = topic
            self.group_id = group_id

            async def records() -> AsyncIterator[Mapping[str, object]]:
                yield _assessment()

            return records()

    class Publisher:
        async def publish(
            self,
            topic: str,
            key: str,
            payload: Mapping[str, object],
        ) -> object:
            raise AssertionError((topic, key, payload))

    store = Store()
    source = Source()
    bridge = WaraAssessmentProjectionBridge(
        store=store,
        source=source,
        publisher=Publisher(),
        retry_seconds=0.01,
    )
    await bridge.start()
    for _ in range(20):
        if store.written is not None:
            break
        await asyncio.sleep(0.01)
    await bridge.aclose()

    assert source.topic == WARA_ASSESSMENT_TOPIC
    assert source.group_id == WARA_ASSESSMENT_CONSUMER_GROUP
    assert store.written is not None
