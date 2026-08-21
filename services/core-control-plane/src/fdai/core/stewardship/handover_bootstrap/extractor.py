"""Parse explicit stewardship assignment records without interpreting prose."""

from __future__ import annotations

import re

from fdai.core.stewardship.handover_bootstrap.contract import (
    ExtractedMapping,
    HandoverDocument,
    MappingSource,
    PersonRef,
    SourceSpan,
)
from fdai.core.stewardship.model import Responsibility, StewardKind
from fdai.core.stewardship.names import AGENT_NAMES

_MAX_QUOTE = 200
_STRUCTURED_ASSIGNMENT_RE = re.compile(
    r"^agent\s*:\s*([^;]+)\s*;\s*"
    r"responsibility\s*:\s*(accountable|informed)\s*;\s*"
    r"subject\s*:\s*(user|group)\s*;\s*"
    r"identity\s*:\s*([^;\r\n]{1,256})\s*$",
    re.IGNORECASE,
)
_AGENT_NAME_BY_CASEFOLD = {name.casefold(): name for name in AGENT_NAMES}


class DeterministicExtractor:
    """Parse only the handover form's explicit machine-like assignment lines."""

    def extract(self, document: HandoverDocument) -> tuple[ExtractedMapping, ...]:
        """Return grounded structured assignments in document order."""

        mappings: list[ExtractedMapping] = []
        for line_number, raw_line in enumerate(document.text.splitlines(), start=1):
            line = raw_line.strip()
            match = _STRUCTURED_ASSIGNMENT_RE.fullmatch(line)
            if match is None:
                continue
            agent_name = _AGENT_NAME_BY_CASEFOLD.get(match.group(1).strip().casefold())
            identity = match.group(4).strip().rstrip(" .,;:")
            if agent_name is None or not identity:
                continue
            mappings.append(
                ExtractedMapping(
                    agent_name=agent_name,
                    person=PersonRef(identity, StewardKind(match.group(3).casefold())),
                    responsibility=Responsibility(match.group(2).casefold()),
                    confidence=1.0,
                    source=MappingSource.DETERMINISTIC,
                    citations=(
                        SourceSpan(
                            doc_id=document.doc_id,
                            line=line_number,
                            quote=line[:_MAX_QUOTE],
                        ),
                    ),
                    rationale="explicit structured assignment",
                )
            )
        return tuple(mappings)


__all__ = ["DeterministicExtractor"]
