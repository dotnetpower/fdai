"""Deterministic handover-document extractor tests."""

from __future__ import annotations

from fdai.core.stewardship.handover_bootstrap import (
    DeterministicExtractor,
    DocumentKind,
    HandoverDocument,
    MappingSource,
)
from fdai.core.stewardship.handover_bootstrap.agent_domains import (
    AGENT_DOMAINS,
    match_agents,
)
from fdai.core.stewardship.model import Responsibility, StewardKind
from fdai.core.stewardship.names import AGENT_NAME_SET


def _doc(text: str, *, kind: DocumentKind = DocumentKind.RACI) -> HandoverDocument:
    return HandoverDocument(doc_id="doc-1", kind=kind, text=text)


def test_domain_catalog_covers_exactly_the_pantheon() -> None:
    assert frozenset(AGENT_DOMAINS) == AGENT_NAME_SET


def test_match_agents_returns_longest_keyword_hit() -> None:
    hits = match_agents("our cost governance program tracks spend")
    agents = {name for name, _spec, _kw in hits}
    assert "Njord" in agents
    njord = next(kw for name, _spec, kw in hits if name == "Njord")
    assert njord == "cost governance"


def test_extracts_grounded_accountable_owner() -> None:
    doc = _doc("Cost governance owner: Jane Kim is accountable for spend.")
    mappings = DeterministicExtractor().extract(doc)
    assert len(mappings) == 1
    mapping = mappings[0]
    assert mapping.agent_name == "Njord"
    assert mapping.person.display_name == "Jane Kim"
    assert mapping.person.kind is StewardKind.USER
    assert mapping.responsibility is Responsibility.ACCOUNTABLE
    assert mapping.source is MappingSource.DETERMINISTIC
    assert mapping.grounded
    assert mapping.citations[0].doc_id == "doc-1"
    assert mapping.citations[0].line == 1
    assert mapping.confidence >= 0.9


def test_team_mention_is_a_group_subject_and_informed() -> None:
    doc = _doc("Monitoring dashboards - consulted: Platform Team")
    mappings = DeterministicExtractor().extract(doc)
    assert mappings
    mapping = mappings[0]
    assert mapping.agent_name == "Heimdall"
    assert mapping.person.kind is StewardKind.GROUP
    assert mapping.responsibility is Responsibility.INFORMED


def test_line_without_domain_keyword_yields_nothing() -> None:
    doc = _doc("Weekly sync every Monday at 10am with the whole crew.")
    assert DeterministicExtractor().extract(doc) == ()


def test_bare_name_without_explicit_cue_scores_lower() -> None:
    explicit = DeterministicExtractor().extract(
        _doc("Rollback owner: Alex Park handles failover.")
    )[0]
    bare = DeterministicExtractor().extract(_doc("Rollback and failover: Alex Park"))[0]
    assert explicit.confidence > bare.confidence
    assert explicit.agent_name == bare.agent_name == "Vidar"


def test_email_local_part_is_a_user_subject() -> None:
    doc = _doc("FinOps budget owned by jane.kim@example.com")
    mappings = DeterministicExtractor().extract(doc)
    assert mappings
    assert mappings[0].person.display_name == "jane.kim"
    assert mappings[0].person.kind is StewardKind.USER


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
