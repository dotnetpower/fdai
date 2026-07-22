"""Deterministic structured extractor - the model-free leg of extraction.

Scans an ingested document line by line and emits grounded candidate person
-> agent mappings using the :mod:`.agent_domains` keyword catalog plus
responsibility and person/team heuristics. No model, no I/O: this is the
deterministic-first stage the bootstrap runs before consulting a
:class:`~fdai.core.stewardship.handover_bootstrap.interpreter.HandoverInterpreter`.

Every emitted mapping carries a :class:`SourceSpan` citation (the matched
line), so nothing is ungrounded. Confidence is a transparent function of the
signals found on the line; the orchestrator applies the abstain floor.
"""

from __future__ import annotations

import re

from fdai.core.stewardship.handover_bootstrap.agent_domains import match_agents
from fdai.core.stewardship.handover_bootstrap.contract import (
    ExtractedMapping,
    HandoverDocument,
    MappingSource,
    PersonRef,
    SourceSpan,
)
from fdai.core.stewardship.model import Responsibility, StewardKind
from fdai.core.stewardship.names import AGENT_NAMES

# Responsibility markers. RACI single-letter tags are matched only as bracketed
# tokens ("(A)") to avoid firing on stray letters.
_ACCOUNTABLE_MARKERS = (
    "accountable",
    "responsible",
    "owner",
    "owned by",
    "owns",
    "on-call",
    "on call",
    "primary",
    "lead",
    "(a)",
    "(r)",
)
_INFORMED_MARKERS = (
    "informed",
    "consulted",
    "stakeholder",
    "cc:",
    "(i)",
    "(c)",
)

_MAX_QUOTE = 200

