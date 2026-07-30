from __future__ import annotations

from dataclasses import replace

from fdai.core.metering.budget import InMemoryBudgetLedger, ModelBudget
from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.tiers.t2_reasoning.recovery import (
    BoundedFailoverT2Proposer,
    T2AttemptReceipt,
    T2FailureClass,
    T2ProposerBudgetExhaustedError,
)
from fdai.core.tiers.t2_reasoning.tier import T2ProposalContext
from fdai.shared.contracts.models import Event, Mode


def _event() -> Event:
    return Event(
        schema_version="1.0.0",
        event_id="00000000-0000-0000-0000-000000000042",  # type: ignore[arg-type]
        idempotency_key="t2-recovery-event",
        source="example_detector",
        event_type="novel_anomaly",
        detected_at="2026-07-31T00:00:00Z",  # type: ignore[arg-type]
        ingested_at="2026-07-31T00:00:01Z",  # type: ignore[arg-type]
        mode=Mode.SHADOW,
        correlation_id="00000000-0000-0000-0000-000000000099",
    )


def _context() -> T2ProposalContext:
    return T2ProposalContext(
        event=_event(),
        target_resource_ref="resource:example/rg/x",
        target_resource_type="compute.vm",
        allowed_rules=(),
    )


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/x",
        params={"tag": "owner"},
        cited_rule_ids=("r1",),
        confidence_signals={"a": 0.9},
    )


