"""Tests for the deterministic manual coverage-diff (false-negative guard)."""

from __future__ import annotations

from fdai.rule_catalog.pipeline.distill import analyze_coverage
from fdai.shared.providers.distiller import CandidateKind, DistilledCandidate

_MANUAL = """\
# Storage hardening

Storage accounts must deny public network access.
Blob containers shall enforce TLS 1.2.

## Deployment

Deployments should be reviewed but this line has no normative term.
The pipeline must run a what-if before apply.
"""


def _cand(start: int, end: int, cid: str = "c") -> DistilledCandidate:
    return DistilledCandidate(
        kind=CandidateKind.RULE,
        candidate_id=cid,
        source_ref="manual://storage",
        source_section="Storage",
        source_lines=(start, end),
    )


def test_empty_manual_is_fully_covered() -> None:
    report = analyze_coverage("", [])
    assert report.total == 0
    assert report.coverage_ratio == 1.0
    assert report.gaps == ()


def test_counts_headings_and_normative_lines() -> None:
    report = analyze_coverage(_MANUAL, [])
    # 2 headings + 3 normative ("must deny", "shall enforce", "must run").
    # "should be reviewed" is NOT normative (should is excluded).
    assert report.total == 5
    assert report.covered == 0
    kinds = sorted(g.kind for g in report.gaps)
    assert kinds == ["heading", "heading", "imperative", "imperative", "imperative"]


def test_candidate_line_range_marks_obligations_covered() -> None:
    # Cover the whole document.
    report = analyze_coverage(_MANUAL, [_cand(1, 10)])
    assert report.total == 5
    assert report.covered == 5
    assert report.gaps == ()
    assert report.coverage_ratio == 1.0


def test_partial_coverage_flags_the_gap() -> None:
    # Line 3 is "must deny public network access".
    report = analyze_coverage(_MANUAL, [_cand(3, 3)])
    assert report.covered == 1
    gap_lines = {g.line for g in report.gaps}
    assert 3 not in gap_lines
    assert report.total - report.covered == len(report.gaps)


def test_fenced_code_is_not_an_obligation() -> None:
    text = (
        "# Config\n"
        "```yaml\n"
        "policy: must-not-count-this\n"
        "required: true\n"
        "```\n"
        "The value must be encrypted.\n"
    )
    report = analyze_coverage(text, [])
    # 1 heading + 1 normative prose line; the two in-fence lines are skipped.
    assert report.total == 2
    texts = [g.text for g in report.gaps]
    assert "The value must be encrypted." in texts
    assert all("count-this" not in t for t in texts)


def test_normative_terms_are_word_bounded() -> None:
    # "mustard" and "shallow" must not trigger a false obligation.
    text = "The mustard is in a shallow dish.\n"
    report = analyze_coverage(text, [])
    assert report.total == 0
