"""Offline evaluation of canonicalization and severity against a labeled corpus.

A corpus case lists the occurrences that one or more producers reported and the issues a reviewer
expects: one expected issue per root cause, with its weakness class, fix site, member occurrence
ids, the reviewer's severity band, and optionally the verified facts a deterministic verifier would
supply. The harness runs the real pipeline and measures:

- **Dedup:** pairwise precision and recall over "these two occurrences share a root cause", plus
  false-merge and false-split pair counts;
- **Detection:** issue-level precision and recall, where an expected issue is found when a produced
  issue has the same class and fix site;
- **Severity:** whether the reviewer band lies inside the produced floor-to-ceiling range before any
  facts are verified, and exact agreement plus quadratic-weighted Cohen's kappa over every issue
  whose severity is determined: by the labeled facts once supplied, or already without facts (for
  example a dependency advisory score);
- **Stability:** whether rerunning identical inputs reproduces identical issue ids and severities,
  and whether every issue is still matched by rescan matching after all code lines shift.

Each case has a kind, ``code`` for source-code weaknesses or ``dependency`` for vulnerable
packages, so the same metrics can be reported separately for code issues and for dependencies.

The harness is pure and deterministic: the same corpus and catalog produce the same metrics. It
measures FDAI's own decision layer, not any scanner's detection quality.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import combinations

from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import (
    CodeSecurityIssue,
    InstanceFacts,
    Lane,
    Occurrence,
    SourceLocation,
)
from fdai.core.security.code_findings.verification import BaselineIssue, matches_rescan
from fdai.rule_catalog.code_security import (
    BAND_ORDER,
    AttackVector,
    CodeSecurityCatalog,
    Exposure,
    Impact,
    PrivilegesRequired,
    SeverityBand,
    UserInteraction,
)

EVALUATION_REVISION = "0" * 40
_PROVENANCE = frozenset({"synthetic", "curated"})
_SPLITS = frozenset({"dev", "holdout"})
KINDS = ("code", "dependency")
_METRIC_FLOORS = (
    "dedup_precision",
    "dedup_recall",
    "detection_precision",
    "detection_recall",
    "severity_range_containment",
    "severity_exact_agreement",
    "severity_weighted_kappa",
    "line_shift_tracking",
)


class EvaluationCorpusError(ValueError):
    """The corpus document is malformed."""


@dataclass(frozen=True, slots=True)
class ExpectedIssue:
    weakness_class: str
    path: str
    line: int
    occurrence_ids: frozenset[str]
    reviewer_band: SeverityBand | None = None
    facts: InstanceFacts | None = None


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    exposure: Exposure
    occurrences: tuple[Occurrence, ...]
    expected: tuple[ExpectedIssue, ...]
    split: str = "dev"
    kind: str = "code"


@dataclass(frozen=True, slots=True)
class EvaluationCorpus:
    corpus_id: str
    version: str
    provenance: str
    digest: str
    line_shift: int
    acceptance: Mapping[str, float]
    cases: tuple[EvaluationCase, ...]


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    cases: int
    expected_issues: int
    produced_issues: int
    dedup_precision: float
    dedup_recall: float
    false_merge_pairs: int
    false_split_pairs: int
    detection_precision: float
    detection_recall: float
    severity_range_pairs: int
    severity_range_containment: float
    severity_pairs: int
    severity_exact_agreement: float
    severity_weighted_kappa: float
    line_shift_tracking: float
    stable: bool
    misses: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {name: getattr(self, name) for name in self.__dataclass_fields__}
        data["misses"] = list(self.misses)
        return data


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def _pairs(groups: Sequence[frozenset[str]]) -> set[frozenset[str]]:
    return {frozenset(pair) for group in groups for pair in combinations(sorted(group), 2)}


def weighted_kappa(pairs: Sequence[tuple[SeverityBand, SeverityBand]]) -> float:
    """Return quadratic-weighted Cohen's kappa over ordered severity bands.

    With perfect agreement and no expected disagreement the statistic is undefined; that case
    returns ``1.0`` when every pair agrees.
    """
    if not pairs:
        return 1.0
    k = len(BAND_ORDER)
    observed = [[0.0] * k for _ in range(k)]
    for left, right in pairs:
        observed[BAND_ORDER[left] - 1][BAND_ORDER[right] - 1] += 1
    n = float(len(pairs))
    rows = [sum(observed[i]) for i in range(k)]
    cols = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    disagreement = expected = 0.0
    for i in range(k):
        for j in range(k):
            weight = ((i - j) ** 2) / ((k - 1) ** 2)
            disagreement += weight * observed[i][j]
            expected += weight * rows[i] * cols[j] / n
    if expected == 0.0:
        return 1.0 if disagreement == 0.0 else 0.0
    return round(1.0 - disagreement / expected, 4)


def _matches(expected: ExpectedIssue, issue: CodeSecurityIssue) -> bool:
    """Same class and fix site, and at least one shared member occurrence.

    Dependency issues for different advisories share a manifest line, so the site alone can't
    tell them apart.
    """
    return (
        issue.weakness_class == expected.weakness_class
        and issue.fix_site.path == expected.path
        and (issue.fix_site.start_line or 0) == expected.line
        and bool(expected.occurrence_ids & set(issue.occurrence_ids))
    )


def _shifted(occurrences: Sequence[Occurrence], offset: int) -> tuple[Occurrence, ...]:
    shifted: list[Occurrence] = []
    for occ in occurrences:
        if occ.advisory_ids or occ.location.start_line is None:
            shifted.append(occ)
            continue
        end = occ.location.end_line
        location = replace(
            occ.location,
            start_line=occ.location.start_line + offset,
            end_line=None if end is None else end + offset,
        )
        shifted.append(replace(occ, location=location))
    return tuple(shifted)


def evaluate(corpus: EvaluationCorpus, catalog: CodeSecurityCatalog) -> EvaluationMetrics:
    """Run the pipeline on every case and aggregate the metrics."""
    truth_pairs = produced_pairs = shared_pairs = 0
    false_merges = false_splits = 0
    found = expected_total = matched_produced = produced_total = 0
    contained = range_pairs = tracked = baseline_total = 0
    severity: list[tuple[SeverityBand, SeverityBand]] = []
    misses: list[str] = []
    stable = True
    for case in corpus.cases:
        ctx = AnalysisContext(revision=EVALUATION_REVISION, exposure=case.exposure)
        issues = build_issues(case.occurrences, catalog, ctx)
        rerun = build_issues(case.occurrences, catalog, ctx)
        stable = stable and [(i.issue_id, i.severity) for i in issues] == [
            (i.issue_id, i.severity) for i in rerun
        ]
        truth = _pairs([item.occurrence_ids for item in case.expected])
        produced = _pairs([frozenset(issue.occurrence_ids) for issue in issues])
        truth_pairs += len(truth)
        produced_pairs += len(produced)
        shared_pairs += len(truth & produced)
        false_merges += len(produced - truth)
        false_splits += len(truth - produced)
        expected_total += len(case.expected)
        produced_total += len(issues)
        facts: dict[str, InstanceFacts] = {}
        matched: dict[int, CodeSecurityIssue] = {}
        for index, item in enumerate(case.expected):
            issue = next((candidate for candidate in issues if _matches(item, candidate)), None)
            if issue is None:
                misses.append(f"{case.case_id}:{item.weakness_class}:{item.path}:{item.line}")
                continue
            found += 1
            matched[index] = issue
            if item.reviewer_band is not None:
                range_pairs += 1
                band = BAND_ORDER[item.reviewer_band]
                low, high = BAND_ORDER[issue.severity.floor], BAND_ORDER[issue.severity.ceiling]
                contained += int(low <= band <= high)
                if item.facts is None and issue.severity.determined:
                    severity.append((issue.severity.floor, item.reviewer_band))
            if item.facts is not None:
                facts.update({instance.instance_id: item.facts for instance in issue.instances})
        matched_produced += len({issue.issue_id for issue in matched.values()})
        if facts:
            verified = build_issues(
                case.occurrences,
                catalog,
                AnalysisContext(
                    revision=EVALUATION_REVISION, exposure=case.exposure, instance_facts=facts
                ),
            )
            by_id = {issue.issue_id: issue for issue in verified}
            for index, issue in matched.items():
                item = case.expected[index]
                if item.facts is None or item.reviewer_band is None:
                    continue
                assessed = by_id[issue.issue_id].severity
                if assessed.determined:
                    severity.append((assessed.floor, item.reviewer_band))
                else:
                    misses.append(f"{case.case_id}:{issue.issue_id}:undetermined_with_facts")
        shifted = build_issues(_shifted(case.occurrences, corpus.line_shift), catalog, ctx)
        for issue in issues:
            baseline_total += 1
            tracked += int(matches_rescan(BaselineIssue.from_issue(issue), shifted))
    return EvaluationMetrics(
        cases=len(corpus.cases),
        expected_issues=expected_total,
        produced_issues=produced_total,
        dedup_precision=_ratio(shared_pairs, produced_pairs),
        dedup_recall=_ratio(shared_pairs, truth_pairs),
        false_merge_pairs=false_merges,
        false_split_pairs=false_splits,
        detection_precision=_ratio(matched_produced, produced_total),
        detection_recall=_ratio(found, expected_total),
        severity_range_pairs=range_pairs,
        severity_range_containment=_ratio(contained, range_pairs),
        severity_pairs=len(severity),
        severity_exact_agreement=_ratio(sum(1 for a, b in severity if a == b), len(severity)),
        severity_weighted_kappa=weighted_kappa(severity),
        line_shift_tracking=_ratio(tracked, baseline_total),
        stable=stable,
        misses=tuple(misses),
    )


def split_corpus(corpus: EvaluationCorpus, split: str) -> EvaluationCorpus | None:
    """Return the cases of one split as their own corpus, or ``None`` when the split is empty."""
    cases = tuple(case for case in corpus.cases if case.split == split)
    return replace(corpus, cases=cases) if cases else None


def kind_corpus(corpus: EvaluationCorpus, kind: str) -> EvaluationCorpus | None:
    """Return the cases of one kind as their own corpus, or ``None`` when the kind is empty."""
    cases = tuple(case for case in corpus.cases if case.kind == kind)
    return replace(corpus, cases=cases) if cases else None


def acceptance_failures(metrics: EvaluationMetrics, acceptance: Mapping[str, float]) -> list[str]:
    """Return the metric names that fall below the corpus acceptance floors."""
    failures = [
        name
        for name, floor in sorted(acceptance.items())
        if name in _METRIC_FLOORS and float(getattr(metrics, name)) < floor
    ]
    if not metrics.stable:
        failures.append("stable")
    return failures


def _str(raw: Mapping[str, object], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise EvaluationCorpusError(f"{where}: {key} must be a non-empty string")
    return value


def _strings(raw: Mapping[str, object], key: str, where: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise EvaluationCorpusError(f"{where}: {key} must be a list of strings")
    return tuple(value)


def _int(raw: Mapping[str, object], key: str, where: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise EvaluationCorpusError(f"{where}: {key} must be a positive integer")
    return value


def _facts(raw: object, where: str) -> InstanceFacts | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise EvaluationCorpusError(f"{where}: facts must be a mapping")
    try:
        return InstanceFacts(
            impact=Impact(raw["impact"]),
            attack_vector=AttackVector(raw["attack_vector"]),
            privileges_required=PrivilegesRequired(raw["privileges_required"]),
            user_interaction=UserInteraction(raw["user_interaction"]),
            evidence_refs=(f"evaluation:{where}",),
        )
    except (KeyError, ValueError) as exc:
        raise EvaluationCorpusError(f"{where}: invalid facts: {exc}") from exc


def _occurrence(raw: object, where: str) -> Occurrence:
    if not isinstance(raw, Mapping):
        raise EvaluationCorpusError(f"{where}: occurrence must be a mapping")
    cwe = raw.get("cwe", [])
    if not isinstance(cwe, list) or not all(isinstance(item, int) for item in cwe):
        raise EvaluationCorpusError(f"{where}: cwe must be a list of integers")
    score = raw.get("advisory_score")
    if score is not None and not isinstance(score, int | float):
        raise EvaluationCorpusError(f"{where}: advisory_score must be a number")
    try:
        lane = Lane(_str(raw, "lane", where))
    except ValueError as exc:
        raise EvaluationCorpusError(f"{where}: {exc}") from exc
    producer = _str(raw, "producer", where)
    package = raw.get("package")
    version = raw.get("package_version")
    return Occurrence(
        occurrence_id=_str(raw, "id", where),
        producer=producer,
        producer_version="evaluation",
        lane=lane,
        scan_digest="sha256:" + hashlib.sha256(producer.encode()).hexdigest(),
        revision=EVALUATION_REVISION,
        rule_id=_str(raw, "rule_id", where),
        location=SourceLocation(path=_str(raw, "path", where), start_line=_int(raw, "line", where)),
        cwe_ids=tuple(cwe),
        tags=_strings(raw, "tags", where),
        source_severity=str(raw.get("source_severity", "")),
        advisory_ids=_strings(raw, "advisories", where),
        package=package if isinstance(package, str) else None,
        package_version=version if isinstance(version, str) else None,
        advisory_score=float(score) if score is not None else None,
    )


def _expected(raw: object, where: str, known: set[str]) -> ExpectedIssue:
    if not isinstance(raw, Mapping):
        raise EvaluationCorpusError(f"{where}: expected issue must be a mapping")
    ids = frozenset(_strings(raw, "occurrences", where))
    if not ids or not ids <= known:
        raise EvaluationCorpusError(f"{where}: occurrences must name known occurrence ids")
    band = raw.get("reviewer_band")
    try:
        reviewer_band = SeverityBand(band) if band is not None else None
    except ValueError as exc:
        raise EvaluationCorpusError(f"{where}: {exc}") from exc
    return ExpectedIssue(
        weakness_class=_str(raw, "weakness_class", where),
        path=_str(raw, "path", where),
        line=_int(raw, "line", where),
        occurrence_ids=ids,
        reviewer_band=reviewer_band,
        facts=_facts(raw.get("facts"), where),
    )


def corpus_from_mapping(raw: object) -> EvaluationCorpus:
    """Validate a parsed corpus document and build its cases."""
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
        raise EvaluationCorpusError("corpus must be a mapping with schema_version 1")
    provenance = _str(raw, "provenance", "corpus")
    if provenance not in _PROVENANCE:
        raise EvaluationCorpusError(f"corpus: provenance must be one of {sorted(_PROVENANCE)}")
    acceptance = raw.get("acceptance", {})
    if not isinstance(acceptance, Mapping) or not all(
        name in _METRIC_FLOORS and isinstance(value, int | float)
        for name, value in acceptance.items()
    ):
        raise EvaluationCorpusError(f"corpus: acceptance keys must be in {list(_METRIC_FLOORS)}")
    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvaluationCorpusError("corpus: cases must be a non-empty list")
    cases: list[EvaluationCase] = []
    seen: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, Mapping):
            raise EvaluationCorpusError("corpus: case must be a mapping")
        case_id = _str(raw_case, "id", "case")
        if case_id in seen:
            raise EvaluationCorpusError(f"{case_id}: duplicate case id")
        seen.add(case_id)
        occurrences = tuple(
            _occurrence(item, f"{case_id}.occurrences") for item in raw_case.get("occurrences", [])
        )
        ids = [occ.occurrence_id for occ in occurrences]
        if len(set(ids)) != len(ids):
            raise EvaluationCorpusError(f"{case_id}: duplicate occurrence id")
        expected = tuple(
            _expected(item, f"{case_id}.expected", set(ids))
            for item in raw_case.get("expected", [])
        )
        claimed = [oid for item in expected for oid in item.occurrence_ids]
        if len(set(claimed)) != len(claimed):
            raise EvaluationCorpusError(f"{case_id}: an occurrence belongs to two expected issues")
        try:
            exposure = Exposure(str(raw_case.get("exposure", "unknown")))
        except ValueError as exc:
            raise EvaluationCorpusError(f"{case_id}: {exc}") from exc
        split = str(raw_case.get("split", "dev"))
        if split not in _SPLITS:
            raise EvaluationCorpusError(f"{case_id}: split must be one of {sorted(_SPLITS)}")
        derived = "dependency" if any(occ.package for occ in occurrences) else "code"
        kind = str(raw_case.get("kind", derived))
        if kind not in KINDS:
            raise EvaluationCorpusError(f"{case_id}: kind must be one of {list(KINDS)}")
        if kind != derived and occurrences:
            raise EvaluationCorpusError(f"{case_id}: kind {kind} contradicts its occurrences")
        cases.append(EvaluationCase(case_id, exposure, occurrences, expected, split, kind))
    shift = raw.get("line_shift", 7)
    if not isinstance(shift, int) or isinstance(shift, bool) or shift < 1:
        raise EvaluationCorpusError("corpus: line_shift must be a positive integer")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return EvaluationCorpus(
        corpus_id=_str(raw, "corpus_id", "corpus"),
        version=_str(raw, "version", "corpus"),
        provenance=provenance,
        digest="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        line_shift=shift,
        acceptance={name: float(value) for name, value in acceptance.items()},
        cases=tuple(cases),
    )


__all__ = [
    "EVALUATION_REVISION",
    "KINDS",
    "EvaluationCase",
    "EvaluationCorpus",
    "EvaluationCorpusError",
    "EvaluationMetrics",
    "ExpectedIssue",
    "acceptance_failures",
    "corpus_from_mapping",
    "evaluate",
    "kind_corpus",
    "split_corpus",
    "weighted_kappa",
]
