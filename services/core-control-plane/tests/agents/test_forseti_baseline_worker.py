from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents._framework.forseti_baseline_evaluation import (
    BASELINE_EVALUATION_COMPLETION_PREFIX,
)
from fdai.agents._framework.forseti_baseline_worker import (
    BASELINE_EVALUATION_CLAIM_PREFIX,
    BASELINE_EVALUATION_COVERAGE_PREFIX,
    BASELINE_EVALUATION_STATUS_KEY,
    BaselineWorkerLimits,
    BaselineWorkerResult,
    ForsetiBaselineScheduler,
    ForsetiBaselineWorker,
)
from fdai.agents.forseti import Forseti
from fdai.core.rule_activation.generation import build_rule_activation_generation
from fdai.core.tiers.t0_deterministic import (
    PolicyResult,
    RuleGenerationSnapshot,
    RuleIndex,
    T0Engine,
)
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)
from fdai.shared.providers.inventory import (
    PromotedInventoryGeneration,
    PromotedInventoryGenerationLimitError,
    ResourceRecord,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.baseline_evaluation import BaselineEvaluationCoverage
from fdai_service_contracts.rule_activation import RuleActivationGeneration

NOW = datetime(2026, 10, 2, tzinfo=UTC)


class _Evaluator:
    def __init__(self, results: Mapping[str, PolicyResult | None]) -> None:
        self.results = dict(results)

    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult | None:
        del resource_props
        return self.results.get(rule.id)


class _Reader:
    def __init__(self, generation: PromotedInventoryGeneration | None | Exception) -> None:
        self.generation = generation
        self.calls = 0

    async def active_generation_id(self) -> str | None:
        if isinstance(self.generation, PromotedInventoryGeneration):
            return self.generation.generation
        return None if self.generation is None else "generation-x"

    async def load_active_generation(self, *, max_resources: int) -> PromotedInventoryGeneration:
        del max_resources
        self.calls += 1
        if isinstance(self.generation, Exception):
            raise self.generation
        return self.generation  # type: ignore[return-value]


class _AuditingStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.audit: list[dict[str, Any]] = []

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        self.audit.append(dict(entry))


def _rule(rule_id: str, *, resource_type: str = "example.resource") -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type=resource_type,
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/example.rego"),
        remediation=Remediation(template_ref="remediation/example.tftpl"),
        remediates="remediate.example",
        triggered_by=["inventory.resource_observed"],
        provenance=Provenance(
            source_url="https://example.com/rule",
            resolved_ref="0" * 40,
            content_hash="sha256:example",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at=NOW,
        ),
    )


RULES = (_rule("rule.compliant"), _rule("rule.violated"), _rule("rule.other", resource_type="x"))
RESULTS = {
    "rule.compliant": PolicyResult(denied=False, context={}),
    "rule.violated": PolicyResult(denied=True, context={"deny_reason": "x"}),
}


def _activation(rules: tuple[Rule, ...] = RULES) -> RuleActivationGeneration:
    return build_rule_activation_generation(
        rules, profile_id="baseline-test", profile_version="1.0.0", created_at=NOW
    )


def _generation(*resources: ResourceRecord) -> PromotedInventoryGeneration:
    return PromotedInventoryGeneration(
        generation="generation-1",
        resources=resources
        or (
            ResourceRecord(
                resource_id="resource-one",
                type="example.resource",
                props={"ready": True},
                last_seen=NOW.isoformat(),
            ),
        ),
        complete=True,
        recorded_at=NOW,
    )


def _worker(
    store: InMemoryStateStore,
    *,
    reader: _Reader | None = None,
    activation: RuleActivationGeneration | None = None,
    snapshot_rules: tuple[Rule, ...] = RULES,
    snapshot_digest: str | None = None,
    clock: list[datetime] | None = None,
    owner: str = "forseti-a",
    limits: BaselineWorkerLimits | None = None,
) -> ForsetiBaselineWorker:
    pinned = activation if activation is not None else _activation()
    engine = T0Engine(index=RuleIndex.build(snapshot_rules), evaluator=_Evaluator(RESULTS))
    times = clock if clock is not None else [NOW]

    async def activation_source() -> RuleActivationGeneration:
        return pinned

    async def snapshot_source() -> RuleGenerationSnapshot:
        return RuleGenerationSnapshot(
            engine=engine,
            rules=snapshot_rules,
            generation_digest=snapshot_digest or pinned.generation_digest,
        )

    return ForsetiBaselineWorker(
        state_store=store,
        reader=reader or _Reader(_generation()),
        activation_source=activation_source,
        rule_snapshot_source=snapshot_source,
        owner=owner,
        clock=lambda: times[0],
        limits=limits,
    )


