"""Handover-bootstrap orchestration + draft-YAML round-trip tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
import yaml
from fdai.core.stewardship.handover_bootstrap import (
    DocumentKind,
    DraftOutcome,
    ExtractedMapping,
    HandoverBootstrapper,
    HandoverDocument,
    MappingSource,
    PersonRef,
    ResolvedIdentity,
    SourceSpan,
    StaticPersonDirectory,
    render_draft_yaml,
)
from fdai.core.stewardship.model import Responsibility, StewardKind
from fdai.core.stewardship.names import AGENT_NAMES
from fdai.core.stewardship.resolver import load_stewardship_from_mapping

_JANE_OID = "00000000-0000-0000-0000-000000000101"
_ALEX_OID = "00000000-0000-0000-0000-000000000102"


def _docs() -> tuple[HandoverDocument, ...]:
    text = "\n".join(
        [
            "Agent: Njord; responsibility: accountable; subject: user; identity: Jane Kim",
            "Agent: Vidar; responsibility: accountable; subject: user; identity: Alex Park",
            "Agent: Loki; responsibility: accountable; subject: user; identity: Sam Lee",
        ]
    )
    return (HandoverDocument(doc_id="raci-1", kind=DocumentKind.RACI, text=text),)


def _directory() -> StaticPersonDirectory:
    return StaticPersonDirectory(
        {
            "Jane Kim": ResolvedIdentity(_JANE_OID, StewardKind.USER),
            "Alex Park": ResolvedIdentity(_ALEX_OID, StewardKind.USER),
            # Sam Lee intentionally unresolved.
        }
    )


async def test_bootstrap_resolves_flags_and_surfaces() -> None:
    draft = await HandoverBootstrapper(directory=_directory()).bootstrap(_docs())
    assert draft.outcome is DraftOutcome.DRAFTED
    agents = {m.agent_name for m in draft.mappings}
    assert {"Njord", "Vidar", "Loki"} <= agents

    njord = next(m for m in draft.mappings if m.agent_name == "Njord")
    assert njord.person.oid == _JANE_OID
    assert not njord.person.unresolved

    # Sam Lee did not resolve -> surfaced, never guessed into an id.
    unresolved_names = {p.display_name for p in draft.unresolved_people}
    assert "Sam Lee" in unresolved_names
    loki = next(m for m in draft.mappings if m.agent_name == "Loki")
    assert loki.person.unresolved

    # Agents with no confident owner are surfaced for manual handling.
    assert "Odin" in draft.unmapped_agents
    assert "Njord" not in draft.unmapped_agents


async def test_low_confidence_is_set_aside_not_applied() -> None:
    class _LowConfidenceInterpreter:
        async def interpret(self, document: HandoverDocument) -> tuple[ExtractedMapping, ...]:
            return (
                ExtractedMapping(
                    agent_name="Vidar",
                    person=PersonRef("Alex Park", StewardKind.USER),
                    responsibility=Responsibility.ACCOUNTABLE,
                    confidence=0.7,
                    source=MappingSource.MODEL,
                    citations=(SourceSpan(document.doc_id, 1, document.text),),
                    rationale="model proposal below configured floor",
                ),
            )

    doc = HandoverDocument(
        doc_id="memo-2",
        kind=DocumentKind.OTHER,
        text="Rollback and failover: Alex Park",
    )
    draft = await HandoverBootstrapper(
        directory=_directory(),
        interpreter=_LowConfidenceInterpreter(),
        confidence_floor=0.8,
    ).bootstrap((doc,))
    assert draft.outcome is DraftOutcome.ABSTAINED
    assert draft.mappings == ()
    assert draft.abstained
    assert any("nothing was drafted" in w for w in draft.warnings)


async def test_default_interpreter_abstains_no_model_guesses() -> None:
    # A document with no deterministic signal + the default abstaining
    # interpreter yields an empty, non-guessing draft.
    doc = HandoverDocument(
        doc_id="memo-1", kind=DocumentKind.HANDOVER_MEMO, text="Team offsite next Friday."
    )
    draft = await HandoverBootstrapper(directory=_directory()).bootstrap((doc,))
    assert draft.outcome is DraftOutcome.ABSTAINED
    assert draft.mappings == ()


class _FakeInterpreter:
    """A grounded model that proposes one mapping deterministic extraction missed."""

    async def interpret(self, document: HandoverDocument) -> tuple[ExtractedMapping, ...]:
        return (
            ExtractedMapping(
                agent_name="Bragi",
                person=PersonRef("Dana Cho", StewardKind.USER),
                responsibility=Responsibility.ACCOUNTABLE,
                confidence=0.82,
                source=MappingSource.MODEL,
                citations=(SourceSpan(document.doc_id, 1, document.text),),
                rationale="model: status comms owner",
            ),
        )


async def test_model_proposals_merge_when_grounded() -> None:
    draft = await HandoverBootstrapper(
        directory=_directory(), interpreter=_FakeInterpreter()
    ).bootstrap(
        (
            HandoverDocument(
                doc_id="memo-model",
                kind=DocumentKind.HANDOVER_MEMO,
                text="Bragi status updates to stakeholders are handled by Dana Cho.",
            ),
        )
    )
    bragi = next((m for m in draft.mappings if m.agent_name == "Bragi"), None)
    assert bragi is not None
    assert bragi.source is MappingSource.MODEL
    assert bragi.grounded


@pytest.mark.parametrize(
    "substitution", ["document", "line", "quote", "person", "agent", "confidence", "identity"]
)
async def test_model_mapping_requires_actual_document_grounding(substitution: str) -> None:
    document = HandoverDocument(
        doc_id="model-memo",
        kind=DocumentKind.HANDOVER_MEMO,
        text="Bragi status updates to stakeholders are handled by Dana Cho.",
    )
    mapping = (await _FakeInterpreter().interpret(document))[0]
    updates = {
        "document": {"citations": (SourceSpan("other-memo", 1, document.text),)},
        "line": {"citations": (SourceSpan(document.doc_id, 2, document.text),)},
        "quote": {"citations": (SourceSpan(document.doc_id, 1, "Invented quotation."),)},
        "person": {"person": PersonRef("Invented Person")},
        "agent": {"agent_name": "InventedAgent"},
        "confidence": {"confidence": float("nan")},
        "identity": {"person": PersonRef("Dana Cho", oid=_JANE_OID)},
    }

    class Interpreter:
        async def interpret(self, _document: HandoverDocument) -> tuple[ExtractedMapping, ...]:
            return (replace(mapping, **updates[substitution]),)

    draft = await HandoverBootstrapper(interpreter=Interpreter()).bootstrap((document,))
    assert draft.outcome is DraftOutcome.ABSTAINED
    assert draft.mappings == ()
    assert draft.unresolved_people == ()


async def test_draft_yaml_round_trips_through_the_resolver() -> None:
    draft = await HandoverBootstrapper(directory=_directory()).bootstrap(_docs())
    text = render_draft_yaml(draft)
    raw = yaml.safe_load(text)
    # Non-fork load so placeholder ids for unresolved people are accepted.
    steward_map = load_stewardship_from_mapping(raw, environ={})

    assert set(steward_map.agents) == set(AGENT_NAMES)
    njord = steward_map.agent("Njord")
    assert _JANE_OID in njord.accountable_user_ids

    # An unmapped agent became accept_autonomous, not a silent gap.
    assert steward_map.agent("Odin").is_autonomous


async def test_draft_yaml_carries_citation_comments() -> None:
    draft = await HandoverBootstrapper(directory=_directory()).bootstrap(_docs())
    text = render_draft_yaml(draft)
    assert "raci-1:L1" in text
    assert "Jane Kim" in text
    assert "UNRESOLVED" in text  # Sam Lee flagged inline
    assert "DRAFT" in text


async def test_handover_bootstrap_hardening_rounds_h017_to_h025() -> None:
    from fdai.core.stewardship.handover_bootstrap.draft_yaml import render_candidate_yaml

    # H017-H020: contract & people validation
    with pytest.raises(ValueError, match="HandoverDocument"):
        HandoverDocument(doc_id="   ", kind=DocumentKind.RACI, text="x")
    with pytest.raises(ValueError, match="1-based positive integer"):
        SourceSpan(doc_id="d1", line=0, quote="q")
    with pytest.raises(ValueError, match="ResolvedIdentity"):
        ResolvedIdentity(oid="   ")
    with pytest.raises(ValueError, match="confidence_floor"):
        HandoverBootstrapper(confidence_floor=True)

    # H021: long structured line segmented into <=200-char citations and whitespace normalized
    long_name = "Jane   " + ("K" * 180)
    doc = HandoverDocument(
        doc_id="raci-long",
        kind=DocumentKind.RACI,
        text=f"Agent: Njord; responsibility: accountable; subject: user; identity: {long_name}",
    )
    draft = await HandoverBootstrapper(directory=_directory()).bootstrap((doc,))
    assert len(draft.mappings) == 1
    assert len(draft.mappings[0].citations) >= 2
    assert "  " not in draft.mappings[0].person.display_name

    # H022-H025: candidate YAML preserves v2 duty and sanitizes comment newlines
    seeded_draft = await HandoverBootstrapper(directory=_directory()).bootstrap(_docs())
    base_raw = yaml.safe_load(render_draft_yaml(seeded_draft))
    base_map = load_stewardship_from_mapping(base_raw, environ={})
    candidate_text = render_candidate_yaml(draft, base=base_map)
    assert load_stewardship_from_mapping(yaml.safe_load(candidate_text), environ={}).version == 1
