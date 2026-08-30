from __future__ import annotations

import pytest
from fdai_operator_service.investigation_projection import (
    project_adaptive_investigation,
)
from fdai_service_contracts.ontology_query import content_digest

DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"
FRAME_DIGEST = content_digest(
    {
        "schema_version": "1.0.0",
        "incident_id": "incident-1",
        "graph_revision": "graph-1",
        "evidence_cutoff": "2026-08-30T00:00:00Z",
        "active_hypothesis_ids": ["hypothesis-a", "hypothesis-b"],
        "active_set_receipt_digest": DIGEST_A,
        "cost_model_digest": DIGEST_B,
    }
)


def _events() -> list[dict[str, object]]:
    budget = {
        "max_rounds": 3,
        "max_queries": 3,
        "max_cost_units": 100,
        "deadline_at": "2026-08-30T00:05:00Z",
        "policy_digest": DIGEST_B,
    }
    selection_material = {
        "schema_version": "1.0.0",
        "frame_digest": FRAME_DIGEST,
        "method_version": "pair-separation-v1",
        "disposition": "held",
        "candidate_digests": [],
        "rejected_candidates": [],
        "total_pair_count": 1,
        "separated_pair_count": 0,
        "selected_candidate_id": None,
        "hold_reason": "no_candidates",
    }
    selection_digest = content_digest(selection_material)
    selection = {
        "selection_id": f"hypothesis-discrimination-{selection_digest[7:39]}",
        "selection_digest": selection_digest,
        **selection_material,
    }
    iteration_digest = content_digest(
        {
            "round_index": 1,
            "frame_digest": FRAME_DIGEST,
            "selection_digest": selection_digest,
            "execution_digest": None,
            "revision_digest": None,
            "shadow_comparison_digest": None,
        }
    )
    nested_iteration = {
        "round_index": 1,
        "frame": {
            "incident_id": "incident-1",
            "graph_revision": "graph-1",
            "evidence_cutoff": "2026-08-30T00:00:00Z",
            "active_hypothesis_ids": ["hypothesis-a", "hypothesis-b"],
            "active_set_receipt_digest": DIGEST_A,
            "cost_model_digest": DIGEST_B,
            "frame_digest": FRAME_DIGEST,
        },
        "selection": selection,
        "execution": None,
        "revision": None,
        "shadow_comparison_digest": None,
        "iteration_digest": iteration_digest,
    }
    result_material = {
        "session_id": "adaptive-1",
        "incident_id": "incident-1",
        "workflow_version": "1.0.0",
        "reducer_version": "adaptive-investigation-reducer-v1",
        "active_strategy_digest": DIGEST_A,
        "challenger_strategy_digest": None,
        "budget": budget,
        "iteration_digests": [iteration_digest],
        "disposition": "held",
        "terminal_frame_digest": FRAME_DIGEST,
        "terminal_active_set_receipt_digest": DIGEST_A,
        "used_queries": 0,
        "used_cost_units": 0,
        "execution_authority": False,
    }
    result_digest = content_digest(result_material)
    result = {
        **result_material,
        "iterations": [nested_iteration],
        "result_digest": result_digest,
        "mutation_authority": False,
        "promotion_authority": False,
    }
    return [
        {
            "payload": {
                "record_type": "adaptive_created",
                "incident_id": "incident-1",
                "initial_frame_digest": FRAME_DIGEST,
                "initial_active_set_receipt_digest": DIGEST_A,
                "initial_cost_model_digest": DIGEST_B,
                "active_strategy_digest": DIGEST_A,
                "challenger_strategy_digest": None,
                "budget": budget,
            }
        },
        {
            "payload": {
                "record_type": "adaptive_iteration",
                "round_index": 1,
                "iteration_digest": iteration_digest,
                "frame_digest": FRAME_DIGEST,
                "evidence_cutoff": "2026-08-30T00:00:00+00:00",
                "graph_revision": "graph-1",
                "cost_model_digest": DIGEST_B,
                "active_hypothesis_ids": ["hypothesis-a", "hypothesis-b"],
                "active_set_receipt_digest": DIGEST_A,
                "selection_digest": selection_digest,
                "selected_candidate_id": None,
                "separated_pair_count": 0,
                "total_pair_count": 1,
                "hold_reason": "no_candidates",
                "shadow_comparison_digest": None,
            }
        },
        {
            "payload": {
                "record_type": "adaptive_terminal",
                "result_digest": result_digest,
                "disposition": "held",
                "terminal_frame_digest": FRAME_DIGEST,
                "terminal_active_set_receipt_digest": DIGEST_A,
                "used_queries": 0,
                "used_cost_units": 0,
                "iteration_digests": [iteration_digest],
                "result": result,
            }
        },
    ]


