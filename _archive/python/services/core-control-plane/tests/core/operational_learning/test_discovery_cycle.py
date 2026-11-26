from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.measurement.promotion_binding import ReviewedReplayBinding
from fdai.core.operational_learning import (
    DiscoveryCandidate,
    DiscoveryCandidateState,
    DiscoveryCycleConfig,
    DiscoveryCycleScheduler,
    DiscoveryIntegrationReceipt,
    DiscoveryModelReview,
    DiscoveryObservationBatch,
    DiscoverySignal,
    DiscoverySignalKind,
    DiscoveryVerificationReceipt,
    ShadowDwellDecision,
    ShadowDwellEvidence,
    ShadowDwellEvidenceError,
    ShadowDwellLedger,
    ShadowDwellObservation,
    ShadowDwellThresholds,
    evaluate_shadow_dwell,
)
from fdai.core.operational_learning.promotion_review import (
    ReviewedReplayAuthority,
    ReviewedReplayReceiptVerifier,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.contracts.test_development_authority import NOW, _binding, _verification
from tests.core.measurement.test_operational_promotion import (
    _action as _promo_action,
)
from tests.core.measurement.test_operational_promotion import (
    _evaluator,
    _passing_batch,
    _with_admission,
)
from tests.core.operational_learning.test_promotion_review import _development_evidence
from tests.core.risk_gate.test_development_authority import _action as _dev_action

_START = datetime(2026, 8, 29, 1, tzinfo=UTC)


class _Source:
    def __init__(
        self,
        signals: tuple[DiscoverySignal, ...],
        *,
        complete: bool = True,
        delay: float = 0.0,
    ) -> None:
        self.signals = signals
        self.complete = complete
        self.delay = delay
        self.calls = 0

    async def observe(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> DiscoveryObservationBatch:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        assert len(self.signals) <= limit
        return DiscoveryObservationBatch(
            window_start=window_start,
            window_end=window_end,
            signals=self.signals,
            complete=self.complete,
        )


class _Primary:
    model_identity = "primary-v1"
    model_family = "family-a"

    def __init__(self, candidates: tuple[DiscoveryCandidate, ...]) -> None:
        self.candidates = candidates
        self.calls = 0

    async def hypothesize(
        self,
        batch: DiscoveryObservationBatch,
    ) -> tuple[DiscoveryCandidate, ...]:
        self.calls += 1
        return self.candidates


class _Reviewer:
    model_identity = "reviewer-v1"
    model_family = "family-b"

    def __init__(self, *, approved: bool = True, wrong_digest: bool = False) -> None:
        self.approved = approved
        self.wrong_digest = wrong_digest
        self.calls = 0

    async def review(
        self,
        candidate: DiscoveryCandidate,
        batch: DiscoveryObservationBatch,
    ) -> DiscoveryModelReview:
        self.calls += 1
        return DiscoveryModelReview(
            candidate_digest="f" * 64 if self.wrong_digest else candidate.digest,
            approved=self.approved,
            reason="approved" if self.approved else "unsupported",
        )


class _Verifier:
    def __init__(self, *, passed: bool = True) -> None:
        self.passed = passed
        self.calls = 0

    async def verify(
        self,
        candidate: DiscoveryCandidate,
        batch: DiscoveryObservationBatch,
    ) -> DiscoveryVerificationReceipt:
        self.calls += 1
        return DiscoveryVerificationReceipt(
            candidate_digest=candidate.digest,
            passed=self.passed,
            reason="quality_gate_passed" if self.passed else "policy_escape",
        )


class _Integrator:
    def __init__(self) -> None:
        self.candidates: list[DiscoveryCandidate] = []

    async def integrate(
        self,
        candidate: DiscoveryCandidate,
        receipt: DiscoveryVerificationReceipt,
    ) -> DiscoveryIntegrationReceipt:
        self.candidates.append(candidate)
        return DiscoveryIntegrationReceipt(
            candidate_digest=candidate.digest,
            review_ref=f"catalog-review:{candidate.digest[:12]}",
            already_existed=False,
        )


def _signal(identifier: str, kind: DiscoverySignalKind) -> DiscoverySignal:
    return DiscoverySignal(
        signal_id=identifier,
        kind=kind,
        observed_at=_START,
        evidence_refs=(f"audit:{identifier}",),
        facts={"target_rule_id": f"rule.{identifier}"},
    )


def _candidate(
    target: str,
    signal_id: str,
    *,
    proposal_kind: str = "revision",
) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        proposal_kind=proposal_kind,
        target_rule_id=target,
        source_signal_ids=(signal_id,),
        payload={
            "proposed_by": "Norns",
            "evidence": {"signal_id": signal_id},
            "suggested_change": "review_rule",
        },
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"nested": {"approved": True}},
        {"items": [{"execution_authority": "auto"}]},
    ],
)
def test_candidate_rejects_nested_authority_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="MUST NOT carry authority"):
        DiscoveryCandidate(
            proposal_kind="revision",
            target_rule_id="rule.revise",
            source_signal_ids=("audit-1",),
            payload=payload,
        )


