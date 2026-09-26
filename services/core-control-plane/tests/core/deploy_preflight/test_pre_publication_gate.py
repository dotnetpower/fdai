"""Pre-publication gate: the analyzer, not the reassembly, authorizes a PR.

Invariants proved here (see
``docs/roadmap/deployment/deployment-preflight.md`` and
``docs/roadmap/deployment/preflight-active-reassembly.md``):
- the analyzer runs again before publication and its truthful verdict decides;
- a blocking finding, an escalated loop, stale evidence, or a scope change
  withholds publication and routes the pass to human review;
- a withheld pass submits nothing at all - never a partial proposal set;
- a raising verifier is fail-closed and reaches no sink;
- on a clean re-verification each applied toggle reaches the governed pipeline
  through Huginn as one typed proposal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents import Forseti, Huginn, InMemoryBus, load_pantheon
from fdai.core.deploy_preflight import (
    ACTION_TYPE,
    INGRESS_EVENT_TYPE,
    AppliedToggle,
    DeploymentReadinessReport,
    PublicationDecision,
    PublicationHold,
    ReadinessVerdict,
    ReassemblyOutcome,
    ReassemblyReason,
    ReassemblyStatus,
    gate_toggle_publication,
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

_SCOPE = "rg:example"
_NOW = datetime(2026, 7, 10, 0, 5, 0, tzinfo=UTC)
_FRESH = "2026-07-10T00:00:00+00:00"
_PRINCIPAL = "control-plane"


def _now() -> datetime:
    return _NOW


def _blocking_finding(fid: str) -> ProbeFinding:
    return ProbeFinding(
        id=fid,
        category=ProbeCategory.POLICY_GUARDRAIL,
        severity=FindingSeverity.BLOCKING,
        title=fid,
        evidence=ProbeEvidence(source="policy:x", detail="d"),
        resolution=ProbeResolution(
            kind=ResolutionKind.TERRAFORM_TOGGLE,
            autofix=True,
            module="compute",
            set_vars={"disk_provisioning": "attach_existing"},
        ),
    )


def _report(
    *findings: ProbeFinding,
    scope: str = _SCOPE,
    generated_at: str = _FRESH,
    mode: Mode = Mode.ENFORCE,
) -> DeploymentReadinessReport:
    verdict = (
        ReadinessVerdict.BLOCKED
        if any(f.severity is FindingSeverity.BLOCKING for f in findings)
        else ReadinessVerdict.CLEAR
    )
    return DeploymentReadinessReport(
        scope=scope,
        generated_at=generated_at,
        mode=mode,
        verdict=verdict,
        findings=tuple(findings),
        checked_categories=(ProbeCategory.POLICY_GUARDRAIL,),
    )


def _toggle(
    finding_id: str = "denied-resource-type:disk",
    *,
    module: str = "compute",
    scope: str = _SCOPE,
) -> AppliedToggle:
    return AppliedToggle(
        finding_id=finding_id,
        module=module,
        set_vars={"disk_provisioning": "attach_existing"},
        scope=scope,
    )


def _cleared(*toggles: AppliedToggle) -> ReassemblyOutcome:
    return ReassemblyOutcome(
        status=ReassemblyStatus.CLEARED,
        reason=ReassemblyReason.NONE,
        overrides={k: v for t in toggles for k, v in t.set_vars.items()},
        iterations=len(toggles),
        applied_toggles=tuple(toggles),
    )


class _RecordingSink:
    """Stand-in for the pipeline seam; records every envelope it receives."""

    def __init__(self) -> None:
        self.envelopes: list[dict[str, Any]] = []

    async def __call__(self, envelope: Any) -> dict[str, Any]:
        self.envelopes.append(dict(envelope))
        return {"accepted": True}


class _ScriptedVerify:
    def __init__(self, report: DeploymentReadinessReport) -> None:
        self._report = report
        self.calls: list[dict[str, str]] = []

    async def __call__(self, overrides: Any) -> DeploymentReadinessReport:
        self.calls.append(dict(overrides))
        return self._report


async def _gate(
    outcome: ReassemblyOutcome,
    verify: Any,
    sink: Any,
    **kwargs: Any,
) -> Any:
    return await gate_toggle_publication(
        outcome,
        verify=verify,
        sink=sink,
        initiator_principal=_PRINCIPAL,
        expected_scope=_SCOPE,
        now=_now,
        **kwargs,
    )


async def test_clean_reverification_submits_one_proposal_per_toggle() -> None:
    verify = _ScriptedVerify(_report())
    sink = _RecordingSink()
    outcome = await _gate(_cleared(_toggle("f0"), _toggle("f1", module="registry")), verify, sink)
    assert outcome.decision is PublicationDecision.SUBMIT
    assert outcome.hold is PublicationHold.NONE
    assert outcome.publishes is True
    assert verify.calls == [{"disk_provisioning": "attach_existing"}]
    assert [e["params"]["finding_id"] for e in sink.envelopes] == ["f0", "f1"]
    assert {e["action_type"] for e in sink.envelopes} == {ACTION_TYPE}
    assert outcome.evidence_age_seconds == 300.0


async def test_blocked_reverification_opens_no_pr() -> None:
    verify = _ScriptedVerify(_report(_blocking_finding("still-denied")))
    sink = _RecordingSink()
    outcome = await _gate(_cleared(_toggle()), verify, sink)
    assert outcome.decision is PublicationDecision.HUMAN_REVIEW
    assert outcome.hold is PublicationHold.BLOCKING_FINDING
    assert outcome.held_findings == ("still-denied",)
    assert sink.envelopes == []
    assert outcome.submitted == ()


async def test_shadow_mode_blocker_still_withholds_publication() -> None:
    # blocks_deploy is False in shadow mode; the truthful verdict still gates.
    report = _report(_blocking_finding("shadow-denied"), mode=Mode.SHADOW)
    assert report.blocks_deploy is False
    sink = _RecordingSink()
    outcome = await _gate(_cleared(_toggle()), _ScriptedVerify(report), sink)
    assert outcome.hold is PublicationHold.BLOCKING_FINDING
    assert sink.envelopes == []


async def test_escalated_outcome_never_reaches_verifier_or_sink() -> None:
    verify = _ScriptedVerify(_report())
    sink = _RecordingSink()
    outcome = await _gate(
        ReassemblyOutcome(
            status=ReassemblyStatus.ESCALATED,
            reason=ReassemblyReason.MANUAL_BLOCKER,
            applied_toggles=(_toggle(),),
        ),
        verify,
        sink,
    )
    assert outcome.decision is PublicationDecision.HUMAN_REVIEW
    assert outcome.hold is PublicationHold.REASSEMBLY_ESCALATED
    assert verify.calls == []
    assert sink.envelopes == []


async def test_stale_evidence_withholds_publication() -> None:
    stale = (_NOW - timedelta(hours=2)).isoformat()
    sink = _RecordingSink()
    outcome = await _gate(_cleared(_toggle()), _ScriptedVerify(_report(generated_at=stale)), sink)
    assert outcome.hold is PublicationHold.STALE_EVIDENCE
    assert outcome.evidence_age_seconds == 7200.0
    assert sink.envelopes == []


@pytest.mark.parametrize("generated_at", ["not-a-timestamp", "2026-07-10T00:00:00"])
async def test_unusable_timestamp_is_treated_as_stale(generated_at: str) -> None:
    sink = _RecordingSink()
    outcome = await _gate(
        _cleared(_toggle()), _ScriptedVerify(_report(generated_at=generated_at)), sink
    )
    assert outcome.hold is PublicationHold.STALE_EVIDENCE
    assert outcome.evidence_age_seconds is None
    assert sink.envelopes == []


async def test_future_timestamp_beyond_skew_is_stale() -> None:
    future = (_NOW + timedelta(minutes=30)).isoformat()
    sink = _RecordingSink()
    outcome = await _gate(_cleared(_toggle()), _ScriptedVerify(_report(generated_at=future)), sink)
    assert outcome.hold is PublicationHold.STALE_EVIDENCE
    assert sink.envelopes == []


async def test_scope_change_on_verified_report_withholds_publication() -> None:
    sink = _RecordingSink()
    outcome = await _gate(_cleared(_toggle()), _ScriptedVerify(_report(scope="rg:other")), sink)
    assert outcome.hold is PublicationHold.SCOPE_DRIFT
    assert sink.envelopes == []


async def test_scope_change_on_applied_toggle_withholds_before_verification() -> None:
    verify = _ScriptedVerify(_report())
    sink = _RecordingSink()
    outcome = await _gate(_cleared(_toggle(scope="rg:other")), verify, sink)
    assert outcome.hold is PublicationHold.SCOPE_DRIFT
    assert verify.calls == []
    assert sink.envelopes == []


async def test_cleared_pass_with_no_toggle_publishes_nothing() -> None:
    verify = _ScriptedVerify(_report())
    sink = _RecordingSink()
    outcome = await _gate(_cleared(), verify, sink)
    assert outcome.decision is PublicationDecision.NO_ACTION
    assert outcome.hold is PublicationHold.NO_APPLIED_TOGGLE
    assert outcome.publishes is False
    assert verify.calls == []
    assert sink.envelopes == []


async def test_raising_verifier_is_fail_closed_before_any_submission() -> None:
    async def _raise(_overrides: Any) -> DeploymentReadinessReport:
        raise RuntimeError("probe unavailable")

    sink = _RecordingSink()
    with pytest.raises(RuntimeError):
        await _gate(_cleared(_toggle()), _raise, sink)
    assert sink.envelopes == []


async def test_partial_hold_never_submits_a_subset() -> None:
    verify = _ScriptedVerify(_report(_blocking_finding("f1")))
    sink = _RecordingSink()
    outcome = await _gate(_cleared(_toggle("f0"), _toggle("f1", module="registry")), verify, sink)
    assert outcome.decision is PublicationDecision.HUMAN_REVIEW
    assert len(outcome.proposals) == 2
    assert sink.envelopes == []


async def test_decision_record_is_content_free_and_auditable() -> None:
    verify = _ScriptedVerify(_report(_blocking_finding("still-denied")))
    outcome = await _gate(_cleared(_toggle()), verify, _RecordingSink())
    record = outcome.to_dict()
    assert record == {
        "decision": "human_review",
        "hold": "blocking_finding",
        "proposal_count": 1,
        "submitted_count": 0,
        "expected_scope": _SCOPE,
        "evidence_age_seconds": 300.0,
        "held_findings": ["still-denied"],
        "verdict": "blocked",
    }


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_evidence_age_seconds": 0.0}, "max_evidence_age_seconds"),
        ({"max_evidence_age_seconds": float("nan")}, "max_evidence_age_seconds"),
        ({"max_evidence_age_seconds": float("inf")}, "max_evidence_age_seconds"),
        ({"expected_scope": "  "}, "expected_scope"),
    ],
)
async def test_invalid_configuration_is_rejected(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        await gate_toggle_publication(
            _cleared(_toggle()),
            verify=_ScriptedVerify(_report()),
            sink=_RecordingSink(),
            initiator_principal=_PRINCIPAL,
            expected_scope=kwargs.pop("expected_scope", _SCOPE),
            now=_now,
            **kwargs,
        )


class _HuginnPipeline:
    """Bind the gate's sink to Huginn, the sole writer of ``object.event``."""

    def __init__(self) -> None:
        self.bus = InMemoryBus(registry=load_pantheon())
        self.huginn = Huginn(bus=self.bus)
        self.forseti = Forseti(bus=self.bus)
        self.ingested: list[dict[str, Any]] = []
        self.bus.subscribe("object.event", "Forseti", self._record)
        self.bus.subscribe("object.event", "Forseti", self.forseti.on_typed_message)

    async def _record(self, topic: str, payload: Any) -> None:
        self.ingested.append(dict(payload))

    @property
    def sink(self) -> Any:
        return self.huginn.ingest

    def verdicts(self) -> list[dict[str, Any]]:
        return [dict(m.payload) for m in self.bus.published if m.topic == "object.verdict"]


