"""Coverage tests for the SRE demo scenario pack.

Ensures :func:`default_scenarios` covers every S/C fault scenario in
``docs/internals/sre-demo-scenarios-08-fdai-coverage.md`` (S13 / S14 are
non-fault and excluded here) with the canonical ``expected_signal`` from
:mod:`fdai.core.detection.signals`. If a scenario is removed or its
``expected_signal`` drifts, these tests fail before any doc drifts.
"""

from __future__ import annotations

import re

from fdai.core.chaos import (
    AKS_BAD_DEPLOY,
    AKS_HTTP_ABORT,
    AKS_POD_CPU_SPIKE,
    AKS_POD_KILL,
    AOAI_TPM_THROTTLE,
    APPGW_BACKEND_FAILURE,
    MYSQL_CPU_PRESSURE,
    NETWORK_RTT_DELAY,
    VM_CPU_STRESS,
    VM_MEM_STRESS,
    default_scenarios,
)
from fdai.core.detection.signals import (
    SIGNAL_BACKEND_HEALTH,
    SIGNAL_DB_CPU,
    SIGNAL_GATEWAY_LATENCY,
    SIGNAL_HOST_CPU,
    SIGNAL_HOST_MEMORY,
    SIGNAL_NODE_CPU,
    SIGNAL_POD_RESTART,
    SIGNAL_RATE_LIMIT,
    SIGNAL_REQUEST_FAILURE,
    SIGNAL_ROLLOUT_STALL,
    is_known_signal,
)

# One row per S/C scenario the coverage matrix promises will fire.
# (scenario, expected_signal). New rows added here must have a
# corresponding FaultScenario in ``default_scenarios``.
_COVERAGE = (
    (AKS_POD_KILL, SIGNAL_POD_RESTART),                # S1, C2
    (AKS_POD_CPU_SPIKE, SIGNAL_NODE_CPU),              # S2, C3
    (NETWORK_RTT_DELAY, SIGNAL_GATEWAY_LATENCY),       # S3, S7, S10
    (AKS_HTTP_ABORT, SIGNAL_REQUEST_FAILURE),          # S4
    (VM_CPU_STRESS, SIGNAL_HOST_CPU),                  # S5
    (VM_MEM_STRESS, SIGNAL_HOST_MEMORY),               # S6, C4
    (MYSQL_CPU_PRESSURE, SIGNAL_DB_CPU),               # S8
    (AOAI_TPM_THROTTLE, SIGNAL_RATE_LIMIT),            # S9
    (APPGW_BACKEND_FAILURE, SIGNAL_BACKEND_HEALTH),    # S11
    (AKS_BAD_DEPLOY, SIGNAL_ROLLOUT_STALL),            # S12
)

# The demo's 5-minute alert window plus one probe cycle. Any scenario
# with a shorter hold could VALIDATE too early to model the demo.
_MIN_HOLD_SECONDS = 360.0


def test_every_covered_scenario_uses_expected_signal() -> None:
    """The coverage-matrix expected_signal ↔ scenario mapping is exact."""
    for scenario, expected in _COVERAGE:
        assert scenario.expected_signal == expected, (
            f"{scenario.scenario_id}: expected_signal drifted "
            f"({scenario.expected_signal!r} vs {expected!r})"
        )


def test_every_covered_scenario_signal_is_registered() -> None:
    """Each scenario's expected_signal is in the canonical registry."""
    for scenario, _expected in _COVERAGE:
        assert is_known_signal(scenario.expected_signal), (
            f"{scenario.scenario_id} expected_signal "
            f"{scenario.expected_signal!r} is not registered in "
            f"fdai.core.detection.signals"
        )


def test_default_scenarios_covers_full_matrix() -> None:
    """default_scenarios returns exactly the set the matrix promises."""
    got = {s.scenario_id for s in default_scenarios()}
    want = {s.scenario_id for s, _ in _COVERAGE}
    assert got == want, f"scenario mismatch: extra={got - want}, missing={want - got}"


def test_scenario_ids_are_unique() -> None:
    """No accidental duplicate scenario id (would break audit lookup)."""
    ids = [s.scenario_id for s in default_scenarios()]
    assert len(ids) == len(set(ids)), f"duplicate scenario ids: {ids}"


def test_every_scenario_holds_through_the_alert_window() -> None:
    """duration_seconds >= 5-min alert window + 1 probe cycle."""
    for scenario in default_scenarios():
        assert scenario.duration_seconds >= _MIN_HOLD_SECONDS, (
            f"{scenario.scenario_id}: duration {scenario.duration_seconds}s "
            f"is under the {_MIN_HOLD_SECONDS}s alert-window minimum"
        )


def test_every_scenario_has_rollback_note() -> None:
    """Rollback path is documented for every governed experiment."""
    for scenario in default_scenarios():
        assert scenario.rollback_note.strip(), (
            f"{scenario.scenario_id}: rollback_note MUST be non-empty"
        )


