"""Answer presentation keeps machine markers but reads as ordinary operator language."""

from __future__ import annotations

import pytest
from fdai_core_service.semantic_answer_presentation import (
    authority_line,
    completeness_text,
    readable_resource_status,
    readable_timestamp,
)


def test_authority_line_keeps_the_machine_marker_in_both_languages() -> None:
    assert "`execution_authority=false`" in authority_line(korean=True)
    assert "실행 권한이 없습니다" in authority_line(korean=True)
    assert authority_line(korean=False).startswith("This read-only result grants no execution")


@pytest.mark.parametrize(
    ("value", "korean", "expected"),
    [
        ("PowerState/deallocated", True, "할당 해제됨"),
        ("PowerState/running", False, "Running"),
        ("Stopped", True, "중지됨"),
        ("ProvisioningState/Unexpected", True, "ProvisioningState/Unexpected"),
        ("", False, ""),
    ],
)
def test_provider_status_reads_in_operator_words_or_stays_verbatim(
    value: str, korean: bool, expected: str
) -> None:
    assert readable_resource_status(value, korean=korean) == expected


def test_timezone_aware_instants_render_as_utc_seconds_and_other_text_is_unchanged() -> None:
    assert readable_timestamp("2026-09-27T09:25:26.128800+00:00") == "2026-09-27 09:25:26 UTC"
    assert readable_timestamp("2026-09-27T18:25:26+09:00") == "2026-09-27 09:25:26 UTC"
    assert readable_timestamp("2026-09-27T09:25:26") == "2026-09-27T09:25:26"
    assert readable_timestamp("Succeeded") == "Succeeded"


def test_completeness_is_named_in_the_answer_language() -> None:
    assert completeness_text(True, korean=True) == "완전"
    assert completeness_text(False, korean=True) == "불완전"
    assert completeness_text(False, korean=False) == "incomplete"


