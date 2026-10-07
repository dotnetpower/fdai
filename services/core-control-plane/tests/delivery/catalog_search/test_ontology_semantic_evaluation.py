"""Mechanics only: scripted HTTP responses are not evidence of semantic quality."""

import asyncio
import json
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fdai.delivery.azure.llm.semantic_planning import AzureOpenAISemanticPlanningModel
from fdai.delivery.catalog_search.ontology_evaluation_evidence import (
    OntologyEvaluationEvidence,
    OntologyEvaluationEvidenceError,
)
from fdai.delivery.catalog_search.ontology_semantic_evaluation import (
    OntologySemanticEvaluationAbortedError,
    OntologySemanticEvaluationBudget,
    OntologySemanticEvaluationPlan,
    OntologySemanticEvaluationReport,
    prepare_ontology_semantic_evaluation,
    run_ontology_semantic_evaluation,
    semantic_candidate_model_binding,
)
from pydantic import TypeAdapter
from tests.delivery.azure.llm.test_ontology_candidate_proposal import _candidate_config
from tests.delivery.azure.llm.test_semantic_planning import _Identity, _target
from tests.delivery.catalog_search.test_ontology_evaluation import _POLICY, _TYPES, _cases
from tests.delivery.catalog_search.test_ontology_evaluation_runner import _RANKING, _harness

_SOURCE = "e" * 40


