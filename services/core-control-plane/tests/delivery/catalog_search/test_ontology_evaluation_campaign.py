"""Calibration is a bounded prerequisite, not a substitute for held-out quality evidence."""

import asyncio
from dataclasses import replace

import pytest
from fdai.delivery.catalog_search.ontology_evaluation import OntologyRetrievalEvaluationCase
from fdai.delivery.catalog_search.ontology_evaluation_campaign import (
    OntologyRetrievalCampaignAbortedError,
    OntologyRetrievalCampaignPlan,
    OntologyRetrievalCampaignReport,
    prepare_ontology_retrieval_campaign,
    run_ontology_retrieval_campaign,
)
from fdai.delivery.catalog_search.ranking import CatalogRankingPolicy
from tests.delivery.catalog_search.test_ontology_evaluation import _POLICY, _TYPES, _cases
from tests.delivery.catalog_search.test_ontology_evaluation_runner import (
    _RANKING,
    _Harness,
    _harness,
)


def _calibration() -> tuple[OntologyRetrievalEvaluationCase, ...]:
    return tuple(
        replace(item, case_id=f"cal-{item.case_id}", query=f"Calibration {item.query}")
        for item in _cases()
        if (item.cohort.endswith("-negative") and item.case_id.endswith("-0"))
        or (item.cohort.endswith("-positive") and item.case_id.endswith(("-0", "-2")))
    )


def _plan(
    harness: _Harness,
    *,
    calibration: tuple[OntologyRetrievalEvaluationCase, ...] | None = None,
    holdout: tuple[OntologyRetrievalEvaluationCase, ...] | None = None,
    ranking: CatalogRankingPolicy = _RANKING,
    calibration_only: bool = False,
) -> OntologyRetrievalCampaignPlan:
    return prepare_ontology_retrieval_campaign(
        build=harness.build,
        manifest=harness.manifest,
        calibration_cases=_calibration() if calibration is None else calibration,
        holdout_cases=_cases() if holdout is None else holdout,
        ranking_policy=ranking,
        evaluation_policy=_POLICY,
        required_object_types=_TYPES,
        calibration_only=calibration_only,
    )


async def _run(
    harness: _Harness,
    *,
    expected: str | None = None,
    timeout: float = 1,
    query_timeout: float | None = None,
    deadline: float | None = None,
) -> OntologyRetrievalCampaignReport:
    return await run_ontology_retrieval_campaign(
        expected_binding_digest=expected or _plan(harness).binding_digest,
        build=harness.build,
        manifest=harness.manifest,
        calibration_cases=_calibration(),
        holdout_cases=_cases(),
        ranking_policy=_RANKING,
        evaluation_policy=_POLICY,
        required_object_types=_TYPES,
        reader=harness.reader,
        snapshots=harness.snapshots,
        staged=harness.staged,
        gateway=harness.gateway,
        clock=lambda: harness.clock.now,
        total_timeout_seconds=timeout,
        query_timeout_seconds=timeout if query_timeout is None else query_timeout,
        deadline=deadline,
    )


async def test_calibration_and_holdout_use_same_reader_without_qualification() -> None:
    harness = await _harness(extra_cases=_calibration())
    plan = _plan(harness)
    report = await _run(harness)
    assert report.passed
    assert report.binding_digest == plan.binding_digest
    assert report.calibration.stage == "calibration"
    assert report.calibration.binding_digest == plan.calibration_binding_digest
    assert len(report.calibration.measurements) == 6
    assert report.holdout is not None
    assert report.holdout.stage == "holdout"
    assert report.holdout.binding_digest == plan.holdout_binding_digest
    assert len(report.holdout.measurements) == 20
    assert harness.embedder.calls == 26
    assert plan.embedding_call_upper_bound == 32
    assert report.production_qualification is report.execution_authority is False
    assert report.calibration.production_qualification is False
    assert report.holdout.production_qualification is False
    assert report.digest != replace(report, holdout=None).digest


