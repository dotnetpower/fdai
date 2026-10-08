"""A real MCSB shadow assessment event reaches the Operator MCSB read without authority."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.framework_assessment import (
    FrameworkAssessmentRequest,
    FrameworkAssessmentRuntime,
    FrameworkAssessmentService,
)
from fdai.delivery.authoritative_framework_projection import _mcsb_assessment_snapshot
from fdai.delivery.framework_assessment_cli import _profile
from fdai.rule_catalog.schema.framework_assessment import (
    canonical_digest,
    load_framework_assessment_catalog,
)
from fdai_operator_service.framework_assessment_projection import (
    FrameworkAssessmentProjectionConsumer,
)
from fdai_operator_service.framework_mcsb_assessment_projection import (
    MCSB_ASSESSMENT_PROJECTION_KEY,
    attach_mcsb_assessment,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 8, tzinfo=UTC)


class _AuditStore:
    async def append_audit_entry(self, entry: Mapping[str, object]) -> None:
        del entry


class _Bus:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object:
        del topic, key
        self.events.append(json.loads(json.dumps(dict(payload), default=str)))
        return object()


class _ProjectionStore:
    def __init__(self, seed: dict[str, object]) -> None:
        self.state = {MCSB_ASSESSMENT_PROJECTION_KEY: seed}

    async def read_framework_catalog(self, framework_id: str) -> dict[str, object]:
        assert framework_id == "azure-mcsb"
        return dict(self.state[MCSB_ASSESSMENT_PROJECTION_KEY])

    async def write_framework_projection(
        self, framework_id: str, value: Mapping[str, object]
    ) -> None:
        assert framework_id == "azure-mcsb"
        self.state[MCSB_ASSESSMENT_PROJECTION_KEY] = json.loads(json.dumps(dict(value)))

    async def read_state(self, key: str) -> dict[str, object] | None:
        return self.state.get(key)


def test_mcsb_shadow_assessment_projects_onto_the_operator_read() -> None:
    catalog = load_framework_assessment_catalog(
        ROOT / "rule-catalog/framework-assessments/generated/azure-mcsb.json"
    )
    profile = _profile(
        catalog,
        scope_digest=canonical_digest({"scope": "workload-example"}),
        ontology_release="2026.09",
        reviewer_identity="reviewer@example.com",
        reviewed_at=NOW,
        inventory_generation="inventory-1",
        rule_activation=None,
    )
    bus = _Bus()
    asyncio.run(
        FrameworkAssessmentService(FrameworkAssessmentRuntime(catalog), _AuditStore(), bus).assess(
            FrameworkAssessmentRequest(
                assessment_id="assessment-mcsb",
                profile=profile,
                evaluated_at=NOW,
                recorded_at=NOW,
                evidence=(),
            )
        )
    )
    store = _ProjectionStore(
        {"_revision": "sha256:" + "0" * 64, **_mcsb_assessment_snapshot(catalog)}
    )

    asyncio.run(FrameworkAssessmentProjectionConsumer(store).handle(bus.events[0]))
    payload, revision = asyncio.run(
        attach_mcsb_assessment(
            {
                "benchmark": {"benchmark_version": "v1"},
                "controls": [{"control_id": "NS-8"}],
            },
            store,
            detail=False,
        )
    )
    detail, _ = asyncio.run(
        attach_mcsb_assessment(
            {"benchmark_version": "v1", "control_id": "NS-8"},
            store,
            detail=True,
        )
    )

    assert revision is not None
    assert payload["assessment_summary"]["status"] == "evaluated"
    assert payload["assessment_summary"]["execution_authority"] is False
    assert sum(payload["assessment_summary"]["satisfaction_counts"].values()) == 86
    assert payload["controls"][0]["assessment"]["satisfaction"] == "unknown"
    roles = {item["ref"]: item["evidence_role"] for item in detail["assessment"]["requirements"]}
    assert roles["mcsb-ns-8-control-evidence"] == "decisive"
    assert roles["network.nsg.no-internet-inbound-rdp"] == "supporting_only"
