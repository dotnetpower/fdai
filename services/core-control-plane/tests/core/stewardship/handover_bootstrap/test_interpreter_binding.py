"""HandoverInterpreter deployment binding: the seam proposes, it never applies."""

from __future__ import annotations

import pytest
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
)
from fdai.core.stewardship.handover_bootstrap.interpreter import (
    AbstainingInterpreter,
    HandoverInterpreter,
)
from fdai.core.stewardship.model import Responsibility, StewardKind

_RIA_OID = "00000000-0000-0000-0000-000000000201"


def _document(text: str = "Cost governance owner: Ria Han is accountable.") -> HandoverDocument:
    return (HandoverDocument(doc_id="doc-1", kind=DocumentKind.RACI, text=text),)[0]


def _directory() -> StaticPersonDirectory:
    return StaticPersonDirectory({"Ria Han": ResolvedIdentity(_RIA_OID, StewardKind.USER)})


def _proposal(
    *,
    agent_name: str = "Njord",
    display_name: str = "Ria Han",
    confidence: float = 0.9,
    citations: tuple[SourceSpan, ...] | None = None,
) -> ExtractedMapping:
    return ExtractedMapping(
        agent_name=agent_name,
        person=PersonRef(display_name=display_name),
        responsibility=Responsibility.ACCOUNTABLE,
        confidence=confidence,
        source=MappingSource.MODEL,
        citations=(
            citations
            if citations is not None
            else (SourceSpan(doc_id="doc-1", line=1, quote="Cost governance owner"),)
        ),
    )


class _StubInterpreter:
    """A deployment-bound adaptive interpreter stand-in."""

    def __init__(self, *proposals: ExtractedMapping) -> None:
        self.documents: list[HandoverDocument] = []
        self._proposals = proposals

    async def interpret(self, document: HandoverDocument) -> tuple[ExtractedMapping, ...]:
        self.documents.append(document)
        return self._proposals


# ---------------------------------------------------------------------------
# Upstream default
# ---------------------------------------------------------------------------


def test_the_upstream_default_satisfies_the_seam_and_abstains() -> None:
    assert isinstance(AbstainingInterpreter(), HandoverInterpreter)


@pytest.mark.asyncio
async def test_an_unbound_deployment_stays_deterministic() -> None:
    draft = await HandoverBootstrapper(directory=_directory()).bootstrap(
        (_document("No ownership cue here."),)
    )

    assert draft.outcome is DraftOutcome.ABSTAINED
    assert draft.mappings == ()


# ---------------------------------------------------------------------------
# Bound adaptive interpreter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_bound_interpreter_is_consulted_for_every_document() -> None:
    interpreter = _StubInterpreter()
    documents = (_document(), _document("Second document."))

    await HandoverBootstrapper(interpreter=interpreter, directory=_directory()).bootstrap(documents)

    assert len(interpreter.documents) == 2


@pytest.mark.asyncio
async def test_a_grounded_proposal_reaches_the_draft_and_resolves_identity() -> None:
    draft = await HandoverBootstrapper(
        interpreter=_StubInterpreter(_proposal()),
        directory=_directory(),
    ).bootstrap((_document("No deterministic cue."),))

    proposed = next(mapping for mapping in draft.mappings if mapping.agent_name == "Njord")
    assert proposed.source is MappingSource.MODEL
    assert proposed.person.oid == _RIA_OID


@pytest.mark.asyncio
async def test_an_ungrounded_proposal_is_dropped() -> None:
    draft = await HandoverBootstrapper(
        interpreter=_StubInterpreter(_proposal(citations=())),
        directory=_directory(),
    ).bootstrap((_document("No deterministic cue."),))

    assert draft.mappings == ()
    assert draft.abstained == ()


@pytest.mark.asyncio
async def test_a_low_confidence_proposal_is_set_aside_for_a_human() -> None:
    draft = await HandoverBootstrapper(
        interpreter=_StubInterpreter(_proposal(confidence=0.2)),
        directory=_directory(),
    ).bootstrap((_document("No deterministic cue."),))

    assert draft.mappings == ()
    assert [mapping.agent_name for mapping in draft.abstained] == ["Njord"]


@pytest.mark.asyncio
async def test_a_proposal_never_invents_an_identity() -> None:
    draft = await HandoverBootstrapper(
        interpreter=_StubInterpreter(_proposal(display_name="Nobody Here")),
        directory=_directory(),
    ).bootstrap((_document("No deterministic cue."),))

    proposed = next(mapping for mapping in draft.mappings if mapping.agent_name == "Njord")
    assert proposed.person.unresolved
    assert "Nobody Here" in {person.display_name for person in draft.unresolved_people}


@pytest.mark.asyncio
async def test_a_draft_is_never_applied() -> None:
    draft = await HandoverBootstrapper(
        interpreter=_StubInterpreter(_proposal()),
        directory=_directory(),
    ).bootstrap((_document(),))

    assert not hasattr(draft, "applied")
    assert not hasattr(draft, "apply")
