from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fdai.core.verticals.cost_governance.finops import FinOpsActionKind
from fdai.delivery.read_api.read_model import (
    AuditPage,
    AuditQueryFilters,
    InMemoryConsoleReadModel,
)
from fdai.delivery.read_api.routes.audit_finops import AuditFinOpsPanel
from fdai.delivery.read_api.routes.audit_measurement_summary import (
    AuditAutonomyMeasurementPanel,
)
from fdai.delivery.read_api.routes.persisted_promotion_gates import (
    PersistedPromotionGatesPanel,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[3]


async def test_empty_audit_keeps_unobserved_autonomy_metrics_unavailable() -> None:
    payload = await AuditAutonomyMeasurementPanel(InMemoryConsoleReadModel()).render(params={})

    assert payload["synthetic"] is False
    assert payload["sample_size"] == 0
    assert payload["success"]["auto_resolution_rate"]["value"] is None
    assert payload["success"]["auto_resolution_rate"]["baseline"] is None
    assert payload["success"]["mttr_seconds"]["value"] is None
    assert payload["verticals"][0]["events"] == 0


async def test_audit_overview_projects_only_recorded_measurements() -> None:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "event_id": "event-1",
            "actor": "fdai.core.control_loop",
            "action_kind": "risk_gate.unified",
            "mode": "shadow",
            "decision": "auto",
            "action_id": "action-event-1",
            "action_type_id": "remediate.enable-zone-redundancy",
            "estimated_savings": 12.5,
        }
    )
    model.record_audit_entry(
        {
            "event_id": "event-1",
            "actor": "fdai.core.executor.direct_api",
            "action_kind": "executor.direct_api.dispatched",
            "mode": "enforce",
            "outcome": "dispatched",
            "action_id": "action-event-1",
            "rollback_succeeded": False,
        }
    )
    model.record_audit_entry(
        {
            "event_id": "event-1",
            "actor": "fdai.measurement",
            "action_kind": "measurement.action_outcome.v1",
            "mode": "enforce",
            "action_id": "action-event-1",
            "action_type_id": "remediate.enable-zone-redundancy",
            "observed_at": "2026-07-29T00:00:00Z",
            "execution_mode": "enforce",
            "verification_passed": True,
            "decision": "auto",
            "rollback_succeeded": False,
        }
    )
    for action_id in ("action-1", "action-2"):
        model.record_audit_entry(
            {
                "event_id": "event-2",
                "actor": "fdai.core.control_loop",
                "action_kind": "risk_gate.unified",
                "mode": "shadow",
                "decision": "hil",
                "action_id": action_id,
                "action_type_id": "remediate.right-size-role",
            }
        )
    model.record_audit_entry(
        {
            "event_id": "event-2",
            "actor": "fdai.core.control_loop",
            "action_kind": "risk_gate.unified",
            "mode": "shadow",
            "decision": "hil",
            "action_id": "action-2",
            "action_type_id": "remediate.right-size-role",
        }
    )
    model.record_audit_entry(
        {
            "event_id": "event-measurement",
            "actor": "fdai.measurement",
            "action_kind": "measurement.observed",
            "mode": "shadow",
            "measurement": {"mttr_seconds": 120.0},
            "baseline": {"mttr_seconds": 300.0},
        }
    )
    model.record_audit_entry(
        {
            "event_id": "event-3",
            "action_kind": next(iter(FinOpsActionKind)).value,
            "mode": "shadow",
            "outcome": "resolved",
            "estimated_savings": 12.5,
        }
    )

    autonomy = await AuditAutonomyMeasurementPanel(model).render(params={})
    finops = await AuditFinOpsPanel(model).render(params={})

    assert autonomy["sample_size"] == 2
    assert autonomy["finalization"] == {
        "finalized_events": 1,
        "pending_events": 0,
        "adverse_events": 0,
    }
    assert autonomy["attribution"] == {
        "attributed_events": 2,
        "unattributed_events": 0,
        "coverage": 1.0,
    }
    assert autonomy["success"]["auto_resolution_rate"]["value"] == 0.5
    assert autonomy["success"]["human_touchpoints_per_100"]["value"] == 100.0
    assert autonomy["success"]["auto_resolution_rate"]["baseline"] is None
    assert autonomy["success"]["mttr_seconds"] == {
        "value": 120.0,
        "baseline": 300.0,
        "direction": "lower",
    }
    assert autonomy["verticals"] == [
        {
            "key": "resilience",
            "events": 1,
            "auto_resolved": 1,
            "open_risks": 0,
            "monthly_savings": 12.5,
        },
        {
            "key": "change_safety",
            "events": 0,
            "auto_resolved": 0,
            "open_risks": 0,
            "monthly_savings": 0.0,
        },
        {
            "key": "cost",
            "events": 1,
            "auto_resolved": 0,
            "open_risks": 2,
            "monthly_savings": 0.0,
        },
        {
            "key": "unattributed",
            "events": 0,
            "auto_resolved": 0,
            "open_risks": 0,
            "monthly_savings": 0.0,
        },
    ]
    assert finops["estimated_monthly_savings"] == 12.5
    assert finops["source"] == "postgres-audit"
    assert finops["durable"] is True