async def test_cleared_pass_reaches_the_governed_pipeline_through_huginn() -> None:
    pipeline = _HuginnPipeline()
    outcome = await _gate(
        _cleared(_toggle("f0"), _toggle("f1", module="registry")),
        _ScriptedVerify(_report()),
        pipeline.sink,
    )
    assert outcome.decision is PublicationDecision.SUBMIT
    assert len(pipeline.ingested) == 2
    assert all(entry["event_type"] == INGRESS_EVENT_TYPE for entry in pipeline.ingested)
    assert all(entry["resource_id"] == _SCOPE for entry in pipeline.ingested)
    # Ingress never carries an ActionType for a non-operator signal.
    assert all("action_type" not in entry for entry in pipeline.ingested)


async def test_submitted_proposal_is_judged_as_the_toggle_action_and_held_for_a_human() -> None:
    pipeline = _HuginnPipeline()
    await _gate(_cleared(_toggle("f0")), _ScriptedVerify(_report()), pipeline.sink)
    verdicts = pipeline.verdicts()
    assert len(verdicts) == 1
    assert verdicts[0]["action_type"] == ACTION_TYPE
    # Human review, never an autonomous provider commit.
    assert verdicts[0]["risk_verdict"] == "hil"


@pytest.mark.parametrize(
    "report",
    [
        _report(_blocking_finding("still-denied")),
        _report(scope="rg:other"),
        _report(generated_at="2026-07-09T00:00:00+00:00"),
    ],
)
async def test_withheld_pass_publishes_no_pipeline_event(
    report: DeploymentReadinessReport,
) -> None:
    pipeline = _HuginnPipeline()
    outcome = await _gate(_cleared(_toggle()), _ScriptedVerify(report), pipeline.sink)
    assert outcome.decision is PublicationDecision.HUMAN_REVIEW
    assert pipeline.ingested == []
    assert pipeline.bus.published == []


