"""Active reassembly convergence loop: clear, escalate, stop-conditions.

Property-level invariants the loop MUST hold (see
``docs/roadmap/deployment/preflight-active-reassembly.md``):
- shadow: the loop never mutates - it only decides and returns overrides;
- all-or-nothing: a manual blocker escalates the whole pass;
- the same toggle is never applied twice (non-convergence -> hil);
- a regression (more blockers) escalates;
- fail-closed: a raising reanalyze propagates.
"""

from __future__ import annotations

import pytest
from fdai.core.deploy_preflight import (
    DeploymentReadinessReport,
    ReadinessVerdict,
    ReassemblyReason,
    ReassemblyStatus,
    reassemble,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.feasibility_probe import (
    FindingSeverity,
    ProbeCategory,
    ProbeEvidence,
    ProbeFinding,
    ProbeResolution,
    ResolutionKind,
)

_CLOCK = "2026-07-10T00:00:00+00:00"


def _toggle_finding(fid: str, set_vars: dict[str, str], *, autofix: bool = True) -> ProbeFinding:
    return ProbeFinding(
        id=fid,
        category=ProbeCategory.POLICY_GUARDRAIL,
        severity=FindingSeverity.BLOCKING,
        title=fid,
        evidence=ProbeEvidence(source="policy:x", detail="d"),
        resolution=ProbeResolution(
            kind=ResolutionKind.TERRAFORM_TOGGLE,
            autofix=autofix,
            module="compute",
            set_vars=set_vars,
        ),
    )


def _manual_finding(fid: str) -> ProbeFinding:
    return ProbeFinding(
        id=fid,
        category=ProbeCategory.POLICY_GUARDRAIL,
        severity=FindingSeverity.BLOCKING,
        title=fid,
        evidence=ProbeEvidence(source="policy:x", detail="d"),
        resolution=ProbeResolution(kind=ResolutionKind.MANUAL, guidance="ask an owner"),
    )


def _report(*findings: ProbeFinding) -> DeploymentReadinessReport:
    verdict = (
        ReadinessVerdict.BLOCKED
        if any(f.severity is FindingSeverity.BLOCKING for f in findings)
        else ReadinessVerdict.CLEAR
    )
    return DeploymentReadinessReport(
        scope="rg:example",
        generated_at=_CLOCK,
        mode=Mode.ENFORCE,
        verdict=verdict,
        findings=tuple(findings),
        checked_categories=(ProbeCategory.POLICY_GUARDRAIL,),
    )


class _ScriptedReanalyze:
    """Return a scripted sequence of reports, recording the overrides seen."""

    def __init__(self, *reports: DeploymentReadinessReport) -> None:
        self._reports = list(reports)
        self.calls: list[dict[str, str]] = []

    async def __call__(self, overrides):  # type: ignore[no-untyped-def]
        self.calls.append(dict(overrides))
        return self._reports.pop(0)


async def test_already_clear_is_cleared_without_reanalyze() -> None:
    calls = _ScriptedReanalyze()  # would raise IndexError if called
    outcome = await reassemble(initial_report=_report(), reanalyze=calls)
    assert outcome.status is ReassemblyStatus.CLEARED
    assert outcome.reason is ReassemblyReason.NONE
    assert outcome.overrides == {}
    assert outcome.iterations == 0
    assert calls.calls == []


async def test_single_toggle_clears() -> None:
    initial = _report(_toggle_finding("f0", {"disk_provisioning": "attach_existing"}))
    reanalyze = _ScriptedReanalyze(_report())
    outcome = await reassemble(initial_report=initial, reanalyze=reanalyze)
    assert outcome.status is ReassemblyStatus.CLEARED
    assert outcome.overrides == {"disk_provisioning": "attach_existing"}
    assert outcome.iterations == 1
    assert reanalyze.calls == [{"disk_provisioning": "attach_existing"}]


async def test_two_toggles_accumulate_then_clear() -> None:
    initial = _report(_toggle_finding("f0", {"disk_provisioning": "attach_existing"}))
    reanalyze = _ScriptedReanalyze(
        _report(_toggle_finding("f1", {"registry_source": "acr_mirror"})),
        _report(),
    )
    outcome = await reassemble(initial_report=initial, reanalyze=reanalyze)
    assert outcome.status is ReassemblyStatus.CLEARED
    assert outcome.overrides == {
        "disk_provisioning": "attach_existing",
        "registry_source": "acr_mirror",
    }
    assert outcome.iterations == 2
    # second reanalyze sees the accumulated override set.
    assert reanalyze.calls[-1] == {
        "disk_provisioning": "attach_existing",
        "registry_source": "acr_mirror",
    }


async def test_manual_blocker_escalates_without_applying() -> None:
    initial = _report(
        _toggle_finding("f0", {"disk_provisioning": "attach_existing"}),
        _manual_finding("f1"),
    )
    calls = _ScriptedReanalyze()  # never called: all-or-nothing
    outcome = await reassemble(initial_report=initial, reanalyze=calls)
    assert outcome.status is ReassemblyStatus.ESCALATED
    assert outcome.reason is ReassemblyReason.MANUAL_BLOCKER
    assert outcome.overrides == {}
    assert calls.calls == []


async def test_non_autofix_toggle_escalates() -> None:
    initial = _report(
        _toggle_finding("f0", {"disk_provisioning": "attach_existing"}, autofix=False)
    )
    calls = _ScriptedReanalyze()
    outcome = await reassemble(initial_report=initial, reanalyze=calls)
    assert outcome.status is ReassemblyStatus.ESCALATED
    assert outcome.reason is ReassemblyReason.MANUAL_BLOCKER
    assert calls.calls == []


async def test_non_convergent_same_toggle_twice() -> None:
    initial = _report(_toggle_finding("f0", {"disk_provisioning": "attach_existing"}))
    # reanalyze returns the SAME blocking finding + toggle: the toggle did not clear it.
    reanalyze = _ScriptedReanalyze(
        _report(_toggle_finding("f0", {"disk_provisioning": "attach_existing"}))
    )
    outcome = await reassemble(initial_report=initial, reanalyze=reanalyze)
    assert outcome.status is ReassemblyStatus.ESCALATED
    assert outcome.reason is ReassemblyReason.NON_CONVERGENT
    assert len(reanalyze.calls) == 1


async def test_regression_more_blockers_escalates() -> None:
    initial = _report(_toggle_finding("f0", {"disk_provisioning": "attach_existing"}))
    reanalyze = _ScriptedReanalyze(
        _report(
            _toggle_finding("f1", {"registry_source": "acr_mirror"}),
            _toggle_finding("f2", {"nsg_provisioning": "byo"}),
        )
    )
    outcome = await reassemble(initial_report=initial, reanalyze=reanalyze)
    assert outcome.status is ReassemblyStatus.ESCALATED
    assert outcome.reason is ReassemblyReason.REGRESSION


async def test_max_iterations_escalates() -> None:
    initial = _report(_toggle_finding("f0", {"a": "1"}))
    # Each pass introduces a distinct new blocker so non-convergence never trips;
    # the loop escalates on the iteration cap instead.
    reanalyze = _ScriptedReanalyze(
        _report(_toggle_finding("f1", {"b": "1"})),
        _report(_toggle_finding("f2", {"c": "1"})),
        _report(_toggle_finding("f3", {"d": "1"})),
    )
    outcome = await reassemble(initial_report=initial, reanalyze=reanalyze, max_iterations=3)
    assert outcome.status is ReassemblyStatus.ESCALATED
    assert outcome.reason is ReassemblyReason.MAX_ITERATIONS
    assert outcome.iterations == 3
    assert len(reanalyze.calls) == 3


async def test_reanalyze_raise_propagates_fail_closed() -> None:
    initial = _report(_toggle_finding("f0", {"disk_provisioning": "attach_existing"}))

    async def _boom(_overrides):  # type: ignore[no-untyped-def]
        raise RuntimeError("probe failed")

    with pytest.raises(RuntimeError, match="probe failed"):
        await reassemble(initial_report=initial, reanalyze=_boom)


async def test_max_iterations_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_iterations MUST be >= 1"):
        await reassemble(initial_report=_report(), reanalyze=_ScriptedReanalyze(), max_iterations=0)