async def _run(
    path: Path,
    *,
    fail_call: int | None = None,
    clarify_negatives: bool = False,
    typed_available: bool = True,
    drift: bool = False,
    poison_proposal: bool = False,
    late_completion: bool = False,
    monkeypatch: pytest.MonkeyPatch | None = None,
    wrong_results: bool = False,
    changed_input: str | None = None,
    cancel_call: int | None = None,
    prepared_plans: list[OntologySemanticEvaluationPlan] | None = None,
    budget: OntologySemanticEvaluationBudget | None = None,
) -> tuple[OntologySemanticEvaluationReport, int]:
    harness = await _harness(typed_selection_available=typed_available)
    cases = _cases()
    by_query = {case.query: case for case in cases}
    calls = 0

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert records[-1]["event"] == "semantic_call_intent"
        if calls > 1:
            assert records[-2]["event"] == "semantic_measurement"
        if calls == fail_call:
            return httpx.Response(503)
        if calls == cancel_call:
            raise asyncio.CancelledError
        query = json.loads(json.loads(request.content)["messages"][1]["content"])[
            "untrusted_input"
        ]["query"]
        case = by_query[query]
        ids_by_type: dict[str, list[str]] = defaultdict(list)
        for document_id in case.expected_document_ids:
            _, object_type, identifier = document_id.split(":", 2)
            ids_by_type[object_type].append(identifier)
        clauses: list[dict[str, object]] = [
            {"object_type": name, "object_ids": identifiers}
            for name, identifiers in sorted(ids_by_type.items())
        ]
        if wrong_results:
            clauses = []
        clarify = clarify_negatives and not clauses
        if not clauses and not clarify:
            clauses = [
                {
                    "object_type": "Resource",
                    "predicates": [{"property": "id", "equals": "not-in-the-fixture"}],
                }
            ]
        proposal = {
            "status": "clarify" if clarify else "select",
            "reason": "unresolved_reference" if clarify else "conditions_proposed",
            "clauses": [dict(clause, quote=query) for clause in clauses],
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        model = AzureOpenAISemanticPlanningModel(
            identity=_Identity(),
            http_client=http,
            config=_candidate_config(),
            owner_loop=asyncio.get_running_loop(),
        )
        plan = prepare_ontology_semantic_evaluation(
            build=harness.build,
            manifest=harness.manifest,
            staged=harness.staged,
            cases=cases,
            calibration_queries=(),
            ranking_policy=_RANKING,
            evaluation_policy=_POLICY,
            required_object_types=_TYPES,
            model_binding=semantic_candidate_model_binding(model, harness.manifest, harness.build),
            model_name="synthetic-model",
            model_version="fixture-v1",
            source_commit=_SOURCE,
            budget=budget or OntologySemanticEvaluationBudget(total_timeout_seconds=30),
        )
        if prepared_plans is not None:
            prepared_plans.append(plan)
        if drift:
            model._config = replace(model._config, candidates=(_target("changed"),))
        if changed_input == "order":
            cases = tuple(reversed(cases))
        elif changed_input == "model-version":
            plan = replace(plan, model_version="changed")
        elif changed_input == "budget":
            plan = replace(plan, budget=replace(plan.budget, query_timeout_seconds=4))
        elif changed_input == "max-tokens":
            model._config = replace(model._config, max_tokens=model._config.max_tokens - 1)
        elif changed_input == "adapter-timeout":
            model._config = replace(
                model._config, timeout_seconds=model._config.timeout_seconds / 2
            )
        with OntologyEvaluationEvidence(
            path, source_commit=_SOURCE, semantic_proposals=True
        ) as evidence:
            if poison_proposal or late_completion:
                original = evidence.record
                loop, offset = asyncio.get_running_loop(), 0.0
                original_time = loop.time
                if late_completion:
                    assert monkeypatch is not None
                    monkeypatch.setattr(loop, "time", lambda: original_time() + offset)

                def fail_record(event, payload):
                    nonlocal offset
                    if poison_proposal and event == "semantic_proposal":
                        raise OntologyEvaluationEvidenceError("synthetic persistence failure")
                    original(event, payload)
                    if late_completion and event == "completed":
                        offset = 30

                evidence.record = fail_record
            result = await run_ontology_semantic_evaluation(
                plan=plan,
                build=harness.build,
                manifest=harness.manifest,
                staged=harness.staged,
                cases=cases,
                calibration_queries=(),
                ranking_policy=_RANKING,
                evaluation_policy=_POLICY,
                required_object_types=_TYPES,
                model=model,
                reader=harness.reader,
                snapshots=harness.snapshots,
                gateway=harness.gateway,
                clock=lambda: harness.clock.now,
                evidence=evidence,
            )
    assert harness.embedder.calls == 0
    return result, calls


async def test_complete_mechanical_campaign_retains_every_call_before_continuing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "semantic.jsonl"
    report, calls = await _run(path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert report.passed
    assert report.proposal_calls == calls == len(_cases())
    assert len(rows) == 4 + 3 * calls
    assert all(row["schema_version"] == "1.1.0" for row in rows)
    assert rows[-1]["event"] == "completed"
    restored = TypeAdapter(OntologySemanticEvaluationReport).validate_python(
        rows[-1]["payload"]["report"]
    )
    assert restored == report
    assert all(outcome == "selected" for outcome in report.outcomes)
    assert report.production_qualification is report.execution_authority is False
    assert path.stat().st_mode & 0o777 == 0o600
    assert not any("clause_quotes" in row["payload"] for row in rows)


async def test_clarification_never_falls_through_to_raw_embedding(tmp_path: Path) -> None:
    report, calls = await _run(tmp_path / "clarified.jsonl", clarify_negatives=True)
    assert report.passed
    assert calls == len(_cases())
    assert report.outcomes.count("clarified") == sum(
        not case.expected_document_ids for case in _cases()
    )


async def test_provider_failure_preserves_prior_measurements_and_stops(tmp_path: Path) -> None:
    path = tmp_path / "failed.jsonl"
    with pytest.raises(OntologySemanticEvaluationAbortedError) as captured:
        await _run(path, fail_call=3)
    assert captured.value.proposal_calls == 3
    assert captured.value.completed == 2
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[-1]["event"] == "aborted"
    assert sum(row["event"] == "semantic_measurement" for row in rows) == 2
    assert sum(row["event"] == "semantic_call_intent" for row in rows) == 3
    assert captured.value.stage == "proposal"
    assert captured.value.failure_chain == (
        {"class": "ValueError", "message": "candidate proposal model unavailable"},
    )
    assert rows[-1]["payload"]["failure_chain"] == [
        {"class": "ValueError", "message": "candidate proposal model unavailable"}
    ]


async def test_unqualified_reader_stops_before_any_model_call(tmp_path: Path) -> None:
    path = tmp_path / "unavailable.jsonl"
    with pytest.raises(OntologySemanticEvaluationAbortedError) as captured:
        await _run(path, typed_available=False)
    assert captured.value.proposal_calls == 0
    assert [json.loads(line)["event"] for line in path.read_text().splitlines()] == [
        "started",
        "aborted",
    ]


async def test_model_target_drift_fails_admission(tmp_path: Path) -> None:
    path = tmp_path / "drifted.jsonl"
    with pytest.raises(ValueError, match="binding changed"):
        await _run(path, drift=True)
    assert path.read_bytes() == b""


async def test_missing_proposal_evidence_stops_before_read_or_next_model(tmp_path: Path) -> None:
    path = tmp_path / "storage-failed.jsonl"
    with pytest.raises(OntologyEvaluationEvidenceError):
        await _run(path, poison_proposal=True)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["event"] for row in rows] == ["started", "stage", "semantic_call_intent"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_proposal_calls": 65},
        {"max_proposal_calls": True},
        {"total_timeout_seconds": 601},
        {"query_timeout_seconds": 20.5},
        {"query_timeout_seconds": float("nan")},
    ],
)
def test_semantic_budgets_cannot_weaken_frozen_ceilings(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="bounded calls"):
        OntologySemanticEvaluationBudget(**kwargs)