async def test_redelivered_pass_is_deduplicated_by_huginn() -> None:
    pipeline = _HuginnPipeline()
    for _ in range(2):
        await _gate(_cleared(_toggle("f0")), _ScriptedVerify(_report()), pipeline.sink)
    assert len(pipeline.ingested) == 1


async def test_padded_expected_scope_is_normalized_before_comparison() -> None:
    verify = _ScriptedVerify(_report())
    sink = _RecordingSink()
    outcome = await gate_toggle_publication(
        _cleared(_toggle("f0")),
        verify=verify,
        sink=sink,
        initiator_principal=_PRINCIPAL,
        expected_scope=f"  {_SCOPE}  ",
        now=_now,
    )
    assert outcome.decision is PublicationDecision.SUBMIT
    assert len(sink.envelopes) == 1


async def test_naive_clock_is_rejected_before_any_submission() -> None:
    sink = _RecordingSink()
    with pytest.raises(ValueError, match="timezone-aware"):
        await gate_toggle_publication(
            _cleared(_toggle("f0")),
            verify=_ScriptedVerify(_report()),
            sink=sink,
            initiator_principal=_PRINCIPAL,
            expected_scope=_SCOPE,
            now=lambda: datetime(2026, 7, 10, 0, 5, 0),
        )
    assert sink.envelopes == []


async def test_hold_record_bounds_the_retained_finding_ids() -> None:
    findings = tuple(_blocking_finding(f"denied-{index:03d}") for index in range(25))
    sink = _RecordingSink()
    outcome = await _gate(_cleared(_toggle("f0")), _ScriptedVerify(_report(*findings)), sink)
    assert outcome.hold is PublicationHold.BLOCKING_FINDING
    assert len(outcome.held_findings) == 20
    assert outcome.held_findings[0] == "denied-000"
    assert sink.envelopes == []
