"""Scenario-driven measurable-behavior tests.

The idea: make each agent's behaviour *observable* (``behavior_snapshot()``)
and then drive it through diverse event sequences, asserting both the
measured behaviour distribution and the structural invariants it must never
violate. This surfaces edge-case defects that per-method unit tests miss,
because it checks the agent as a whole against many inputs at once.

Every agent inherits ``record_behavior`` / ``behavior_snapshot`` from the
base ``Agent`` (colon-namespaced keys), so this harness generalises to any
agent; Forseti (the judge) is the richest first target.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from fdai.agents.forseti import Forseti


@dataclass(frozen=True)
class Scenario:
    """One named event fed to an agent with the behaviour it should record."""

    name: str
    event: dict[str, Any]
    expect_verdict: str | None  # risk_verdict, or None when the judge abstains


# A deliberately diverse set: each of the risk verdicts, an abstain, an
# irreversible action, an RBAC violation, and a cross-domain conflict.
_FORSETI_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "auto_rule_fired",
        {"event_type": "public_network_enabled", "correlation_id": "s1", "resource_id": "sa-1"},
        "auto",
    ),
    Scenario(
        "hil_rule_fired",
        {"event_type": "unencrypted_disk", "correlation_id": "s2", "resource_id": "d-1"},
        "hil",
    ),
    Scenario(
        "deny_irreversible",
        {"action_type": "remediate.delete-storage", "correlation_id": "s3", "resource_id": "sa-2"},
        "deny",
    ),
    Scenario(
        # No rule matches, but the event names a concrete resource target ->
        # fail toward safety (rule 4.7): route to HIL for human triage rather
        # than dropping the event.
        "hil_unknown_event_triage",
        {"event_type": "totally_unknown_signal", "correlation_id": "s4", "resource_id": "x-1"},
        "hil",
    ),
    Scenario(
        # No rule match AND no concrete resource target -> nothing actionable
        # to triage; abstains (recorded via no_rule_match) so malformed / junk
        # ingress cannot manufacture HIL items.
        "abstain_no_resource_target",
        {"event_type": "totally_unknown_signal", "correlation_id": "s6"},
        None,
    ),
    Scenario(
        "rbac_denied_operator",
        {
            "action_type": "remediate.disable-public-access",
            "initiator_principal": "guest@example.com",
            "operator_initiated": True,
            "correlation_id": "s5",
            "resource_id": "sa-3",
        },
        "deny",
    ),
)


def _run_forseti_scenarios(forseti: Forseti) -> list[dict[str, Any] | None]:
    verdicts: list[dict[str, Any] | None] = []
    for sc in _FORSETI_SCENARIOS:
        verdicts.append(asyncio.run(forseti.judge(dict(sc.event))))
    return verdicts


def test_forseti_behavior_distribution_is_measurable() -> None:
    forseti = Forseti(bus=None)
    _run_forseti_scenarios(forseti)
    behavior = forseti.behavior_snapshot()
    # The measured verdict distribution matches the scenario set exactly.
    assert behavior.get("verdict:auto") == 1
    assert behavior.get("verdict:hil") == 2  # 1 rule-fired + 1 no-rule-match triage
    assert behavior.get("verdict:deny") == 2  # irreversible + rbac-denied
    assert behavior.get("no_rule_match") == 2  # 1 triaged (has resource) + 1 abstained
    assert behavior.get("rbac_denied") == 1
    assert behavior.get("security_event") == 1  # emitted on the rbac violation


def test_forseti_each_scenario_yields_expected_verdict() -> None:
    forseti = Forseti(bus=None)
    verdicts = _run_forseti_scenarios(forseti)
    for sc, verdict in zip(_FORSETI_SCENARIOS, verdicts, strict=True):
        if sc.expect_verdict is None:
            assert verdict is None, f"{sc.name}: expected abstain, got {verdict}"
        else:
            assert verdict is not None, f"{sc.name}: expected a verdict, got abstain"
            assert verdict["risk_verdict"] == sc.expect_verdict, sc.name


def test_invariant_deny_never_auto() -> None:
    """Structural invariant across the whole scenario set: a denied action
    never carries an auto verdict, and a deny count never exceeds the number
    of deny+abstain scenarios."""
    forseti = Forseti(bus=None)
    verdicts = _run_forseti_scenarios(forseti)
    for verdict in verdicts:
        if verdict is not None and verdict["reason"] in ("risk_deny", "rbac_insufficient"):
            assert verdict["risk_verdict"] == "deny"


def test_invariant_rbac_violation_always_denies_and_alerts() -> None:
    """An operator action the initiator's RBAC does not permit MUST deny AND
    emit exactly one security event - no silent allow."""
    forseti = Forseti(bus=None)
    _run_forseti_scenarios(forseti)
    behavior = forseti.behavior_snapshot()
    # One rbac violation in the set -> one deny-by-rbac + one security event.
    assert behavior.get("rbac_denied") == 1
    assert behavior.get("security_event") == 1


def test_invariant_irreversible_carries_quorum_two() -> None:
    """Every deny/hil verdict for an irreversible action carries the
    two-approver quorum (so a fork that routes it to hil is safe)."""
    forseti = Forseti(bus=None)
    verdicts = _run_forseti_scenarios(forseti)
    for sc, verdict in zip(_FORSETI_SCENARIOS, verdicts, strict=True):
        if verdict is not None and "delete" in verdict["action_type"]:
            assert verdict["quorum_required"] == 2, sc.name


def test_behavior_snapshot_is_a_copy() -> None:
    """A caller cannot corrupt the agent's live counters through the snapshot."""
    forseti = Forseti(bus=None)
    _run_forseti_scenarios(forseti)
    snap = forseti.behavior_snapshot()
    snap["verdict:auto"] = 999
    assert forseti.behavior_snapshot().get("verdict:auto") == 1