async def _coverage(store: InMemoryStateStore) -> BaselineEvaluationCoverage:
    rows, total = await store.read_state_page(prefix=BASELINE_EVALUATION_COVERAGE_PREFIX, limit=10)
    assert total == 1
    return BaselineEvaluationCoverage.model_validate(rows[0])


@pytest.mark.asyncio
async def test_run_records_complete_coverage_with_dispatch_denominator() -> None:
    store = _AuditingStore()

    result = await _worker(store).run_once()

    assert result is BaselineWorkerResult.COMPLETED
    coverage = await _coverage(store)
    assert coverage.complete is True
    assert coverage.expected_pair_count == 2
    assert coverage.covered_pair_count == 2
    assert coverage.compliant_count == 1
    assert coverage.violated_count == 1
    assert coverage.limitations == ()
    assert coverage.execution_authority is False
    assert coverage.dispatch_signal == "inventory.resource_observed"
    assert [entry["action_kind"] for entry in store.audit] == [
        "baseline_evaluation.started",
        "baseline_evaluation.coverage",
    ]
    assert all(entry["producer_principal"] == "Forseti" for entry in store.audit)
    assert coverage.audit_ref == store.audit[-1]["audit_ref"]
    _, completions = await store.read_state_page(
        prefix=BASELINE_EVALUATION_COMPLETION_PREFIX, limit=10
    )
    assert completions == 1


@pytest.mark.asyncio
async def test_second_run_is_already_completed_without_duplicate_audit() -> None:
    store = _AuditingStore()
    worker = _worker(store)

    assert await worker.run_once() is BaselineWorkerResult.COMPLETED
    assert await worker.run_once() is BaselineWorkerResult.UNCHANGED
    assert await _worker(store).run_once() is BaselineWorkerResult.ALREADY_COMPLETED

    assert len(store.audit) == 2
    status = await store.read_state(BASELINE_EVALUATION_STATUS_KEY)
    assert status is not None
    assert status["result"] == "already_completed"
    assert status["inventory_generation"] == "generation-1"
    assert status["execution_authority"] is False


@pytest.mark.asyncio
async def test_unchanged_generation_skips_the_full_inventory_read() -> None:
    store = _AuditingStore()
    reader = _Reader(_generation())
    worker = _worker(store, reader=reader)

    await worker.run_once()
    await worker.run_once()

    assert reader.calls == 1


@pytest.mark.asyncio
async def test_live_claim_held_elsewhere_is_not_taken_over() -> None:
    store = _AuditingStore()
    clock = [NOW]
    first = _worker(store, clock=clock, owner="forseti-a")
    claim_key = await _seed_claim(store, first, clock)

    result = await _worker(store, clock=clock, owner="forseti-b").run_once()

    assert result is BaselineWorkerResult.CLAIMED_ELSEWHERE
    claim = await store.read_state(claim_key)
    assert claim is not None and claim["owner"] == "forseti-a"


@pytest.mark.asyncio
async def test_stale_claim_is_resumed_with_pinned_evaluation_time() -> None:
    store = _AuditingStore()
    clock = [NOW]
    first = _worker(store, clock=clock, owner="forseti-a")
    claim_key = await _seed_claim(store, first, clock)
    clock[0] = NOW + timedelta(hours=2)

    result = await _worker(store, clock=clock, owner="forseti-b").run_once()

    assert result is BaselineWorkerResult.COMPLETED
    claim = await store.read_state(claim_key)
    assert claim is not None
    assert claim["status"] == "completed"
    assert claim["owner"] == "forseti-b"
    assert claim["evaluated_at"] == NOW.isoformat()
    assert store.audit[0]["action_kind"] == "baseline_evaluation.resumed"
    coverage = await _coverage(store)
    assert coverage.completed_at == NOW


