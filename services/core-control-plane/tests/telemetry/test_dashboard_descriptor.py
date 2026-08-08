"""Dashboard descriptor consistency test.

Verifies:

1. Every panel declares a ``source`` with a supported ``kind``.
2. Panels whose ``source.kind == 'audit_log_derivation'`` reference a
   ``field`` that actually exists on :class:`DashboardMetrics` (or a
   ``per_tier.<tier>`` shorthand). This is the "renaming the field
   fails the build" acceptance check for W1.9.
3. Every panel category is one of ``success`` / ``guard`` / ``leading``.
4. Every panel has an ``id``, ``title``, ``unit``, ``direction``,
   ``target``.
5. Deferred panels name where they will be sourced from.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, cast

import pytest
from fdai.shared.telemetry.metrics_derivation import DashboardMetrics

DESCRIPTOR_PATH = Path(__file__).resolve().parents[2] / "docs" / "dashboards" / "phase-0-kpi.json"


def _load() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(DESCRIPTOR_PATH.read_text(encoding="utf-8")))


def _dashboard_field_names() -> set[str]:
    return {f.name for f in dataclasses.fields(DashboardMetrics)}


def test_descriptor_file_is_readable_and_shaped() -> None:
    d = _load()
    assert d["id"] == "phase-0-kpi"
    assert isinstance(d["panels"], list)
    assert d["panels"]


def test_every_panel_has_required_fields() -> None:
    for panel in _load()["panels"]:
        for key in (
            "id",
            "title",
            "description",
            "category",
            "unit",
            "direction",
            "target",
            "source",
        ):
            assert key in panel, f"panel {panel.get('id')} missing {key!r}"
        assert panel["category"] in ("success", "guard", "leading")


def test_audit_log_derivation_panels_reference_real_fields() -> None:
    """Renaming a field on DashboardMetrics MUST break this test.

    Panel source is ``{"kind": "audit_log_derivation", "field": "<name>"}``.
    ``<name>`` MUST match a real :class:`DashboardMetrics` attribute or a
    ``per_tier.<tier>`` shorthand.
    """
    valid_fields = _dashboard_field_names()

    for panel in _load()["panels"]:
        source = panel["source"]
        if source["kind"] != "audit_log_derivation":
            continue

        field = source["field"]
        if field.startswith("per_tier."):
            assert "per_tier" in valid_fields, (
                f"panel {panel['id']}: DashboardMetrics has no per_tier field"
            )
            tier = field.split(".", 1)[1]
            assert tier in {"t0", "t1", "t2"}, f"panel {panel['id']}: unknown tier {tier!r}"
        else:
            assert field in valid_fields, (
                f"panel {panel['id']}: unknown DashboardMetrics field {field!r} "
                f"(known: {sorted(valid_fields)})"
            )


def test_deferred_panels_name_a_source() -> None:
    """A deferred panel MUST cite where its data will come from - no orphans."""
    for panel in _load()["panels"]:
        source = panel["source"]
        if source["kind"] == "deferred":
            assert source.get("deferred_to"), (
                f"panel {panel['id']}: deferred source without deferred_to"
            )


def test_no_source_kind_is_manual() -> None:
    """W1.9 acceptance: no panel is manually populated."""
    for panel in _load()["panels"]:
        assert panel["source"]["kind"] != "manual", (
            f"panel {panel['id']}: manual sources are forbidden"
        )


def test_success_and_guard_panels_are_all_present() -> None:
    """Panels 1-4 (success) + 5 guard metrics MUST all be represented."""
    ids = {p["id"] for p in _load()["panels"]}
    expected = {
        # success 1..4
        "success.1.cost_per_unit",
        "success.2.auto_resolution_rate",
        "success.3a.mttr",
        "success.3b.change_lead_time",
        "success.4.human_intervention",
        # guard metrics
        "guard.cfr",
        "guard.false_positive_rate",
        "guard.false_negative_rate",
        "guard.rollback_rate",
        "guard.policy_violation_escapes",
    }
    missing = expected - ids
    assert not missing, f"missing required panels: {sorted(missing)}"


def test_leading_indicators_cover_tier_shares() -> None:
    ids = {p["id"] for p in _load()["panels"]}
    expected = {
        "leading.tier_coverage_t0",
        "leading.tier_coverage_t1",
        "leading.tier_coverage_t2",
    }
    missing = expected - ids
    assert not missing, f"missing tier-coverage leading indicators: {sorted(missing)}"


@pytest.mark.parametrize(
    "panel_id", ["success.2.auto_resolution_rate", "success.4.human_intervention"]
)
def test_wired_success_panels_derive_from_dashboard_metrics(panel_id: str) -> None:
    """Wired panels (not deferred) MUST reference DashboardMetrics fields."""
    panels = {p["id"]: p for p in _load()["panels"]}
    panel = panels[panel_id]
    assert panel["source"]["kind"] == "audit_log_derivation"
    assert panel["source"]["field"] in _dashboard_field_names()
