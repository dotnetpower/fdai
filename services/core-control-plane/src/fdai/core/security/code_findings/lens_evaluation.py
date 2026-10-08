"""Label every kept LLM lens hypothesis against a corpus with an independent per-file verdict.

The lens corpus names one public benchmark whose maintainers label every test file: its weakness
category and whether the file is a real vulnerability. The harness evaluates a deterministic
sample (the first ``sample_per_label`` true and false files of each mapped category, in test-name
order), runs the lens lane over exactly those files, and labels each kept hypothesis:

- **true positive:** the hypothesis's lens class equals the file's mapped class and the file is a
  real vulnerability;
- **false positive:** anything else, including a hypothesis of another class, because each test
  file exercises one category.

Precision is per lens class and overall. Recall is the share of sampled vulnerable files of a class
that received at least one true-positive hypothesis. The module is pure: it never reads files or
calls models.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai.core.security.code_findings.models import Lane, Occurrence

_PROVENANCE = frozenset({"curated"})
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_CATEGORY = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_LENS_PREFIX = "lens."
_MAX_SAMPLE = 100


class LensCorpusError(ValueError):
    """The lens corpus document or its label file is malformed."""


@dataclass(frozen=True, slots=True)
class LensCorpus:
    corpus_id: str
    version: str
    provenance: str
    digest: str
    source_id: str
    repository: str
    commit: str
    license: str
    labels_path: str
    test_root: str
    file_suffix: str
    categories: Mapping[str, str]
    lenses: tuple[str, ...]
    sample_per_label: int


@dataclass(frozen=True, slots=True)
class LabeledFile:
    name: str
    path: str
    category: str
    weakness_class: str
    vulnerable: bool


@dataclass(frozen=True, slots=True)
class HypothesisLabel:
    path: str
    line: int
    lens_id: str
    weakness_class: str
    cwe: int | None
    true_positive: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "lens": self.lens_id,
            "weakness_class": self.weakness_class,
            "cwe": self.cwe,
            "label": "true_positive" if self.true_positive else "false_positive",
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LensClassMetrics:
    weakness_class: str
    kept: int
    true_positives: int
    false_positives: int
    precision: float | None
    vulnerable_files: int
    detected_files: int
    recall: float

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _str(raw: Mapping[str, object], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LensCorpusError(f"{where}: {key} must be a non-empty string")
    return value


def lens_corpus_from_mapping(raw: object, lens_classes: Mapping[str, str]) -> LensCorpus:
    """Validate a parsed lens corpus against the lens catalog's ``lens id -> class`` map."""
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
        raise LensCorpusError("lens corpus must be a mapping with schema_version 1")
    provenance = _str(raw, "provenance", "corpus")
    if provenance not in _PROVENANCE:
        raise LensCorpusError(f"corpus: provenance must be one of {sorted(_PROVENANCE)}")
    source = raw.get("source")
    if not isinstance(source, Mapping):
        raise LensCorpusError("corpus: source must be a mapping")
    commit = _str(source, "commit", "source")
    if _COMMIT.fullmatch(commit) is None:
        raise LensCorpusError("source: commit must be a full lowercase commit id")
    categories = raw.get("categories")
    if (
        not isinstance(categories, Mapping)
        or not categories
        or not all(
            isinstance(k, str) and _CATEGORY.fullmatch(k) and isinstance(v, str)
            for k, v in categories.items()
        )
    ):
        raise LensCorpusError("corpus: categories must map category ids to weakness classes")
    lenses = raw.get("lenses")
    if not isinstance(lenses, list) or not lenses or len(set(lenses)) != len(lenses):
        raise LensCorpusError("corpus: lenses must be a non-empty list of distinct lens ids")
    unknown = [lens for lens in lenses if lens not in lens_classes]
    if unknown:
        raise LensCorpusError(f"corpus: unknown lenses {unknown}")
    covered = {lens_classes[lens] for lens in lenses}
    if covered != set(categories.values()):
        raise LensCorpusError("corpus: lens classes must equal the mapped category classes")
    sample = raw.get("sample_per_label")
    if not isinstance(sample, int) or isinstance(sample, bool) or not 1 <= sample <= _MAX_SAMPLE:
        raise LensCorpusError(f"corpus: sample_per_label must be 1..{_MAX_SAMPLE}")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return LensCorpus(
        corpus_id=_str(raw, "corpus_id", "corpus"),
        version=_str(raw, "version", "corpus"),
        provenance=provenance,
        digest="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        source_id=_str(source, "id", "source"),
        repository=_str(source, "repository", "source"),
        commit=commit,
        license=_str(source, "license", "source"),
        labels_path=_str(source, "labels", "source"),
        test_root=_str(source, "test_root", "source").strip("/"),
        file_suffix=_str(source, "file_suffix", "source"),
        categories=dict(categories),
        lenses=tuple(str(lens) for lens in lenses),
        sample_per_label=sample,
    )