async def test_audit_overview_uses_latest_savings_observation_per_action() -> None:
    model = InMemoryConsoleReadModel()
    for savings in (100.0, 50.0):
        model.record_audit_entry(
            {
                "event_id": "event-1",
                "actor": "fdai.core.control_loop",
                "action_kind": "risk_gate.unified",
                "mode": "shadow",
                "decision": "hil",
                "action_id": "action-1",
                "action_type_id": "remediate.right-size-role",
                "estimated_savings": savings,
            }
        )

    payload = await AuditAutonomyMeasurementPanel(model).render(params={})

    cost = next(row for row in payload["verticals"] if row["key"] == "cost")
    assert cost["monthly_savings"] == 50.0


async def test_audit_overview_uses_latest_metric_observation_per_event() -> None:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "event_id": "event-core",
            "actor": "fdai.core.control_loop",
            "action_kind": "control_loop.abstain",
            "mode": "shadow",
            "stage": "trust_router",
        }
    )
    for mttr_seconds in (100.0, 200.0):
        model.record_audit_entry(
            {
                "event_id": "measurement-1",
                "actor": "fdai.measurement",
                "action_kind": "measurement.observed",
                "mode": "shadow",
                "measurement": {"mttr_seconds": mttr_seconds},
            }
        )
    model.record_audit_entry(
        {
            "event_id": "measurement-2",
            "actor": "fdai.measurement",
            "action_kind": "measurement.observed",
            "mode": "shadow",
            "measurement": {"mttr_seconds": 400.0},
        }
    )

    payload = await AuditAutonomyMeasurementPanel(model).render(params={})

    assert payload["success"]["mttr_seconds"]["value"] == 300.0


async def test_audit_overview_reads_complete_window_beyond_page_limit() -> None:
    class CapturingReadModel(InMemoryConsoleReadModel):
        window_starts: list[datetime] = []

        async def list_audit(
            self,
            *,
            limit: int = 50,
            cursor: str | None = None,
            correlation_id: str | None = None,
            filters: AuditQueryFilters | None = None,
        ) -> AuditPage:
            if filters is not None:
                assert filters.recorded_at_from is not None
                assert filters.window_days is None
                self.window_starts.append(filters.recorded_at_from)
            return await super().list_audit(
                limit=limit,
                cursor=cursor,
                correlation_id=correlation_id,
                filters=filters,
            )

    model = CapturingReadModel()
    for index in range(501):
        model.record_audit_entry(
            {
                "event_id": f"event-{index}",
                "actor": "fdai.core.control_loop",
                "action_kind": "control_loop.abstain",
                "mode": "shadow",
                "stage": "trust_router",
            }
        )

    payload = await AuditAutonomyMeasurementPanel(model).render(params={})

    assert payload["sample_size"] == 501
    assert len(model.window_starts) == 2
    assert len(set(model.window_starts)) == 1


