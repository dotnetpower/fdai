"""Precision and recall of the weakness verifiers against labeled real-code locations.

A labeled location names a sink in a pinned public project, the weakness class, which verifier
covers it (``python`` for the AST verifier or ``taint`` for an FDAI taint rule), whether the
project documents it as vulnerable or safe, and the split it belongs to. ``dev`` locations may
inform rule development; ``holdout`` locations must not. A location without a line labels a whole
file, the way a benchmark's expected-results file does: any verifier hit in that file counts.

Sources may list labels inline or point at the project's own expected-results file, which is
expanded only after the pinned tree is acquired. The delivery layer runs the verifiers and
reports one outcome per location; this module turns outcomes into per-verifier, per-split metrics
and promotion decisions. A verifier is promoted only when its precision meets the corpus floor
with enough true positives in every split; otherwise it stays in shadow and can't grant
``verified`` confidence.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

TAINT_LANGUAGES = {
    ".js": "js",
    ".jsx": "js",
    ".ts": "js",
    ".tsx": "js",
    ".java": "java",
    ".cs": "csharp",
}
_TAINT_RULE_SUFFIX = {
    "command_injection": "command-injection",
    "code_injection": "code-injection",
    "sql_injection": "sql-injection",
    "path_traversal": "path-traversal",
}
_PYTHON_CLASSES = frozenset(
    {
        "command_injection",
        "code_injection",
        "sql_injection",
        "path_traversal",
        "unsafe_deserialization",
    }
)
SPLITS = ("dev", "holdout")
_EXPECTED_SPLITS = frozenset({*SPLITS, "hash"})


class LocationOutcome(StrEnum):
    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    UNSUPPORTED = "unsupported"


class VerifierCorpusError(ValueError):
    """The verifier corpus or an expected-results file is malformed."""


def _verifier_key(verifier: str, path: str, weakness_class: str) -> str:
    if verifier == "python":
        return f"python:{weakness_class}"
    suffix = "." + path.rsplit(".", 1)[-1]
    return f"fdai.verify.{TAINT_LANGUAGES[suffix]}.{_TAINT_RULE_SUFFIX[weakness_class]}"


@dataclass(frozen=True, slots=True)
class LabeledLocation:
    source_id: str
    path: str
    line: int | None
    weakness_class: str
    verifier: str
    vulnerable: bool
    split: str = "dev"

    @property
    def key(self) -> str:
        """``python:<class>`` or the taint rule id ``fdai.verify.<language>.<rule>``."""
        return _verifier_key(self.verifier, self.path, self.weakness_class)


@dataclass(frozen=True, slots=True)
class ExpectedResults:
    """Labels read from a project's own expected-results CSV at the pinned commit.

    Rows are ``test name, category, real vulnerability, cwe``; lines starting with ``#`` are
    comments. Each mapped row labels the whole file ``path_template`` names for that test.
    """

    source_id: str
    file: str
    path_template: str
    verifier: str
    categories: Mapping[str, str]
    split: str

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(
            _verifier_key(self.verifier, self.path_template, weakness)
            for weakness in self.categories.values()
        )

    def split_for(self, test: str) -> str:
        if self.split != "hash":
            return self.split
        digest = hashlib.sha256(f"{self.source_id}:{test}".encode()).digest()
        return SPLITS[digest[0] % 2]

    def expand(self, text: str) -> tuple[LabeledLocation, ...]:
        """Return one whole-file location per mapped row of the expected-results text."""
        locations: list[LabeledLocation] = []
        seen: set[str] = set()
        for row in csv.reader(io.StringIO(text)):
            if not row or row[0].lstrip().startswith("#"):
                continue
            if len(row) < 3:
                raise VerifierCorpusError(f"{self.source_id}: expected-results row {row!r}")
            test, category, real = (cell.strip() for cell in row[:3])
            weakness = self.categories.get(category)
            if weakness is None:
                continue
            if real not in ("true", "false") or not test.replace("_", "").isalnum():
                raise VerifierCorpusError(f"{self.source_id}: expected-results row {row!r}")
            if test in seen:
                raise VerifierCorpusError(f"{self.source_id}: duplicate test {test}")
            seen.add(test)
            locations.append(
                LabeledLocation(
                    self.source_id,
                    self.path_template.format(test=test),
                    None,
                    weakness,
                    self.verifier,
                    real == "true",
                    self.split_for(test),
                )
            )
        if not locations:
            raise VerifierCorpusError(f"{self.source_id}: expected results matched no category")
        return tuple(locations)


@dataclass(frozen=True, slots=True)
class VerifierCorpus:
    header: dict[str, object]
    locations: tuple[LabeledLocation, ...]
    expected_results: tuple[ExpectedResults, ...]
    precision_floor: float
    min_true_positives: int

    def covered_keys(self) -> frozenset[str]:
        """Verifier keys that inline vulnerable labels or expected-results files can evidence."""
        inline = {item.key for item in self.locations if item.vulnerable}
        return frozenset(inline).union(*(spec.keys for spec in self.expected_results))


@dataclass(frozen=True, slots=True)
class SplitMetrics:
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    unsupported: int
    precision: float | None
    recall: float | None

    def qualifies(self, precision_floor: float, min_true_positives: int) -> bool:
        return (
            self.precision is not None
            and self.precision >= precision_floor
            and self.true_positives >= min_true_positives
        )

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class VerifierMetrics:
    key: str
    dev: SplitMetrics
    holdout: SplitMetrics
    promoted: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "dev": self.dev.as_dict(),
            "holdout": self.holdout.as_dict(),
            "promoted": self.promoted,
        }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _split_metrics(
    locations: Iterable[LabeledLocation], outcomes: Mapping[LabeledLocation, LocationOutcome]
) -> SplitMetrics:
    tp = fp = fn = tn = unsupported = 0
    for location in locations:
        outcome = outcomes.get(location, LocationOutcome.UNSUPPORTED)
        if outcome is LocationOutcome.UNSUPPORTED:
            unsupported += 1
        elif outcome is LocationOutcome.VERIFIED:
            tp, fp = (tp + 1, fp) if location.vulnerable else (tp, fp + 1)
        else:
            fn, tn = (fn + 1, tn) if location.vulnerable else (fn, tn + 1)
    return SplitMetrics(tp, fp, fn, tn, unsupported, _ratio(tp, tp + fp), _ratio(tp, tp + fn))


def verifier_metrics(
    locations: Sequence[LabeledLocation],
    outcomes: Mapping[LabeledLocation, LocationOutcome],
    *,
    precision_floor: float,
    min_true_positives: int,
) -> tuple[VerifierMetrics, ...]:
    """Aggregate outcomes per verifier key and split, and decide promotion.

    A verifier is promoted only when both the dev and the holdout split meet the precision floor
    with at least ``min_true_positives`` true positives each.
    """
    results: list[VerifierMetrics] = []
    for key in sorted({location.key for location in locations}):
        mine = [item for item in locations if item.key == key]
        dev, holdout = (
            _split_metrics((item for item in mine if item.split == split), outcomes)
            for split in SPLITS
        )
        results.append(
            VerifierMetrics(
                key=key,
                dev=dev,
                holdout=holdout,
                promoted=dev.qualifies(precision_floor, min_true_positives)
                and holdout.qualifies(precision_floor, min_true_positives),
            )
        )
    return tuple(results)


def _text(raw: Mapping[str, object], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise VerifierCorpusError(f"{where}: {key} must be a non-empty string")
    return value


def _split(raw: Mapping[str, object], where: str, default: str | None) -> str:
    value = raw.get("split", default)
    if value not in SPLITS:
        raise VerifierCorpusError(f"{where}: split must be one of {list(SPLITS)}")
    return str(value)


def _check_coverage(verifier: object, path: str, weakness: str, where: str) -> str:
    if verifier == "python":
        if not path.endswith(".py") or weakness not in _PYTHON_CLASSES:
            raise VerifierCorpusError(f"{where}: the python verifier doesn't cover it")
        return "python"
    if verifier == "taint":
        if "." + path.rsplit(".", 1)[-1] not in TAINT_LANGUAGES or weakness not in (
            _TAINT_RULE_SUFFIX
        ):
            raise VerifierCorpusError(f"{where}: no taint rule covers it")
        return "taint"
    raise VerifierCorpusError(f"{where}: bad label or verifier")


def _expected_results(raw: object, source_id: str, source_split: str | None) -> ExpectedResults:
    if not isinstance(raw, Mapping):
        raise VerifierCorpusError(f"{source_id}: expected_results must be a mapping")
    file = _text(raw, "file", source_id)
    template = _text(raw, "path_template", source_id)
    if "{test}" not in template or file.startswith("/") or ".." in file.split("/"):
        raise VerifierCorpusError(f"{source_id}: bad expected_results file or path_template")
    split = raw.get("split", source_split)
    if split not in _EXPECTED_SPLITS:
        raise VerifierCorpusError(f"{source_id}: split must be one of {sorted(_EXPECTED_SPLITS)}")
    categories = raw.get("categories")
    if not isinstance(categories, Mapping) or not categories:
        raise VerifierCorpusError(f"{source_id}: categories must be a non-empty mapping")
    verifier = ""
    for category, weakness in categories.items():
        if not isinstance(category, str) or not isinstance(weakness, str):
            raise VerifierCorpusError(f"{source_id}: categories must map strings to classes")
        verifier = _check_coverage(raw.get("verifier"), template, weakness, source_id)
    return ExpectedResults(source_id, file, template, verifier, dict(categories), str(split))


def load_verifier_corpus(raw: object) -> VerifierCorpus:
    """Validate a parsed verifier corpus and return its header, labels, and label files."""
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
        raise VerifierCorpusError("verifier corpus must be a mapping with schema_version 1")
    if raw.get("provenance") != "curated":
        raise VerifierCorpusError("verifier corpus provenance must be curated")
    floor = raw.get("precision_floor")
    minimum = raw.get("min_true_positives")
    if not isinstance(floor, int | float) or not 0 < float(floor) <= 1:
        raise VerifierCorpusError("precision_floor must be in (0, 1]")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        raise VerifierCorpusError("min_true_positives must be a positive integer")
    sources = raw.get("sources")
    if not isinstance(sources, list) or not sources:
        raise VerifierCorpusError("sources must be a non-empty list")
    locations: list[LabeledLocation] = []
    expected: list[ExpectedResults] = []
    seen: set[tuple[str, str, int | None, str]] = set()
    ids: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping):
            raise VerifierCorpusError("source must be a mapping")
        source_id = _text(source, "id", "source")
        if source_id in ids:
            raise VerifierCorpusError(f"{source_id}: duplicate source id")
        ids.add(source_id)
        for field in ("repository", "commit", "license", "label_source"):
            _text(source, field, source_id)
        if len(str(source["commit"])) != 40:
            raise VerifierCorpusError(f"{source_id}: commit must be a full 40-character id")
        source_split = source.get("split")
        if source_split is not None:
            _split(source, source_id, None)
        items = source.get("locations", [])
        if "expected_results" in source:
            expected.append(
                _expected_results(
                    source["expected_results"],
                    source_id,
                    None if source_split is None else str(source_split),
                )
            )
        elif not isinstance(items, list) or not items:
            raise VerifierCorpusError(f"{source_id}: locations must be a non-empty list")
        if not isinstance(items, list):
            raise VerifierCorpusError(f"{source_id}: locations must be a list")
        for item in items:
            if not isinstance(item, Mapping):
                raise VerifierCorpusError(f"{source_id}: location must be a mapping")
            path = _text(item, "path", source_id)
            line = item.get("line")
            if not isinstance(line, int) or isinstance(line, bool) or line < 1:
                raise VerifierCorpusError(f"{source_id}:{path}: line must be positive")
            where = f"{source_id}:{path}:{line}"
            label = item.get("label")
            weakness = _text(item, "weakness_class", source_id)
            if label not in ("vulnerable", "safe"):
                raise VerifierCorpusError(f"{where}: bad label or verifier")
            verifier = _check_coverage(item.get("verifier"), path, weakness, where)
            if label == "safe" and not isinstance(item.get("reason"), str):
                raise VerifierCorpusError(f"{where}: safe labels need a reason")
            split = _split(item, where, None if source_split is None else str(source_split))
            if (source_id, path, line, weakness) in seen:
                raise VerifierCorpusError(f"{where}: duplicate location")
            seen.add((source_id, path, line, weakness))
            locations.append(
                LabeledLocation(
                    source_id, path, line, weakness, verifier, label == "vulnerable", split
                )
            )
    header: dict[str, object] = {
        "corpus_id": _text(raw, "corpus_id", "corpus"),
        "version": _text(raw, "version", "corpus"),
        "precision_floor": float(floor),
        "min_true_positives": minimum,
        "sources": [
            {key: source[key] for key in ("id", "repository", "commit", "license")}
            for source in sources
        ],
    }
    return VerifierCorpus(header, tuple(locations), tuple(expected), float(floor), minimum)


def promoted_keys(metrics: Iterable[VerifierMetrics]) -> frozenset[str]:
    return frozenset(item.key for item in metrics if item.promoted)


__all__ = [
    "SPLITS",
    "TAINT_LANGUAGES",
    "ExpectedResults",
    "LabeledLocation",
    "LocationOutcome",
    "SplitMetrics",
    "VerifierCorpus",
    "VerifierCorpusError",
    "VerifierMetrics",
    "load_verifier_corpus",
    "promoted_keys",
    "verifier_metrics",
]