def parse_labels(text: str, corpus: LensCorpus) -> tuple[LabeledFile, ...]:
    """Parse ``test name, category, real vulnerability, ...`` rows for the mapped categories."""
    files: list[LabeledFile] = []
    seen: set[str] = set()
    rows = csv.reader(io.StringIO(text))
    for row in rows:
        if not row or row[0].lstrip().startswith("#"):
            continue
        if len(row) < 3:
            raise LensCorpusError("labels: every row needs a name, category, and verdict")
        name, category, verdict = (cell.strip() for cell in row[:3])
        if verdict not in {"true", "false"} or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", name):
            raise LensCorpusError(f"labels: malformed row for {name[:64]!r}")
        if name in seen:
            raise LensCorpusError(f"labels: duplicate test name {name}")
        seen.add(name)
        weakness_class = corpus.categories.get(category)
        if weakness_class is None:
            continue
        files.append(
            LabeledFile(
                name=name,
                path=f"{corpus.test_root}/{name}{corpus.file_suffix}",
                category=category,
                weakness_class=weakness_class,
                vulnerable=verdict == "true",
            )
        )
    return tuple(files)


def select_sample(
    files: Sequence[LabeledFile], corpus: LensCorpus, offset: int = 0
) -> tuple[LabeledFile, ...]:
    """Return N true and N false files per category in test-name order, after ``offset``.

    ``offset`` skips that many files per category and verdict, so ``offset`` equal to the sample
    size selects a sample disjoint from the default one.
    """
    if offset < 0:
        raise LensCorpusError("sample offset must not be negative")
    size = corpus.sample_per_label
    chosen: list[LabeledFile] = []
    for category in sorted(corpus.categories):
        for vulnerable in (True, False):
            pool = sorted(
                (f for f in files if f.category == category and f.vulnerable is vulnerable),
                key=lambda f: f.name,
            )
            if len(pool) < offset + size:
                raise LensCorpusError(f"labels: too few {category} files with verdict {vulnerable}")
            chosen.extend(pool[offset : offset + size])
    return tuple(chosen)


def label_hypotheses(
    occurrences: Sequence[Occurrence],
    sample: Sequence[LabeledFile],
    lens_classes: Mapping[str, str],
) -> tuple[HypothesisLabel, ...]:
    """Label every kept lens occurrence; occurrences of other lanes are ignored."""
    by_path = {item.path: item for item in sample}
    labels: list[HypothesisLabel] = []
    for occ in occurrences:
        if occ.lane is not Lane.LLM_LENS:
            continue
        lens_id = occ.rule_id.removeprefix(_LENS_PREFIX)
        weakness_class = lens_classes.get(lens_id, "unknown")
        target = by_path.get(occ.location.path)
        if target is None:
            verdict, reason = False, "file outside the labeled sample"
        elif target.weakness_class != weakness_class:
            verdict, reason = False, f"file exercises {target.category}, not this class"
        elif not target.vulnerable:
            verdict, reason = False, f"maintainers label this {target.category} file as safe"
        else:
            verdict, reason = True, f"maintainers label this {target.category} file vulnerable"
        labels.append(
            HypothesisLabel(
                path=occ.location.path,
                line=occ.location.start_line or 0,
                lens_id=lens_id,
                weakness_class=weakness_class,
                cwe=occ.cwe_ids[0] if occ.cwe_ids else None,
                true_positive=verdict,
                reason=reason,
            )
        )
    return tuple(sorted(labels, key=lambda item: (item.path, item.line, item.lens_id)))


def lens_metrics(
    labels: Sequence[HypothesisLabel], sample: Sequence[LabeledFile], classes: Sequence[str]
) -> tuple[LensClassMetrics, ...]:
    """Return per-class precision and recall over the labeled hypotheses."""
    metrics: list[LensClassMetrics] = []
    for weakness_class in sorted(set(classes)):
        mine = [item for item in labels if item.weakness_class == weakness_class]
        true_positives = sum(1 for item in mine if item.true_positive)
        vulnerable = {f.path for f in sample if f.weakness_class == weakness_class and f.vulnerable}
        detected = {item.path for item in mine if item.true_positive} & vulnerable
        metrics.append(
            LensClassMetrics(
                weakness_class=weakness_class,
                kept=len(mine),
                true_positives=true_positives,
                false_positives=len(mine) - true_positives,
                precision=round(true_positives / len(mine), 4) if mine else None,
                vulnerable_files=len(vulnerable),
                detected_files=len(detected),
                recall=round(len(detected) / len(vulnerable), 4) if vulnerable else 0.0,
            )
        )
    return tuple(metrics)


__all__ = [
    "HypothesisLabel",
    "LabeledFile",
    "LensClassMetrics",
    "LensCorpus",
    "LensCorpusError",
    "label_hypotheses",
    "lens_corpus_from_mapping",
    "lens_metrics",
    "parse_labels",
    "select_sample",
]
