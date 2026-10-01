"""Core revalidates typed slot values against its closed concept catalogs."""

from __future__ import annotations

from types import SimpleNamespace

from fdai.core.conversation.semantic_slot_grounding import reground_constraint_slots
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal
from fdai_service_contracts.semantic_slots import SemanticConstraintSlot


def _proposal(*slots: SemanticConstraintSlot) -> SemanticJudgmentProposal:
    return SemanticJudgmentProposal(
        schema_version="1.3.0",
        primary_intent="query.contextual_resources",
        confidence=0.9,
        ambiguous=False,
        action_subject="none",
        constraint_slots=slots,
    )


def _slot(role: str, value: str, *, start: int = 0) -> SemanticConstraintSlot:
    return SemanticConstraintSlot(
        role=role,
        source_start=start,
        source_end=start + 5,
        grounded=True,
        value=value,
    )


def test_location_and_lifecycle_slots_must_use_canonical_catalog_values() -> None:
    descriptors = (
        {
            "kind": "object",
            "name": "Resource",
            "properties": {
                "location": {
                    "values": ["koreacentral"],
                    "language_groups": [
                        {"id": "koreacentral", "terms": ["Korea Central", "한국 중부"]}
                    ],
                }
            },
        },
        {
            "kind": "object",
            "name": "Incident",
            "properties": {
                "status": {
                    "values": ["open", "resolved"],
                    "language_groups": [],
                    "lifecycle_state": True,
                }
            },
        },
        {
            "kind": "function",
            "name": "query.resource_state_inventory",
            "output_schema": {
                "x-fdai-measure-concepts": ["resource_state.degraded"],
            },
        },
    )
    proposal = _proposal(
        _slot("location", "koreacentral"),
        _slot("location", "Korea Central", start=6),
        _slot("lifecycle_status", "lifecycle:Incident.status=open", start=12),
        _slot("lifecycle_status", "열린", start=18),
        _slot("lifecycle_status", "resource_state.degraded", start=24),
    )

    grounded = reground_constraint_slots(
        proposal,
        manifest=SimpleNamespace(descriptors=descriptors, property_reads=()),
    )

    assert [slot.grounded for slot in grounded.constraint_slots] == [
        True,
        False,
        True,
        False,
        False,
    ]
    assert grounded.constraint_slots[1].unbound_reason == "out_of_domain"
    assert grounded.constraint_slots[3].unbound_reason == "out_of_domain"
    assert grounded.constraint_slots[4].unbound_reason == "out_of_domain"


def test_non_catalog_slot_roles_keep_their_typed_values() -> None:
    proposal = _proposal(_slot("time_window", "PT24H"))

    manifest = SimpleNamespace(descriptors=(), property_reads=())
    assert (
        reground_constraint_slots(proposal, manifest=manifest).constraint_slots
        == proposal.constraint_slots
    )
