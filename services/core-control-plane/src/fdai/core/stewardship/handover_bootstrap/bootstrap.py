"""Handover-bootstrap orchestrator - documents in, a reviewable draft out.

Ties the deterministic-first pipeline together (issue #23):

1. Run the :class:`~fdai.core.stewardship.handover_bootstrap.extractor.DeterministicExtractor`
   on every document (model-free, grounded).
2. Consult the injected
   :class:`~fdai.core.stewardship.handover_bootstrap.interpreter.HandoverInterpreter`
   (the upstream default abstains) for grounded model proposals.
3. Resolve each mentioned person to an Entra object id through the injected
   :class:`~fdai.core.stewardship.handover_bootstrap.people.PersonDirectory`;
   unresolved names are flagged, never guessed.
4. Split by a confidence floor: above-floor grounded mappings land in the
   draft, below-floor ones are set aside for a human, and agents with no
   confident owner are surfaced as ``unmapped``.

The result is a :class:`StewardMapDraft` - it is never applied. The delivery
layer renders it as a governance draft PR a human reviews and merges.
"""

from __future__ import annotations

from fdai.core.stewardship.handover_bootstrap.contract import (
    DraftOutcome,
    ExtractedMapping,
    HandoverDocument,
    PersonRef,
    StewardMapDraft,
)
from fdai.core.stewardship.handover_bootstrap.extractor import DeterministicExtractor
from fdai.core.stewardship.handover_bootstrap.interpreter import (
    AbstainingInterpreter,
    HandoverInterpreter,
)
from fdai.core.stewardship.handover_bootstrap.people import (
    NullPersonDirectory,
    PersonDirectory,
)
from fdai.core.stewardship.model import Responsibility
from fdai.core.stewardship.names import AGENT_NAMES

_DEFAULT_CONFIDENCE_FLOOR = 0.6


class HandoverBootstrapper:
    """Orchestrate document -> draft steward-map extraction."""

    def __init__(
        self,
        *,
        extractor: DeterministicExtractor | None = None,
        interpreter: HandoverInterpreter | None = None,
        directory: PersonDirectory | None = None,
        confidence_floor: float = _DEFAULT_CONFIDENCE_FLOOR,
    ) -> None:
        if not 0.0 <= confidence_floor <= 1.0:
            raise ValueError("confidence_floor MUST be in [0, 1]")
        self._extractor = extractor or DeterministicExtractor()
        self._interpreter = interpreter or AbstainingInterpreter()
        self._directory = directory or NullPersonDirectory()
        self._floor = confidence_floor

    async def bootstrap(
        self, documents: tuple[HandoverDocument, ...], *, version: int = 1
    ) -> StewardMapDraft:
        """Produce a reviewable :class:`StewardMapDraft` from ``documents``."""
        candidates: list[ExtractedMapping] = []
        for document in documents:
            candidates.extend(self._extractor.extract(document))
            candidates.extend(self._grounded(await self._interpreter.interpret(document)))

        resolved = await self._resolve_identities(candidates)
        deduped = _dedupe_highest_confidence(resolved)

        mappings = tuple(m for m in deduped if m.confidence >= self._floor)
        abstained = tuple(m for m in deduped if m.confidence < self._floor)
        unresolved = _distinct_unresolved(mappings)
        unmapped = _unmapped_agents(mappings)
        outcome = DraftOutcome.DRAFTED if mappings else DraftOutcome.ABSTAINED
        return StewardMapDraft(
            version=version,
            outcome=outcome,
            mappings=mappings,
            abstained=abstained,
            unresolved_people=unresolved,
            unmapped_agents=unmapped,
            warnings=_warnings(mappings, abstained, unresolved, unmapped),
        )

    @staticmethod
    def _grounded(proposals: tuple[ExtractedMapping, ...]) -> tuple[ExtractedMapping, ...]:
        """Drop any model proposal that is not grounded (defense in depth)."""
        return tuple(m for m in proposals if m.grounded)

    async def _resolve_identities(
        self, candidates: list[ExtractedMapping]
    ) -> list[ExtractedMapping]:
        cache: dict[str, PersonRef] = {}
        out: list[ExtractedMapping] = []
        for mapping in candidates:
            key = mapping.person.display_name.strip().casefold()
            person = cache.get(key)
            if person is None:
                identity = await self._directory.resolve(mapping.person.display_name)
                person = (
                    mapping.person
                    if identity is None
                    else PersonRef(
                        display_name=mapping.person.display_name,
                        kind=identity.kind,
                        oid=identity.oid,
                    )
                )
                cache[key] = person
            out.append(
                ExtractedMapping(
                    agent_name=mapping.agent_name,
                    person=person,
                    responsibility=mapping.responsibility,
                    confidence=mapping.confidence,
                    source=mapping.source,
                    citations=mapping.citations,
                    rationale=mapping.rationale,
                )
            )
        return out


def _dedupe_highest_confidence(
    mappings: list[ExtractedMapping],
) -> tuple[ExtractedMapping, ...]:
    """Collapse duplicate (agent, person, responsibility) to the best confidence."""
    best: dict[tuple[str, str, str], ExtractedMapping] = {}
    for mapping in mappings:
        key = (
            mapping.agent_name,
            mapping.person.display_name.strip().casefold(),
            mapping.responsibility.value,
        )
        current = best.get(key)
        if current is None or mapping.confidence > current.confidence:
            best[key] = mapping
    return tuple(
        sorted(best.values(), key=lambda m: (m.agent_name, -m.confidence, m.person.display_name))
    )


def _distinct_unresolved(mappings: tuple[ExtractedMapping, ...]) -> tuple[PersonRef, ...]:
    seen: dict[str, PersonRef] = {}
    for mapping in mappings:
        if mapping.person.unresolved:
            seen.setdefault(mapping.person.display_name.strip().casefold(), mapping.person)
    return tuple(seen.values())


def _unmapped_agents(mappings: tuple[ExtractedMapping, ...]) -> tuple[str, ...]:
    """Pantheon agents with no confident **accountable** mapping."""
    owned = {m.agent_name for m in mappings if m.responsibility is Responsibility.ACCOUNTABLE}
    return tuple(name for name in AGENT_NAMES if name not in owned)


def _warnings(
    mappings: tuple[ExtractedMapping, ...],
    abstained: tuple[ExtractedMapping, ...],
    unresolved: tuple[PersonRef, ...],
    unmapped: tuple[str, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if abstained:
        warnings.append(
            f"{len(abstained)} candidate mapping(s) below the confidence floor were set "
            "aside for human review"
        )
    if unresolved:
        warnings.append(
            f"{len(unresolved)} person/team name(s) did not resolve to an Entra object id"
        )
    if unmapped:
        warnings.append(
            f"{len(unmapped)} agent(s) have no confident accountable owner and need a manual "
            "steward or accept_autonomous"
        )
    if not mappings:
        warnings.append("no mapping cleared the confidence floor; nothing was drafted")
    return tuple(warnings)


__all__ = ["HandoverBootstrapper"]
