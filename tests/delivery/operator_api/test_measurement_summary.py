"""Tests for the autonomy measurement summary read panel."""

from __future__ import annotations

from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.measurement_summary import (
    AutonomyMeasurementPanel,
    _vertical_of,
)


def test_vertical_of_maps_action_kinds() -> None:
    assert _vertical_of("right_size") == "cost"
    assert _vertical_of("shutdown") == "cost"
    assert _vertical_of("dr.failover") == "resilience"
    assert _vertical_of("zone-redundancy") == "resilience"
    assert _vertical_of("enable-encryption") == "change_safety"
    assert _vertical_of("restrict-network-access") == "change_safety"


async def test_render_shape_and_synthetic_flag() -> None:
    panel = AutonomyMeasurementPanel(InMemoryConsoleReadModel())
    out = await panel.render(params={})
    assert out["synthetic"] is True
    assert out["sample_size"] == 1284
    assert out["confidence"] == 0.95
    assert out["source"] == {
        "name": "synthetic-dev-harness",
        "kind": "synthetic",
        "as_of": "2026-07-15T00:00:00Z",
    }
    assert out["rules"] == {"active": 47, "candidates_30d": 6, "promoted_30d": 3}
    assert set(out["success"]) == {
        "auto_resolution_rate",
        "human_touchpoints_per_100",
        "mttr_seconds",
        "change_lead_time_seconds",
        "cost_per_resolved_event_usd",
    }
    assert set(out["leading"]) == {
        "mixed_model_disagreement_rate",
        "verifier_failure_rate",
        "shadow_divergence_rate",
    }
    assert {g["key"] for g in out["guards"]} == {
        "cfr",
        "false_positive",
        "false_negative",
        "rollback",
    }
    assert {v["key"] for v in out["verticals"]} == {
        "resilience",
        "change_safety",
        "cost",
        "unattributed",
    }
    assert out["attribution"] == {
        "attributed_events": 0,
        "unattributed_events": 1284,
        "coverage": 0.0,
    }
    assert out["finalization"] == {
        "finalized_events": 0,
        "pending_events": 0,
        "adverse_events": 0,
    }
    assert out["tier"]["bands"]["t0"] == [0.7, 0.8]


async def test_render_derives_verticals_and_savings_from_audit() -> None:
    rm = InMemoryConsoleReadModel()
    rm.record_audit_entry(
        {
            "action_kind": "right_size",
            "outcome": "shadow_pr_opened",
            "tier": "t0",
            "estimated_savings": 128.0,
        }
    )
    rm.record_audit_entry(
        {
            "action_kind": "shutdown",
            "outcome": "shadow_pr_opened",
            "tier": "t0",
            "estimated_savings": 45.5,
        }
    )
    rm.record_audit_entry({"action_kind": "enable-encryption", "outcome": "auto", "tier": "t0"})
    rm.record_audit_entry(
        {"action_kind": "hil.await", "outcome": "awaiting_approval", "tier": "t2"}
    )

    out = await AutonomyMeasurementPanel(rm).render(params={})
    verticals = {v["key"]: v for v in out["verticals"]}

    assert verticals["cost"]["events"] == 2
    assert verticals["cost"]["monthly_savings"] == 173.5
    assert verticals["cost"]["auto_resolved"] == 2
    # enable-encryption is auto-resolved change-safety; hil.await is an
    # intervention (open risk), so change-safety has 1 auto + 1 open.
    assert verticals["change_safety"]["events"] == 2
    assert verticals["change_safety"]["auto_resolved"] == 1
    assert verticals["change_safety"]["open_risks"] == 1
    assert verticals["unattributed"]["events"] == 1280

    # Tier mix is normalized over the 4 tiered rows (3x t0, 1x t2).
    assert out["tier"]["mix"]["t0"] == 0.75
    assert out["tier"]["mix"]["t2"] == 0.25


async def test_injected_measurement_source_is_not_marked_synthetic() -> None:
    panel = AutonomyMeasurementPanel(
        InMemoryConsoleReadModel(),
        measurement={
            "source": {"name": "production-measurement", "kind": "measurement", "as_of": None}
        },
    )
    out = await panel.render(params={})
    assert out["synthetic"] is False
