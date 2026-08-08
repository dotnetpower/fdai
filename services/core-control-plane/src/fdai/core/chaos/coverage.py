"""Scenario-coverage learner - propose scenario candidates for uncovered symptoms.

Feeds the autonomous discovery loop described in
`.github/instructions/architecture.instructions.md` and
`docs/internals/sre-scenario-library-scaling.md`: when a live incident
arrives with a symptom (signal + target_type + severity) that the
compiled chaos-scenarios symptom index cannot match, Norns should see
it and (after enough evidence) propose a new scenario candidate for
Mimir's promotion gate.

Design intent:

- **This module never mutates the catalog.** It emits inert dicts that
  Norns pushes onto its `pending_candidates` list, exactly like the
  existing fingerprint / outcome / override learners.
- **Every proposal cites grounded evidence.** The `provenance` field
  names the operational observations (`sample_incidents`) that led to
  the proposal, so Mimir's `CandidateGuard` treats it the same way it
  treats any other grounded proposal.
- **Bounded memory.** The learner keeps at most `_MAX_TRACKED` distinct
  symptom keys and at most `sample_incidents_cap` example incident ids
  per key.
- **Idempotent proposals.** A symptom key that has already crossed the
  threshold is remembered so re-observation does not re-propose.

The module is `core/` code: no `delivery/` imports, no cloud SDKs, no
subprocess. `Norns` (or any fork) composes an instance and calls
`observe(...)` / `proposals()`.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any

from fdai.core.chaos.symptom_index import SymptomIndex

_MAX_TRACKED = 50_000


@dataclass(frozen=True, slots=True)
class _Track:
    """Per-symptom-key aggregate. Mutable state lives in the deque + counter."""

    signal: str
    target_type: str
    severity: str
    sample_incidents: tuple[str, ...]
    count: int


class ScenarioCoverageAggregator:
    """Aggregate uncovered-symptom observations and emit scenario proposals.

    Composition:

        agg = ScenarioCoverageAggregator(index=my_symptom_index,
                                         gap_threshold=3)
        for evt in incoming_events:
            agg.observe(
                incident_id=evt.id,
                signal=evt.signal,
                target_type=evt.resource_type,
                severity=evt.severity_bucket,
            )
        for candidate in agg.drain_proposals():
            norns.pending_candidates.append(candidate)

    Threshold semantics: an uncovered symptom must be observed
    `gap_threshold` times (in distinct incidents) before a proposal is
    emitted. `drain_proposals()` returns each proposal exactly once -
    the same symptom key does not re-propose unless the index is
    refreshed (via `rebind_index`).
    """

    def __init__(
        self,
        *,
        index: SymptomIndex,
        gap_threshold: int = 3,
        sample_incidents_cap: int = 5,
    ) -> None:
        if gap_threshold < 1:
            raise ValueError("gap_threshold MUST be >= 1")
        if sample_incidents_cap < 1:
            raise ValueError("sample_incidents_cap MUST be >= 1")
        self._index = index
        self._gap_threshold = gap_threshold
        self._sample_cap = sample_incidents_cap
        # OrderedDict as bounded LRU: capped by _MAX_TRACKED so a long-lived
        # learner cannot leak one entry per distinct symptom forever.
        self._pending: OrderedDict[tuple[str, str, str], deque[str]] = OrderedDict()
        self._counts: OrderedDict[tuple[str, str, str], int] = OrderedDict()
        # Distinct-incident dedup, kept separate from the display deque so a
        # small sample_incidents_cap cannot evict a seen id and let it re-count
        # toward the threshold. The key (and its set) is dropped once the
        # threshold crosses, so each set is bounded by gap_threshold and
        # _MAX_TRACKED bounds the number of keys.
        self._seen: OrderedDict[tuple[str, str, str], set[str]] = OrderedDict()
        # Already-proposed keys; a symptom key does not re-propose until
        # the index is rebound.
        self._proposed: OrderedDict[tuple[str, str, str], None] = OrderedDict()
        self._ready: list[dict[str, Any]] = []

    def rebind_index(self, index: SymptomIndex) -> None:
        """Swap in a fresh SymptomIndex (e.g. after a catalog PR merged).

        Also clears the `_proposed` memo so a symptom that was previously
        uncovered but that a merged scenario now covers is not eligible
        for a duplicate proposal, and vice versa.
        """
        self._index = index
        self._proposed.clear()

    def observe(
        self,
        *,
        incident_id: str,
        signal: str,
        target_type: str,
        severity: str,
    ) -> None:
        """Record one observation. Emits nothing until the threshold is met."""
        if not incident_id:
            raise ValueError("incident_id MUST be non-empty")
        if not signal:
            raise ValueError("signal MUST be non-empty")
        # Covered by the catalog? Then this is not a gap - drop.
        hits = self._index.lookup_widening(
            signal=signal, target_type=target_type, severity=severity
        )
        if hits:
            return
        key = (signal, target_type, severity)
        if key in self._proposed:
            return
        # Track sample incident ids (bounded per key + de-duplicated).
        samples = self._pending.get(key)
        if samples is None:
            samples = deque(maxlen=self._sample_cap)
            self._pending[key] = samples
            self._counts[key] = 0
            self._seen[key] = set()
            self._enforce_cap()
        # Only count NEW incident ids toward the threshold; the same incident
        # observed twice must not double-count. The `_seen` set is the
        # authoritative dedup (the deque only holds the most recent sample_cap
        # ids for display), so a sample_cap smaller than gap_threshold cannot
        # evict a seen id and let it re-count.
        if incident_id not in self._seen[key]:
            self._seen[key].add(incident_id)
            samples.append(incident_id)
            self._counts[key] = self._counts.get(key, 0) + 1
        # Threshold crossed? Materialize the proposal.
        if self._counts[key] >= self._gap_threshold:
            self._ready.append(self._materialize(key, tuple(samples)))
            self._proposed[key] = None
            # Free the buffers for this key; it will not re-emit until rebind.
            del self._pending[key]
            del self._counts[key]
            del self._seen[key]
            self._enforce_cap()

    def drain_proposals(self) -> list[dict[str, Any]]:
        """Return all threshold-crossing proposals and clear the ready list."""
        out = self._ready
        self._ready = []
        return out

    def uncovered_symptom_count(self) -> int:
        """How many distinct uncovered symptom keys are we currently tracking?"""
        return len(self._pending)

    def proposed_count(self) -> int:
        """How many proposals has this aggregator emitted (post-drain)?"""
        return len(self._proposed)

    def _enforce_cap(self) -> None:
        while len(self._pending) > _MAX_TRACKED:
            self._pending.popitem(last=False)
            # counts key mirrors pending; discard silently
        while len(self._counts) > _MAX_TRACKED:
            self._counts.popitem(last=False)
        while len(self._seen) > _MAX_TRACKED:
            self._seen.popitem(last=False)
        while len(self._proposed) > _MAX_TRACKED:
            self._proposed.popitem(last=False)

    def _materialize(self, key: tuple[str, str, str], samples: tuple[str, ...]) -> dict[str, Any]:
        signal, target_type, severity = key
        # Kebab-safe id fragment for downstream schema. Blank target
        # becomes `unspecified` so the id shape is always valid.
        target_slug = (target_type or "unspecified").replace("_", "-")
        return {
            "candidate_type": "scenario-coverage-gap",
            # Grounded provenance: names the observation stream and the
            # sample incident ids that triggered the proposal.
            "provenance": {
                "source": "internal-incident",
                "synthesis_method": "distilled",
                "sample_incidents": list(samples),
                "observed_count": self._gap_threshold,
            },
            "target_symptom": {
                "signal": signal,
                "target_type": target_type,
                "severity": severity,
            },
            "proposed_scenario_id": (
                f"chaos.coverage-gap.{signal.replace('_', '-')}-on-{target_slug}"
            ),
            "notes": (
                f"{self._gap_threshold} distinct incidents observed with signal="
                f"{signal} target_type={target_type} severity={severity}, "
                "and no catalog scenario matches. Propose a new scenario or "
                "widen an existing one to cover this symptom."
            ),
        }


__all__ = ["ScenarioCoverageAggregator"]