def test_behavior_surfaces_in_health() -> None:
    forseti = Forseti(bus=None)
    _run_forseti_scenarios(forseti)
    health = forseti.health()
    assert "behavior" in health
    assert health["behavior"].get("verdict:auto") == 1


def test_record_behavior_lazy_inits_if_counter_missing() -> None:
    """Observability must never raise: a subclass that skipped super().__init__
    (a defect elsewhere) still records without an AttributeError."""
    forseti = Forseti(bus=None)
    del forseti._behavior  # simulate the missing counter  # noqa: SLF001
    forseti.record_behavior("x")  # must not raise
    assert forseti.behavior_snapshot()["x"] == 1


def test_behavior_snapshot_robust_to_missing_counter() -> None:
    forseti = Forseti(bus=None)
    del forseti._behavior  # noqa: SLF001
    assert forseti.behavior_snapshot() == {}


def test_record_behavior_caps_key_space() -> None:
    """A caller that mistakenly builds keys from unbounded data cannot explode
    the counter: new keys past the cap fold into a bounded overflow sentinel."""
    from fdai.agents._framework.base import _MAX_BEHAVIOR_KEYS

    forseti = Forseti(bus=None)
    for i in range(_MAX_BEHAVIOR_KEYS + 50):
        forseti.record_behavior(f"dynamic:{i}")
    snap = forseti.behavior_snapshot()
    # Distinct keys bounded (the cap + the single overflow sentinel).
    assert len(snap) <= _MAX_BEHAVIOR_KEYS + 1
    assert snap["behavior:overflow"] >= 50


def test_record_behavior_ignores_non_positive_count() -> None:
    """A measurement counter never decreases: a zero/negative count is a
    caller mistake and is ignored, not applied."""
    forseti = Forseti(bus=None)
    forseti.record_behavior("k", 3)
    forseti.record_behavior("k", 0)
    forseti.record_behavior("k", -5)
    assert forseti.behavior_snapshot()["k"] == 3


def test_thor_degraded_shadow_is_distinguished() -> None:
    """A shadow forced by a downed hard dependency is measured distinctly from
    a policy shadow, so a scenario sees the degradation."""
    import asyncio

    from fdai.agents.thor import Thor

    # Not forced by policy, but Vidar unavailable -> degraded shadow.
    thor = Thor(shadow_by_default=False, vidar_available=False)
    asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "d1",
                "action_type": "remediate.disable-public-access",
                "risk_verdict": "auto",
                "resource_id": "r1",
            }
        )
    )
    b = thor.behavior_snapshot()
    assert b.get("dispatch:shadow") == 1
    assert b.get("dispatch:degraded") == 1


def test_huginn_measures_ingest_and_dedup() -> None:
    import asyncio

    from fdai.agents.huginn import Huginn

    huginn = Huginn(bus=None)
    asyncio.run(huginn.ingest({"idempotency_key": "k1", "event_type": "e"}))
    asyncio.run(huginn.ingest({"idempotency_key": "k1", "event_type": "e"}))  # dup
    asyncio.run(huginn.ingest({"idempotency_key": "k2", "event_type": "e"}))
    b = huginn.behavior_snapshot()
    assert b.get("ingested") == 2
    assert b.get("deduped") == 1
    # Huginn overrides health() - it must still surface behavior.
    assert "behavior" in huginn.health()
