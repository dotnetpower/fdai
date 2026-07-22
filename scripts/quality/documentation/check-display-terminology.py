#!/usr/bin/env python3
"""Audit display terminology across tracked Markdown source documents."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATED_PREFIX = "site/src/content/docs/"


@dataclass(frozen=True)
class Term:
    name: str
    pattern: re.Pattern[str]
    display_hints: tuple[str, ...]


@dataclass(frozen=True)
class Occurrence:
    path: str
    line: int
    term: str
    classification: str
    context: str


TERMS = (
    Term(
        "hil",
        re.compile(
            r"(?<![A-Za-z0-9_])(?:human-in-the-loop\s*(?:\(HIL\))?|HIL)"
            r"(?![A-Za-z0-9_])",
            re.IGNORECASE,
        ),
        ("human approval", "사람 승인"),
    ),
    Term(
        "verdict",
        re.compile(r"(?<![A-Za-z0-9_])verdicts?(?![A-Za-z0-9_])", re.IGNORECASE),
        ("decision", "결정", "판정"),
    ),
    Term(
        "stewardship",
        re.compile(r"(?<![A-Za-z0-9_])stewardship(?![A-Za-z0-9_])", re.IGNORECASE),
        ("ownership", "담당 체계", "운영 책임"),
    ),
    Term(
        "steward",
        re.compile(r"(?<![A-Za-z0-9_])stewards?(?![A-Za-z0-9_])", re.IGNORECASE),
        ("accountable owner", "책임 담당자"),
    ),
    Term(
        "maintainer",
        re.compile(r"(?<![A-Za-z0-9_])maintainers?(?![A-Za-z0-9_])", re.IGNORECASE),
        ("FDAI maintainer", "FDAI 유지관리자"),
    ),
    Term(
        "bus-factor",
        re.compile(r"(?<![A-Za-z0-9_])bus factor(?![A-Za-z0-9_])", re.IGNORECASE),
        ("backup coverage", "single-person dependency", "담당 가능 인원", "1인 의존 여부"),
    ),
    Term(
        "abstain",
        re.compile(r"(?<![A-Za-z0-9_])abstain(?:s|ed)?(?![A-Za-z0-9_])", re.IGNORECASE),
        ("held for review", "hold for review", "판단 보류"),
    ),
    Term(
        "shadow-mode",
        re.compile(
            r"(?<![A-Za-z0-9_])(?:shadow[- ]mode|shadow,? (?:then|before) enforce|"
            r"enforce보다 shadow 우선)(?![A-Za-z0-9_])",
            re.IGNORECASE,
        ),
        ("observation mode", "관찰 모드"),
    ),
    Term(
        "enforce-mode",
        re.compile(
            r"(?<![A-Za-z0-9_])(?:enforce mode|live enforce|(?:in|from) enforce|"
            r"(?:promotion|promoted) to enforce|enforce(?=[은는이가을를과와으로로]))"
            r"(?![A-Za-z0-9_])",
            re.IGNORECASE,
        ),
        ("enforcement mode", "changes enabled", "적용 모드", "변경 적용"),
    ),
    Term(
        "blast-radius",
        re.compile(r"(?<![A-Za-z0-9_])blast[- ]radius(?![A-Za-z0-9_])", re.IGNORECASE),
        ("impact scope", "영향 범위"),
    ),
    Term(
        "grounding",
        re.compile(r"(?<![A-Za-z0-9_])grounding(?![A-Za-z0-9_])", re.IGNORECASE),
        ("evidence check", "근거 확인"),
    ),
    Term(
        "remediation",
        re.compile(r"(?<![A-Za-z0-9_])remediations?(?![A-Za-z0-9_])", re.IGNORECASE),
        ("fix", "recovery action", "수정", "복구 작업"),
    ),
    Term(
        "risk-gate",
        re.compile(
            r"(?<![A-Za-z0-9_])(?:risk[- ]gate(?:d)?|리스크 게이트)(?![A-Za-z0-9_])",
            re.IGNORECASE,
        ),
        ("safety check", "safety-gated", "안전성 검토"),
    ),
    Term(
        "finding",
        re.compile(r"(?<![A-Za-z0-9_])findings?(?![A-Za-z0-9_])", re.IGNORECASE),
        ("detected issue", "발견된 문제", "점검 결과"),
    ),
    Term(
        "handover",
        re.compile(r"(?<![A-Za-z0-9_])handover(?![A-Za-z0-9_])", re.IGNORECASE),
        ("ownership handover", "담당자 인수인계"),
    ),
    Term(
        "accountable",
        re.compile(r"(?<![A-Za-z0-9_])Accountable(?![A-Za-z0-9_])"),
        ("final owner", "최종 책임자"),
    ),
    Term(
        "informed",
        re.compile(r"(?<![A-Za-z0-9_])Informed(?![A-Za-z0-9_])"),
        ("notified", "kept informed", "알림 대상"),
    ),
)

CRITICAL_PROSE_TERMS = frozenset({"hil", "verdict", "stewardship"})
READER_PREFIXES = (
    "docs/user-guide/",
    "docs/runbooks/",
    "docs/baselines/",
    "docs/dashboards/",
)
CONTRACT_PREFIXES = (
    ".github/",
    "docs/roadmap/",
    "rule-catalog/",
    "scripts/",
    "security/",
    "src/",
    "tests/",
)
FRONTMATTER_DISPLAY_KEYS = frozenset({"title", "description"})
PROTECTED_INLINE = re.compile(
    r"(`[^`]*`|\]\([^)]*\)|<[^>]+>|https?://\S+|"
    r"(?<!\w)/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+)"
)

ENGLISH_DISPLAY = {
    "hil": "human approval",
    "verdict": "decision",
    "stewardship": "operational ownership",
    "steward": "accountable owner",
    "maintainer": "FDAI maintainer",
    "bus-factor": "backup coverage",
    "abstain": "hold for review",
    "shadow-mode": "observation mode",
    "enforce-mode": "enforcement mode",
    "blast-radius": "impact scope",
    "grounding": "evidence check",
    "remediation": "fix",
    "risk-gate": "safety check",
    "finding": "detected issue",
    "handover": "ownership handover",
    "accountable": "final owner",
    "informed": "notified",
}
KOREAN_DISPLAY = {
    "hil": ("사람 승인", True),
    "verdict": ("결정", True),
    "stewardship": ("담당 체계", False),
    "steward": ("책임 담당자", False),
    "maintainer": ("FDAI 유지관리자", False),
    "bus-factor": ("담당 가능 인원", True),
    "abstain": ("판단 보류", False),
    "shadow-mode": ("관찰 모드", False),
    "enforce-mode": ("적용 모드", False),
    "blast-radius": ("영향 범위", False),
    "grounding": ("근거 확인", True),
    "remediation": ("수정", True),
    "risk-gate": ("안전성 검토", False),
    "finding": ("발견된 문제", False),
    "handover": ("담당자 인수인계", False),
    "accountable": ("최종 책임자", False),
    "informed": ("알림 대상", True),
}
KOREAN_PARTICLES = {
    "은": ("는", "은"),
    "는": ("는", "은"),
    "이": ("가", "이"),
    "가": ("가", "이"),
    "을": ("를", "을"),
    "를": ("를", "을"),
    "과": ("와", "과"),
    "와": ("와", "과"),
    "로": ("로", "으로"),
    "으로": ("로", "으로"),
}


def _tracked_markdown() -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(
        path
        for path in result.stdout.splitlines()
        if path and not path.startswith(GENERATED_PREFIX)
    )


def _blank_range(chars: list[str], start: int, end: int) -> None:
    chars[start:end] = " " * (end - start)


def visible_text(line: str) -> str:
    """Blank non-display Markdown syntax while retaining character offsets."""
    chars = list(line)
    for match in re.finditer(r"`[^`]*`", line):
        _blank_range(chars, match.start(), match.end())
    for match in re.finditer(r"\]\([^)]*\)", line):
        _blank_range(chars, match.start() + 1, match.end())
    for match in re.finditer(r"<[^>]+>", line):
        _blank_range(chars, match.start(), match.end())
    for match in re.finditer(r"https?://\S+", line):
        _blank_range(chars, match.start(), match.end())
    for match in re.finditer(r"(?<!\w)/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+", line):
        _blank_range(chars, match.start(), match.end())
    return "".join(chars)


def _is_reader_document(path: str) -> bool:
    return (
        path in {"README.md", "README-ko.md"}
        or path.endswith("/README.md")
        or path.startswith(READER_PREFIXES)
    )


def _is_contract_document(path: str) -> bool:
    return path.startswith(CONTRACT_PREFIXES)


def _is_normative_instruction(path: str) -> bool:
    return path.startswith(".github/")


def _has_display_hint(text: str, term: Term) -> bool:
    lowered = text.casefold()
    return any(hint.casefold() in lowered for hint in term.display_hints)


def _frontmatter_key(line: str) -> str | None:
    match = re.match(r"^([A-Za-z0-9_-]+):", line)
    return match.group(1) if match else None


def audit_document(path: str, text: str) -> tuple[list[Occurrence], list[Occurrence]]:
    occurrences: list[Occurrence] = []
    violations: list[Occurrence] = []
    in_frontmatter = False
    in_fence = False
    fence_marker = ""
    glossed_terms: set[str] = set()

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if line_number == 1 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter and stripped == "---":
            in_frontmatter = False
            continue
        fence_match = re.match(r"^\s*(```+|~~~+)", line)
        if fence_match:
            marker = fence_match.group(1)[0]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            continue

        frontmatter_key = _frontmatter_key(line) if in_frontmatter else None
        display_frontmatter = frontmatter_key in FRONTMATTER_DISPLAY_KEYS
        heading = bool(re.match(r"^#{1,6}\s+", line))
        high_signal = display_frontmatter or heading
        visible = visible_text(line)

        for term in TERMS:
            for match in term.pattern.finditer(line):
                protected = in_fence or not visible[match.start() : match.end()].strip()
                if (
                    protected
                    or _is_normative_instruction(path)
                    or (in_frontmatter and not display_frontmatter)
                ):
                    classification = "intentional-contract"
                elif _has_display_hint(visible, term):
                    classification = "first-technical-gloss"
                elif term.name in glossed_terms and term.name not in CRITICAL_PROSE_TERMS:
                    classification = "intentional-contract"
                elif _is_contract_document(path) and not high_signal:
                    classification = "intentional-contract"
                else:
                    classification = "reader-facing-prose"

                occurrence = Occurrence(
                    path=path,
                    line=line_number,
                    term=term.name,
                    classification=classification,
                    context=line.strip(),
                )
                occurrences.append(occurrence)
                if classification == "first-technical-gloss":
                    glossed_terms.add(term.name)

                is_violation = classification == "reader-facing-prose" and (
                    high_signal or _is_reader_document(path)
                )
                if is_violation:
                    violations.append(occurrence)

    return occurrences, violations


def _case_like(value: str, replacement: str) -> str:
    if re.match(r"^[A-Z][a-z]", value) and replacement[:1].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _english_replacement(term: str, value: str) -> str:
    replacement = ENGLISH_DISPLAY[term]
    plural_replacements = {
        "verdict": "decisions",
        "remediation": "fixes",
        "finding": "detected issues",
        "steward": "accountable owners",
        "maintainer": "FDAI maintainers",
    }
    if value.casefold().endswith("s") and term in plural_replacements:
        replacement = plural_replacements[term]
    if term == "abstain":
        lowered = value.casefold()
        if lowered.endswith("ed"):
            replacement = "held for review"
        elif lowered.endswith("s"):
            replacement = "holds for review"
    if term == "enforce-mode":
        if value.casefold() == "live enforce":
            replacement = "live enforcement"
        else:
            replacement = re.sub(
                r"enforce(?: mode)?$",
                "enforcement mode",
                value,
                flags=re.IGNORECASE,
            )
    if term == "shadow-mode" and re.search(r"(?:then|before) enforce$", value, re.I):
        replacement = "Observe, then enable changes"
    if term == "risk-gate" and value.casefold().endswith("gated"):
        replacement = "safety-gated"
    return _case_like(value, replacement)


def _korean_replacement(term: str, value: str, particle: str | None) -> str:
    replacement, has_batchim = KOREAN_DISPLAY[term]
    if term == "shadow-mode" and value.casefold() == "enforce보다 shadow 우선":
        replacement = "변경 적용 전 관찰 우선"
    if term == "enforce-mode" and value.casefold() != "enforce":
        replacement = re.sub(
            r"enforce(?: mode)?$",
            replacement,
            value,
            flags=re.IGNORECASE,
        )
    if particle is None:
        return replacement
    forms = KOREAN_PARTICLES.get(particle)
    if forms is None:
        return replacement + particle
    return replacement + forms[1 if has_batchim else 0]


def _replace_visible_segment(segment: str, terms: set[str], korean: bool) -> str:
    if "hil" in terms:
        phrase = "사람 승인" if korean else "human approval"
        segment = re.sub(
            r"\bhuman-in-the-loop\s*\(HIL\)(?:\s+approval)?",
            phrase,
            segment,
            flags=re.IGNORECASE,
        )
        segment = re.sub(
            r"\bHIL\s+approvals?\b",
            phrase,
            segment,
            flags=re.IGNORECASE,
        )
    if "steward" in terms and not korean:
        segment = re.sub(r"\bMimir stewards\b", "Mimir owns", segment)
    for term in TERMS:
        if term.name not in terms:
            continue
        if korean:
            pattern = re.compile(
                term.pattern.pattern + r"(은|는|이|가|을|를|과|와|으로|로|의|에)?",
                re.IGNORECASE,
            )
            segment = pattern.sub(
                lambda match, name=term.name: _korean_replacement(
                    name,
                    match.group(0)[: -len(match.group(1))] if match.group(1) else match.group(0),
                    match.group(1),
                ),
                segment,
            )
        else:
            segment = term.pattern.sub(
                lambda match, name=term.name: _english_replacement(name, match.group(0)),
                segment,
            )
    if korean:
        segment = segment.replace("사람 승인 승인자", "사람 승인 담당자")
        segment = segment.replace("사람의 사람 승인 승인", "사람 승인")
        segment = segment.replace("사람 승인 승인", "사람 승인")
    return segment


def fix_document(path: str, text: str) -> str:
    _, violations = audit_document(path, text)
    terms_by_line: dict[int, set[str]] = {}
    for violation in violations:
        terms_by_line.setdefault(violation.line, set()).add(violation.term)
    if not terms_by_line:
        return text

    lines = text.splitlines(keepends=True)
    for line_number, terms in terms_by_line.items():
        line = lines[line_number - 1]
        korean = path.endswith("-ko.md") or bool(re.search(r"[가-힣]", line))
        parts = PROTECTED_INLINE.split(line)
        lines[line_number - 1] = "".join(
            part if index % 2 else _replace_visible_segment(part, terms, korean)
            for index, part in enumerate(parts)
        )
    return "".join(lines)


def fix_repository() -> int:
    changed = 0
    for relative in _tracked_markdown():
        path = REPO_ROOT / relative
        original = path.read_text(encoding="utf-8")
        updated = fix_document(relative, original)
        if updated == original:
            continue
        path.write_text(updated, encoding="utf-8")
        changed += 1
    return changed


def audit_repository() -> tuple[list[Occurrence], list[Occurrence]]:
    occurrences: list[Occurrence] = []
    violations: list[Occurrence] = []
    for relative in _tracked_markdown():
        document_occurrences, document_violations = audit_document(
            relative,
            (REPO_ROOT / relative).read_text(encoding="utf-8"),
        )
        occurrences.extend(document_occurrences)
        violations.extend(document_violations)
    return occurrences, violations


def _write_report(path: Path, occurrences: list[Occurrence]) -> None:
    by_classification: dict[str, int] = {}
    for occurrence in occurrences:
        by_classification[occurrence.classification] = (
            by_classification.get(occurrence.classification, 0) + 1
        )
    report = {
        "source_documents": len(_tracked_markdown()),
        "occurrences": len(occurrences),
        "by_classification": dict(sorted(by_classification.items())),
        "items": [asdict(occurrence) for occurrence in occurrences],
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args(argv[1:])
    if args.fix:
        changed = fix_repository()
        print(f"display-terminology: fixed {changed} source document(s)")
    occurrences, violations = audit_repository()
    if args.report_json is not None:
        _write_report(args.report_json, occurrences)
    if violations:
        for violation in violations:
            print(
                f"display-terminology: ERROR: {violation.path}:{violation.line}: "
                f"bare {violation.term}: {violation.context}",
                file=sys.stderr,
            )
        print(
            f"display-terminology: {len(violations)} violation(s) across "
            f"{len(_tracked_markdown())} source document(s)",
            file=sys.stderr,
        )
        return 1
    print(
        f"display-terminology: OK ({len(occurrences)} classified occurrence(s) across "
        f"{len(_tracked_markdown())} source document(s))"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
