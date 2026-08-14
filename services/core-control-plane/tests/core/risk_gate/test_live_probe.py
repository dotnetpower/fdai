"""Axis-E live-probe resolution focused checks (execution-model.md 4).

The controlling invariant is that Axis E is ceiling-lowering only: no probe
reading, however favorable, may make an action more autonomous than the same
decision taken with no probe evidence at all.
"""

from __future__ import annotations

import itertools

import pytest
from fdai.core.risk_gate.ceiling import AxisLevel, resolve_ceiling
from fdai.core.risk_gate.live_probe import (
    FAILURE_ESCALATION_THRESHOLD,
    LiveProbeObservation,
    resolve_live_probe_axis,
)
from fdai.core.risk_gate.risk_table import RiskLevel, RiskTableVerdict
from fdai.shared.contracts.models import (
    ActionBlastRadius,
    ActionInterface,
    BlastRadiusComputation,
    BlastRadiusScope,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    Tier,
)
from fdai.shared.providers.blast_probe import ProbeVerdict

_PROBE = "vm_traffic_last_5m"


def _action_type(*, live_probe_ref: str | None) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="remediate.restart-vm",
        version="1.0.0",
        operation=Operation.RESTART,
        interfaces=[ActionInterface.CONTROL_PLANE],
        rollback_contract=RollbackKind.SCRIPTED,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            static_bucket=BlastRadiusScope.RESOURCE,
        ),
        live_probe_ref=live_probe_ref,
    )


def _fresh(verdict: ProbeVerdict, *, degraded: bool = False) -> LiveProbeObservation:
    return LiveProbeObservation(
        probe_id=_PROBE,
        verdict=verdict,
        degraded=degraded,
        age_seconds=10.0,
        max_age_seconds=60.0,
    )


# --- no live_probe_ref declared -------------------------------------------------


def test_unconfigured_probe_has_no_opinion() -> None:
    axis = resolve_live_probe_axis(_action_type(live_probe_ref=None))
    assert axis.result is None
    assert "no live_probe_ref" in axis.reason


def test_unsolicited_reading_for_an_unconfigured_action_lowers_to_hil() -> None:
    # An unbound probe must never be able to speak for this ActionType.
    axis = resolve_live_probe_axis(
        _action_type(live_probe_ref=None), observation=_fresh(ProbeVerdict.QUIET)
    )
    assert axis.result == "active"
    assert "unsolicited" in axis.reason


# --- configured probe: happy path ------------------------------------------------


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        (ProbeVerdict.QUIET, "quiet"),
        (ProbeVerdict.ACTIVE, "active"),
        (ProbeVerdict.OVERLOADED, "overloaded"),
    ],
)
def test_fresh_reading_maps_to_its_axis_level(verdict: ProbeVerdict, expected: str) -> None:
    axis = resolve_live_probe_axis(_action_type(live_probe_ref=_PROBE), observation=_fresh(verdict))
    assert axis.result == expected
    assert _PROBE in axis.reason


# --- configured probe: every uncertainty fails toward safety ---------------------


def test_unavailable_reading_forces_hil() -> None:
    axis = resolve_live_probe_axis(_action_type(live_probe_ref=_PROBE))
    assert axis.result == "active"
    assert "unavailable" in axis.reason


def test_substituted_reading_is_refused() -> None:
    other = LiveProbeObservation(
        probe_id="some_other_probe",
        verdict=ProbeVerdict.QUIET,
        age_seconds=1.0,
        max_age_seconds=60.0,
    )
    axis = resolve_live_probe_axis(_action_type(live_probe_ref=_PROBE), observation=other)
    assert axis.result == "active"
    assert "does not match" in axis.reason


def test_no_opinion_verdict_from_a_configured_probe_forces_hil() -> None:
    axis = resolve_live_probe_axis(
        _action_type(live_probe_ref=_PROBE), observation=_fresh(ProbeVerdict.NO_OPINION)
    )
    assert axis.result == "active"


def test_degraded_quiet_reading_cannot_authorize_auto() -> None:
    axis = resolve_live_probe_axis(
        _action_type(live_probe_ref=_PROBE),
        observation=_fresh(ProbeVerdict.QUIET, degraded=True),
    )
    assert axis.result == "active"
    assert "degraded" in axis.reason


