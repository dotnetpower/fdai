"""Stakeholder briefing composer - M10 proactive operations summary.

Verifies the composer is deterministic, fail-closed on empty windows
(says "no significant activity" instead of fabricating), and surfaces
guard-metric breaches as explicit escalations.
"""

from __future__ import annotations

from fdai.core.notifications import (
    ActionTally,
    BriefingInput,
    CostSnapshot,
    ForecastRisk,
    IncidentTally,
    StakeholderBriefingComposer,
)


def _busy_input(**overrides) -> BriefingInput:  # noqa: ANN003
    base = dict(
        window_label="2026-W28",
        incidents=IncidentTally(
            by_severity={"sev1": 1, "sev3": 4},
            opened=5,
            resolved=4,
        ),
        actions=ActionTally(
            auto_executed=12,
            hil_approved=3,
            rolled_back=1,
            shadow_only=7,
        ),
        cost=CostSnapshot(
            current_run_rate=1234.50,
            delta_pct=8.3,
            top_drivers=("idle compute", "over-provisioned disk"),
        ),
        forecast_risks=(
            ForecastRisk(
                label="quota exhaustion",
                horizon="72h",
                detail="projected to cross 90% cores",
            ),
        ),
        guard_breaches=(),
    )
    base.update(overrides)
    return BriefingInput(**base)


def _quiet_input() -> BriefingInput:
    return BriefingInput(
        window_label="2026-W29",
        incidents=IncidentTally(by_severity={}, opened=0, resolved=0),
        actions=ActionTally(auto_executed=0, hil_approved=0, rolled_back=0, shadow_only=0),
    )


# ---------------------------------------------------------------------------
# Busy window - full briefing
# ---------------------------------------------------------------------------


def test_busy_window_renders_every_section_and_is_significant() -> None:
    composer = StakeholderBriefingComposer()
    briefing = composer.compose(_busy_input())
    assert briefing.has_significant_activity is True
    for header in (
        "## Incidents",
        "## Actions",
        "## Cost",
        "## Forward-looking risks",
        "## Guardrails",
    ):
        assert header in briefing.content
    assert "5 opened, 4 resolved" in briefing.content
    assert "12 auto-executed" in briefing.content
    assert "quota exhaustion" in briefing.content
    assert "up 8.3%" in briefing.content


def test_composer_is_deterministic() -> None:
    composer = StakeholderBriefingComposer()
    first = composer.compose(_busy_input())
    second = composer.compose(_busy_input())
    assert first.content == second.content
    assert first.sections == second.sections


def test_severity_breakdown_is_sorted_and_labelled() -> None:
    composer = StakeholderBriefingComposer()
    briefing = composer.compose(_busy_input())
    incidents = briefing.sections["incidents"]
    # sev1 sorts before sev3.
    assert incidents.index("`sev1`") < incidents.index("`sev3`")


# ---------------------------------------------------------------------------
# Quiet window - fail-closed, no fabrication
# ---------------------------------------------------------------------------


def test_quiet_window_is_not_significant_and_says_so() -> None:
    composer = StakeholderBriefingComposer()
    briefing = composer.compose(_quiet_input())
    assert briefing.has_significant_activity is False
    assert "No significant operational activity" in briefing.content
    assert "No incidents in this window." in briefing.sections["incidents"]
    assert "No actions taken in this window." in briefing.sections["actions"]
    assert "No cost data recorded" in briefing.sections["cost"]


def test_flat_small_cost_change_alone_is_not_significant() -> None:
    composer = StakeholderBriefingComposer()
    briefing = composer.compose(
        _quiet_input().__class__(
            window_label="2026-W30",
            incidents=IncidentTally(by_severity={}, opened=0, resolved=0),
            actions=ActionTally(auto_executed=0, hil_approved=0, rolled_back=0, shadow_only=0),
            cost=CostSnapshot(current_run_rate=100.0, delta_pct=0.4, top_drivers=()),
        )
    )
    # A sub-1% cost wobble with nothing else is noise, not a briefing.
    assert briefing.has_significant_activity is False


# ---------------------------------------------------------------------------
# Guard breaches -> escalations
# ---------------------------------------------------------------------------


def test_guard_breaches_become_escalations_and_headline() -> None:
    composer = StakeholderBriefingComposer()
    briefing = composer.compose(_busy_input(guard_breaches=("rollback rate 0.12 > baseline 0.05",)))
    assert briefing.escalations == ("rollback rate 0.12 > baseline 0.05",)
    assert "guard-metric breach" in briefing.content
    assert "rollback rate 0.12" in briefing.sections["guardrails"]


def test_no_guard_breaches_reports_within_threshold() -> None:
    composer = StakeholderBriefingComposer()
    briefing = composer.compose(_busy_input())
    assert briefing.escalations == ()
    assert "All guard metrics within threshold." in briefing.sections["guardrails"]