async def test_standalone_calibration_has_no_holdout_and_binds_its_exact_order() -> None:
    harness = await _harness()
    plan = _plan(harness, calibration=_cases(), holdout=(), calibration_only=True)
    assert plan.holdout_binding_digest is None
    assert plan.embedding_call_upper_bound == len(harness.build.documents) + len(_cases())
    assert plan != _plan(
        harness, calibration=tuple(reversed(_cases())), holdout=(), calibration_only=True
    )
    report = await run_ontology_retrieval_campaign(
        expected_binding_digest=plan.binding_digest,
        build=harness.build,
        manifest=harness.manifest,
        calibration_cases=_cases(),
        holdout_cases=(),
        ranking_policy=_RANKING,
        evaluation_policy=_POLICY,
        required_object_types=_TYPES,
        reader=harness.reader,
        snapshots=harness.snapshots,
        staged=harness.staged,
        gateway=harness.gateway,
        clock=lambda: harness.clock.now,
        total_timeout_seconds=1,
        query_timeout_seconds=1,
        calibration_only=True,
    )
    assert report.calibration.passed
    assert report.calibration.stage == "calibration"
    assert len(report.calibration.measurements) == len(_cases())
    assert report.holdout is None
    assert not report.passed
    assert report.production_qualification is False


@pytest.mark.parametrize("mutation", ["holdout", "missing-cohort", "sample-floor"])
async def test_standalone_calibration_cannot_bypass_floors_or_open_a_holdout(
    mutation: str,
) -> None:
    harness = await _harness()
    cases = _cases()
    if mutation == "missing-cohort":
        cases = tuple(item for item in cases if item.cohort != "en-negative")
    elif mutation == "sample-floor":
        cases = cases[1:]
    with pytest.raises(ValueError):
        _plan(
            harness,
            calibration=cases,
            holdout=_cases() if mutation == "holdout" else (),
            calibration_only=True,
        )
    assert harness.embedder.calls == 0


async def test_campaign_binds_order_labels_and_policy_before_any_query() -> None:
    harness = await _harness(extra_cases=_calibration())
    plan = _plan(harness)
    assert _plan(harness, calibration=tuple(reversed(_calibration()))) != plan
    assert _plan(harness, holdout=tuple(reversed(_cases()))) != plan
    assert _plan(harness, ranking=replace(_RANKING, minimum_score=0.6)) != plan
    calibration = tuple(
        replace(item, expected_document_ids=(item.expected_document_ids[0][:-1] + "1",))
        if item.expected_document_ids
        else item
        for item in _calibration()
    )
    assert _plan(harness, calibration=calibration) != plan
    with pytest.raises(ValueError, match="frozen input binding changed"):
        await _run(harness, expected="sha256:" + "c" * 64)
    assert harness.embedder.calls == 0


@pytest.mark.parametrize(
    "mutation",
    ["empty", "overlap", "stage-id", "duplicate", "oracle", "locale", "type", "no-match"],
)
async def test_invalid_calibration_fails_before_calls(mutation: str) -> None:
    harness = await _harness(extra_cases=_calibration())
    cases = list(_calibration())
    if mutation == "empty":
        cases = []
    elif mutation == "overlap":
        cases[0] = replace(cases[0], query=_cases()[0].query.upper())
    elif mutation == "stage-id":
        cases[0] = replace(cases[0], case_id=_cases()[0].case_id)
    elif mutation == "duplicate":
        cases.append(cases[0])
    elif mutation == "oracle":
        cases[1] = replace(cases[1], expected_document_ids=("object:Resource:missing",))
    elif mutation == "locale":
        cases = [item for item in cases if item.cohort.startswith("en-")]
    elif mutation == "type":
        cases = [
            item
            for item in cases
            if not any("Resource" in target for target in item.expected_document_ids)
        ]
    else:
        cases = [item for item in cases if item.expected_document_ids]
    with pytest.raises(ValueError):
        _plan(harness, calibration=tuple(cases))
    assert harness.embedder.calls == 0


async def test_calibration_cannot_replace_missing_holdout_cohort_or_floor() -> None:
    harness = await _harness(extra_cases=_calibration())
    with pytest.raises(ValueError, match="missing a required cohort"):
        _plan(harness, holdout=tuple(item for item in _cases() if item.cohort != "en-negative"))
    with pytest.raises(ValueError, match="per-cohort metric sample floor"):
        _plan(harness, holdout=_cases()[1:])
    assert harness.embedder.calls == 0


async def test_failed_calibration_never_opens_holdout() -> None:
    harness = await _harness(extra_cases=_calibration())
    harness.embedder.wrong = True
    report = await _run(harness)
    assert not report.passed
    assert not report.calibration.passed
    assert report.holdout is None
    assert harness.embedder.calls == 6


