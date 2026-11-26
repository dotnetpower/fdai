"""Deterministic resource-name suggestion tests."""

from types import MappingProxyType

from fdai.core.ontology_platform import QueryNodeResult, QueryPlanExecution
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai_core_service.semantic_target_suggestions import (
    observed_resource_name_candidates,
    resource_name_suggestions,
)


def _execution(names: tuple[str, ...]) -> QueryPlanExecution:
    return QueryPlanExecution(
        plan_digest="sha256:" + ("a" * 64),
        status="held",
        results=MappingProxyType(
            {
                "gateway-name-candidates-1": QueryNodeResult(
                    value=QueryTable(
                        rows=tuple(
                            QueryRow.from_values(
                                f"resource-{index}",
                                {"name": name, "type": "network.application-gateway"},
                            )
                            for index, name in enumerate(names)
                        ),
                        complete=True,
                    ),
                    evidence_refs=("inventory:candidates",),
                )
            }
        ),
        receipts=(),
        output_node_ids=(),
    )


def test_suggestions_rank_similar_verified_names_without_exact_rebinding() -> None:
    suggestions = resource_name_suggestions(
        "SRE-AppGW-01",
        _execution(("SRE-AppGW-02", "SRE-AppGW-001", "unrelated-gateway")),
    )

    assert tuple(item.name for item in suggestions) == ("SRE-AppGW-001", "SRE-AppGW-02")
    assert all(item.similarity < 1.0 for item in suggestions)


def test_suggestions_report_no_candidate_below_similarity_floor() -> None:
    assert (
        resource_name_suggestions(
            "SRE-AppGW-01",
            _execution(("billing-api", "production-edge")),
        )
        == ()
    )


def test_same_type_candidates_remain_available_below_similarity_floor() -> None:
    candidates = observed_resource_name_candidates(
        _execution(("agw-fdai-trace-lab",)),
        requested_name="SRE-AppGW-99",
    )

    assert tuple(item.name for item in candidates) == ("agw-fdai-trace-lab",)
