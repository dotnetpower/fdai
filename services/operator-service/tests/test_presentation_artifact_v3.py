"""Adaptive presentation layout and assembly integrity tests."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import cast

import pytest
from fdai_operator_service.families.conversation.channel_edge.presentation import (
    normalize_terminal_presentation,
)
from fdai_operator_service.families.conversation.presentation_artifact_v2 import (
    compile_presentation_artifact_v2,
)
from fdai_operator_service.families.conversation.presentation_artifact_v3 import (
    verify_presentation_artifact_v3,
)
from fdai_operator_service.families.conversation.semantic_turn_presentation import (
    semantic_presentation_artifact,
)

_REF = "ontology-function:verified-output"
_SEMANTIC = {
    "disposition": "answered",
    "checks_completed": 1,
    "checks_total": 1,
    "evidence_refs": [_REF],
}


def _details(
    rows: list[Mapping[str, object]],
    *,
    operation: str,
    output_shape: str,
) -> dict[str, object]:
    return {
        "presentation_context": {
            "operation": operation,
            "output_shape": output_shape,
        },
        "outputs": [
            {
                "rows": [
                    {"row_id": f"row-{index}", "values": dict(row)}
                    for index, row in enumerate(rows)
                ],
                "returned_rows": len(rows),
                "total_rows": len(rows),
            }
        ],
    }


def _terminal(artifact: object) -> dict[str, object]:
    return {
        "status": "answered",
        "answer": "Verified answer.",
        "verification": {
            "authority": "ontology-query",
            "evidence_refs": [_REF],
        },
        "presentation_artifact": artifact,
    }


def test_health_assessment_uses_digest_bound_operational_brief() -> None:
    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=_details(
            [
                {
                    "overall_assessment": "insufficient_evidence",
                    "evidence_sufficient": False,
                    "platform_lifecycle": "observed_running",
                    "readiness": "not_proven",
                    "application_service_health": "not_proven",
                    "stability": "process_stability_not_proven",
                    "resource_pressure": "cpu_observed_capacity_unknown",
                    "source_observed_at": "2026-08-21T00:09:00Z",
                    "evidence_gaps": "runtime_logs_unavailable",
                    "execution_authority": False,
                }
            ],
            operation="validate",
            output_shape="target_health_assessment",
        ),
        locale="en",
    )

    assert artifact is not None
    assert artifact["schema_version"] == 3
    assert artifact["layout"] == "operational_brief"
    assembly = cast(dict[str, object], artifact["assembly"])
    assert assembly["section_count"] == 2
    assert assembly["input_kinds"] == [
        "verified_semantic_result",
        "presentation_context",
        "operator_locale",
    ]
    verify_presentation_artifact_v3(artifact)
    assert normalize_terminal_presentation(_terminal(artifact)).artifact_version == 3


def test_ontology_manifest_uses_markdown_document_layout() -> None:
    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=_details(
            [{"object_type": "Service", "status": "active"}],
            operation="select",
            output_shape="ontology_manifest",
        ),
        locale="ko",
    )

    assert artifact is not None
    assert artifact["schema_version"] == 3
    assert artifact["layout"] == "markdown_document"
    assembly = cast(dict[str, object], artifact["assembly"])
    assert assembly["label"] == "동적으로 조립된 Markdown"
    verify_presentation_artifact_v3(artifact)


def test_modified_v3_artifact_fails_integrity_and_degrades_for_channels() -> None:
    artifact = compile_presentation_artifact_v2(
        semantic=_SEMANTIC,
        technical_details=_details(
            [{"object_type": "Service", "status": "active"}],
            operation="select",
            output_shape="ontology_manifest",
        ),
        locale="en",
    )
    assert artifact is not None
    modified = copy.deepcopy(artifact)
    blocks = cast(list[dict[str, object]], modified["blocks"])
    blocks[0]["title"] = "Changed after assembly"

    with pytest.raises(ValueError, match="assembly is invalid"):
        verify_presentation_artifact_v3(modified)

    envelope = normalize_terminal_presentation(_terminal(modified))
    assert envelope.artifact_version is None
    assert envelope.artifact_degraded is True


def test_legacy_incident_projection_migrates_to_v3_operational_brief() -> None:
    artifact = semantic_presentation_artifact(
        semantic={"evidence_refs": [_REF]},
        technical_details={
            "outputs": [
                {
                    "incident_profile": {"status": "triaging"},
                    "correlated_evidence": [{"audit_ref": "audit:1"}],
                    "verified_records": 1,
                    "evidence_gaps": [],
                    "root_cause": None,
                    "impact_evidence": [],
                    "grounded_citations": [],
                }
            ]
        },
        locale="en",
    )

    assert artifact is not None
    assert artifact["schema_version"] == 3
    assert artifact["layout"] == "operational_brief"
    assembly = cast(dict[str, object], artifact["assembly"])
    assert assembly["input_kinds"] == [
        "verified_semantic_result",
        "incident_projection",
        "operator_locale",
    ]
    verify_presentation_artifact_v3(artifact)
