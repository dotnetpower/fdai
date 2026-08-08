"""Deterministic coverage analysis for manual distillation (false-negative guard).

Design contract:
``docs/roadmap/rules-and-detection/manual-distillation.md`` § "Residual risk:
false negatives". The gates that verify *extracted* candidates (grounding,
back-translation, shadow replay) cannot catch a rule the manual states but
distillation never extracted - a fragment that does not exist has nothing to
replay. This module is the structural coverage diff that mitigates that gap: it
counts a manual's obligations (section headings + normative statements) and flags
the ones no distilled candidate cites, for human review.

Pure and deterministic: no LLM, no network, no wall-clock. The keyword set is a
conservative starting heuristic (see the design doc's Open Decisions) and is
tuned per manual style, not treated as ground truth.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from fdai.shared.providers.distiller import (
    CoverageGap,
    CoverageReport,
    DistilledCandidate,
)

# Markdown ATX heading: 1-6 '#' then required space then text.
_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<text>\S.*)$")

# RFC-2119-style normative terms. `must` also matches `must not`, so the
# negative-polarity phrases need no separate entry - obligation *counting* only
# needs to detect that a normative statement exists on the line.
_NORMATIVE_RE = re.compile(
    r"\b(?:must|shall|required|prohibited|forbidden)\b",
    re.IGNORECASE,
)

_FENCE = "```"


def _is_covered(line: int, candidates: Sequence[DistilledCandidate]) -> bool:
    for c in candidates:
        start, end = c.source_lines
        if start <= line <= end:
            return True
    return False


def analyze_coverage(
    text: str,
    candidates: Sequence[DistilledCandidate],
) -> CoverageReport:
    """Measure how much of ``text`` the distilled ``candidates`` cover.

    An *obligation* is a section heading or a line carrying a normative term.
    An obligation at line ``L`` is *covered* when some candidate's
    ``source_lines`` range includes ``L``. Lines inside fenced code blocks are
    skipped so example code is not mistaken for an obligation.

    Returns a :class:`CoverageReport` whose ``gaps`` list the uncovered
    obligations (1-based line, text, kind) for human review. An empty manual (no
    obligations) reports ``coverage_ratio == 1.0`` - there is nothing to miss.
    """
    total = 0
    covered = 0
    gaps: list[CoverageGap] = []
    in_fence = False

    for idx, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith(_FENCE):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        heading = _HEADING_RE.match(stripped)
        if heading is not None:
            kind = "heading"
            obligation_text = heading.group("text").strip()
        elif _NORMATIVE_RE.search(stripped):
            kind = "imperative"
            obligation_text = stripped
        else:
            continue

        total += 1
        if _is_covered(idx, candidates):
            covered += 1
        else:
            gaps.append(CoverageGap(line=idx, text=obligation_text, kind=kind))

    return CoverageReport(total=total, covered=covered, gaps=tuple(gaps))


__all__ = ["analyze_coverage"]
