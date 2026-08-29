from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
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
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

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