def _scheduler(
    *,
    source: _Source,
    primary: _Primary,
    reviewer: _Reviewer | None = None,
    verifier: _Verifier | None = None,
    integrator: _Integrator | None = None,
    config: DiscoveryCycleConfig | None = None,
) -> tuple[DiscoveryCycleScheduler, InMemoryStateStore, _Integrator]:
    store = InMemoryStateStore()
    resolved_integrator = integrator or _Integrator()
    return (
        DiscoveryCycleScheduler(
            state_store=store,
            source=source,
            primary_model=primary,
            cross_check_models=(reviewer or _Reviewer(),),
            verifier=verifier or _Verifier(),
            integrator=resolved_integrator,
            config=config,
            clock=lambda: _START,
        ),
        store,
        resolved_integrator,
    )


async def test_cycle_persists_all_stages_metrics_and_replays_without_side_effects() -> None:
    source = _Source(
        (
            _signal("override-1", DiscoverySignalKind.OVERRIDE),
            _signal("audit-1", DiscoverySignalKind.OPERATIONAL),
        )
    )
    primary = _Primary(
        (
            _candidate("rule.retire", "override-1", proposal_kind="retirement"),
            _candidate("rule.revise", "audit-1"),
        )
    )
    scheduler, store, integrator = _scheduler(source=source, primary=primary)

    report = await scheduler.run_due(scheduled_for=_START + timedelta(minutes=5))

    assert report.status == "completed"
    assert [decision.state for decision in report.decisions] == [
        DiscoveryCandidateState.INTEGRATED,
        DiscoveryCandidateState.INTEGRATED,
    ]
    assert report.metrics is not None
    assert report.metrics.candidates_per_cycle == 2
    assert report.metrics.gate_pass_rate == 1.0
    assert report.metrics.override_trigger_rate == 0.5
    assert report.metrics.retirement_rate == 0.5
    cycle = await store.read_state(f"operational-learning:discovery-cycle:{report.cycle_id}")
    assert cycle is not None
    assert [item["signal_id"] for item in cycle["signal_refs"]] == ["override-1", "audit-1"]
    assert len(cycle["candidate_refs"]) == 2
    assert [item["model_family"] for item in cycle["model_bindings"]] == [
        "family-a",
        "family-b",
    ]
    metrics = await store.read_state(f"operational-learning:discovery-metrics:{report.cycle_id}")
    assert metrics is not None
    assert metrics["grants_authority"] is False
    audit_payloads = [record["entry"] for record in store.audit_entries]
    assert [
        item["stage"]
        for item in audit_payloads
        if item.get("action_kind") == "rule_discovery.cycle"
    ] == ["scheduled", "observe", "hypothesize", "verify", "integrate"]
    assert any(item.get("action_kind") == "rule_discovery.metrics" for item in audit_payloads)

    replay = await scheduler.run_due(scheduled_for=_START + timedelta(minutes=40))

    assert replay.replayed is True
    assert replay.cycle_id == report.cycle_id
    assert replay.decisions == report.decisions
    assert replay.metrics == report.metrics
    assert source.calls == 1
    assert primary.calls == 1
    assert len(integrator.candidates) == 2

    tampered = dict(cycle)
    tampered["decisions"] = [
        {**cycle["decisions"][0], "candidate_digest": "not-a-digest"},
        *cycle["decisions"][1:],
    ]
    await store.write_state(
        f"operational-learning:discovery-cycle:{report.cycle_id}",
        tampered,
    )
    with pytest.raises(ValueError, match="MUST be lowercase SHA-256"):
        await scheduler.run_due(scheduled_for=_START)