def test_projects_bounded_read_only_room() -> None:
    projection = project_adaptive_investigation(
        process_id="adaptive-1",
        workflow_ref="adaptive-investigation",
        workflow_version="1.0.0",
        process_revision=2,
        events=_events(),
    )

    assert projection is not None
    assert projection["read_only"] is True
    assert projection["mutation_controls"] is False
    assert projection["process_revision"] == 2
    assert projection["round_count"] == 1
    assert projection["rounds"][0]["hold_reason"] == "no_candidates"  # type: ignore[index]


def test_non_adaptive_process_has_no_room() -> None:
    assert (
        project_adaptive_investigation(
            process_id="adaptive-1",
            workflow_ref="operational-planning",
            workflow_version="1.0.0",
            process_revision=1,
            events=[],
        )
        is None
    )


def test_rejects_terminal_lineage_substitution() -> None:
    events = _events()
    terminal = events[-1]["payload"]
    assert isinstance(terminal, dict)
    terminal["iteration_digests"] = [DIGEST_B]

    with pytest.raises(ValueError, match="terminal lineage"):
        project_adaptive_investigation(
            process_id="adaptive-1",
            workflow_ref="adaptive-investigation",
            workflow_version="1.0.0",
            process_revision=2,
            events=events,
        )


def test_rejects_raw_unbounded_evidence_reference() -> None:
    events = _events()
    iteration = events[1]["payload"]
    assert isinstance(iteration, dict)
    iteration["execution"] = {
        "frame_digest": FRAME_DIGEST,
        "selection_digest": iteration["selection_digest"],
        "candidate_digest": DIGEST_A,
        "verification_receipt_digest": DIGEST_B,
        "plan_digest": DIGEST_A,
        "result_digest": DIGEST_B,
        "execution_digest": DIGEST_A,
        "query_status": "completed",
        "evidence_refs": ["x" * 513],
        "reserved_cost_units": 1,
        "actual_cost_units": 1,
    }
    iteration["selected_candidate_id"] = f"observation-candidate-{'a' * 32}"

    with pytest.raises(ValueError, match="bounded strings"):
        project_adaptive_investigation(
            process_id="adaptive-1",
            workflow_ref="adaptive-investigation",
            workflow_version="1.0.0",
            process_revision=2,
            events=events,
        )


@pytest.mark.parametrize(
    ("used_queries", "used_cost_units", "message"),
    [
        (1, 0, "query count"),
        (0, 1, "cost does not match"),
    ],
)
def test_rejects_terminal_usage_not_supported_by_rounds(
    used_queries: int,
    used_cost_units: int,
    message: str,
) -> None:
    events = _events()
    terminal = events[-1]["payload"]
    assert isinstance(terminal, dict)
    terminal["used_queries"] = used_queries
    terminal["used_cost_units"] = used_cost_units

    with pytest.raises(ValueError, match=message):
        project_adaptive_investigation(
            process_id="adaptive-1",
            workflow_ref="adaptive-investigation",
            workflow_version="1.0.0",
            process_revision=2,
            events=events,
        )