async def _seed_claim(
    store: InMemoryStateStore, worker: ForsetiBaselineWorker, clock: list[datetime]
) -> str:
    activation = _activation()
    from fdai.agents._framework.forseti_baseline_evaluation import (
        baseline_inventory_observation_digest,
    )
    from fdai.agents._framework.forseti_baseline_worker import baseline_claim_key

    key = baseline_claim_key(
        inventory_observation_digest=baseline_inventory_observation_digest(_generation()),
        activation_digest=activation.generation_digest,
    )
    claim, refused = await worker._claim(  # noqa: SLF001 - exercise the atomic claim directly
        key,
        baseline_inventory_observation_digest(_generation()),
        activation,
    )
    assert refused is None and claim is not None
    del clock
    return key


@pytest.mark.asyncio
async def test_activation_drift_is_refused_before_reading_inventory() -> None:
    store = _AuditingStore()
    reader = _Reader(_generation())

    result = await _worker(store, reader=reader, snapshot_rules=RULES[:2]).run_once()

    assert result is BaselineWorkerResult.ACTIVATION_DRIFT
    assert reader.calls == 0
    assert store.audit == []


@pytest.mark.asyncio
async def test_snapshot_without_activation_digest_is_drift() -> None:
    store = _AuditingStore()
    worker = _worker(store, snapshot_digest="0" * 64)

    assert await worker.run_once() is BaselineWorkerResult.ACTIVATION_DRIFT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("generation", "expected"),
    [
        (None, BaselineWorkerResult.NO_GENERATION),
        (
            PromotedInventoryGenerationLimitError("too many"),
            BaselineWorkerResult.GENERATION_TOO_LARGE,
        ),
        (
            PromotedInventoryGeneration(
                generation="g", resources=(), complete=False, recorded_at=NOW
            ),
            BaselineWorkerResult.GENERATION_UNAVAILABLE,
        ),
    ],
)
async def test_unusable_generation_writes_nothing(
    generation: PromotedInventoryGeneration | None | Exception,
    expected: BaselineWorkerResult,
) -> None:
    store = _AuditingStore()

    result = await _worker(store, reader=_Reader(generation)).run_once()

    assert result is expected
    assert store.audit == []
    _, claims = await store.read_state_page(prefix=BASELINE_EVALUATION_CLAIM_PREFIX, limit=10)
    assert claims == 0
    status = await store.read_state(BASELINE_EVALUATION_STATUS_KEY)
    assert status is not None and status["result"] == expected.value


@pytest.mark.asyncio
async def test_missing_activation_is_unavailable() -> None:
    store = _AuditingStore()
    worker = _worker(store)

    async def none_source() -> None:
        return None

    worker._activation_source = none_source  # noqa: SLF001

    assert await worker.run_once() is BaselineWorkerResult.ACTIVATION_UNAVAILABLE


@pytest.mark.asyncio
async def test_scheduler_runs_once_per_interval_from_forseti_tick() -> None:
    store = _AuditingStore()
    clock = [NOW]
    results: list[str] = []
    scheduler = ForsetiBaselineScheduler(
        _worker(store, clock=clock),
        interval_seconds=300,
        clock=lambda: clock[0],
        on_result=results.append,
    )
    forseti = Forseti(state_store=store, test_context_clock=lambda: clock[0])
    forseti.bind_baseline_scheduler(scheduler)

    await forseti.maintenance_tick()
    await forseti.maintenance_tick()
    while scheduler.running:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0)

    assert results == ["completed"]
    clock[0] = NOW + timedelta(seconds=301)
    assert scheduler.tick() is True
    while scheduler.running:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0)
    assert results == ["completed", "unchanged"]


def test_limits_reject_lease_shorter_than_deadline() -> None:
    with pytest.raises(ValueError, match="lease"):
        BaselineWorkerLimits(deadline_seconds=60, claim_lease_seconds=30)