async def test_audit_overview_excludes_rows_appended_after_snapshot_head() -> None:
    class AppendAfterHeadReadModel(InMemoryConsoleReadModel):
        calls = 0

        async def list_audit(
            self,
            *,
            limit: int = 50,
            cursor: str | None = None,
            correlation_id: str | None = None,
            filters: AuditQueryFilters | None = None,
        ) -> AuditPage:
            page = await super().list_audit(
                limit=limit,
                cursor=cursor,
                correlation_id=correlation_id,
                filters=filters,
            )
            self.calls += 1
            if self.calls == 1:
                self.record_audit_entry(
                    {
                        "event_id": "event-after-head",
                        "actor": "fdai.core.control_loop",
                        "action_kind": "control_loop.abstain",
                        "mode": "shadow",
                        "stage": "trust_router",
                    }
                )
            return page

    model = AppendAfterHeadReadModel()
    model.record_audit_entry(
        {
            "event_id": "event-before-head",
            "actor": "fdai.core.control_loop",
            "action_kind": "control_loop.abstain",
            "mode": "shadow",
            "stage": "trust_router",
        }
    )

    payload = await AuditAutonomyMeasurementPanel(model).render(params={})

    assert payload["sample_size"] == 1


async def test_audit_overview_does_not_guess_change_safety_attribution() -> None:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "event_id": "event-1",
            "actor": "fdai.core.control_loop",
            "action_kind": "control_loop.abstain",
            "mode": "shadow",
            "stage": "trust_router",
            "resource_type": "event-grid-topic",
        }
    )

    payload = await AuditAutonomyMeasurementPanel(model).render(params={})
    verticals = {row["key"]: row for row in payload["verticals"]}

    assert verticals["change_safety"]["events"] == 0
    assert verticals["unattributed"]["events"] == 1
    assert sum(row["events"] for row in payload["verticals"]) == payload["sample_size"]
    assert payload["attribution"] == {
        "attributed_events": 0,
        "unattributed_events": 1,
        "coverage": 0.0,
    }


async def test_audit_overview_requires_explicit_verified_finalization() -> None:
    model = InMemoryConsoleReadModel()
    for event_id, action_id, rolled_back in (
        ("event-pending", "action-pending", None),
        ("event-finalized", "action-finalized", False),
        ("event-adverse", "action-adverse", True),
    ):
        model.record_audit_entry(
            {
                "event_id": event_id,
                "actor": "fdai.core.control_loop",
                "action_kind": "risk_gate.unified",
                "mode": "shadow",
                "decision": "auto",
                "action_id": action_id,
                "action_type_id": "remediate.enable-zone-redundancy",
            }
        )
        model.record_audit_entry(
            {
                "event_id": event_id,
                "actor": "fdai.core.executor.direct_api",
                "action_kind": "executor.direct_api.dispatched",
                "mode": "enforce",
                "outcome": "dispatched",
                "action_id": action_id,
                "rollback_succeeded": False,
            }
        )
        if rolled_back is not None:
            model.record_audit_entry(
                {
                    "event_id": event_id,
                    "actor": "fdai.measurement",
                    "action_kind": "measurement.action_outcome.v1",
                    "mode": "enforce",
                    "action_id": action_id,
                    "action_type_id": "remediate.enable-zone-redundancy",
                    "observed_at": "2026-07-29T00:00:00Z",
                    "execution_mode": "enforce",
                    "verification_passed": True,
                    "decision": "auto",
                    "rollback_succeeded": rolled_back,
                }
            )

    payload = await AuditAutonomyMeasurementPanel(model).render(params={})

    assert payload["finalization"] == {
        "finalized_events": 2,
        "pending_events": 1,
        "adverse_events": 1,
    }
    assert payload["success"]["auto_resolution_rate"]["value"] == 1 / 3
    assert sum(row["auto_resolved"] for row in payload["verticals"]) == 1