@pytest.mark.parametrize("wrong_digest", [False, True], ids=["disagree", "digest-mismatch"])
async def test_mixed_model_disagreement_is_held_for_human_review(wrong_digest: bool) -> None:
    source = _Source((_signal("audit-1", DiscoverySignalKind.OPERATIONAL),))
    candidate = _candidate("rule.revise", "audit-1")
    reviewer = _Reviewer(approved=False, wrong_digest=wrong_digest)
    scheduler, _, integrator = _scheduler(
        source=source,
        primary=_Primary((candidate,)),
        reviewer=reviewer,
    )

    report = await scheduler.run_due(scheduled_for=_START)

    assert report.decisions[0].state is DiscoveryCandidateState.HELD
    assert report.decisions[0].reason.startswith("mixed_model_")
    assert integrator.candidates == []
    assert report.metrics is not None
    assert report.metrics.gate_pass_rate == 0.0


def test_scheduler_requires_distinct_model_identities_and_families() -> None:
    class _SameFamilyReviewer(_Reviewer):
        model_identity = "reviewer-v2"
        model_family = "family-a"

    source = _Source(())
    with pytest.raises(ValueError, match="families MUST be distinct"):
        _scheduler(
            source=source,
            primary=_Primary(()),
            reviewer=_SameFamilyReviewer(),
        )


async def test_incomplete_observation_fails_closed_and_replays_failure() -> None:
    source = _Source((), complete=False)
    scheduler, _, _ = _scheduler(source=source, primary=_Primary(()))

    with pytest.raises(RuntimeError, match="window is incomplete"):
        await scheduler.run_due(scheduled_for=_START)

    replay = await scheduler.run_due(scheduled_for=_START)
    assert replay.status == "failed"
    assert replay.failure_kind == "RuntimeError"
    assert replay.replayed is True
    assert source.calls == 1


async def test_cycle_timeout_is_persisted_as_a_failed_attempt() -> None:
    source = _Source((), delay=0.02)
    scheduler, _, _ = _scheduler(
        source=source,
        primary=_Primary(()),
        config=DiscoveryCycleConfig(timeout_seconds=0.001),
    )

    with pytest.raises(TimeoutError):
        await scheduler.run_due(scheduled_for=_START)

    replay = await scheduler.run_due(scheduled_for=_START)
    assert replay.failure_kind == "TimeoutError"


async def test_concurrent_claim_loser_does_not_report_inflight_cycle_as_replay() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingSource(_Source):
        async def observe(
            self,
            *,
            window_start: datetime,
            window_end: datetime,
            limit: int,
        ) -> DiscoveryObservationBatch:
            started.set()
            await release.wait()
            return await super().observe(
                window_start=window_start,
                window_end=window_end,
                limit=limit,
            )

    source = _BlockingSource(())
    scheduler, _, _ = _scheduler(source=source, primary=_Primary(()))
    winner = asyncio.create_task(scheduler.run_due(scheduled_for=_START))
    await started.wait()

    with pytest.raises(RuntimeError, match="already in progress"):
        await scheduler.run_due(scheduled_for=_START)

    release.set()
    assert (await winner).status == "completed"


