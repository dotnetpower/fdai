"""Tests for RcaCoordinator.analyze_t2_from_symptom.

Covers the wiring that turns a symptom key + optional telemetry
window into T2 candidate citations. Reasoner is mocked so these are
deterministic and never touch a real model.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.core.chaos.symptom_index import build_from_entries
from fdai.core.rca.contract import (
    Citation,
    CitationKind,
    RcaOutcome,
    RcaTier,
    RootCauseHypothesis,
)
from fdai.core.rca.coordinator import RcaCoordinator


class _EchoReasoner:
    """Reasoner that echoes the caller-vouched citations as the cause."""

    def __init__(self) -> None:
        self.received: list[tuple[Citation, ...]] = []

    async def reason(
        self, *, incident_summary: str, candidate_citations
    ) -> RootCauseHypothesis:  # noqa: D401
        self.received.append(tuple(candidate_citations))
        return RootCauseHypothesis(
            tier=RcaTier.T2,
            cause=f"echo: {incident_summary}",
            confidence=0.9,
            citations=tuple(candidate_citations),
        )


class _AbstainingReasoner:
    async def reason(self, *, incident_summary: str, candidate_citations):
        return None


def _entry(
    scenario_id: str,
    signal: str,
    target: str = "pod",
    intensity: str = "mild",
) -> CatalogEntry:
    spec = {
        "id": scenario_id,
        "version": 1,
        "provenance": {"source": "synthesized", "synthesis_method": "deterministic"},
        "category": "compute",
        "target_type": target,
        "fault_family": "stop",
        "intensity": intensity,
        "duration_seconds": 360,
        "expected_signal": signal,
        "injector": "chaos-mesh:PodChaos",
        "blast_radius_cap": 1,
        "rollback_note": "n/a",
        "gates": {"shadow_status": "pending", "enforce_status": None},
        "requires_hardware": False,
        "gpu_domain": None,
    }
    return CatalogEntry(
        id=scenario_id,
        source_path=pathlib.Path("/tmp/x.yaml"),  # noqa: S108 - synthetic marker, never opened
        spec=spec,
    )


async def test_analyze_t2_from_symptom_adds_scenario_citations() -> None:
    idx = build_from_entries(
        [
            _entry("chaos.a.pod-a", "pod_restart", "pod", "mild"),
            _entry("chaos.a.pod-b", "pod_restart", "pod", "high"),
        ]
    )
    reasoner = _EchoReasoner()
    c = RcaCoordinator(reasoner=reasoner, symptom_index=idx)
    result = await c.analyze_t2_from_symptom(
        incident_summary="pods restarting",
        signal="pod_restart",
        target_type="pod",
        severity="low",
    )
    assert result.outcome is RcaOutcome.GROUNDED
    got = reasoner.received[0]
    assert all(c.kind is CitationKind.SCENARIO for c in got)
    assert {c.ref for c in got} == {"chaos.a.pod-a"}  # exact bucket only


async def test_symptom_widening_pulls_in_lower_severity() -> None:
    idx = build_from_entries(
        [_entry("chaos.a.pod-mild", "pod_restart", "pod", "mild")]
    )
    reasoner = _EchoReasoner()
    c = RcaCoordinator(reasoner=reasoner, symptom_index=idx)
    result = await c.analyze_t2_from_symptom(
        incident_summary="pods restarting hard",
        signal="pod_restart",
        target_type="pod",
        severity="high",
    )
    got = reasoner.received[0]
    # No exact 'high' match; widen path drops severity => the 'mild' entry
    # is still surfaced (this is a legitimate candidate, not a fabrication).
    assert {c.ref for c in got} == {"chaos.a.pod-mild"}
    assert result.outcome is RcaOutcome.GROUNDED


async def test_no_symptom_index_bound_yields_only_extra_citations() -> None:
    reasoner = _EchoReasoner()
    c = RcaCoordinator(reasoner=reasoner)  # no symptom_index
    extras = (Citation(kind=CitationKind.EVENT, ref="evt-1"),)
    await c.analyze_t2_from_symptom(
        incident_summary="orphan",
        signal="pod_restart",
        target_type="pod",
        severity="low",
        extra_citations=extras,
    )
    got = reasoner.received[0]
    # Only the caller-supplied EVENT citation survives.
    assert list(got) == list(extras)
    assert not c.has_symptom_index


async def test_extra_and_scenario_citations_are_both_grounded() -> None:
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    reasoner = _EchoReasoner()
    c = RcaCoordinator(reasoner=reasoner, symptom_index=idx)
    extras = (
        Citation(kind=CitationKind.RULE, ref="rule-42"),
        Citation(kind=CitationKind.EVENT, ref="evt-x"),
    )
    result = await c.analyze_t2_from_symptom(
        incident_summary="mixed",
        signal="pod_restart",
        target_type="pod",
        severity="low",
        extra_citations=extras,
    )
    got = reasoner.received[0]
    kinds = {c.kind for c in got}
    assert kinds == {CitationKind.RULE, CitationKind.EVENT, CitationKind.SCENARIO}
    # The reasoner is grounded on this superset; the echo reasoner echoes
    # all of them so the result is SUCCEEDED with matching citations.
    assert result.outcome is RcaOutcome.GROUNDED


class _StubGatherer:
    async def gather(self, *, resource_ref: str, since, until):
        return (Citation(kind=CitationKind.TELEMETRY, ref=f"tel-{resource_ref}"),)


async def test_telemetry_gatherer_is_called_when_window_supplied() -> None:
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    reasoner = _EchoReasoner()
    c = RcaCoordinator(
        reasoner=reasoner, symptom_index=idx, evidence_gatherer=_StubGatherer()
    )
    since = datetime.now(tz=UTC) - timedelta(minutes=5)
    until = datetime.now(tz=UTC)
    await c.analyze_t2_from_symptom(
        incident_summary="both",
        signal="pod_restart",
        target_type="pod",
        severity="low",
        resource_ref="rg/vm/1",
        since=since,
        until=until,
    )
    got = reasoner.received[0]
    kinds = {c.kind for c in got}
    assert CitationKind.SCENARIO in kinds
    assert CitationKind.TELEMETRY in kinds
    assert any(c.ref == "tel-rg/vm/1" for c in got)


async def test_telemetry_gatherer_skipped_without_window() -> None:
    reasoner = _EchoReasoner()
    c = RcaCoordinator(reasoner=reasoner, evidence_gatherer=_StubGatherer())
    await c.analyze_t2_from_symptom(
        incident_summary="s",
        signal="pod_restart",
        target_type="pod",
        severity="low",
    )
    assert reasoner.received[0] == ()


async def test_abstain_when_no_reasoner_configured() -> None:
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    c = RcaCoordinator(symptom_index=idx)  # no reasoner
    result = await c.analyze_t2_from_symptom(
        incident_summary="s",
        signal="pod_restart",
        target_type="pod",
        severity="low",
    )
    assert result.outcome is RcaOutcome.ABSTAINED
    assert result.reason == "no_t2_reasoner_configured"


async def test_abstain_when_reasoner_returns_none() -> None:
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    c = RcaCoordinator(reasoner=_AbstainingReasoner(), symptom_index=idx)
    result = await c.analyze_t2_from_symptom(
        incident_summary="s",
        signal="pod_restart",
        target_type="pod",
        severity="low",
    )
    assert result.outcome is RcaOutcome.ABSTAINED


async def test_max_scenario_candidates_caps_fan_out() -> None:
    entries = [
        _entry(f"chaos.a.p-{i}", "pod_restart", "pod", "mild") for i in range(20)
    ]
    idx = build_from_entries(entries)
    reasoner = _EchoReasoner()
    c = RcaCoordinator(reasoner=reasoner, symptom_index=idx)
    await c.analyze_t2_from_symptom(
        incident_summary="s",
        signal="pod_restart",
        target_type="pod",
        severity="low",
        max_scenario_candidates=3,
    )
    got = reasoner.received[0]
    assert len(got) == 3


def test_has_symptom_index_flag() -> None:
    assert not RcaCoordinator().has_symptom_index
    idx = build_from_entries([])
    assert RcaCoordinator(symptom_index=idx).has_symptom_index


@pytest.mark.parametrize("severity", ["low", "medium", "high"])
async def test_unknown_signal_yields_empty_scenario_set(severity: str) -> None:
    """A signal the catalog does not carry produces no scenario citations
    but T2 still runs on whatever extras / telemetry the caller vouches
    for (or abstains when none exist)."""
    idx = build_from_entries([_entry("chaos.a.p", "pod_restart", "pod", "mild")])
    reasoner = _EchoReasoner()
    c = RcaCoordinator(reasoner=reasoner, symptom_index=idx)
    result = await c.analyze_t2_from_symptom(
        incident_summary="s",
        signal="no_such_signal",
        target_type="pod",
        severity=severity,
    )
    got = reasoner.received[0]
    assert got == ()
    # No candidates at all -> grounding gate abstains.
    assert result.outcome is RcaOutcome.ABSTAINED
