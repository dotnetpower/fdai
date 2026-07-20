"""Fail-closed export scanner for secrets, identifiers, and prompt injection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdai.core.operator_memory.sanitizer import detect_injection_markers
from fdai.core.trajectory.models import TrajectoryEnvelope
from fdai.core.trajectory.serialization import canonical_json_bytes, envelope_to_mapping

_SECRET_PATTERNS: Final = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~-]{12,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|client[_-]?secret|password)\s*[:=]\s*\S+"),
    re.compile(r"(?i)[?&](?:sig|se|sp|sv|token)=[^&\s]+"),
)
_GUID_PATTERN: Final = re.compile(
    r"\b(?!0{8}-0{4}-0{4}-0{4}-0{12})[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_RESOURCE_ID_PATTERN: Final = re.compile(r"(?i)/subscriptions/[^/\s]+/")
_EMAIL_PATTERN: Final = re.compile(
    r"\b[A-Za-z0-9._%+-]+@(?!example\.com\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)


class ScanFindingKind(StrEnum):
    SENSITIVE = "secret"
    IDENTIFIER = "identifier"
    PROMPT_INJECTION = "prompt_injection"


@dataclass(frozen=True, slots=True)
class ScanFinding:
    kind: ScanFindingKind
    code: str


def scan_envelope(envelope: TrajectoryEnvelope) -> tuple[ScanFinding, ...]:
    """Return findings without echoing the matched sensitive value."""

    raw = canonical_json_bytes(envelope_to_mapping(envelope)).decode()
    findings: list[ScanFinding] = []
    if any(pattern.search(raw) for pattern in _SECRET_PATTERNS):
        findings.append(ScanFinding(ScanFindingKind.SENSITIVE, "secret_pattern"))
    if _GUID_PATTERN.search(raw) or _RESOURCE_ID_PATTERN.search(raw) or _EMAIL_PATTERN.search(raw):
        findings.append(ScanFinding(ScanFindingKind.IDENTIFIER, "identifier_pattern"))
    if detect_injection_markers(raw):
        findings.append(ScanFinding(ScanFindingKind.PROMPT_INJECTION, "injection_marker"))
    return tuple(findings)


__all__ = ["ScanFinding", "ScanFindingKind", "scan_envelope"]
