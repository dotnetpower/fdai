"""Consistency of scripted diagnostics does not establish real-model relevance."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fdai.delivery.catalog_search.ontology_semantic_evaluation import (
    OntologySemanticEvaluationAbortedError,
    OntologySemanticEvaluationBudget,
)
from fdai.delivery.catalog_search.ontology_semantic_evidence import (
    verify_ontology_semantic_evidence,
)
from tests.delivery.catalog_search.test_ontology_evaluation import _POLICY, _TYPES, _cases
from tests.delivery.catalog_search.test_ontology_evaluation_runner import _RANKING, _harness
from tests.delivery.catalog_search.test_ontology_semantic_evaluation import _run


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


async def _fixture(path: Path, **kwargs):
    plans = []
    report, _ = await _run(path, prepared_plans=plans, **kwargs)
    source = await _harness(typed_selection_available=True)
    return report, {
        "expected_file_digest": _digest(path),
        "plan": plans[0],
        "build": source.build,
        "manifest": source.manifest,
        "staged": source.staged,
        "cases": _cases(),
        "calibration_queries": (),
        "ranking_policy": _RANKING,
        "evaluation_policy": _POLICY,
        "required_object_types": _TYPES,
    }


def _write(path: Path, rows) -> str:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return _digest(path)


@pytest.mark.parametrize(
    "options",
    [{}, {"wrong_results": True}, {"clarify_negatives": True}],
    ids=["selected", "failed-quality", "clarified"],
)
async def test_verifies_complete_reports_without_upgrading_quality_or_authority(tmp_path, options):
    path = tmp_path / "evidence.jsonl"
    report, inputs = await _fixture(path, **options)
    verified = verify_ontology_semantic_evidence(path, **inputs)
    assert verified == report
    assert verified.passed is (not options.get("wrong_results", False))
    assert verified.production_qualification is verified.execution_authority is False


@pytest.mark.parametrize(
    "change",
    [
        "sequence",
        "source",
        "schema",
        "authority",
        "extra-header",
        "naive-time",
        "backward-time",
        "early-terminal",
        "aborted",
        "missing-record",
        "duplicate-record",
        "trailing-abort",
        "start-plan",
        "intent-case",
        "intent-input",
        "intent-index",
        "intent-boolean",
        "proposal-index",
        "proposal-digest",
        "proposal-observation",
        "proposal-span",
        "proposal-span-boolean",
        "proposal-clauses",
        "proposal-extra",
        "measurement-index",
        "measurement-boolean",
        "measurement-outcome",
        "report-count",
        "report-stage",
        "report-binding",
        "report-elapsed",
        "report-outcomes",
        "report-proposals",
        "report-metrics",
        "report-failures",
        "report-extra",
        "source-validation",
        "source-time",
        "result-digest",
        "source-projection-digest",
        "unknown-result",
        "duplicate-result",
        "too-many-results",
        "measurement-query",
        "measurement-case",
    ],
)
async def test_rejects_inconsistent_records_even_when_file_digest_is_repinned(tmp_path, change):
    path = tmp_path / "evidence.jsonl"
    _, inputs = await _fixture(path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    intent, proposal, measured = rows[2:5]
    report = rows[-1]["payload"]["report"]
    if change == "sequence":
        proposal["sequence"] = 0
    elif change == "source":
        proposal["source_commit"] = "f" * 40
    elif change == "schema":
        proposal["schema_version"] = "1.0.0"
    elif change == "authority":
        proposal["production_qualification"] = True
    elif change == "extra-header":
        proposal["unexpected"] = "private-sentinel"
    elif change == "naive-time":
        proposal["recorded_at"] = "2026-10-01T00:00:00"
    elif change == "backward-time":
        proposal["recorded_at"] = "2026-01-01T00:00:00Z"
    elif change == "early-terminal":
        proposal["event"] = "completed"
    elif change == "aborted":
        rows[-1]["event"] = "aborted"
    elif change == "missing-record":
        rows.pop(3)
    elif change == "duplicate-record":
        rows.insert(3, proposal)
    elif change == "trailing-abort":
        rows.append({**rows[-1], "event": "aborted", "sequence": len(rows)})
    elif change == "start-plan":
        rows[0]["payload"]["plan"]["model_version"] = "private-sentinel"
    elif change == "intent-case":
        intent["payload"]["case_id"] = "private-sentinel"
    elif change == "intent-input":
        intent["payload"]["input_digest"] = "sha256:" + "0" * 64
    elif change == "intent-index":
        intent["payload"]["call_index"] = 2
    elif change == "intent-boolean":
        intent["payload"]["call_index"] = True
    elif change == "proposal-index":
        proposal["payload"]["call_index"] = 2
    elif change == "proposal-digest":
        proposal["payload"]["proposal_digest"] = "sha256:" + "0" * 64
    elif change == "proposal-observation":
        proposal["payload"]["observation_digest"] = "private-sentinel"
    elif change == "proposal-span":
        proposal["payload"]["quote_spans"][0][1] = 100000
    elif change == "proposal-span-boolean":
        proposal["payload"]["quote_spans"][0][0] = False
    elif change == "proposal-clauses":
        proposal["payload"]["clauses"] = []
    elif change == "proposal-extra":
        proposal["payload"]["unexpected"] = "private-sentinel"
    elif change == "measurement-index":
        measured["payload"]["call_index"] = 2
    elif change == "measurement-boolean":
        measured["payload"]["call_index"] = True
    elif change == "measurement-outcome":
        measured["payload"]["outcome"] = "clarified"
    elif change == "report-count":
        report["proposal_calls"] -= 1
    elif change == "report-stage":
        report["stage"] = "holdout"
    elif change == "report-binding":
        report["binding_digest"] = "sha256:" + "0" * 64
    elif change == "report-elapsed":
        report["elapsed_seconds"] = 31
    elif change == "report-outcomes":
        report["outcomes"] = []
    elif change == "report-proposals":
        report["proposal_digests"] = []
    elif change == "report-metrics":
        report["cohort_metrics"][0]["value"] = 0.5
    elif change == "report-failures":
        report["failure_codes"] = ["private-sentinel"]
    elif change == "report-extra":
        report["unexpected"] = "private-sentinel"
    elif change in ("source-validation", "source-time", "source-projection-digest"):
        key, value = {
            "source-validation": ("snapshot_digest", "sha256:" + "0" * 64),
            "source-time": ("checked_at", "2026-10-01T00:00:00"),
            "source-projection-digest": ("checked_projection_digest", "private-sentinel"),
        }[change]
        rows[1]["payload"]["validation"][key] = value
        report["source_validations"][0][key] = value
    else:
        measurement = report["measurements"][0]
        if change == "result-digest":
            measurement["result_digest"] = "private-sentinel"
        elif change == "unknown-result":
            measurement["retrieved_document_ids"] = ["object:Resource:absent"]
        elif change == "duplicate-result":
            measurement["retrieved_document_ids"] = ["object:Resource:resource-0"] * 2
        elif change == "too-many-results":
            measurement["retrieved_document_ids"] = ["object:Resource:resource-0"] * 6
        elif change == "measurement-query":
            measurement["query_digest"] = "sha256:" + "0" * 64
        elif change == "measurement-case":
            measurement["case_id"] = "private-sentinel"
        else:
            raise AssertionError(change)
        measured["payload"]["measurement"] = measurement
    inputs["expected_file_digest"] = _write(path, rows)
    with pytest.raises(ValueError, match="semantic evidence is inconsistent") as failure:
        verify_ontology_semantic_evidence(path, **inputs)
    assert "private-sentinel" not in str(failure.value)


@pytest.mark.parametrize("change", ["file-digest", "permissions", "symlink", "truncated"])
async def test_rejects_unsafe_or_unpinned_files(tmp_path, change):
    path = tmp_path / "evidence.jsonl"
    _, inputs = await _fixture(path)
    if change == "file-digest":
        inputs["expected_file_digest"] = "sha256:" + "0" * 64
    elif change == "permissions":
        path.chmod(0o644)
    elif change == "symlink":
        link = tmp_path / "link.jsonl"
        link.symlink_to(path)
        path = link
    else:
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
        inputs["expected_file_digest"] = _digest(path)
    with pytest.raises(ValueError):
        verify_ontology_semantic_evidence(path, **inputs)


@pytest.mark.parametrize("change", ["labels", "order", "policy", "model", "budget"])
async def test_recomputes_the_plan_from_independently_supplied_inputs(tmp_path, change):
    path = tmp_path / "evidence.jsonl"
    _, inputs = await _fixture(path)
    if change == "labels":
        cases = _cases()
        index = next(i for i, case in enumerate(cases) if case.expected_document_ids)
        changed = replace(cases[index], expected_document_ids=("object:Resource:resource-0",))
        inputs["cases"] = (*cases[:index], changed, *cases[index + 1 :])
    elif change == "order":
        inputs["cases"] = tuple(reversed(_cases()))
    elif change == "policy":
        inputs["evaluation_policy"] = replace(_POLICY, min_recall_at_k=0.5)
    elif change == "model":
        inputs["plan"] = replace(inputs["plan"], model_version="changed")
    else:
        plan = inputs["plan"]
        inputs["plan"] = replace(plan, budget=replace(plan.budget, query_timeout_seconds=4))
    with pytest.raises(ValueError):
        verify_ontology_semantic_evidence(path, **inputs)


async def test_rejects_actual_late_completion_correction(tmp_path, monkeypatch):
    path = tmp_path / "evidence.jsonl"
    _, inputs = await _fixture(tmp_path / "complete.jsonl")
    with pytest.raises(OntologySemanticEvaluationAbortedError):
        await _run(path, late_completion=True, monkeypatch=monkeypatch)
    inputs["expected_file_digest"] = _digest(path)
    with pytest.raises(ValueError, match="record_sequence"):
        verify_ontology_semantic_evidence(path, **inputs)


async def test_recomputes_metrics_instead_of_accepting_a_rewritten_passing_summary(tmp_path):
    path = tmp_path / "evidence.jsonl"
    original, inputs = await _fixture(path, wrong_results=True)
    assert not original.passed
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    report = rows[-1]["payload"]["report"]
    report["failure_codes"] = []
    for metric in report["cohort_metrics"]:
        metric["value"] = 1.0
    inputs["expected_file_digest"] = _write(path, rows)
    with pytest.raises(ValueError, match="inconsistent: metrics"):
        verify_ontology_semantic_evidence(path, **inputs)


async def test_boolean_budget_is_not_equivalent_to_a_numeric_budget(tmp_path):
    path = tmp_path / "evidence.jsonl"
    _, inputs = await _fixture(
        path,
        budget=OntologySemanticEvaluationBudget(total_timeout_seconds=30, query_timeout_seconds=1),
    )
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["payload"]["plan"]["budget"]["query_timeout_seconds"] = True
    inputs["expected_file_digest"] = _write(path, rows)
    with pytest.raises(ValueError, match="record_sequence"):
        verify_ontology_semantic_evidence(path, **inputs)
