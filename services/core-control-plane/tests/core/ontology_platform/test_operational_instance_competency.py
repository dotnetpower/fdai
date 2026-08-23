"""Representative answer-text-free operational instance competency tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fdai.core.ontology_platform.archive_retention import ArchiveHistoryStatus
from fdai.core.ontology_platform.graph_evidence_refresh import (
    GraphEvidenceFreshness,
    GraphEvidenceRefreshInput,
    GraphEvidenceRefreshOutcome,
    GraphQueryIntent,
    decide_graph_evidence_refresh,
)
from fdai.core.ontology_platform.operational_instance_competency import (
    OperationalInstanceExpectation,
    OperationalInstanceObservation,
    OperationalInstancePathStep,
    evaluate_operational_instance_competency,
)
from fdai.delivery.golden_question_dataset import load_golden_question_dataset

_ROOT = Path(__file__).resolve().parents[5]
_DATASET = _ROOT / "eval" / "golden-dataset"
_RELEASE = "sha256:" + "a" * 64


def _refresh(**changes: object):
    values: dict[str, object] = {
        "query_intent": GraphQueryIntent.CURRENT,
        "requested_ontology_release_digest": _RELEASE,
        "graph_ontology_release_digest": _RELEASE,
        "graph_available": True,
        "graph_freshness": GraphEvidenceFreshness.CURRENT,
        "graph_complete": True,
        "graph_truncated": False,
        "graph_synthetic": False,
        "graph_conflict_count": 0,
        "explicit_live_read": False,
        "live_read_permitted": False,
        "verified_live_receipt": False,
        "live_receipt_principal_scoped": False,
        "deadline_remaining_ms": 10_000,
        "live_read_budget_ms": 2_000,
        "projection_budget_ms": 2_000,
        "archive_status": ArchiveHistoryStatus.UNAVAILABLE,
        "archive_principal_scoped": False,
    }
    values.update(changes)
    return decide_graph_evidence_refresh(
        GraphEvidenceRefreshInput(**values)  # type: ignore[arg-type]
    )


def _cases():
    corpus = load_golden_question_dataset(_DATASET)
    selected = {}
    for case in sorted(corpus.cases, key=lambda item: item.case_id):
        if case.locale == "en":
            logical_id, separator, _variation = case.semantic_pair_id.rpartition(".")
            assert separator
            selected.setdefault(logical_id, case)
    return selected


def test_representative_questions_match_instances_paths_functions_and_refresh() -> None:
    resource = "resource:example"
    workload = "workload:example"
    service = "service:example"
    examples = (
        (
            "current-resource-state",
            (resource,),
            (),
            ("query.resource_current_state",),
            _refresh(),
            ArchiveHistoryStatus.UNAVAILABLE,
        ),
        (
            "topology-dependency",
            (resource, workload, service),
            (
                OperationalInstancePathStep(workload, "workload_runs_on", resource),
                OperationalInstancePathStep(workload, "workload_depends_on", workload),
                OperationalInstancePathStep(service, "implemented_by", workload),
            ),
            ("query.ontology_relationships",),
            _refresh(
                graph_freshness=GraphEvidenceFreshness.STALE,
                live_read_permitted=True,
            ),
            ArchiveHistoryStatus.UNAVAILABLE,
        ),
        (
            "service-current-health",
            (resource, workload, service),
            (
                OperationalInstancePathStep(workload, "workload_runs_on", resource),
                OperationalInstancePathStep(service, "implemented_by", workload),
            ),
            ("query.ontology_relationships", "query.resource_current_state"),
            _refresh(
                graph_complete=False,
                live_read_permitted=True,
                verified_live_receipt=True,
                live_receipt_principal_scoped=True,
            ),
            ArchiveHistoryStatus.UNAVAILABLE,
        ),
        (
            "operation-historical-topology",
            (resource,),
            (OperationalInstancePathStep(resource, "contains", resource),),
            ("topology_at", "topology_diff"),
            _refresh(
                query_intent=GraphQueryIntent.HISTORICAL,
                archive_status=ArchiveHistoryStatus.ARCHIVED,
                archive_principal_scoped=True,
            ),
            ArchiveHistoryStatus.ARCHIVED,
        ),
        (
            "evidence-gap",
            (resource, workload, service),
            (
                OperationalInstancePathStep(workload, "workload_runs_on", resource),
                OperationalInstancePathStep(service, "implemented_by", workload),
            ),
            ("query.ontology_relationships",),
            _refresh(graph_complete=False),
            ArchiveHistoryStatus.UNAVAILABLE,
        ),
        (
            "network-path",
            ("resource:network-a", "resource:network-b"),
            (OperationalInstancePathStep("resource:network-a", "routes_to", "resource:network-b"),),
            ("query.ontology_relationships",),
            _refresh(graph_conflict_count=1),
            ArchiveHistoryStatus.UNAVAILABLE,
        ),
    )
    golden = _cases()
    receipts = []
    for pair_id, instance_ids, path_steps, functions, refresh, archive_status in examples:
        expectation = OperationalInstanceExpectation(
            semantic_pair_id=pair_id,
            instance_ids=tuple(sorted(instance_ids)),
            path_steps=tuple(sorted(path_steps)),
            functions=tuple(sorted(functions)),
            refresh_outcome=refresh.outcome,
            archive_status=archive_status,
        )
        observation = OperationalInstanceObservation(
            semantic_pair_id=pair_id,
            instance_ids=expectation.instance_ids,
            path_steps=expectation.path_steps,
            functions=expectation.functions,
            refresh_decision=refresh,
            archive_status=archive_status,
            execution_authority=False,
        )
        receipts.append(
            evaluate_operational_instance_competency(
                golden[pair_id],
                expectation,
                observation,
            )
        )

    assert len(receipts) == 6
    assert all(receipt.passed for receipt in receipts)
    assert {receipt.digest for receipt in receipts} == {receipt.digest for receipt in receipts}
    assert {item[4].outcome for item in examples} == {
        GraphEvidenceRefreshOutcome.HOLD,
        GraphEvidenceRefreshOutcome.QUERY_ARCHIVE,
        GraphEvidenceRefreshOutcome.REFRESH_THEN_QUERY,
        GraphEvidenceRefreshOutcome.USE_GRAPH,
        GraphEvidenceRefreshOutcome.USE_LIVE_EVIDENCE,
    }


def test_wrong_instance_or_refresh_outcome_fails_without_reading_answer_text() -> None:
    golden = _cases()["current-resource-state"]
    expectation = OperationalInstanceExpectation(
        semantic_pair_id="current-resource-state",
        instance_ids=("resource:expected",),
        path_steps=(),
        functions=("query.resource_current_state",),
        refresh_outcome=GraphEvidenceRefreshOutcome.USE_GRAPH,
        archive_status=ArchiveHistoryStatus.UNAVAILABLE,
    )
    observation = OperationalInstanceObservation(
        semantic_pair_id=expectation.semantic_pair_id,
        instance_ids=("resource:wrong",),
        path_steps=(),
        functions=expectation.functions,
        refresh_decision=_refresh(),
        archive_status=ArchiveHistoryStatus.UNAVAILABLE,
        execution_authority=False,
    )

    wrong_instance = evaluate_operational_instance_competency(
        golden,
        expectation,
        observation,
    )
    wrong_refresh = evaluate_operational_instance_competency(
        golden,
        expectation,
        replace(
            observation,
            instance_ids=expectation.instance_ids,
            refresh_decision=_refresh(graph_complete=False),
        ),
    )

    assert wrong_instance.instances_exact is False
    assert wrong_instance.passed is False
    assert wrong_refresh.refresh_outcome_exact is False
    assert wrong_refresh.passed is False