class _StaticProposer:
    def __init__(
        self,
        result: QualityCandidate | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    async def propose(self, *, context: T2ProposalContext) -> QualityCandidate | None:
        del context
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class _Recorder:
    def __init__(self) -> None:
        self.receipts: list[T2AttemptReceipt] = []

    async def observe(self, receipt: T2AttemptReceipt) -> None:
        self.receipts.append(receipt)


class _Selector:
    def __init__(self, preferred: str = "secondary", error: Exception | None = None) -> None:
        self.preferred = preferred
        self.error = error
        self.available_routes: tuple[str, ...] = ()

    async def preferred_route(self, available_routes: tuple[str, ...]) -> str:
        self.available_routes = available_routes
        if self.error is not None:
            raise self.error
        return self.preferred


async def test_primary_failure_fails_over_and_records_sanitized_recovery() -> None:
    primary = _StaticProposer(error=RuntimeError("secret endpoint payload"))
    secondary = _StaticProposer(result=_candidate())
    recorder = _Recorder()
    proposer = BoundedFailoverT2Proposer(
        candidates=(("primary", primary), ("secondary", secondary)),
        observer=recorder,
    )
    ledger = InMemoryBudgetLedger(ModelBudget(max_calls_per_correlation=2, max_calls_total=2))

    result = await proposer.propose_with_budget(
        context=_context(),
        reserve_attempt=lambda: ledger.reserve("event", calls=1, cost_microusd=0),
    )

    assert result == _candidate()
    assert primary.calls == 1
    assert secondary.calls == 1
    assert [receipt.status for receipt in recorder.receipts] == ["failed", "succeeded"]
    assert recorder.receipts[0].failure_class is T2FailureClass.PROVIDER_ERROR
    assert recorder.receipts[0].terminal is False
    assert recorder.receipts[1].recovered is True
    assert all("secret" not in str(receipt.to_dict()) for receipt in recorder.receipts)


async def test_all_candidates_fail_once_and_terminal_receipt_is_bounded() -> None:
    first = _StaticProposer(error=TimeoutError("target detail"))
    second = _StaticProposer(error=ValueError("raw response detail"))
    recorder = _Recorder()
    proposer = BoundedFailoverT2Proposer(
        candidates=(("primary", first), ("secondary", second)),
        observer=recorder,
    )
    ledger = InMemoryBudgetLedger(ModelBudget(max_calls_per_correlation=2, max_calls_total=2))

    try:
        await proposer.propose_with_budget(
            context=_context(),
            reserve_attempt=lambda: ledger.reserve("event", calls=1, cost_microusd=0),
        )
    except RuntimeError as exc:
        assert str(exc) == "all bounded T2 proposer candidates failed"
    else:
        raise AssertionError("exhausted proposer must fail closed")

    assert first.calls == second.calls == 1
    assert [receipt.failure_class for receipt in recorder.receipts] == [
        T2FailureClass.TIMEOUT,
        T2FailureClass.INVALID_RESPONSE,
    ]
    assert recorder.receipts[-1].terminal is True
    assert recorder.receipts[-1].attempt == 2


async def test_budget_prevents_unreserved_failover_call() -> None:
    first = _StaticProposer(error=RuntimeError("provider down"))
    second = _StaticProposer(result=_candidate())
    recorder = _Recorder()
    proposer = BoundedFailoverT2Proposer(
        candidates=(("primary", first), ("secondary", second)),
        observer=recorder,
    )
    ledger = InMemoryBudgetLedger(ModelBudget(max_calls_per_correlation=1, max_calls_total=1))

    try:
        await proposer.propose_with_budget(
            context=_context(),
            reserve_attempt=lambda: ledger.reserve("event", calls=1, cost_microusd=0),
        )
    except T2ProposerBudgetExhaustedError:
        pass
    else:
        raise AssertionError("unreserved candidate must not run")

    assert first.calls == 1
    assert second.calls == 0
    assert recorder.receipts[-1].failure_class is T2FailureClass.BUDGET_EXHAUSTED
    assert recorder.receipts[-1].terminal is True


async def test_candidate_routes_must_be_unique_and_bounded() -> None:
    proposer = _StaticProposer(result=_candidate())
    for candidates in (
        (),
        (("same", proposer), ("same", proposer)),
        (("a", proposer), ("b", proposer), ("c", proposer)),
    ):
        try:
            BoundedFailoverT2Proposer(candidates=candidates)
        except ValueError:
            continue
        raise AssertionError(f"invalid candidates accepted: {candidates!r}")

    context = _context()
    changed = replace(context, target_resource_ref="resource:example/rg/y")
    assert changed.target_resource_ref.endswith("/y")


async def test_persistent_selector_moves_secondary_to_first_attempt() -> None:
    primary = _StaticProposer(error=RuntimeError("must not run"))
    secondary = _StaticProposer(result=_candidate())
    recorder = _Recorder()
    selector = _Selector()
    proposer = BoundedFailoverT2Proposer(
        candidates=(("primary", primary), ("secondary", secondary)),
        observer=recorder,
        route_selector=selector,
    )
    ledger = InMemoryBudgetLedger(ModelBudget(max_calls_per_correlation=1, max_calls_total=1))

    result = await proposer.propose_with_budget(
        context=_context(),
        reserve_attempt=lambda: ledger.reserve("event", calls=1, cost_microusd=0),
    )

    assert result == _candidate()
    assert selector.available_routes == ("primary", "secondary")
    assert secondary.calls == 1
    assert primary.calls == 0
    assert recorder.receipts[0].route_ref == "secondary"
    assert recorder.receipts[0].attempt == 1


async def test_selector_failure_retains_primary_first_bounded_failover() -> None:
    primary = _StaticProposer(result=_candidate())
    secondary = _StaticProposer(error=RuntimeError("must not run"))
    proposer = BoundedFailoverT2Proposer(
        candidates=(("primary", primary), ("secondary", secondary)),
        route_selector=_Selector(error=RuntimeError("state store unavailable")),
    )
    ledger = InMemoryBudgetLedger(ModelBudget(max_calls_per_correlation=1, max_calls_total=1))

    result = await proposer.propose_with_budget(
        context=_context(),
        reserve_attempt=lambda: ledger.reserve("event", calls=1, cost_microusd=0),
    )

    assert result == _candidate()
    assert primary.calls == 1
    assert secondary.calls == 0


async def test_failover_abstention_is_terminal_but_not_recovered() -> None:
    primary = _StaticProposer(error=RuntimeError("provider down"))
    secondary = _StaticProposer(result=None)
    recorder = _Recorder()
    proposer = BoundedFailoverT2Proposer(
        candidates=(("primary", primary), ("secondary", secondary)),
        observer=recorder,
    )
    ledger = InMemoryBudgetLedger(ModelBudget(max_calls_per_correlation=2, max_calls_total=2))

    result = await proposer.propose_with_budget(
        context=_context(),
        reserve_attempt=lambda: ledger.reserve("event", calls=1, cost_microusd=0),
    )

    assert result is None
    assert recorder.receipts[-1].status == "abstained"
    assert recorder.receipts[-1].terminal is True
    assert recorder.receipts[-1].recovered is False
