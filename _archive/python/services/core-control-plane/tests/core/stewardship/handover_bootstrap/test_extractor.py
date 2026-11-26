"""Deterministic handover-document extractor tests."""

from __future__ import annotations

from fdai.core.stewardship.handover_bootstrap import (
    DeterministicExtractor,
    DocumentKind,
    HandoverDocument,
)
from fdai.core.stewardship.model import Responsibility, StewardKind
from fdai.core.stewardship.names import AGENT_NAME_SET


def _doc(text: str, *, kind: DocumentKind = DocumentKind.RACI) -> HandoverDocument:
    return HandoverDocument(doc_id="doc-1", kind=kind, text=text)


def test_unstructured_human_prose_requires_the_injected_interpreter() -> None:
    extractor = DeterministicExtractor()
    for text in (
        "Cost governance owner: Jane Kim is accountable for spend.",
        "Monitoring dashboards - consulted: Platform Team",
        "Rollback owner: Alex Park handles failover.",
        "FinOps budget owned by jane.kim@example.com",
    ):
        assert extractor.extract(_doc(text)) == ()


def test_explicit_agent_tags_cover_the_fixed_pantheon() -> None:
    lines = [
        f"Agent: {name}; responsibility: accountable; subject: user; identity: Jane Kim"
        for name in sorted(AGENT_NAME_SET)
    ]
    mappings = DeterministicExtractor().extract(_doc("\n".join(lines)))

    assert [mapping.agent_name for mapping in mappings] == sorted(AGENT_NAME_SET)
    assert all(mapping.person.display_name == "Jane Kim" for mapping in mappings)
    assert all(mapping.confidence >= 0.9 for mapping in mappings)


def test_explicit_subject_tag_preserves_arbitrary_group_name() -> None:
    mappings = DeterministicExtractor().extract(
        _doc(
            "Agent: Heimdall; responsibility: informed; subject: group; identity: Cloud Operations"
        )
    )

    assert len(mappings) == 1
    assert mappings[0].person.display_name == "Cloud Operations"
    assert mappings[0].person.kind is StewardKind.GROUP
    assert mappings[0].responsibility is Responsibility.INFORMED


def test_structured_identity_cannot_add_agents_or_override_responsibility() -> None:
    mappings = DeterministicExtractor().extract(
        _doc(
            "Agent: Odin; responsibility: accountable; "
            "subject: group; identity: FinOps Monitoring Informed Team"
        )
    )

    assert len(mappings) == 1
    assert mappings[0].agent_name == "Odin"
    assert mappings[0].person.display_name == "FinOps Monitoring Informed Team"
    assert mappings[0].responsibility is Responsibility.ACCOUNTABLE


def test_malformed_or_unknown_structured_assignment_fails_closed() -> None:
    extractor = DeterministicExtractor()

    assert (
        extractor.extract(
            _doc(
                "Agent: Unknown; responsibility: accountable; "
                "subject: group; identity: FinOps Monitoring Team"
            )
        )
        == ()
    )
    assert extractor.extract(_doc("Agent: Odin; subject: user; identity: Monitoring Owner")) == ()


def test_unknown_agent_tag_does_not_create_a_mapping() -> None:
    assert (
        DeterministicExtractor().extract(_doc("Agent: Unknown; accountable owner: Jane Kim.")) == ()
    )