def test_shadow_dwell_thresholds_observations_and_evidence_branches() -> None:
    thresholds = ShadowDwellThresholds(min_shadow_days=14, min_samples=100, min_accuracy=0.98)
    for bad_thresholds in (
        {"min_shadow_days": True},
        {"min_samples": True},
        {"min_shadow_days": 0},
        {"min_accuracy": 0.0},
    ):
        with pytest.raises(ValueError):
            ShadowDwellThresholds(**bad_thresholds)  # type: ignore[arg-type]
    with pytest.raises(ShadowDwellEvidenceError, match="observation_reviewed_invalid"):
        ShadowDwellObservation(
            target="rule.one",
            observed_at=_START,
            reviewed="yes",  # type: ignore[arg-type]
            agreed=False,
            policy_escape=False,
        )
    with pytest.raises(ShadowDwellEvidenceError, match="observation_agreement_unreviewed"):
        ShadowDwellObservation(
            target="rule.one",
            observed_at=_START,
            reviewed=False,
            agreed=True,
            policy_escape=False,
        )
    base_ev = ShadowDwellEvidence(
        target="rule.one",
        window_start=_START,
        window_end=_START + timedelta(days=20),
        sample_size=120,
        reviewed_count=120,
        agreed_count=120,
        policy_escapes=0,
    )
    assert evaluate_shadow_dwell(None, thresholds).gaps == ("no_shadow_dwell_evidence",)
    assert evaluate_shadow_dwell(base_ev, thresholds).eligible is True
    unreviewed_ev = ShadowDwellEvidence.from_mapping(
        {
            **base_ev.to_mapping(),
            "window_start": _START,
            "reviewed_count": 0,
            "agreed_count": 0,
        }
    )
    assert unreviewed_ev.accuracy == 0.0
    assert "no_reviewed_samples" in evaluate_shadow_dwell(unreviewed_ev, thresholds).gaps
    failing_ev = ShadowDwellEvidence(
        target="rule.one",
        window_start=_START,
        window_end=_START + timedelta(days=1),
        sample_size=10,
        reviewed_count=10,
        agreed_count=5,
        policy_escapes=1,
    )
    assert len(evaluate_shadow_dwell(failing_ev, thresholds).gaps) == 4
    with pytest.raises(ValueError, match="eligible exactly when no gap"):
        ShadowDwellDecision(eligible=True, gaps=("gap",))
    for bad_ev in (
        {"window_end": _START - timedelta(seconds=1)},
        {"sample_size": -1},
        {"sample_size": 1_000_001},
        {"reviewed_count": 121},
        {"agreed_count": 121},
        {"policy_escapes": 121},
        {"window_end": _START + timedelta(days=3651)},
        {"target": "BAD"},
        {"window_start": datetime(2026, 8, 29, 1)},  # noqa: DTZ001
    ):
        with pytest.raises(ShadowDwellEvidenceError):
            ShadowDwellEvidence(
                **{
                    **base_ev.to_mapping(),
                    "window_start": _START,
                    "window_end": _START + timedelta(days=20),
                    **bad_ev,
                }  # type: ignore[arg-type]
            )
    with pytest.raises(ShadowDwellEvidenceError, match="evidence_schema_invalid"):
        ShadowDwellEvidence.from_mapping("bad")
    for bad_map in (
        {"target": 123},
        {"window_start": "bad-date"},
        {"window_start": 123},
        {"window_end": "2026-08-29T01:00:00"},
        {"sample_size": True},
    ):
        with pytest.raises(ShadowDwellEvidenceError):
            ShadowDwellEvidence.from_mapping({**base_ev.to_mapping(), **bad_map})


