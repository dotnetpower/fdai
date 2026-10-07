"""Off-path LLM lens lane: grounded, quorum-checked hypotheses for weaknesses rules miss.

The lane complements deterministic scanners for weakness families such as missing authorization
or logic flaws. It never runs in an agent hot path and never decides anything:

1. **Select deterministically.** Walk the read-only source in sorted order, skip vendored,
   oversized, and binary files, and pick excerpts around lines that match a lens sink hint.
2. **Ask several models.** Send each excerpt, fenced as untrusted JSON data, to every configured
   model. Calls are bounded by a global budget.
3. **Verify in code.** Keep a model's candidate only if the cited line is inside the excerpt,
   matches a lens sink hint, and uses one of the lens CWEs.
4. **Require a quorum.** Emit an occurrence only when at least ``quorum`` distinct model families
   report grounded candidates within ``line_tolerance`` lines of each other.

Emitted occurrences use the ``llm_lens`` lane, so canonicalization labels them ``hypothesis`` and
they cannot reach alerting priorities on their own. Budget exhaustion and model failures are
reported as notes, never hidden.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from fdai.core.security.code_findings.models import Lane, Occurrence, SourceLocation
from fdai.core.security.code_findings.sarif import clean_text
from fdai.rule_catalog.code_security_lenses import Lens, LensCatalog
from fdai.shared.providers.code_security_lens import (
    CodeSecurityLensModel,
    LensModelError,
    LensRequest,
    LensResponse,
)

PRODUCER = "fdai-lens"
_SKIP_DIRS = frozenset({".git", "node_modules", "vendor", "third_party", "dist", "build", ".venv"})
_CONFIDENCE = frozenset({"low", "medium", "high"})


class LensLaneUnavailableError(RuntimeError):
    """Raised when the configured models cannot form a quorum of distinct families."""


@dataclass(frozen=True, slots=True)
class LensCandidate:
    lens_id: str
    path: str
    language: str
    hint_line: int
    first_line: int
    last_line: int
    numbered_excerpt: str


@dataclass(slots=True)
class LensLaneReport:
    files_scanned: int = 0
    files_skipped: int = 0
    candidates_selected: int = 0
    candidates_dropped_by_limit: int = 0
    candidates_reviewed: int = 0
    model_calls: int = 0
    model_errors: int = 0
    rejected_ungrounded: int = 0
    rejected_cwe: int = 0
    rejected_quorum: int = 0
    kept: int = 0
    budget_exhausted: bool = False
    model_error_reasons: Counter[str] = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """True when every selected candidate was reviewed without errors or drops."""
        return not (
            self.budget_exhausted
            or self.model_errors
            or self.candidates_dropped_by_limit
            or self.files_skipped
        )


def _iter_files(root: Path, catalog: LensCatalog, report: LensLaneReport) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in relative.parts) or path.is_symlink():
            continue
        if not path.is_file() or catalog.language_for(path.name) is None:
            continue
        if len(files) >= catalog.limits.max_files:
            report.files_skipped += 1
            continue
        files.append(path)
    return files


def _excerpt(lines: Sequence[str], center: int, catalog: LensCatalog) -> tuple[int, int, str]:
    radius = catalog.limits.excerpt_radius
    while True:
        first = max(1, center - radius)
        last = min(len(lines), center + radius)
        text = "\n".join(f"{n:>6}| {lines[n - 1][:400]}" for n in range(first, last + 1))
        if len(text.encode("utf-8")) <= catalog.limits.max_excerpt_bytes or radius <= 3:
            return first, last, text
        radius = max(3, radius // 2)


def select_candidates(
    root: Path, catalog: LensCatalog, report: LensLaneReport
) -> list[LensCandidate]:
    """Return lens candidates in deterministic order, bounded per lens."""
    per_lens: dict[str, list[LensCandidate]] = {lens_id: [] for lens_id in catalog.lenses}
    hints = {
        lens_id: [re.compile(hint) for hint in lens.sink_hints]
        for lens_id, lens in catalog.lenses.items()
    }
    for path in _iter_files(root, catalog, report):
        data = path.read_bytes()
        if len(data) > catalog.limits.max_file_bytes or b"\x00" in data[:8_192]:
            report.files_skipped += 1
            continue
        try:
            lines = data.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            report.files_skipped += 1
            continue
        report.files_scanned += 1
        relative = path.relative_to(root).as_posix()
        language = catalog.language_for(path.name) or ""
        for lens_id, lens in catalog.lenses.items():
            if language not in lens.languages:
                continue
            covered_until = 0
            for number, line in enumerate(lines, start=1):
                if number <= covered_until or not any(h.search(line) for h in hints[lens_id]):
                    continue
                first, last, text = _excerpt(lines, number, catalog)
                covered_until = last
                bucket = per_lens[lens_id]
                if len(bucket) >= catalog.limits.max_candidates_per_lens:
                    report.candidates_dropped_by_limit += 1
                    continue
                bucket.append(LensCandidate(lens_id, relative, language, number, first, last, text))
    if report.files_skipped:
        report.notes.append(
            f"{report.files_skipped} files were skipped "
            "(file limit, size limit, binary, or encoding)"
        )
    candidates = [c for lens_id in sorted(per_lens) for c in per_lens[lens_id]]
    report.candidates_selected = len(candidates)
    if report.candidates_dropped_by_limit:
        report.notes.append(
            f"{report.candidates_dropped_by_limit} candidates exceeded per-lens limits"
        )
    return candidates


def _grounded(
    response: LensResponse,
    candidate: LensCandidate,
    lens: Lens,
    source_lines: Sequence[str],
    report: LensLaneReport,
) -> list[tuple[int, int, str]]:
    hints = [re.compile(hint) for hint in lens.sink_hints]
    kept = []
    for finding in response.findings:
        if not candidate.first_line <= finding.line <= candidate.last_line:
            report.rejected_ungrounded += 1
            continue
        text = source_lines[finding.line - 1] if finding.line <= len(source_lines) else ""
        if not any(h.search(text) for h in hints) or finding.confidence not in _CONFIDENCE:
            report.rejected_ungrounded += 1
            continue
        if finding.cwe not in lens.cwe:
            report.rejected_cwe += 1
            continue
        kept.append((finding.line, finding.cwe, clean_text(finding.explanation, 300)))
    return kept


async def run_lens_lane(
    root: Path,
    catalog: LensCatalog,
    models: Sequence[CodeSecurityLensModel],
    *,
    revision: str,
) -> tuple[tuple[Occurrence, ...], LensLaneReport]:
    """Review ``root`` with every model and return quorum-agreed hypothesis occurrences."""
    families = {model.identity.family for model in models}
    if len(families) < catalog.limits.quorum:
        raise LensLaneUnavailableError(
            f"lens lane needs {catalog.limits.quorum} distinct model families, got {len(families)}"
        )
    report = LensLaneReport()
    candidates = select_candidates(root, catalog, report)
    occurrences: list[Occurrence] = []
    for candidate in candidates:
        if report.model_calls + len(models) > catalog.limits.max_model_calls:
            report.budget_exhausted = True
            remaining = report.candidates_selected - report.candidates_reviewed
            report.notes.append(f"model-call budget exhausted; {remaining} candidates not reviewed")
            break
        lens = catalog.lenses[candidate.lens_id]
        request = LensRequest(
            lens_id=candidate.lens_id,
            focus=lens.focus,
            cwe=lens.cwe,
            language=candidate.language,
            path=candidate.path,
            first_line=candidate.first_line,
            last_line=candidate.last_line,
            numbered_excerpt=candidate.numbered_excerpt,
            max_findings=catalog.limits.max_findings_per_response,
        )
        report.model_calls += len(models)
        report.candidates_reviewed += 1
        results = await asyncio.gather(
            *(model.review(request) for model in models), return_exceptions=True
        )
        source_lines = (root / candidate.path).read_text(encoding="utf-8").splitlines()
        votes: list[tuple[str, int, int, str]] = []
        for result in results:
            if isinstance(result, LensModelError):
                report.model_errors += 1
                report.model_error_reasons[clean_text(str(result), 80)] += 1
                continue
            if isinstance(result, BaseException):
                raise result
            for line, cwe, text in _grounded(result, candidate, lens, source_lines, report):
                votes.append((result.model.family, line, cwe, text))
        occurrence = _quorum(votes, candidate, catalog, revision, report)
        if occurrence is not None:
            occurrences.append(occurrence)
    if report.model_errors:
        reasons = ", ".join(
            f"{reason} x{count}" for reason, count in report.model_error_reasons.most_common(5)
        )
        report.notes.append(f"{report.model_errors} model calls failed: {reasons}")
    return tuple(occurrences), report


def _quorum(
    votes: Sequence[tuple[str, int, int, str]],
    candidate: LensCandidate,
    catalog: LensCatalog,
    revision: str,
    report: LensLaneReport,
) -> Occurrence | None:
    if not votes:
        return None
    tolerance = catalog.limits.line_tolerance
    for anchor in sorted({line for _, line, _, _ in votes}):
        near = [v for v in votes if abs(v[1] - anchor) <= tolerance]
        if len({family for family, _, _, _ in near}) < catalog.limits.quorum:
            continue
        cwe = Counter(v[2] for v in near).most_common(1)[0][0]
        report.kept += 1
        digest = hashlib.sha256(
            f"{revision}:{candidate.lens_id}:{candidate.path}:{anchor}".encode()
        ).hexdigest()
        return Occurrence(
            occurrence_id=digest[:24],
            producer=PRODUCER,
            producer_version=catalog.version,
            lane=Lane.LLM_LENS,
            scan_digest=digest,
            revision=revision,
            rule_id=f"lens.{candidate.lens_id}",
            location=SourceLocation(path=candidate.path, start_line=anchor, end_line=anchor),
            cwe_ids=(cwe,),
            source_severity="hypothesis",
            message=next(text for _, line, c, text in near if c == cwe),
        )
    report.rejected_quorum += 1
    return None


__all__ = [
    "PRODUCER",
    "LensCandidate",
    "LensLaneReport",
    "LensLaneUnavailableError",
    "run_lens_lane",
    "select_candidates",
]