def test_schema_property_relationship_candidates_rows_handles_health_and_change_answers() -> None:
    from types import MappingProxyType, SimpleNamespace

    from fdai.core.ontology_platform import QueryPlanExecution
    from fdai.core.ontology_platform.query_execution import QueryNodeResult
    from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
    from fdai_core_service.semantic_instance_candidates import render_instance_candidates
    from fdai_core_service.semantic_ontology_answers import render_ontology_schema_answer
    from fdai_core_service.semantic_property_answer import (
        render_property_value_answer,
        reviewed_structured_cells,
    )
    from fdai_core_service.semantic_relationship_projection import (
        render_ontology_relationship_answer,
    )
    from fdai_core_service.semantic_resource_change_answer import render_resource_change_answer
    from fdai_core_service.semantic_resource_health_answer import _claims_from_mapping
    from fdai_core_service.semantic_result_handle_projection import (
        result_handle_from_technical_details,
    )
    from fdai_core_service.semantic_source_limitations import (
        known_source_limitation,
        source_limitation_text,
    )
    from fdai_core_service.semantic_target_suggestions import observed_resource_name_candidates
    from fdai_core_service.semantic_verified_rows import verified_rows_table
    from fdai_service_contracts import SemanticTurnDisposition

    assert readable_timestamp(" 2026-09-27T09:25:26Z ") == "2026-09-27 09:25:26 UTC"
    schema_count = render_ontology_schema_answer(
        [
            {
                "source_complete": True,
                "display_truncated": False,
                "rows": [
                    {
                        "row_id": "agg",
                        "values": {"operation": "count", "group": {"kind": "object"}, "value": 89},
                    }
                ],
            }
        ],
        korean=False,
        output_shape="aggregation_table",
        subject_constraints=("ObjectTypes",),
    )
    assert schema_count is not None and "ObjectTypes: 89" in schema_count

    cells = reviewed_structured_cells(
        {"properties.properties.config": {"db_connstr": "secret", "mode": "ha"}},
        redact=lambda _f, v: v,
    )
    assert cells["properties.properties.config"] == {"db_connstr": "<redacted>", "mode": "ha"}
    nan_prop = render_property_value_answer(
        [{"rows": [{"values": {"id": "vm-1", "properties.cpu": float("nan")}}]}],
        korean=False,
        output_shape="target_property_value",
        measure_concepts=("CPU", "properties.cpu"),
    )
    assert nan_prop is not None and "(see technical details)" in nan_prop

    rel_answer = render_ontology_relationship_answer(
        "en",
        {
            "ontology_relationships": {
                "object_types": ["Resource", "Incident"],
                "relationships": [
                    {
                        "link_type": "affects",
                        "from_type": "Incident",
                        "to_type": "Resource",
                        "cardinality": "many_to_many",
                        "description": "Line 1\nLine 2",
                    }
                ],
                "complete": True,
            }
        },
    )
    assert "Line 1 Line 2" in rel_answer

    cand_text = render_instance_candidates(
        "en",
        {
            "instance_candidates": [MappingProxyType({"object_type": "Resource", "id": "vm-1"})],
            "source_truncated": False,
        },
    )
    assert "`Resource: vm-1`" in cand_text
    with pytest.raises(ValueError, match="malformed"):
        render_instance_candidates(
            "en",
            {
                "instance_candidates": [{"object_type": "Resource", "id": "   "}],
                "source_truncated": False,
            },
        )

    table_lines = verified_rows_table(
        {
            "rows": [{"row_id": "r1", "values": {"name": "vm-1", "status": "running"}}],
            "total_rows": 5,
        },
        korean=False,
    )
    assert any("4 more verified rows" in line for line in table_lines)
    assert known_source_limitation("source_incomplete + state_changed")
    assert "source completeness" in source_limitation_text(
        "source_incomplete + state_changed", korean=False
    )

    req = SimpleNamespace(session_id="sess-1", purpose="operations-review")
    res = SimpleNamespace(
        disposition=SemanticTurnDisposition.ANSWERED,
        ontology_release_digest="sha256:" + "a" * 64,
        principal_manifest_digest="sha256:" + "b" * 64,
    )
    handle = result_handle_from_technical_details(
        req,  # type: ignore[arg-type]
        res,  # type: ignore[arg-type]
        technical_details={
            "outputs": [
                {"node_id": "n1", "rows": [{"row_id": "vm-1", "values": {"name": "vm-1"}}]},
                {"node_id": "n2", "rows": [{"row_id": "vm-1", "values": {"name": "vm-1"}}]},
            ]
        },
    )
    assert handle is not None and handle.row_identities == ("vm-1",)

    exec_res = QueryPlanExecution(
        plan_digest="sha256:" + "c" * 64,
        status="completed",
        results={
            "gateway-name-candidates-1": QueryNodeResult(
                QueryTable(
                    rows=(
                        QueryRow.from_values(
                            "vm-1",
                            {
                                "id": "vm-1",
                                "properties": {"name": "vm-app-01", "type": "compute.vm"},
                            },
                        ),
                    ),
                    complete=True,
                )
            )
        },
        receipts=(),
        output_node_ids=("gateway-name-candidates-1",),
    )
    suggestions = observed_resource_name_candidates(exec_res, requested_name="vm-app-02")
    assert len(suggestions) == 1 and suggestions[0].name == "vm-app-01"

    assert (
        _claims_from_mapping(
            {
                "terminal_disposition": "all_clear",
                "all_clear": True,
                "denominator_count": 1,
                "observed_count": 1,
                "reason_codes": [],
                "window_started_at": "2026-09-27T09:00:00",
                "window_completed_at": "2026-09-27T09:05:00Z",
                "execution_authority": False,
            }
        )
        is None
    )

    from fdai.core.ontology_platform.recent_resource_changes import (
        ARG_RESOURCE_CHANGE_SOURCE_IDENTITY,
    )

    change_ans = render_resource_change_answer(
        [
            {
                "source_complete": True,
                "rows": [
                    {
                        "values": {
                            "subject_name": "   ",
                            "subject_ref": (
                                "/subscriptions/s/resourceGroups/rg/providers/"
                                "Microsoft.Compute/virtualMachines/vm-trailing/"
                            ),
                            "operation": "write",
                            "mutation_kind": "upsert",
                            "source_identity": ARG_RESOURCE_CHANGE_SOURCE_IDENTITY,
                            "observation_kind": "full",
                            "occurred_at": "2026-09-27T09:00:00Z",
                            "execution_authority": False,
                        }
                    }
                ],
            }
        ],
        korean=False,
        output_shape="resource_changes",
    )
    assert change_ans is not None and "`vm-trailing`" in change_ans
