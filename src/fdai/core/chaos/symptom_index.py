"""Symptom -> scenarios inverted index for O(1) lookup.

Given a live incident symptom (`SymptomKey = (signal_id, target_type,
severity_bucket)`), returns the list of catalog scenarios that
produce that symptom. Consumed by:

- **RCA / trust router**: when an event enters the pipeline, look up
  `symptom_index[(signal_id, target_type, severity)]` to get the
    candidate scenarios that explain it in O(1). The current RCA path
    uses deterministic widening and supplies the results as T2 evidence;
    similarity re-ranking is not wired yet.
- **Chaos harness (advisory)**: given the same symptom, propose the
  smallest scenario that reproduces it as a repro / verification
  experiment; Loki proposes, Forseti judges, Var approves.

The index is built from `load_promoted()` (runtime path) or
`load_all()` (tooling / CI). Falling back on `load_all()` in dev keeps
the index useful before scenarios have been promoted.

Design intent (see
`docs/internals/sre-scenario-library-scaling.md#symptom-index-for-o1-lookup`):

    symptom_index: dict[SymptomKey, list[ScenarioRef]]
    SymptomKey = (signal_id, target_type, severity_bucket)

- severity_bucket is derived from the scenario `intensity` field
  (`mild` -> `low`, `high` -> `medium`, `extreme` -> `high`), keeping
  incidents that share a symptom family together while still allowing
  a router to prefer a lower-intensity match on a lower-severity
  incident.
- The index also carries a fallback: if no exact triple matches, the
  router can widen to `(signal_id, target_type, None)` or
  `(signal_id, None, None)` via the `lookup_widening` helper.
- The committed tooling snapshot is generated explicitly by
    `scripts/build-symptom-index.py`; runtime callers can rebuild from
    promoted entries in memory or load a snapshot for cold-start speed.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from fdai.core.chaos.scenario_catalog import CatalogEntry, load_all, load_promoted

_HERE = pathlib.Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[4]

_INTENSITY_TO_SEVERITY: Mapping[str, str] = {
    "mild": "low",
    "high": "medium",
    "extreme": "high",
}


@dataclass(frozen=True, slots=True)
class ScenarioRef:
    """A lightweight reference to one catalog scenario.

    Kept smaller than the full :class:`CatalogEntry` so the index can be
    JSON-serialized without carrying the entire spec into the compiled
    artifact.
    """

    id: str
    expected_signal: str
    target_type: str
    intensity: str
    severity_bucket: str
    category: str
    injector: str
    requires_hardware: bool
    gpu_domain: str | None
    source_path: str

    @classmethod
    def from_entry(cls, e: CatalogEntry) -> ScenarioRef:
        intensity = str(e.spec["intensity"])
        severity = _INTENSITY_TO_SEVERITY.get(intensity, "medium")
        # Repo-relative path so the compiled artifact never leaks an
        # absolute build-host path when committed.
        try:
            rel = e.source_path.resolve().relative_to(_REPO_ROOT)
            source = str(rel)
        except ValueError:
            source = str(e.source_path)
        return cls(
            id=e.id,
            expected_signal=e.expected_signal,
            target_type=str(e.spec["target_type"]),
            intensity=intensity,
            severity_bucket=severity,
            category=e.category,
            injector=str(e.spec["injector"]),
            requires_hardware=e.requires_hardware,
            gpu_domain=e.gpu_domain,
            source_path=source,
        )


SymptomKey = tuple[str, str | None, str | None]
"""(signal_id, target_type_or_None, severity_bucket_or_None)."""


@dataclass(frozen=True, slots=True)
class SymptomIndex:
    """Read-only inverted index. Build via :func:`build_from_entries`
    (fast, in-memory) or :func:`load_snapshot` (JSON, cold-start)."""

    by_key: Mapping[SymptomKey, tuple[ScenarioRef, ...]]

    def lookup(self, key: SymptomKey) -> tuple[ScenarioRef, ...]:
        """Exact match; empty tuple if nothing."""
        return self.by_key.get(key, ())

    def lookup_widening(
        self, signal: str, target_type: str, severity: str
    ) -> tuple[ScenarioRef, ...]:
        """Try exact, then drop severity, then drop target_type.

        Returns the first non-empty bucket in the widening path; empty
        tuple if the signal is unknown to the catalog.
        """
        for k in (
            (signal, target_type, severity),
            (signal, target_type, None),
            (signal, None, None),
        ):
            hit = self.by_key.get(k, ())
            if hit:
                return hit
        return ()

    def all_signals(self) -> frozenset[str]:
        return frozenset(k[0] for k in self.by_key)

    def size(self) -> int:
        return sum(len(v) for v in self.by_key.values())


def _bucketize(entries: Iterable[CatalogEntry]) -> Mapping[SymptomKey, tuple[ScenarioRef, ...]]:
    """Build the multi-level buckets: exact + target-only + signal-only."""
    exact: dict[SymptomKey, list[ScenarioRef]] = {}
    by_signal_target: dict[SymptomKey, list[ScenarioRef]] = {}
    by_signal: dict[SymptomKey, list[ScenarioRef]] = {}
    for e in entries:
        ref = ScenarioRef.from_entry(e)
        exact_key: SymptomKey = (ref.expected_signal, ref.target_type, ref.severity_bucket)
        target_key: SymptomKey = (ref.expected_signal, ref.target_type, None)
        signal_key: SymptomKey = (ref.expected_signal, None, None)
        exact.setdefault(exact_key, []).append(ref)
        by_signal_target.setdefault(target_key, []).append(ref)
        by_signal.setdefault(signal_key, []).append(ref)
    merged: dict[SymptomKey, tuple[ScenarioRef, ...]] = {}
    for k, v in exact.items():
        merged[k] = tuple(sorted(v, key=lambda r: r.id))
    for k, v in by_signal_target.items():
        merged[k] = tuple(sorted(v, key=lambda r: r.id))
    for k, v in by_signal.items():
        merged[k] = tuple(sorted(v, key=lambda r: r.id))
    return merged


def build_from_entries(entries: Iterable[CatalogEntry]) -> SymptomIndex:
    return SymptomIndex(by_key=_bucketize(entries))


def build_from_promoted() -> SymptomIndex:
    return build_from_entries(load_promoted())


def build_from_all() -> SymptomIndex:
    return build_from_entries(load_all())


def _key_to_str(k: SymptomKey) -> str:
    # `|` chosen because signals / target names cannot contain it.
    return f"{k[0]}|{k[1] or ''}|{k[2] or ''}"


def _str_to_key(s: str) -> SymptomKey:
    signal, target, severity = s.split("|", 2)
    return (signal, target or None, severity or None)


def write_snapshot(index: SymptomIndex, path: pathlib.Path) -> None:
    """Serialize the index to JSON for cold-start reuse."""
    payload: dict[str, list[dict[str, Any]]] = {}
    for k, refs in index.by_key.items():
        payload[_key_to_str(k)] = [
            {
                "id": r.id,
                "expected_signal": r.expected_signal,
                "target_type": r.target_type,
                "intensity": r.intensity,
                "severity_bucket": r.severity_bucket,
                "category": r.category,
                "injector": r.injector,
                "requires_hardware": r.requires_hardware,
                "gpu_domain": r.gpu_domain,
                "source_path": r.source_path,
            }
            for r in refs
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load_snapshot(path: pathlib.Path) -> SymptomIndex:
    payload = json.loads(path.read_text())
    by_key: dict[SymptomKey, tuple[ScenarioRef, ...]] = {}
    for skey, items in payload.items():
        k = _str_to_key(skey)
        refs = tuple(
            ScenarioRef(
                id=item["id"],
                expected_signal=item["expected_signal"],
                target_type=item["target_type"],
                intensity=item["intensity"],
                severity_bucket=item["severity_bucket"],
                category=item["category"],
                injector=item["injector"],
                requires_hardware=item["requires_hardware"],
                gpu_domain=item.get("gpu_domain"),
                source_path=item["source_path"],
            )
            for item in items
        )
        by_key[k] = refs
    return SymptomIndex(by_key=by_key)


__all__ = [
    "ScenarioRef",
    "SymptomIndex",
    "SymptomKey",
    "build_from_all",
    "build_from_entries",
    "build_from_promoted",
    "load_snapshot",
    "write_snapshot",
]