def test_shadow_dwell_ledger_reviews_and_eviction_branches() -> None:
    with pytest.raises(ValueError, match="MUST be positive"):
        ShadowDwellLedger(max_targets=0)
    ledger = ShadowDwellLedger(max_targets=1, max_observations_per_target=1)
    with pytest.raises(TypeError):
        ledger.record("bad")  # type: ignore[arg-type]
    obs1 = ShadowDwellObservation(
        target="rule.one",
        observed_at=_START,
        reviewed=False,
        agreed=False,
        policy_escape=False,
    )
    with pytest.raises(ShadowDwellEvidenceError, match="observation_id_invalid"):
        ledger.record(obs1, observation_id="")
    assert ledger.record(obs1, observation_id="id-1") is True
    assert ledger.record(obs1, observation_id="id-1") is False
    assert ledger.record(obs1, observation_id="id-2") is True
    with pytest.raises(ShadowDwellEvidenceError, match="observation_agreed_invalid"):
        ledger.apply_review(target="rule.one", observation_id="id-2", agreed="yes")  # type: ignore[arg-type]
    assert ledger.apply_review(target="rule.missing", observation_id="id-2", agreed=True) is False
    assert ledger.apply_review(target="rule.one", observation_id="id-2", agreed=True) is True
    assert ledger.apply_review(target="rule.one", observation_id="id-2", agreed=True) is False
    ledger._targets["rule.one"].sample_size = 1_000_000
    assert ledger.record(obs1) is True
    ev = ledger.evidence_for("rule.one")
    assert ev is not None and ev.sample_size == 1_000_000
    assert ledger.observation_count("rule.one") == 1
    assert ledger.observation_count("rule.missing") == 0
    assert ledger.evidence_for("rule.missing") is None
    obs_escaped = ShadowDwellObservation(
        target="rule.two",
        observed_at=_START + timedelta(days=1),
        reviewed=True,
        agreed=True,
        policy_escape=True,
    )
    assert ledger.record(obs_escaped) is True
    assert ledger.targets() == ("rule.two",)
    with pytest.raises(
        ShadowDwellEvidenceError, match="target_capacity_exhausted_by_escaped_evidence"
    ):
        ledger.record(obs1)


