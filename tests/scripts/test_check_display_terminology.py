"""Tests for the source-document display terminology audit."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts/quality/documentation/check-display-terminology.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_display_terminology", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = _load_script()


def test_reader_heading_with_bare_term_is_rejected() -> None:
    occurrences, violations = CHECKER.audit_document(
        "docs/user-guide/concepts/example.md",
        "# Three verdicts\n",
    )

    assert [item.classification for item in occurrences] == ["reader-facing-prose"]
    assert [item.term for item in violations] == ["verdict"]


def test_spelled_out_hil_term_is_rejected_in_reader_prose() -> None:
    occurrences, violations = CHECKER.audit_document(
        "docs/user-guide/concepts/example.md",
        "This action requires human-in-the-loop review.\n",
    )

    assert [item.term for item in occurrences] == ["hil"]
    assert [item.term for item in violations] == ["hil"]


def test_display_gloss_is_accepted() -> None:
    occurrences, violations = CHECKER.audit_document(
        "docs/user-guide/concepts/example.md",
        "Human approval (the `hil` decision) is required.\n",
    )

    assert [item.classification for item in occurrences] == ["intentional-contract"]
    assert violations == []


def test_noncritical_term_is_allowed_after_first_gloss() -> None:
    occurrences, violations = CHECKER.audit_document(
        "docs/user-guide/concepts/example.md",
        "Impact scope (blast radius) is bounded.\nThe blast radius is recorded.\n",
    )

    assert [item.classification for item in occurrences] == [
        "first-technical-gloss",
        "intentional-contract",
    ]
    assert violations == []


def test_unglossed_noncritical_reader_term_is_rejected() -> None:
    _, violations = CHECKER.audit_document(
        "docs/user-guide/concepts/example.md",
        "The risk gate checks the action.\n",
    )

    assert [item.term for item in violations] == ["risk-gate"]


def test_enforce_pattern_does_not_match_enforced_or_enforcement() -> None:
    occurrences, violations = CHECKER.audit_document(
        "docs/user-guide/concepts/example.md",
        "A live enforced capability differs from live enforcement.\n",
    )

    assert occurrences == []
    assert violations == []


def test_raw_html_display_phrases_are_audited_and_fixed() -> None:
    text = "<div><strong>Shadow before enforce</strong><span>Risk-gated autonomy</span></div>\n"

    updated = CHECKER.fix_document("docs/user-guide/example.md", text)

    assert updated == (
        "<div><strong>Observe, then enable changes</strong>"
        "<span>Safety-gated autonomy</span></div>\n"
    )


def test_contract_syntax_and_link_targets_are_accepted() -> None:
    text = """Use `verdict=hil` with [the decision API](/verdict?mode=hil).
```json
{"verdict":"hil"}
```
"""

    occurrences, violations = CHECKER.audit_document(
        "docs/user-guide/concepts/example.md",
        text,
    )

    assert occurrences
    assert {item.classification for item in occurrences} == {"intentional-contract"}
    assert violations == []


def test_technical_body_terms_are_classified_as_contract_usage() -> None:
    occurrences, violations = CHECKER.audit_document(
        "docs/roadmap/decisioning/example.md",
        "The risk gate records a verdict.\n",
    )

    assert {item.classification for item in occurrences} == {"intentional-contract"}
    assert violations == []


def test_frontmatter_description_is_reader_facing() -> None:
    occurrences, violations = CHECKER.audit_document(
        "docs/roadmap/decisioning/example.md",
        "---\ntitle: Decision contract\ndescription: How the risk gate returns a verdict.\n---\n",
    )

    assert {item.term for item in occurrences} == {"risk-gate", "verdict"}
    assert {item.term for item in violations} == {"risk-gate", "verdict"}


def test_normative_instruction_heading_is_contract_usage() -> None:
    occurrences, violations = CHECKER.audit_document(
        ".github/instructions/example.instructions.md",
        "# HIL verdict contract\n",
    )

    assert {item.classification for item in occurrences} == {"intentional-contract"}
    assert violations == []


def test_fixer_changes_only_reader_text() -> None:
    text = "# HIL verdicts\nUse `verdict=hil` at [/hil](/hil).\n"

    updated = CHECKER.fix_document("docs/user-guide/example.md", text)

    assert updated == "# human approval decisions\nUse `verdict=hil` at [/hil](/hil).\n"


def test_fixer_selects_korean_particles() -> None:
    text = "# HIL로 보낸 verdict를 검토\n"

    updated = CHECKER.fix_document("docs/user-guide/example-ko.md", text)

    assert updated == "# 사람 승인으로 보낸 결정을 검토\n"


def test_fixer_deduplicates_korean_approval_nouns() -> None:
    text = "# HIL 승인과 HIL 승인자\n"

    updated = CHECKER.fix_document("docs/user-guide/example-ko.md", text)

    assert updated == "# 사람 승인과 사람 승인 담당자\n"


def test_fixer_preserves_mimir_stewards_as_a_verb() -> None:
    text = "Mimir stewards rules.\n"

    updated = CHECKER.fix_document("docs/user-guide/example.md", text)

    assert updated == "Mimir owns rules.\n"
