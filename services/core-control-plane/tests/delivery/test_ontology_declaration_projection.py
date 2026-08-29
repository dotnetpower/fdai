"""Focused declaration-detail projection tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.delivery.ontology_declaration_projection import (
    build_action_type_detail_projection,
    build_link_type_detail_projection,
    build_object_type_detail_projection,
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog, load_ontology_catalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.shared.contracts.models import (
    CeilingRole,
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]


def _shipped_catalog() -> OntologyCatalog:
    return load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )


def test_decision_detail_preserves_exact_identity_and_relationship_direction() -> None:
    catalog = _shipped_catalog()

    detail = build_object_type_detail_projection(
        ontology=catalog,
        name="Decision",
        role=CeilingRole.READER,
        purpose="operations-review",
    )

    declaration = detail["declaration"]
    assert isinstance(declaration, dict)
    assert declaration["name"] == "Decision"
    assert declaration["version"] == "1.1.0"
    assert declaration["key"] == "id"
    assert list(declaration["properties"]) == [
        "approval_receipt_refs",
        "approver_ids",
        "arbitrator_id",
        "audit_intent_ref",
        "authority_basis",
        "authority_ref",
        "catalog_release",
        "change_id",
        "conditions",
        "context_snapshot_id",
        "decision_case_id",
        "effective_from",
        "effective_until",
        "evidence_bundle_id",
        "evidence_refs",
        "execution_authority",
        "graph_revision",
        "id",
        "impact_envelope_id",
        "judge_id",
        "outcome",
        "quorum",
        "rationale",
        "receipt_digest",
        "receipt_schema_version",
        "recorded_at",
        "reevaluation_trigger",
        "requester_id",
        "review_case_id",
        "target_revision",
        "terminal_audit_ref",
    ]
    assert declaration["lifecycle"] if "lifecycle" in declaration else None is None
    assert detail["ontology_release_digest"] == catalog.build_release().digest
    assert detail["mutation_authority"] is False
    assert str(detail["_revision"]).startswith("sha256:")
    directions = {
        (relationship["name"], relationship["selected_type_direction"])
        for relationship in detail["relationships"]
    }
    assert ("based_on", "outgoing") in directions
    assert ("resolved_by", "incoming") in directions


def test_property_redaction_and_self_direction_are_server_owned() -> None:
    object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "operator_note": PropertyDecl(
                type=PropertyType.STRING,
                access_scope=CeilingRole.APPROVER,
            ),
            "private_context": PropertyDecl(
                type=PropertyType.STRING,
                access_scope=CeilingRole.OWNER,
                purpose_binding=["user_context"],
            ),
        },
    )
    self_link = OntologyLinkType(
        schema_version="1.0.0",
        name="depends_on",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    catalog = OntologyCatalog(
        object_types=(object_type,),
        interface_types=(),
        interface_implementations=(),
        link_types=(self_link,),
        action_types=(),
        property_semantics=empty_property_semantic_registry(),
    )

    detail = build_object_type_detail_projection(
        ontology=catalog,
        name="Resource",
        role=CeilingRole.READER,
        purpose="operations-review",
    )

    declaration = detail["declaration"]
    assert isinstance(declaration, dict)
    assert list(declaration["properties"]) == ["id"]
    assert detail["redaction"] == {
        "redacted_field_count": 2,
        "reasons": ["purpose", "role"],
    }
    assert detail["relationships"][0]["selected_type_direction"] == "self"


def test_projection_rejects_a_stale_expected_release() -> None:
    with pytest.raises(ValueError, match="does not match active release"):
        build_object_type_detail_projection(
            ontology=_shipped_catalog(),
            name="Decision",
            role=CeilingRole.READER,
            purpose="operations-review",
            expected_release_digest=f"sha256:{'0' * 64}",
        )


def test_link_and_action_details_keep_exact_contracts_without_authority() -> None:
    catalog = _shipped_catalog()

    link_detail = build_link_type_detail_projection(
        ontology=catalog,
        name="based_on",
    )
    action_detail = build_action_type_detail_projection(
        ontology=catalog,
        name=catalog.action_types[0].name,
    )

    assert link_detail["declaration_kind"] == "link_type"
    assert link_detail["declaration"]["from_type"] == "Decision"
    assert link_detail["declaration"]["to_type"] == "EvidenceArtifact"
    assert link_detail["mutation_authority"] is False
    assert action_detail["declaration_kind"] == "action_type"
    assert action_detail["declaration"]["rollback_contract"]
    assert action_detail["declaration"]["stop_conditions"] is not None
    assert action_detail["mutation_authority"] is False
