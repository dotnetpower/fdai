"""Deterministic text redaction and prompt-injection scanning."""

from __future__ import annotations

import re
from dataclasses import dataclass

from fdai.shared.providers.browser_evidence import BrowserRedactionEntry

_REDACTED = "[REDACTED]"
_TRUNCATED = "\n[TRUNCATED]"
_BUILTIN_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:password|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b"),
)
_INJECTION_PATTERNS = (
    ("instruction_override", re.compile(r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions?\b")),
    (
        "system_prompt_request",
        re.compile(r"(?i)\b(?:reveal|print|show)\s+(?:the\s+)?system\s+prompt\b"),
    ),
    ("tool_authority_claim", re.compile(r"(?i)\b(?:call|invoke|execute)\s+(?:the\s+)?tool\b")),
    ("approval_claim", re.compile(r"(?i)\b(?:approve|authorize)\s+(?:this\s+)?action\b")),
)


class BrowserEvidenceUnsafeContentError(ValueError):
    """Raised when capture content cannot be safely retained."""


@dataclass(frozen=True, slots=True)
class RedactedBrowserText:
    value: str
    manifest: tuple[BrowserRedactionEntry, ...]


def redact_browser_text(
    value: str,
    *,
    surface: str,
    patterns: tuple[str, ...],
    canary_markers: tuple[str, ...],
    max_chars: int,
) -> RedactedBrowserText:
    """Redact secrets and custom patterns, then apply a deterministic bound."""

    output = value
    entries: list[BrowserRedactionEntry] = []
    for index, pattern in enumerate(_BUILTIN_SECRET_PATTERNS):
        output, count = pattern.subn(_REDACTED, output)
        if count:
            entries.append(
                BrowserRedactionEntry(
                    surface=surface,  # type: ignore[arg-type]
                    rule=f"builtin-secret-{index + 1}",
                    replacements=count,
                )
            )
    for index, expression in enumerate(patterns):
        try:
            pattern = re.compile(expression)
        except re.error as exc:
            raise BrowserEvidenceUnsafeContentError("browser redaction pattern is invalid") from exc
        output, count = pattern.subn(_REDACTED, output)
        if count:
            entries.append(
                BrowserRedactionEntry(
                    surface=surface,  # type: ignore[arg-type]
                    rule=f"policy-pattern-{index + 1}",
                    replacements=count,
                )
            )
    for index, marker in enumerate(canary_markers):
        if not marker:
            raise BrowserEvidenceUnsafeContentError("browser secret canary MUST be non-empty")
        count = output.count(marker)
        if count:
            output = output.replace(marker, _REDACTED)
            entries.append(
                BrowserRedactionEntry(
                    surface=surface,  # type: ignore[arg-type]
                    rule=f"secret-canary-{index + 1}",
                    replacements=count,
                )
            )
    if len(output) > max_chars:
        keep = max(0, max_chars - len(_TRUNCATED))
        output = f"{output[:keep]}{_TRUNCATED}"[:max_chars]
        entries.append(
            BrowserRedactionEntry(
                surface=surface,  # type: ignore[arg-type]
                rule="character-limit",
                replacements=1,
            )
        )
    if any(marker in output for marker in canary_markers):
        raise BrowserEvidenceUnsafeContentError("browser secret canary survived redaction")
    return RedactedBrowserText(value=output, manifest=tuple(entries))


def scan_prompt_injection(*values: str | None) -> tuple[str, ...]:
    findings = {
        finding
        for value in values
        if value is not None
        for finding, pattern in _INJECTION_PATTERNS
        if pattern.search(value)
    }
    return tuple(sorted(findings))


__all__ = [
    "BrowserEvidenceUnsafeContentError",
    "RedactedBrowserText",
    "redact_browser_text",
    "scan_prompt_injection",
]
