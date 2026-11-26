"""Deterministic review rules over added unified-diff lines."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from .models import (
    FindingSeverity,
    PullRequestSnapshot,
    ReviewFinding,
    ReviewProfile,
    ReviewReport,
)

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True, slots=True)
class _Rule:
    rule_id: str
    severity: FindingSeverity
    category: str
    pattern: re.Pattern[str]
    message: str
    profiles: frozenset[ReviewProfile]
    excluded_pattern: re.Pattern[str] | None = None


_RULES = (
    _Rule(
        "security.private-key",
        FindingSeverity.CRITICAL,
        "credential",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "A private-key marker was added to source.",
        frozenset({ReviewProfile.SECURITY, ReviewProfile.ALL}),
    ),
    _Rule(
        "security.secret-literal",
        FindingSeverity.CRITICAL,
        "credential",
        re.compile(
            r"(?i)\b(?:api[_-]?key|client[_-]?secret|password|access[_-]?token)\b"
            r"\s*[:=]\s*['\"][^'\"]{8,}['\"]"
        ),
        "A credential-like literal was added to source.",
        frozenset({ReviewProfile.SECURITY, ReviewProfile.ALL}),
    ),
    _Rule(
        "security.dynamic-code",
        FindingSeverity.HIGH,
        "code-execution",
        re.compile(r"\b(?:eval|exec)\s*\("),
        "Dynamic code execution was added.",
        frozenset({ReviewProfile.CODE, ReviewProfile.SECURITY, ReviewProfile.ALL}),
    ),
    _Rule(
        "security.shell-true",
        FindingSeverity.HIGH,
        "command-execution",
        re.compile(r"\bshell\s*=\s*True\b"),
        "A subprocess call enables shell interpretation.",
        frozenset({ReviewProfile.SECURITY, ReviewProfile.ALL}),
    ),
    _Rule(
        "security.tls-verification-disabled",
        FindingSeverity.HIGH,
        "transport",
        re.compile(r"\bverify\s*=\s*False\b"),
        "TLS certificate verification was disabled.",
        frozenset({ReviewProfile.SECURITY, ReviewProfile.ALL}),
    ),
    _Rule(
        "security.unsafe-yaml-load",
        FindingSeverity.HIGH,
        "deserialization",
        re.compile(r"\byaml\.load\s*\("),
        "An unrestricted YAML loader was added; use a safe loader.",
        frozenset({ReviewProfile.SECURITY, ReviewProfile.ALL}),
        re.compile(r"\bLoader\s*=\s*(?:yaml\.)?SafeLoader\b"),
    ),
    _Rule(
        "code.bare-except",
        FindingSeverity.MEDIUM,
        "error-handling",
        re.compile(r"^\s*except\s*:\s*(?:#.*)?$"),
        "A bare exception handler was added.",
        frozenset({ReviewProfile.CODE, ReviewProfile.ALL}),
    ),
    _Rule(
        "code.mutable-default",
        FindingSeverity.MEDIUM,
        "correctness",
        re.compile(r"\bdef\s+\w+\s*\([^)]*=\s*(?:\[\]|\{\}|set\(\))"),
        "A mutable function default was added.",
        frozenset({ReviewProfile.CODE, ReviewProfile.ALL}),
    ),
)


def analyze_snapshot(
    snapshot: PullRequestSnapshot,
    *,
    profile: ReviewProfile,
) -> ReviewReport:
    findings: list[ReviewFinding] = []
    omitted: list[str] = []
    reviewed_files = 0
    for file in snapshot.files:
        if not file.patch:
            omitted.append(file.path)
            continue
        reviewed_files += 1
        for line_number, line in _added_lines(file.patch):
            findings.extend(_evaluate_line(file.path, line_number, line, profile=profile))
    findings.sort(key=lambda item: (item.path, item.line, item.rule_id))
    return ReviewReport(
        repository=snapshot.repository,
        pull_number=snapshot.pull_number,
        base_sha=snapshot.base_sha,
        head_sha=snapshot.head_sha,
        profile=profile,
        changed_files=snapshot.changed_files,
        reviewed_files=reviewed_files,
        omitted_patch_files=tuple(sorted(omitted)),
        findings=tuple(findings),
    )


def _added_lines(patch: str) -> Iterable[tuple[int, str]]:
    next_line: int | None = None
    for raw_line in patch.splitlines():
        hunk = _HUNK.match(raw_line)
        if hunk is not None:
            next_line = int(hunk.group(1))
            continue
        if next_line is None or raw_line.startswith("\\"):
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            yield next_line, raw_line[1:]
            next_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        else:
            next_line += 1


def _evaluate_line(
    path: str,
    line_number: int,
    line: str,
    *,
    profile: ReviewProfile,
) -> list[ReviewFinding]:
    digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
    return [
        ReviewFinding(
            rule_id=rule.rule_id,
            severity=rule.severity,
            category=rule.category,
            path=path,
            line=line_number,
            message=rule.message,
            evidence_sha256=digest,
        )
        for rule in _RULES
        if (
            profile in rule.profiles
            and rule.pattern.search(line) is not None
            and (rule.excluded_pattern is None or rule.excluded_pattern.search(line) is None)
        )
    ]


__all__ = ["analyze_snapshot"]
