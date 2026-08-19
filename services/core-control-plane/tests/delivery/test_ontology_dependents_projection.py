"""Focused deterministic ontology dependent projection tests."""

from __future__ import annotations

from fdai.delivery.ontology_dependents_projection import (
    build_declaration_dependents_projection,
)

DIGEST = f"sha256:{'a' * 64}"


def _topology() -> dict[str, object]:
    return {
        "ontologyReleaseDigest": DIGEST,
        "nodes": [
            {"id": "ot:Decision", "label": "Decision", "kind": "object_type"},
            {"id": "ot:EvidenceArtifact", "label": "EvidenceArtifact", "kind": "object_type"},
            {"id": "it:Reviewable", "label": "Reviewable", "kind": "interface_type"},
            {"id": "agent:Saga", "label": "Saga", "kind": "agent"},
        ],
        "edges": [
            {
                "id": "link:based_on",
                "source": "ot:Decision",
                "target": "ot:EvidenceArtifact",
                "kind": "link_type",
                "label": "based_on",
            },
            {
                "id": "interface:Decision:Reviewable",
                "source": "ot:Decision",
                "target": "it:Reviewable",
                "kind": "interface",
                "label": "implements",
            },
            {
                "id": "agent:Saga:Decision",
                "source": "agent:Saga",
                "target": "ot:Decision",
                "kind": "agent",
                "label": "owns_type",
            },
        ],
    }


def test_dependents_keep_only_topology_backed_references() -> None:
    result = build_declaration_dependents_projection(
        topology=_topology(),
        declaration_kind="object-types",
        declaration_name="Decision",
    )

    assert result["ontology_release_digest"] == DIGEST
    assert result["mutation_authority"] is False
    assert result["complete"] is True
    assert result["dependents"] == [
        {
            "kind": "agent",
            "name": "Saga",
            "relationship": "owns_object_type",
            "evidence_ref": "agent:Saga",
        },
        {
            "kind": "interface_type",
            "name": "Reviewable",
            "relationship": "implemented_by_object_type",
            "evidence_ref": "interface_type:Reviewable",
        },
        {
            "kind": "link_type",
            "name": "based_on",
            "relationship": "references_object_type",
            "evidence_ref": "LinkType:based_on",
        },
    ]


def test_dependents_report_truncation_without_inference() -> None:
    result = build_declaration_dependents_projection(
        topology=_topology(),
        declaration_kind="object-types",
        declaration_name="Decision",
        limit=1,
    )

    assert result["complete"] is False
    assert result["truncated"] is True
    assert result["truncation_reason"] == "result_limit"
    assert len(result["dependents"]) == 1
