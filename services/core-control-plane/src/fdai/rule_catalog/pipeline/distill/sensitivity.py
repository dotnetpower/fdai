"""Deterministic sensitivity guard for manual distillation (secret + PII scan).

Design contract:
``docs/roadmap/rules-and-detection/manual-distillation.md`` § "Permission and
sensitivity, not just authentication". A manual the source account *can* read
may still be one FDAI must not distill blindly: an HR page, an incident
post-mortem naming customers, or a runbook with an embedded credential. This
module scans a :class:`ManualDocument` for secrets and PII and returns a
disposition; a hit routes the document to HIL rather than auto-extracting.

Pure and deterministic: regex + Luhn only, no LLM, no network, no wall-clock.
Fail-closed: a borderline match reports ``HOLD`` so a human reviews it, because
routing a clean doc to HIL is cheap while auto-distilling a secret is not.

Secret-free by construction: a :class:`SensitivityFinding` records only the
*kind*, a *label*, and the *line*, NEVER the matched value. The report is safe
to log, audit, and surface in a PR body (L0 stays English and secret-free, per
``.github/instructions/coding-conventions.instructions.md``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from fdai.shared.providers.distiller import ManualDocument


class SensitivityKind(StrEnum):
    """The class of a sensitivity finding."""

    SECRET = "secret"  # noqa: S105 - enum label, not a credential
    PII = "pii"


class SensitivityDisposition(StrEnum):
    """What the guard concludes about a document."""

    CLEAR = "clear"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class SensitivityFinding:
    """One secret / PII hit - carries NO matched value, only where and what kind.

    ``label`` names the detector (``private-key``, ``connection-string``,
    ``email``, ...) so a reviewer knows what to look for without the report
    itself leaking the sensitive text. ``line`` is 1-based.
    """

    kind: SensitivityKind
    label: str
    line: int

    def __post_init__(self) -> None:
        if self.line < 1:
            raise ValueError("SensitivityFinding.line MUST be 1-based (>= 1)")


@dataclass(frozen=True, slots=True)
class SensitivityReport:
    """Aggregate scan result over one manual."""

    disposition: SensitivityDisposition
    findings: tuple[SensitivityFinding, ...] = ()

    @property
    def is_clear(self) -> bool:
        return self.disposition is SensitivityDisposition.CLEAR


# ---------------------------------------------------------------------------
# Detectors (deterministic). Each entry is (kind, label, compiled pattern).
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
    ("connection-string", re.compile(r"(?i)AccountKey=[^;\s]{8,}")),
    (
        "connection-string",
        re.compile(r"(?i)(?:Server|Data Source|Host)=[^;]+;[^;]*(?:Password|Pwd)=[^;\s]+"),
    ),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("sas-token", re.compile(r"(?i)[?&]sig=[A-Za-z0-9%]{16,}")),
)

# Credential assignment: `password: <value>` / `api_key=<value>` with a real
# value. The negative-lookahead skips obvious placeholders so docs that spell
# out `password: <your-password>` do not all route to HIL.
_CREDENTIAL_ASSIGN_RE = re.compile(
    r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|"
    r"client[_-]?secret|auth[_-]?token|token)\b\s*[:=]\s*"
    r"(?P<value>['\"]?[^\s'\"]{6,}['\"]?)"
)

_PLACEHOLDER_RE = re.compile(
    r"(?i)^['\"]?(?:"
    r"<[^>]*>"  # <your-password>, <secret>
    r"|[<>*xX._-]+"  # ****, xxxx, ----, <...>
    r"|(?:example|redacted|placeholder|changeme|dummy|sample|your[_-]?\w*)"
    r")['\"]?$"
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[-.\s])?\d{3}[-.\s]\d{3,4}[-.\s]\d{4}(?!\d)")
_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?<=\d)")


def _looks_like_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(value.strip()))


def _luhn_ok(digits: str) -> bool:
    """Return whether ``digits`` (13-19 chars) passes the Luhn checksum."""
    total = 0
    parity = len(digits) % 2
    for idx, ch in enumerate(digits):
        d = ord(ch) - 48
        if idx % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _scan_line(line: str, lineno: int) -> list[SensitivityFinding]:
    findings: list[SensitivityFinding] = []

    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(line):
            findings.append(SensitivityFinding(SensitivityKind.SECRET, label, lineno))

    cred = _CREDENTIAL_ASSIGN_RE.search(line)
    if cred and not _looks_like_placeholder(cred.group("value")):
        findings.append(SensitivityFinding(SensitivityKind.SECRET, "credential-assignment", lineno))

    if _EMAIL_RE.search(line):
        findings.append(SensitivityFinding(SensitivityKind.PII, "email", lineno))
    if _PHONE_RE.search(line):
        findings.append(SensitivityFinding(SensitivityKind.PII, "phone", lineno))
    for match in _CARD_CANDIDATE_RE.finditer(line):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            findings.append(SensitivityFinding(SensitivityKind.PII, "card-number", lineno))
            break

    return findings


def scan_text(text: str) -> tuple[SensitivityFinding, ...]:
    """Scan raw ``text`` for secrets and PII (deterministic, value-free result)."""
    out: list[SensitivityFinding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        out.extend(_scan_line(line, lineno))
    return tuple(out)


def scan_sensitivity(document: ManualDocument) -> SensitivityReport:
    """Scan ``document`` and return a HOLD-on-any-hit disposition.

    ``HOLD`` means "do not auto-distill; route to HIL". ``CLEAR`` means the
    deterministic scan found no secret or PII and distillation may proceed.
    """
    findings = scan_text(document.text)
    disposition = SensitivityDisposition.HOLD if findings else SensitivityDisposition.CLEAR
    return SensitivityReport(disposition=disposition, findings=findings)


__all__ = [
    "SensitivityDisposition",
    "SensitivityFinding",
    "SensitivityKind",
    "SensitivityReport",
    "scan_sensitivity",
    "scan_text",
]