# An explicit "role: Name" / "Name (Accountable)" style person cue - a stronger
# signal than a bare capitalized bigram. The role keyword is case-insensitive
# (scoped ``(?i:...)``) but the name group stays case-sensitive so it does not
# swallow trailing lowercase words ("Jane Kim is accountable" -> "Jane Kim").
_OWNER_NAME_RE = re.compile(
    r"(?i:owner|accountable|responsible|lead|owned by|primary)\s*[:\-\u2014]?\s*"
    r"([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){0,3})"
)
_TEAM_RE = re.compile(
    r"\b((?:[A-Z][\w'.-]+\s+)?(?i:team|squad|guild|group)(?:\s+[A-Z][\w'.-]+)?)\b"
)
_NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b")
_EMAIL_RE = re.compile(r"\b([a-z0-9._%+-]+)@[a-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE)
_STRUCTURED_PREFIX_RE = re.compile(r"^agent\s*:", re.IGNORECASE)
_STRUCTURED_ASSIGNMENT_RE = re.compile(
    r"^agent\s*:\s*([^;]+)\s*;\s*"
    r"responsibility\s*:\s*(accountable|informed)\s*;\s*"
    r"subject\s*:\s*(user|group)\s*;\s*"
    r"identity\s*:\s*([^;\r\n]{1,256})\s*$",
    re.IGNORECASE,
)
_AGENT_NAME_BY_CASEFOLD = {name.casefold(): name for name in AGENT_NAMES}


class DeterministicExtractor:
    """Extract grounded candidate mappings from a document without a model."""

    def extract(self, document: HandoverDocument) -> tuple[ExtractedMapping, ...]:
        """Return grounded candidate mappings, in document order."""
        mappings: list[ExtractedMapping] = []
        for index, raw_line in enumerate(document.text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            mappings.extend(self._extract_line(document, index, line))
        return tuple(mappings)

    def _extract_line(
        self, document: HandoverDocument, line_no: int, line: str
    ) -> list[ExtractedMapping]:
        if _STRUCTURED_PREFIX_RE.match(line):
            mapping = self._extract_structured(document, line_no, line)
            return [mapping] if mapping is not None else []
        lowered = line.casefold()
        agent_hits = match_agents(lowered)
        if not agent_hits:
            return []
        person, explicit_person = self._extract_person(line)
        if person is None:
            return []
        responsibility, explicit_resp = self._classify_responsibility(lowered)
        citation = SourceSpan(doc_id=document.doc_id, line=line_no, quote=line[:_MAX_QUOTE])
        results: list[ExtractedMapping] = []
        for agent_name, specificity, keyword in agent_hits:
            confidence = self._score(specificity, explicit_resp, explicit_person)
            results.append(
                ExtractedMapping(
                    agent_name=agent_name,
                    person=person,
                    responsibility=responsibility,
                    confidence=confidence,
                    source=MappingSource.DETERMINISTIC,
                    citations=(citation,),
                    rationale=f"domain keyword {keyword!r} -> {agent_name}",
                )
            )
        return results

    @staticmethod
    def _extract_structured(
        document: HandoverDocument, line_no: int, line: str
    ) -> ExtractedMapping | None:
        match = _STRUCTURED_ASSIGNMENT_RE.match(line)
        if match is None:
            return None
        agent_name = _AGENT_NAME_BY_CASEFOLD.get(match.group(1).strip().casefold())
        identity = _clean_name(match.group(4))
        if agent_name is None or not identity:
            return None
        return ExtractedMapping(
            agent_name=agent_name,
            person=PersonRef(identity, StewardKind(match.group(3).casefold())),
            responsibility=Responsibility(match.group(2).casefold()),
            confidence=1.0,
            source=MappingSource.DETERMINISTIC,
            citations=(SourceSpan(doc_id=document.doc_id, line=line_no, quote=line[:_MAX_QUOTE]),),
            rationale="explicit structured assignment",
        )

    @staticmethod
    def _extract_person(line: str) -> tuple[PersonRef | None, bool]:
        """Return ``(person, explicit)``; ``explicit`` marks a strong cue."""
        owner_match = _OWNER_NAME_RE.search(line)
        if owner_match:
            return PersonRef(_clean_name(owner_match.group(1)), StewardKind.USER), True
        team_match = _TEAM_RE.search(line)
        if team_match:
            return PersonRef(_clean_name(team_match.group(1)), StewardKind.GROUP), True
        email_match = _EMAIL_RE.search(line)
        if email_match:
            return PersonRef(email_match.group(1).strip(), StewardKind.USER), True
        name_match = _NAME_RE.search(line)
        if name_match:
            return PersonRef(_clean_name(name_match.group(1)), StewardKind.USER), False
        return None, False

    @staticmethod
    def _classify_responsibility(lowered: str) -> tuple[Responsibility, bool]:
        """Return ``(responsibility, explicit_marker_present)``."""
        if any(marker in lowered for marker in _INFORMED_MARKERS):
            return Responsibility.INFORMED, True
        if any(marker in lowered for marker in _ACCOUNTABLE_MARKERS):
            return Responsibility.ACCOUNTABLE, True
        # No explicit marker: default to accountable (a named owner in an ops
        # doc is accountable unless flagged informed) but mark it non-explicit
        # so the confidence score stays lower.
        return Responsibility.ACCOUNTABLE, False

    @staticmethod
    def _score(specificity: float, explicit_resp: bool, explicit_person: bool) -> float:
        confidence = 0.45 + specificity * 0.25
        if explicit_resp:
            confidence += 0.2
        if explicit_person:
            confidence += 0.15
        return round(min(confidence, 1.0), 3)


def _clean_name(raw: str) -> str:
    """Trim surrounding whitespace and trailing sentence punctuation.

    The name character class allows ``.`` / ``-`` (for initials and
    hyphenated names), so a name at a sentence end can capture a trailing
    period; strip it so ``"Sam Lee."`` resolves as ``"Sam Lee"``.
    """
    return raw.strip().rstrip(" .,;:")


__all__ = ["DeterministicExtractor"]