def test_semantic_budget_accepts_the_twenty_second_call_ceiling() -> None:
    assert OntologySemanticEvaluationBudget(query_timeout_seconds=20).query_timeout_seconds == 20


def test_semantic_evidence_requires_source_and_has_its_own_finite_record_bound(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="source provenance"):
        OntologyEvaluationEvidence(tmp_path / "missing.jsonl", semantic_proposals=True)
    with pytest.raises(ValueError, match="separate vector"):
        OntologyEvaluationEvidence(
            tmp_path / "mixed.jsonl",
            source_commit=_SOURCE,
            semantic_proposals=True,
            retain_vectors=True,
        )
    path = tmp_path / "bounded.jsonl"
    with OntologyEvaluationEvidence(
        path, source_commit=_SOURCE, semantic_proposals=True
    ) as evidence:
        evidence.record("started", {})
        for index in range(197):
            evidence.record("stage", {"index": index})
        with pytest.raises(OntologyEvaluationEvidenceError, match="bounded|retained"):
            evidence.record("completed", {})
    assert len(path.read_bytes().splitlines()) == 198


async def test_late_completion_is_downgraded_without_erasing_measurements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "late-completion.jsonl"
    with pytest.raises(OntologySemanticEvaluationAbortedError) as captured:
        await _run(path, late_completion=True, monkeypatch=monkeypatch)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert captured.value.completed == len(_cases())
    assert [row["event"] for row in rows[-2:]] == ["completed", "aborted"]
    assert rows[-1]["payload"]["stage"] == "completion"


def test_semantic_terminal_downgrade_cannot_resume_or_upgrade(tmp_path: Path) -> None:
    with OntologyEvaluationEvidence(
        tmp_path / "terminal.jsonl", source_commit=_SOURCE, semantic_proposals=True
    ) as evidence:
        evidence.record("started", {})
        evidence.record("completed", {})
        with pytest.raises(OntologyEvaluationEvidenceError):
            evidence.record("semantic_call_intent", {})
        evidence.record("aborted", {"stage": "completion"})
        for event in ("completed", "aborted"):
            with pytest.raises(OntologyEvaluationEvidenceError):
                evidence.record(event, {})


async def test_wrong_results_keep_all_frozen_thresholds_and_fail_quality(tmp_path: Path) -> None:
    report, calls = await _run(tmp_path / "wrong-results.jsonl", wrong_results=True)
    assert calls == len(_cases())
    assert not report.passed
    assert len(report.failure_codes) == 4
    assert all(
        metric.value == (1.0 if metric.metric == "no-match-precision" else 0.0)
        for metric in report.cohort_metrics
    )


@pytest.mark.parametrize(
    "changed_input", ["order", "model-version", "budget", "max-tokens", "adapter-timeout"]
)
async def test_frozen_semantic_inputs_cannot_change_before_execution(
    tmp_path: Path,
    changed_input: str,
) -> None:
    path = tmp_path / "changed-input.jsonl"
    with pytest.raises(ValueError, match="binding changed"):
        await _run(path, changed_input=changed_input)
    assert path.read_bytes() == b""


async def test_cancellation_remains_cancellation_with_explicit_partial_evidence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cancelled.jsonl"
    with pytest.raises(asyncio.CancelledError):
        await _run(path, cancel_call=2)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[-1]["event"] == "cancelled"
    assert rows[-1]["payload"] == {"proposal_calls": 2, "completed": 1}
