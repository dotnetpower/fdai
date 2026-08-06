"""Bounded deployment-signal aggregation owned by the Norns learner."""

from __future__ import annotations

import hashlib
from typing import Any

from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.core.chaos.coverage import ScenarioCoverageAggregator


class NornsDeploymentLearning:
    """Aggregate scenario gaps and recurring preflight blockers into inert candidates."""

    def __init__(
        self,
        *,
        coverage_aggregator: ScenarioCoverageAggregator | None,
        preflight_blocker_threshold: int,
        max_tracked: int,
    ) -> None:
        if preflight_blocker_threshold < 2:
            raise ValueError("preflight_blocker_threshold MUST be >= 2")
        self._coverage_aggregator = coverage_aggregator
        self._preflight_blocker_threshold = preflight_blocker_threshold
        self._preflight_blocker_scopes: BoundedLruDict[str, frozenset[str]] = BoundedLruDict(
            max_tracked
        )
        self._preflight_blocker_proposed: BoundedLruSet[str] = BoundedLruSet(max_tracked)

    def observe_incident_symptom(
        self,
        *,
        incident_id: str,
        signal: str,
        target_type: str,
        severity: str,
    ) -> tuple[dict[str, Any], ...]:
        if self._coverage_aggregator is None:
            return ()
        self._coverage_aggregator.observe(
            incident_id=incident_id,
            signal=signal,
            target_type=target_type,
            severity=severity,
        )
        return tuple(
            {
                "source_signal": "scenario_coverage_gap",
                "evidence": candidate["target_symptom"],
                "provenance": candidate["provenance"],
                "proposed_by": "Norns",
                "proposal_kind": "new-scenario",
                "candidate_type": candidate["candidate_type"],
                "proposed_scenario_id": candidate["proposed_scenario_id"],
                "notes": candidate["notes"],
            }
            for candidate in self._coverage_aggregator.drain_proposals()
        )

    def observe_preflight_manual_blocker(
        self,
        *,
        finding_id: str,
        category: str,
        evidence_source: str,
        scope: str,
    ) -> dict[str, Any] | None:
        values = {
            "finding_id": finding_id,
            "category": category,
            "evidence_source": evidence_source,
            "scope": scope,
        }
        for name, value in values.items():
            if not value or len(value) > 512 or "\n" in value or "\r" in value:
                raise ValueError(f"preflight manual blocker {name} is invalid")
        blocker_digest = hashlib.sha256(
            "\0".join((category, finding_id, evidence_source)).encode()
        ).hexdigest()
        scope_digest = hashlib.sha256(scope.encode()).hexdigest()
        observed = set(self._preflight_blocker_scopes.get(blocker_digest) or ())
        if scope_digest in observed:
            return None
        observed.add(scope_digest)
        self._preflight_blocker_scopes.set(blocker_digest, frozenset(observed))
        if (
            len(observed) < self._preflight_blocker_threshold
            or blocker_digest in self._preflight_blocker_proposed
        ):
            return None
        self._preflight_blocker_proposed.add(blocker_digest)
        return {
            "source_signal": "recurring_preflight_manual_blocker",
            "evidence": {
                "finding_id": finding_id,
                "category": category,
                "source_ref": evidence_source,
                "occurrence_count": len(observed),
                "scope_digests": sorted(observed),
            },
            "provenance": {
                "source": "deployment_preflight",
                "blocker_digest": blocker_digest,
            },
            "proposed_by": "Norns",
            "proposal_kind": "new",
            "candidate_type": "preflight-toggle-gap",
            "target_rule_id": f"preflight-toggle-gap.{blocker_digest[:24]}",
            "suggested_pattern": "add_reviewed_preflight_alternate_rendering",
        }


__all__ = ["NornsDeploymentLearning"]