def test_promotion_review_validation_and_development_authority_branches() -> None:
    (
        profile,
        source,
        _request,
        binding_val,
        confirmation,
        _grant,
        dev_ev,
        promotion_action,
    ) = _development_evidence()
    plain = replace(
        dev_ev,
        reviewer_principal="independent-reviewer",
        reviewer_role="independent_reviewer",
        development_confirmation=None,
        development_binding_verification=None,
        development_grant=None,
        development_binding_request=None,
    )
    binding = ReviewedReplayBinding(
        candidate_digest=plain.candidate_digest,
        package_digest=plain.package_digest,
        replay_first_digest=plain.replay_first_digest,
        replay_second_digest=plain.replay_second_digest,
        immutable_case_refs=("case-history:one:1:" + "4" * 64,),
        access_scope_digest="5" * 64,
        purpose="operational-learning",
    )
    bound_review = replace(plain, reviewed_replay_binding=binding)
    assert plain.reviewed_replay_digest != bound_review.reviewed_replay_digest
    assert plain.promotion_target_digest.startswith("sha256:")
    for bad in (
        {"action_type": "BAD"},
        {"action_type_version": ""},
        {"fdai_revision": "bad"},
        {"scenario_set_version": "BAD"},
        {"candidate_digest": "bad"},
        {"replay_second_digest": "9" * 64},
        {"reviewer_principal": "Norns"},
        {"approved": "yes"},
        {"reviewer_role": "invalid"},
        {"reviewer_role": "owner"},
        {"development_confirmation": confirmation},
    ):
        with pytest.raises(ValueError):
            replace(plain, **bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="does not match reviewed artifacts"):
        replace(bound_review, candidate_digest="9" * 64)
    with pytest.raises(ValueError, match="unique"):
        ReviewedReplayAuthority((plain, plain))
    with pytest.raises(ValueError, match="injected development profile"):
        ReviewedReplayAuthority((dev_ev,))
    alt_binding = _binding(
        profile,
        action_type=promotion_action.name,
        action_type_digest=binding_val.action_type_digest,
        action_id="promotion:other",
        target="registry:development:ops.restart-service",
        params={},
        idempotency_key="promotion-other",
    )
    with pytest.raises(ValueError, match="binding changed"):
        ReviewedReplayAuthority(
            (replace(dev_ev, development_binding_verification=_verification(alt_binding)),),
            development_profile=profile,
            development_binding_source=source,
            development_action_types={promotion_action.name: promotion_action},
            clock=lambda: NOW,
        )
    with pytest.raises(ValueError, match="does not match current ActionType"):
        ReviewedReplayAuthority(
            (dev_ev,),
            development_profile=profile,
            development_binding_source=source,
            development_action_types={},
            clock=lambda: NOW,
        )
    with pytest.raises(ValueError, match="does not match exact development authority"):
        ReviewedReplayAuthority(
            (replace(dev_ev, reviewer_principal="other-owner"),),
            development_profile=profile,
            development_binding_source=source,
            development_action_types={promotion_action.name: promotion_action},
            clock=lambda: NOW,
        )
    with pytest.raises(ValueError, match="unique"):
        ReviewedReplayAuthority(
            (dev_ev, dev_ev),
            development_profile=profile,
            development_binding_source=source,
            development_action_types={promotion_action.name: promotion_action},
            clock=lambda: NOW,
        )
    dev_auth = ReviewedReplayAuthority(
        (dev_ev,),
        development_profile=profile,
        development_binding_source=source,
        development_action_types={promotion_action.name: promotion_action},
        clock=lambda: NOW,
    )
    dev_args = {
        "profile_digest": profile.digest,
        "action_type": dev_ev.action_type,
        "action_type_version": dev_ev.action_type_version,
        "action_type_digest": dev_ev.action_type_digest,
        "fdai_revision": dev_ev.fdai_revision,
        "scenario_set_version": dev_ev.scenario_set_version,
        "evidence_digest": dev_ev.promotion_evidence_digest,
        "policy_digest": dev_ev.promotion_policy_digest,
    }
    assert dev_auth.accepts_development(**dev_args) is True
    assert dev_auth.review_attribution(**dev_args) is not None
    assert dev_auth.review_attribution(**{**dev_args, "profile_digest": "none"}) is None
    assert (
        dev_auth.authorize_development(
            profile_digest=profile.digest,
            action_type=_dev_action(),
            fdai_revision=dev_ev.fdai_revision,
            scenario_set_version=dev_ev.scenario_set_version,
            evidence_digest=dev_ev.promotion_evidence_digest,
            policy_digest=dev_ev.promotion_policy_digest,
            approved_at=NOW,
        )
        is not None
    )
    assert (
        dev_auth.authorize_development(
            profile_digest="none",
            action_type=_dev_action(),
            fdai_revision=dev_ev.fdai_revision,
            scenario_set_version=dev_ev.scenario_set_version,
            evidence_digest=dev_ev.promotion_evidence_digest,
            policy_digest=dev_ev.promotion_policy_digest,
            approved_at=NOW,
        )
        is None
    )
    base_receipt = _evaluator().evaluate(_promo_action(), _with_admission(_passing_batch()))
    dev_receipt = replace(
        base_receipt,
        action_type_version=dev_ev.action_type_version,
        action_type_digest=dev_ev.action_type_digest,
        fdai_revision=dev_ev.fdai_revision,
        scenario_set_version=dev_ev.scenario_set_version,
        evidence_digest=dev_ev.promotion_evidence_digest,
        policy_digest=dev_ev.promotion_policy_digest,
    )
    assert (
        ReviewedReplayReceiptVerifier(dev_auth).verify_development(
            profile_digest=profile.digest,
            action_type=_dev_action(),
            receipt=dev_receipt,
        )
        is True
    )