# ---------------------------------------------------------------------------
# Catalog shape invariants (R2 hardening)
# ---------------------------------------------------------------------------
#
# ``FaultScenario`` itself only validates non-empty strings; a fork MAY
# author scenarios with any shape. But the *shipped* upstream catalog is
# audit / operator surface, so we enforce a grep-friendly shape here so
# a drive-by change like ``scenario_id="AKS Pod Kill!"`` fails CI.

_SCENARIO_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_FAULT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_TARGET_SELECTOR_RE = re.compile(r"^[a-z][a-z0-9_-]*:[a-z0-9][a-z0-9_-]*$")

# ``fault_type`` values that are intentionally reused by more than one
# shipped scenario. Locking this set means a maintainer who renames one
# scenario's fault_type has to update this constant, which surfaces the
# shared-injector coupling instead of silently changing it.
_INTENTIONAL_FAULT_TYPE_REUSE: frozenset[str] = frozenset({"pod_kill"})


def test_scenario_ids_are_kebab_case() -> None:
    for scenario in default_scenarios():
        assert _SCENARIO_ID_RE.match(scenario.scenario_id), (
            f"scenario_id {scenario.scenario_id!r} must match "
            f"{_SCENARIO_ID_RE.pattern!r} (kebab-case, no spaces, "
            f"no punctuation - audit-log id shape)"
        )


def test_fault_types_are_snake_case() -> None:
    for scenario in default_scenarios():
        assert _FAULT_TYPE_RE.match(scenario.fault_type), (
            f"{scenario.scenario_id}: fault_type "
            f"{scenario.fault_type!r} must match "
            f"{_FAULT_TYPE_RE.pattern!r} (snake_case; injector-lookup key)"
        )


def test_target_selectors_are_type_colon_name() -> None:
    """target_selector is an opaque, CSP-neutral handle: '<type>:<name>'."""
    for scenario in default_scenarios():
        assert _TARGET_SELECTOR_RE.match(scenario.target_selector), (
            f"{scenario.scenario_id}: target_selector "
            f"{scenario.target_selector!r} must match "
            f"{_TARGET_SELECTOR_RE.pattern!r} "
            "(CSP-neutral '<type>:<name>' handle)"
        )


def test_scenario_expected_signals_are_all_registered() -> None:
    """Full-catalog cross-check, not just the coverage-matrix rows."""
    for scenario in default_scenarios():
        assert is_known_signal(scenario.expected_signal), (
            f"{scenario.scenario_id}: expected_signal "
            f"{scenario.expected_signal!r} missing from "
            f"fdai.core.detection.signals"
        )


def test_fault_type_reuse_is_intentional_only() -> None:
    """A fault_type used by more than one scenario means the two share
    an injector at runtime. Lock the intentional reuse set so a rename
    surfaces the coupling instead of silently changing it."""
    counts: dict[str, int] = {}
    for scenario in default_scenarios():
        counts[scenario.fault_type] = counts.get(scenario.fault_type, 0) + 1
    reused = {ft for ft, n in counts.items() if n > 1}
    assert reused == _INTENTIONAL_FAULT_TYPE_REUSE, (
        f"fault_type reuse drifted: expected {_INTENTIONAL_FAULT_TYPE_REUSE}, "
        f"got {reused}. Either add an intentional entry (with justification "
        f"in the commit) or pick a distinct fault_type."
    )


# ---------------------------------------------------------------------------
# Signals with intentional gaps (R3 hardening)
# ---------------------------------------------------------------------------
#
# Not every registered signal is the ``expected_signal`` of a scenario;
# some are emitted only by the RCA layer (e.g. ``member_hotspot``) when
# it identifies which pool member is responsible for an already-detected
# aggregate anomaly. Lock the "RCA-only" set so a maintainer does not
# delete ``member_hotspot`` from the registry as dead code, and does not
# quietly add a scenario with it as ``expected_signal`` (that would
# collapse the aggregate vs member distinction the RCA layer relies on).

# Locked list of signals that MUST exist in the registry but MUST NOT
# be any scenario's ``expected_signal``. Editing this set requires a
# justification in the commit that also documents the RCA path.
_RCA_ONLY_SIGNALS: frozenset[str] = frozenset({"member_hotspot"})


def test_rca_only_signals_are_registered() -> None:
    """Every RCA-only signal is still in the canonical registry."""
    for signal in _RCA_ONLY_SIGNALS:
        assert is_known_signal(signal), (
            f"RCA-only signal {signal!r} missing from registry - "
            "either restore it or update _RCA_ONLY_SIGNALS."
        )


def test_rca_only_signals_are_not_scenario_expected() -> None:
    """No scenario declares an RCA-only signal as its expected_signal."""
    scenario_signals = {s.expected_signal for s in default_scenarios()}
    conflicts = scenario_signals & _RCA_ONLY_SIGNALS
    assert not conflicts, (
        f"Scenario(s) declared an RCA-only signal as expected_signal: "
        f"{sorted(conflicts)}. RCA-only signals surface a member-level "
        f"causal chain over an already-detected aggregate anomaly; a "
        f"scenario that expects one directly would collapse that "
        f"distinction. Author a distinct signal instead."
    )
