"""Real catalog candidate selection stays exact, bounded, and principal-scoped."""

from fdai.composition.semantic_query_descriptor_selector import ManifestDescriptorIndex
from fdai.core.conversation.semantic_planning_judgment import _descriptors_for_judgment
from fdai.core.ontology_platform.query_manifest import build_query_manifest
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal


def test_large_release_selects_matching_declaration_without_512_cliff() -> None:
    declarations = tuple(
        OntologyObjectType(
            schema_version="1.0.0",
            name=f"Object{index}",
            version="1.0.0",
            key="id",
            properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
        )
        for index in range(600)
    )
    release = build_ontology_release(object_types=declarations)
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
        object_types=declarations,
    )
    selector = ManifestDescriptorIndex()
    selected = selector.select(utterance="Object599", manifest=manifest, limit=512)
    assert len(selected) == 96
    assert selected[0]["name"] == "Object599"
    assert all(descriptor in manifest.descriptors for descriptor in selected)
    assert selector.select(utterance="Object599", manifest=manifest, limit=512) == selected


def test_candidate_index_never_exposes_hidden_properties() -> None:
    declaration = OntologyObjectType(
        schema_version="1.0.0",
        name="Example",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "private_note": PropertyDecl(type=PropertyType.STRING, access_scope=CeilingRole.OWNER),
        },
    )
    release = build_ontology_release(object_types=(declaration,))
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "b" * 64,
        object_types=(declaration,),
    )
    selected = ManifestDescriptorIndex().select(
        utterance="private_note", manifest=manifest, limit=20
    )
    assert "private_note" not in selected[0]["properties"]


def test_secondary_intents_keep_their_descriptors() -> None:
    names = (
        "Resource",
        "query.resource_current_state",
        "query.subscription_service_health",
        "unrelated",
    )
    descriptors = tuple({"kind": "function", "name": name} for name in names)
    judgment = SemanticJudgmentProposal(
        primary_intent="query.resource_current_state",
        secondary_intents=("query.subscription_service_health",),
        targets=(),
        requested_facets=(),
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
    )
    assert {item["name"] for item in _descriptors_for_judgment(descriptors, judgment)} == set(
        names[:-1]
    )


def test_complete_small_manifest_is_not_reduced_to_candidate_limit() -> None:
    declarations = tuple(
        OntologyObjectType(
            schema_version="1.0.0",
            name=f"Example{index}",
            version="1.0.0",
            key="id",
            properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
        )
        for index in range(10)
    )
    manifest = build_query_manifest(
        release=build_ontology_release(object_types=declarations),
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "c" * 64,
        object_types=declarations,
    )
    assert (
        len(
            ManifestDescriptorIndex(candidate_limit=2).select(
                utterance="Example9", manifest=manifest, limit=512
            )
        )
        == 10
    )
