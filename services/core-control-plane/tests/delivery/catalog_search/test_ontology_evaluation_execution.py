"""One bounded diagnostic includes document preparation without enabling runtime search."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime

import httpx
import pytest
from fdai.delivery.catalog_search.ontology_evaluation_execution import (
    OntologyRetrievalExecutionAbortedError,
    OntologyRetrievalExecutionBudget,
    OntologyRetrievalExecutionReport,
    _BudgetedEmbedder,
    execute_ontology_retrieval_campaign,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.delivery.catalog_search.test_ontology_evaluation import _POLICY, _TYPES, _cases
from tests.delivery.catalog_search.test_ontology_evaluation_campaign import _calibration, _plan
from tests.delivery.catalog_search.test_ontology_evaluation_runner import (
    _RANKING,
    _Embedder,
    _Harness,
    _harness,
)

_BUDGET = OntologyRetrievalExecutionBudget(32, 3, 1)


class _BoundEmbedder(_Embedder):
    embedding_space_id = "test-space"
    embedding_model_version = "test-model-v1"
    dim = 4

    def __init__(self) -> None:
        super().__init__(_calibration())


async def _execute(
    harness: _Harness,
    embedder: _BoundEmbedder,
    *,
    budget: OntologyRetrievalExecutionBudget = _BUDGET,
    expected: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> OntologyRetrievalExecutionReport:
    return await execute_ontology_retrieval_campaign(
        expected_binding_digest=expected or _plan(harness).binding_digest,
        build=harness.build,
        manifest=harness.manifest,
        calibration_cases=_calibration(),
        holdout_cases=_cases(),
        ranking_policy=_RANKING,
        evaluation_policy=_POLICY,
        required_object_types=_TYPES,
        state=InMemoryStateStore(),
        gateway=harness.gateway,
        source_generation=harness.staged.source_generation,
        embedder=embedder,
        clock=(lambda: harness.clock.now) if clock is None else clock,
        budget=budget,
    )


async def test_counts_document_and_query_calls_without_production_authority() -> None:
    harness = await _harness()
    embedder = _BoundEmbedder()
    report = await _execute(harness, embedder)
    assert report.campaign.passed
    assert report.embedding_calls == embedder.calls == 32
    assert report.budget == _BUDGET
    assert 0 < report.elapsed_seconds < _BUDGET.total_timeout_seconds
    assert report.production_qualification is report.execution_authority is False
    assert report.campaign.production_qualification is False
    assert harness.embedder.calls == 0


@pytest.mark.parametrize("invalid", ["binding", "call-budget", "model", "space", "dimension"])
async def test_preflight_denies_drift_and_insufficient_budget_before_provider(invalid: str) -> None:
    harness = await _harness()
    embedder = _BoundEmbedder()
    expected = "sha256:" + "0" * 64 if invalid == "binding" else None
    budget = replace(_BUDGET, max_embedding_calls=31) if invalid == "call-budget" else _BUDGET
    if invalid == "model":
        embedder.embedding_model_version = "changed"
    elif invalid == "space":
        embedder.embedding_space_id = "changed"
    elif invalid == "dimension":
        embedder.dim = 3
    with pytest.raises(ValueError):
        await _execute(harness, embedder, budget=budget, expected=expected)
    assert embedder.calls == 0


@pytest.mark.parametrize(
    "values",
    [
        (0, 1, 1),
        (129, 1, 1),
        (True, 1, 1),
        (32, 601, 1),
        (32, 10, 6),
        (32, float("nan"), 1),
        (32, 2, float("inf")),
        (32, 0, 0),
    ],
)
def test_rejects_unbounded_execution_budget(values: tuple[int, float, float]) -> None:
    with pytest.raises(ValueError, match="bounded calls and deadlines"):
        OntologyRetrievalExecutionBudget(*values)


async def test_source_drift_is_rejected_before_document_embeddings() -> None:
    harness = await _harness()
    assert await harness.store.delete_object("incident-0")
    embedder = _BoundEmbedder()
    with pytest.raises(OntologyRetrievalExecutionAbortedError) as failure:
        await _execute(harness, embedder)
    assert failure.value.stage == "preparation"
    assert failure.value.embedding_calls == embedder.calls == 0


@pytest.mark.parametrize("call", [2, 8, 14])
async def test_provider_abort_preserves_counts_and_partial_campaign(call: int) -> None:
    harness = await _harness()
    embedder = _BoundEmbedder()
    embedder.fail_on_call = call
    with pytest.raises(OntologyRetrievalExecutionAbortedError) as failure:
        await _execute(harness, embedder)
    assert failure.value.embedding_calls == embedder.calls == call
    assert "private" not in str(failure.value)
    nested = failure.value.campaign_failure
    if call == 2:
        assert failure.value.stage == "preparation"
        assert nested is None
    else:
        assert failure.value.stage == "measurement"
        assert nested is not None
        assert nested.stage == ("calibration" if call == 8 else "holdout")
        assert (nested.calibration is not None) == (call == 14)
        assert len(nested.completed) == 1


@pytest.mark.parametrize("status", [429, 503])
async def test_http_failure_is_counted_once_without_retry_or_raw_details(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    harness = await _harness()
    embedder = _BoundEmbedder()

    async def fail(_text: str) -> Sequence[float]:
        embedder.calls += 1
        response = httpx.Response(status, request=httpx.Request("POST", "https://example.com"))
        raise httpx.HTTPStatusError(
            "private-provider-error", request=response.request, response=response
        )

    monkeypatch.setattr(embedder, "embed", fail)
    with pytest.raises(OntologyRetrievalExecutionAbortedError) as failure:
        await _execute(harness, embedder)
    assert failure.value.embedding_calls == embedder.calls == 1
    assert "private" not in str(failure.value)


async def test_failed_calibration_spends_no_holdout_calls() -> None:
    harness = await _harness()
    embedder = _BoundEmbedder()
    embedder.wrong = True
    report = await _execute(harness, embedder)
    assert not report.campaign.passed
    assert report.campaign.holdout is None
    assert report.embedding_calls == embedder.calls == 12


async def test_preparation_calibration_and_holdout_share_the_enclosing_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness()
    deadlines: list[float | None] = []
    original = asyncio.timeout_at

    def record_deadline(when: float | None) -> asyncio.Timeout:
        deadlines.append(when)
        return original(when)

    monkeypatch.setattr(asyncio, "timeout_at", record_deadline)
    assert (await _execute(harness, _BoundEmbedder())).campaign.passed
    enclosing = deadlines[0]
    assert enclosing is not None
    assert all(value is not None and value <= enclosing for value in deadlines)
    assert deadlines.count(enclosing) == 3


async def test_stalled_preparation_stops_at_the_call_deadline() -> None:
    harness = await _harness()
    embedder = _BoundEmbedder()
    embedder.stall = True
    with pytest.raises(OntologyRetrievalExecutionAbortedError) as failure:
        await _execute(harness, embedder, budget=replace(_BUDGET, call_timeout_seconds=0.01))
    assert failure.value.stage == "preparation"
    assert failure.value.embedding_calls == embedder.calls == 1


async def test_source_drift_during_preparation_cannot_open_calibration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness()
    embedder = _BoundEmbedder()
    original = embedder.embed

    async def change(text: str) -> Sequence[float]:
        vector = await original(text)
        if embedder.calls == 2:
            assert await harness.store.delete_object("incident-0")
        return vector

    monkeypatch.setattr(embedder, "embed", change)
    with pytest.raises(OntologyRetrievalExecutionAbortedError) as failure:
        await _execute(harness, embedder)
    assert failure.value.stage == "preparation"
    assert failure.value.embedding_calls == embedder.calls == 6


@pytest.mark.parametrize("drift", ["deadline", "identity"])
async def test_non_yielding_provider_cannot_overrun_or_change_model(
    monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    harness = await _harness()
    embedder = _BoundEmbedder()
    loop = asyncio.get_running_loop()
    original_time, original_embed = loop.time, embedder.embed
    offset = 0.0

    async def change(text: str) -> Sequence[float]:
        nonlocal offset
        vector = await original_embed(text)
        if drift == "deadline":
            offset = 6.0
        else:
            embedder.embedding_model_version = "changed"
        return vector

    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)
    monkeypatch.setattr(embedder, "embed", change)
    with pytest.raises(OntologyRetrievalExecutionAbortedError) as failure:
        await _execute(harness, embedder, budget=OntologyRetrievalExecutionBudget(32, 600, 5))
    assert failure.value.embedding_calls == embedder.calls == 1


@pytest.mark.parametrize("limit", [1, 128])
async def test_call_limit_is_enforced_before_an_unexpected_extra_dispatch(limit: int) -> None:
    harness = await _harness()
    embedder = _BoundEmbedder()
    bounded = _BudgetedEmbedder(
        embedder,
        build=harness.build,
        budget=replace(_BUDGET, max_embedding_calls=limit),
        deadline=asyncio.get_running_loop().time() + 3,
    )
    for _ in range(limit):
        await bounded.embed(_calibration()[0].query)
    with pytest.raises(ValueError, match="call budget exhausted"):
        await bounded.embed(_calibration()[0].query)
    assert bounded.calls == embedder.calls == limit


async def test_final_identity_drift_aborts_but_preserves_completed_measurements() -> None:
    harness = await _harness()
    embedder = _BoundEmbedder()

    def change_after_final_call() -> datetime:
        if embedder.calls == 32:
            embedder.embedding_model_version = "changed"
        return harness.clock.now

    with pytest.raises(OntologyRetrievalExecutionAbortedError) as failure:
        await _execute(harness, embedder, clock=change_after_final_call)
    assert failure.value.stage == "measurement"
    assert failure.value.embedding_calls == 32
    completed = failure.value.completed_campaign
    assert completed is not None
    assert completed.calibration.passed
    assert completed.holdout is not None
    assert len(completed.holdout.measurements) == 20


async def test_parent_cancellation_during_preparation_propagates() -> None:
    harness = await _harness()
    embedder = _BoundEmbedder()
    embedder.stall = True
    task = asyncio.create_task(_execute(harness, embedder))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert embedder.calls == 1


async def test_preparation_deadline_stops_non_yielding_calls_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness()
    embedder = _BoundEmbedder()
    loop = asyncio.get_running_loop()
    original_time, original_embed = loop.time, embedder.embed
    offset = 0.0

    def slow_clock() -> datetime:
        nonlocal offset
        if offset == 0:
            offset = 119.0
        return harness.clock.now

    async def slow_embedding(text: str) -> Sequence[float]:
        nonlocal offset
        vector = await original_embed(text)
        offset += 2.0
        return vector

    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)
    monkeypatch.setattr(embedder, "embed", slow_embedding)
    with pytest.raises(OntologyRetrievalExecutionAbortedError) as failure:
        await _execute(
            harness, embedder, budget=OntologyRetrievalExecutionBudget(32, 600, 5), clock=slow_clock
        )
    assert failure.value.stage == "preparation"
    assert failure.value.embedding_calls == embedder.calls == 1
