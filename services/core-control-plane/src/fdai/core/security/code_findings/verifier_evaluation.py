"""Precision and recall of the weakness verifiers against labeled real-code locations.

A labeled location names a sink in a pinned public project, the weakness class, which verifier
covers it (``python`` for the AST verifier or ``taint`` for an FDAI taint rule), and whether the
project documents it as vulnerable or safe. The delivery layer runs the verifiers and reports one
outcome per location; this module turns outcomes into per-verifier metrics and promotion
decisions. A verifier is promoted only when its precision meets the corpus floor with enough true
positives; otherwise it stays in shadow and can't grant ``verified`` confidence.
"""

from __future__ import annotations

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


class LocationOutcome(StrEnum):
    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    UNSUPPORTED = "unsupported"


class VerifierCorpusError(ValueError):
    """The verifier corpus is malformed."""


@dataclass(frozen=True, slots=True)
class LabeledLocation:
    source_id: str
    path: str
    line: int
    weakness_class: str
    verifier: str
    vulnerable: bool

    @property
    def key(self) -> str:
        """``python:<class>`` or the taint rule id ``fdai.verify.<language>.<rule>``."""
        if self.verifier == "python":
            return f"python:{self.weakness_class}"
        suffix = "." + self.path.rsplit(".", 1)[-1]
        return f"fdai.verify.{TAINT_LANGUAGES[suffix]}.{_TAINT_RULE_SUFFIX[self.weakness_class]}"


@dataclass(frozen=True, slots=True)
class VerifierMetrics:
    key: str
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    unsupported: int
    precision: float | None
    recall: float | None
    promoted: bool

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def verifier_metrics(
    locations: Sequence[LabeledLocation],
    outcomes: Mapping[LabeledLocation, LocationOutcome],
    *,
    precision_floor: float,
    min_true_positives: int,
) -> tuple[VerifierMetrics, ...]:
    """Aggregate outcomes per verifier key and decide promotion."""
    keys = sorted({location.key for location in locations})
    results: list[VerifierMetrics] = []
    for key in keys:
        tp = fp = fn = tn = unsupported = 0
        for location in (item for item in locations if item.key == key):
            outcome = outcomes.get(location, LocationOutcome.UNSUPPORTED)
            if outcome is LocationOutcome.UNSUPPORTED:
                unsupported += 1
            elif outcome is LocationOutcome.VERIFIED:
                tp, fp = (tp + 1, fp) if location.vulnerable else (tp, fp + 1)
            else:
                fn, tn = (fn + 1, tn) if location.vulnerable else (fn, tn + 1)
        precision = _ratio(tp, tp + fp)
        results.append(
            VerifierMetrics(
                key=key,
                true_positives=tp,
                false_positives=fp,
                false_negatives=fn,
                true_negatives=tn,
                unsupported=unsupported,
                precision=precision,
                recall=_ratio(tp, tp + fn),
                promoted=precision is not None
                and precision >= precision_floor
                and tp >= min_true_positives,
            )
        )
    return tuple(results)


def _text(raw: Mapping[str, object], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise VerifierCorpusError(f"{where}: {key} must be a non-empty string")
    return value


def locations_from_mapping(raw: object) -> tuple[dict[str, object], tuple[LabeledLocation, ...]]:
    """Validate a parsed verifier corpus and return its header and labeled locations."""
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
    seen: set[tuple[str, str, int]] = set()
    for source in sources:
        if not isinstance(source, Mapping):
            raise VerifierCorpusError("source must be a mapping")
        source_id = _text(source, "id", "source")
        for field in ("repository", "commit", "license", "label_source"):
            _text(source, field, source_id)
        if len(str(source["commit"])) != 40:
            raise VerifierCorpusError(f"{source_id}: commit must be a full 40-character id")
        items = source.get("locations")
        if not isinstance(items, list) or not items:
            raise VerifierCorpusError(f"{source_id}: locations must be a non-empty list")
        for item in items:
            if not isinstance(item, Mapping):
                raise VerifierCorpusError(f"{source_id}: location must be a mapping")
            path = _text(item, "path", source_id)
            line = item.get("line")
            if not isinstance(line, int) or isinstance(line, bool) or line < 1:
                raise VerifierCorpusError(f"{source_id}:{path}: line must be positive")
            label = item.get("label")
            verifier = item.get("verifier")
            weakness = _text(item, "weakness_class", source_id)
            if label not in ("vulnerable", "safe") or verifier not in ("python", "taint"):
                raise VerifierCorpusError(f"{source_id}:{path}:{line}: bad label or verifier")
            if label == "safe" and not isinstance(item.get("reason"), str):
                raise VerifierCorpusError(f"{source_id}:{path}:{line}: safe labels need a reason")
            if verifier == "taint" and (
                "." + path.rsplit(".", 1)[-1] not in TAINT_LANGUAGES
                or weakness not in _TAINT_RULE_SUFFIX
            ):
                raise VerifierCorpusError(f"{source_id}:{path}:{line}: no taint rule covers it")
            if (source_id, path, line) in seen:
                raise VerifierCorpusError(f"{source_id}:{path}:{line}: duplicate location")
            seen.add((source_id, path, line))
            locations.append(
                LabeledLocation(
                    source_id, path, line, weakness, str(verifier), label == "vulnerable"
                )
            )
    header = {
        "corpus_id": _text(raw, "corpus_id", "corpus"),
        "version": _text(raw, "version", "corpus"),
        "precision_floor": float(floor),
        "min_true_positives": minimum,
        "sources": [
            {key: source[key] for key in ("id", "repository", "commit", "license")}
            for source in sources
        ],
    }
    return header, tuple(locations)


def promoted_keys(metrics: Iterable[VerifierMetrics]) -> frozenset[str]:
    return frozenset(item.key for item in metrics if item.promoted)


__all__ = [
    "LabeledLocation",
    "LocationOutcome",
    "TAINT_LANGUAGES",
    "VerifierCorpusError",
    "VerifierMetrics",
    "locations_from_mapping",
    "promoted_keys",
    "verifier_metrics",
]