async def test_audit_overview_holds_partially_finalized_multi_action_event() -> None:
    model = InMemoryConsoleReadModel()
    for action_id in ("action-1", "action-2"):
        model.record_audit_entry(
            {
                "event_id": "event-1",
                "actor": "fdai.core.control_loop",
                "action_kind": "risk_gate.unified",
                "mode": "shadow",
                "decision": "auto",
                "action_id": action_id,
                "action_type_id": "remediate.enable-zone-redundancy",
            }
        )
        model.record_audit_entry(
            {
                "event_id": "event-1",
                "actor": "fdai.core.executor.direct_api",
                "action_kind": "executor.direct_api.dispatched",
                "mode": "enforce",
                "outcome": "dispatched",
                "action_id": action_id,
                "rollback_succeeded": False,
            }
        )
    model.record_audit_entry(
        {
            "event_id": "event-1",
            "actor": "fdai.measurement",
            "action_kind": "measurement.action_outcome.v1",
            "mode": "enforce",
            "action_id": "action-1",
            "action_type_id": "remediate.enable-zone-redundancy",
            "observed_at": "2026-07-29T00:00:00Z",
            "execution_mode": "enforce",
            "verification_passed": True,
            "decision": "auto",
            "rollback_succeeded": False,
        }
    )

    payload = await AuditAutonomyMeasurementPanel(model).render(params={})

    assert payload["finalization"] == {
        "finalized_events": 0,
        "pending_events": 1,
        "adverse_events": 0,
    }
    assert payload["success"]["auto_resolution_rate"]["value"] == 0.0


async def test_audit_overview_does_not_override_derived_rates_with_metric_rows() -> None:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "event_id": "event-pending",
            "actor": "fdai.core.control_loop",
            "action_kind": "risk_gate.unified",
            "mode": "shadow",
            "decision": "auto",
            "action_id": "action-pending",
            "action_type_id": "remediate.enable-zone-redundancy",
        }
    )
    model.record_audit_entry(
        {
            "event_id": "event-pending",
            "actor": "fdai.core.executor.direct_api",
            "action_kind": "executor.direct_api.dispatched",
            "mode": "enforce",
            "outcome": "dispatched",
            "action_id": "action-pending",
            "rollback_succeeded": False,
        }
    )
    model.record_audit_entry(
        {
            "event_id": "measurement-1",
            "actor": "fdai.measurement",
            "action_kind": "measurement.observed",
            "mode": "shadow",
            "measurement": {
                "auto_resolution_rate": 0.99,
                "human_touchpoints_per_100": 0.01,
            },
        }
    )

    payload = await AuditAutonomyMeasurementPanel(model).render(params={})

    assert payload["success"]["auto_resolution_rate"]["value"] == 0.0
    assert payload["success"]["human_touchpoints_per_100"]["value"] == 0.0


async def test_persisted_promotion_panel_holds_without_durable_evidence() -> None:
    action_type = load_action_type_catalog(
        REPO_ROOT / "rule-catalog" / "action-types",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=None,
    )[0]
    store = InMemoryStateStore()
    panel = PersistedPromotionGatesPanel(action_types=(action_type,), store=store)

    missing = await panel.render(params={})
    assert missing["ready_count"] == 0
    assert missing["rows"][0]["gaps"] == ["no_persisted_promotion_evidence"]

    gate = action_type.promotion_gate
    await store.write_state(
        f"action_promotion:{action_type.name}",
        {
            "metrics": {
                "shadow_days": gate.min_shadow_days,
                "samples": gate.min_samples,
                "accuracy": gate.min_accuracy,
                "policy_escapes": gate.max_policy_escapes,
            }
        },
    )
    ready = await panel.render(params={})
    assert ready["ready_count"] == 1
    assert ready["rows"][0]["ready"] is True