def test_degraded_overloaded_reading_stays_at_the_lower_level() -> None:
    # Flooring at active must not *raise* an already-lower reading.
    axis = resolve_live_probe_axis(
        _action_type(live_probe_ref=_PROBE),
        observation=_fresh(ProbeVerdict.OVERLOADED, degraded=True),
    )
    assert axis.result == "overloaded"


@pytest.mark.parametrize(
    ("age", "max_age"),
    [
        (61.0, 60.0),  # past its window
        (None, 60.0),  # undatable
        (10.0, None),  # no declared window
        (-1.0, 60.0),  # nonsense age
        (10.0, 0.0),  # nonsense window
    ],
)
def test_unproven_freshness_cannot_authorize_auto(age: float | None, max_age: float | None) -> None:
    stale = LiveProbeObservation(
        probe_id=_PROBE,
        verdict=ProbeVerdict.QUIET,
        age_seconds=age,
        max_age_seconds=max_age,
    )
    axis = resolve_live_probe_axis(_action_type(live_probe_ref=_PROBE), observation=stale)
    assert axis.result == "active"
    assert "stale" in axis.reason


def test_reading_exactly_at_its_window_edge_is_still_fresh() -> None:
    edge = LiveProbeObservation(
        probe_id=_PROBE,
        verdict=ProbeVerdict.QUIET,
        age_seconds=60.0,
        max_age_seconds=60.0,
    )
    assert edge.is_fresh
    assert resolve_live_probe_axis(
        _action_type(live_probe_ref=_PROBE), observation=edge
    ).result == ("quiet")


def test_persistently_blind_probe_defers_instead_of_asking_forever() -> None:
    axis = resolve_live_probe_axis(
        _action_type(live_probe_ref=_PROBE),
        observation=_fresh(ProbeVerdict.QUIET),
        failure_streak=FAILURE_ESCALATION_THRESHOLD,
    )
    assert axis.result == "overloaded"
    assert "blind" in axis.reason


def test_streak_below_the_threshold_does_not_escalate() -> None:
    axis = resolve_live_probe_axis(
        _action_type(live_probe_ref=_PROBE),
        observation=_fresh(ProbeVerdict.QUIET),
        failure_streak=FAILURE_ESCALATION_THRESHOLD - 1,
    )
    assert axis.result == "quiet"


def test_empty_probe_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="probe_id"):
        LiveProbeObservation(probe_id="", verdict=ProbeVerdict.QUIET)


# --- the ceiling-lowering invariant ---------------------------------------------


def _ceiling_level(at: OntologyActionType, probe: str | None) -> AxisLevel:
    return resolve_ceiling(
        tier=Tier.T0,
        action_type=at,
        risk_table=RiskTableVerdict(rule_id="r1", decision=RiskLevel.AUTO, quorum=1, reason="ok"),
        principal_role=None,
        env="non_prod",
        live_probe=probe,  # type: ignore[arg-type]
    ).final_level


def test_no_resolved_reading_can_raise_autonomy_above_the_probeless_decision() -> None:
    """Exhaustive falsifying sweep of the Axis-E invariant."""
    verdicts = list(ProbeVerdict)
    ids = [_PROBE, "some_other_probe"]
    ages: list[tuple[float | None, float | None]] = [(10.0, 60.0), (999.0, 60.0), (None, None)]
    for ref, verdict, probe_id, (age, max_age), degraded, streak in itertools.product(
        [None, _PROBE], verdicts, ids, ages, [False, True], [0, FAILURE_ESCALATION_THRESHOLD]
    ):
        at = _action_type(live_probe_ref=ref)
        axis = resolve_live_probe_axis(
            at,
            observation=LiveProbeObservation(
                probe_id=probe_id,
                verdict=verdict,
                degraded=degraded,
                age_seconds=age,
                max_age_seconds=max_age,
            ),
            failure_streak=streak,
        )
        assert _ceiling_level(at, axis.result) <= _ceiling_level(at, None), (
            f"axis raised autonomy for ref={ref} verdict={verdict} id={probe_id} "
            f"age={age} degraded={degraded} streak={streak}"
        )
