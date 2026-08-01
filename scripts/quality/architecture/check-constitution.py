#!/usr/bin/env python3
"""Validate the FDAI constitutional authority and its required mirrors."""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGLISH_CONSTITUTION = "docs/roadmap/architecture/fdai-constitution.md"
KOREAN_CONSTITUTION = "docs/roadmap/architecture/fdai-constitution-ko.md"
EXPECTED_IDS = tuple(f"FDAI-CONST-{number:03d}" for number in range(1, 11))
ID_PATTERN = re.compile(r"FDAI-CONST-\d{3}")
EXPECTED_TRACE_ROWS = tuple(f"{number:03d}" for number in range(1, 11))
TRACE_ROW_PATTERN = re.compile(r"^\| (00[1-9]|010) \|", re.MULTILINE)

REQUIRED_PHRASES: Mapping[str, tuple[str, ...]] = {
    ".github/copilot-instructions.md": (
        "docs/roadmap/architecture/fdai-constitution.md",
        "all seven safeguards",
        "standing human authorization",
        "always prevails.",
        "SRE/SLO is the operating",
    ),
    ".github/instructions/architecture.instructions.md": (
        "docs/roadmap/architecture/fdai-constitution.md",
        "Seven Autonomous-Action Safeguards",
        "Constitutional objective precedence",
    ),
    ".github/instructions/coding-conventions.instructions.md": (
        "docs/roadmap/architecture/fdai-constitution.md",
        "all seven safeguards",
        "silence grants nothing",
    ),
    ".github/instructions/agent-pantheon.instructions.md": (
        "docs/roadmap/architecture/fdai-constitution.md",
        "Hard constraints precede weighted arbitration",
    ),
    "docs/roadmap/README.md": ("architecture/fdai-constitution.md",),
    "docs/roadmap/architecture/fdai-constitution.md": (
        "resource-group-equivalent or narrower",
        "A3-E never authorizes Chaos fault injection",
        "Every active, candidate, or calculated threshold",
        "latest value never rewrites a historical decision",
        "Bounded peer deliberation may",
        "Recovery and Chaos Enforcement",
        "Operator-Initiated SRE and ARB",
        "approved primitives do not make a new composition pre-approved",
    ),
    "docs/roadmap/agents/agent-pantheon.md": ("Constitutional eligibility comes first",),
    "docs/roadmap/agents/conversational-deliberation.md": (
        "composition-owned read-only peer deliberation",
    ),
    "docs/roadmap/agents/agent-pantheon-implementation.md": (
        "constitutional hard constraints remove ineligible options",
    ),
    "docs/roadmap/phases/phase-3-integrated-loop.md": (
        "constitutional hard constraints first remove ineligible",
    ),
    "docs/roadmap/decisioning/process-automation.md": ("ineligible for enforce promotion",),
    "docs/roadmap/decisioning/risk-classification.md": (
        "Standing authorization does not raise an `hil` baseline to `auto`",
    ),
    "docs/roadmap/decisioning/escalation-and-standing-authority.md": (
        "pre-recorded human Approval",
        "authorization_revision",
        "policy_digest",
        "target_revision",
        "history_review_ref",
        "handover_confirmation_ref",
        "Chaos injection is excluded",
    ),
}

FORBIDDEN_PHRASES: Mapping[str, tuple[str, ...]] = {
    ".github/copilot-instructions.md": ("SRE/SLO, etc.), which are future scope",),
    ".github/instructions/architecture.instructions.md": ("all four safety invariants",),
    ".github/instructions/coding-conventions.instructions.md": ("high-risk never auto-executes",),
    ".github/instructions/agent-pantheon.instructions.md": (
        "all nine structural invariants",
        "If they disagree, the code wins",
    ),
    "docs/roadmap/architecture/security-and-identity.md": (
        "high-risk never auto-executes",
        "Missing any of the four",
    ),
    "docs/roadmap/decisioning/escalation-and-standing-authority.md": (
        "`auto`-eligible",
        "verdict flips to `auto`",
    ),
}

GLOBAL_ROADMAP_FORBIDDEN = (
    "four safety invariants",
    "four autonomy invariants",
    "four-safety",
    "네 가지 안전 불변",
    "네 안전 불변",
    "네 개의 안전 불변",
    "4 대 safety invariant",
    "4-safety",
    "4 개 안전 invariant",
    "4개 안전 불변",
    "4대 안전 불변",
    "4 autonomy invariant",
)


def validate_texts(texts: Mapping[str, str]) -> list[str]:
    """Return constitutional consistency errors for repository-relative texts."""
    errors: list[str] = []
    for path in (ENGLISH_CONSTITUTION, KOREAN_CONSTITUTION):
        text = texts.get(path)
        if text is None:
            errors.append(f"missing constitutional document: {path}")
            continue
        found_ids = tuple(ID_PATTERN.findall(text))
        if found_ids != EXPECTED_IDS:
            errors.append(f"{path}: expected each FDAI-CONST-001..010 once in order")
        found_trace_rows = tuple(TRACE_ROW_PATTERN.findall(text))
        if found_trace_rows != EXPECTED_TRACE_ROWS:
            errors.append(f"{path}: expected traceability rows 001..010 once in order")

    for path, phrases in REQUIRED_PHRASES.items():
        text = texts.get(path)
        if text is None:
            errors.append(f"missing constitutional mirror: {path}")
            continue
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{path}: missing required constitutional phrase: {phrase}")

    for path, phrases in FORBIDDEN_PHRASES.items():
        text = texts.get(path)
        if text is None:
            continue
        for phrase in phrases:
            if phrase in text:
                errors.append(f"{path}: obsolete constitutional phrase: {phrase}")

    for path, text in texts.items():
        if not path.startswith("docs/roadmap/"):
            continue
        lowered = text.lower()
        for phrase in GLOBAL_ROADMAP_FORBIDDEN:
            if phrase.lower() in lowered:
                errors.append(f"{path}: obsolete roadmap safeguard phrase: {phrase}")
    return errors


def validate(root: Path = REPO_ROOT) -> list[str]:
    """Load the constitutional surface from root and validate it."""
    paths = {
        ENGLISH_CONSTITUTION,
        KOREAN_CONSTITUTION,
        *REQUIRED_PHRASES,
        *FORBIDDEN_PHRASES,
    }
    paths.update(
        path.relative_to(root).as_posix() for path in (root / "docs/roadmap").rglob("*.md")
    )
    texts = {
        path: (root / path).read_text(encoding="utf-8") for path in paths if (root / path).is_file()
    }
    return validate_texts(texts)


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"constitution: ERROR: {error}", file=sys.stderr)
        return 1
    print("constitution: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
