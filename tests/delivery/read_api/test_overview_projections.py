from __future__ import annotations

from pathlib import Path

from fdai.core.verticals.cost_governance.finops import FinOpsActionKind
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
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
    ]
    assert finops["estimated_monthly_savings"] == 12.5
    assert finops["source"] == "postgres-audit"
    assert finops["durable"] is True


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