@pytest.mark.parametrize("call", [2, 8])
async def test_provider_failure_retains_completed_stage_and_stops(call: int) -> None:
    harness = await _harness(extra_cases=_calibration())
    harness.embedder.fail_on_call = call
    with pytest.raises(OntologyRetrievalCampaignAbortedError) as failure:
        await _run(harness)
    assert failure.value.stage == ("calibration" if call == 2 else "holdout")
    assert (failure.value.calibration is not None) == (call == 8)
    assert len(failure.value.completed) == 1
    assert harness.embedder.calls == call
    assert "private" not in str(failure.value)


async def test_policy_drift_between_stages_aborts_before_holdout_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness(extra_cases=_calibration())
    original = harness.embedder.embed

    async def change_policy(text: str) -> tuple[float, ...]:
        vector = await original(text)
        if harness.embedder.calls == 6:
            monkeypatch.setattr(harness.reader, "_policy", replace(_RANKING, minimum_score=0.6))
        return vector

    monkeypatch.setattr(harness.embedder, "embed", change_policy)
    with pytest.raises(OntologyRetrievalCampaignAbortedError) as failure:
        await _run(harness)
    assert failure.value.stage == "holdout"
    assert failure.value.calibration is not None
    assert failure.value.completed == ()
    assert harness.embedder.calls == 6


async def test_deadline_is_not_reset_for_holdout(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = await _harness(extra_cases=_calibration())
    deadlines: list[float | None] = []
    original = asyncio.timeout_at

    def record_deadline(when: float | None) -> asyncio.Timeout:
        deadlines.append(when)
        return original(when)

    monkeypatch.setattr(asyncio, "timeout_at", record_deadline)
    assert (await _run(harness)).passed
    assert len(deadlines) == 2
    assert deadlines[0] == deadlines[1]


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), float("-inf")])
async def test_nonfinite_enclosing_deadline_is_rejected_without_query(deadline: float) -> None:
    harness = await _harness(extra_cases=_calibration())
    with pytest.raises(ValueError, match="finite enclosing deadline"):
        await _run(harness, deadline=deadline)
    assert harness.embedder.calls == 0


async def test_expired_enclosing_deadline_cannot_be_renewed_by_local_timeout() -> None:
    harness = await _harness(extra_cases=_calibration())
    with pytest.raises(OntologyRetrievalCampaignAbortedError) as failure:
        await _run(harness, deadline=asyncio.get_running_loop().time() - 1)
    assert failure.value.completed == ()
    assert harness.embedder.calls == 0


@pytest.mark.parametrize("total_timeout", [1, 3])
async def test_non_yielding_provider_cannot_return_success_after_deadline(
    monkeypatch: pytest.MonkeyPatch,
    total_timeout: float,
) -> None:
    harness = await _harness(extra_cases=_calibration())
    loop = asyncio.get_running_loop()
    original_time = loop.time
    original_embed = harness.embedder.embed
    offset = 0.0

    async def exceed_deadline(text: str) -> tuple[float, ...]:
        nonlocal offset
        vector = await original_embed(text)
        offset = 2.0
        return vector

    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)
    monkeypatch.setattr(harness.embedder, "embed", exceed_deadline)
    with pytest.raises(OntologyRetrievalCampaignAbortedError) as failure:
        await _run(harness, timeout=total_timeout, query_timeout=1)
    assert failure.value.stage == "calibration"
    assert failure.value.completed == ()
    assert harness.embedder.calls == 1


async def test_timeout_stops_campaign_and_parent_cancellation_propagates() -> None:
    harness = await _harness(extra_cases=_calibration())
    harness.embedder.stall = True
    with pytest.raises(OntologyRetrievalCampaignAbortedError) as failure:
        await _run(harness, timeout=0.01)
    assert failure.value.stage == "calibration"
    assert failure.value.completed == ()
    assert harness.embedder.calls == 1
    task = asyncio.create_task(_run(harness))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert harness.embedder.calls == 2


async def test_holdout_failure_is_not_hidden_by_successful_calibration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness(extra_cases=_calibration())
    original = harness.embedder.embed

    async def fail_holdout(text: str) -> tuple[float, ...]:
        harness.embedder.wrong = harness.embedder.calls >= 6
        return await original(text)

    monkeypatch.setattr(harness.embedder, "embed", fail_holdout)
    report = await _run(harness)
    assert report.calibration.passed
    assert report.holdout is not None and not report.holdout.passed
    assert not report.passed
    assert harness.embedder.calls == 26
