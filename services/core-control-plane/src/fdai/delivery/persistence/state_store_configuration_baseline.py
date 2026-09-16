"""Publish the latest completed configuration check through Core-owned state."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.detection.configuration_drift_codec import report_to_dict
from fdai.core.detection.configuration_drift_models import (
    ConfigurationDriftReport,
    FrozenConfigurationBaseline,
)
from fdai.shared.providers.state_store import StateStore

CONFIGURATION_BASELINE_PREFIX = "runtime:configuration-baseline:"


@dataclass(frozen=True, slots=True)
class StateStoreConfigurationBaselineSink:
    """Keep one audited, revision-fenced latest observation per exact scope.

    Equal evidence is idempotent, older observations cannot replace newer ones,
    and persistence or same-time evidence conflicts fail the calling check.
    Baseline activation and review campaigns remain deployment-owned.
    """

    store: StateStore

    async def record(
        self,
        baseline: FrozenConfigurationBaseline,
        report: ConfigurationDriftReport,
    ) -> None:
        """Persist verified metadata and measurements, never inferred history."""
        if (report.baseline_version, report.baseline_sha256, report.scope) != (
            baseline.version,
            baseline.sha256,
            baseline.scope,
        ):
            raise ValueError("configuration projection requires matching baseline evidence")
        if report.observed_at.tzinfo is None or report.observed_at.utcoffset() is None:
            raise ValueError("configuration projection requires an aware observation time")
        digest = hashlib.sha256(
            json.dumps(report_to_dict(report), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        key = CONFIGURATION_BASELINE_PREFIX + hashlib.sha256(baseline.scope.encode()).hexdigest()
        observed_at = report.observed_at.astimezone(UTC).isoformat()
        performance = report.performance
        payload: dict[str, object] = {
            "source": "core:configuration-drift",
            "evidence_digest": digest,
            "observed_at": observed_at,
            "baseline": {
                "version": baseline.version,
                "sha256": baseline.sha256,
                "scope": baseline.scope,
                "created_at": baseline.created_at.isoformat(),
                "document_name": baseline.source,
                "document_sha256": baseline.document_sha256,
                "lifecycle": "active-pinned",
                "resource_count": len(baseline.resources),
                "topology_count": len(baseline.links),
                "unknown_count": len(baseline.unknown_items),
            },
            "versions": [],
            "drift": {
                "verdict": report.verdict.value,
                "observed_at": observed_at,
                "finding_count": len(report.findings),
            },
            "knowledge": {
                "status": report.knowledge_status.value,
                "citation_count": len(report.knowledge_citations),
                "citations": list(report.knowledge_citations),
            },
            "safety": {
                "mutation_count": report.mutation_count,
                "approval_request_count": report.approval_request_count,
                "mitigation_execution_count": report.mitigation_execution_count,
                "unsupported_claim_count": report.unsupported_claim_count,
            },
            "performance": performance.to_dict() if performance is not None else None,
            "review": {
                "configured": False,
                "state": "not-configured",
                "completed_runs": 0,
                "required_runs": 0,
                "failed_attempts": 0,
            },
        }
        audit = {
            "kind": "configuration_baseline.projected",
            "correlation_id": digest,
            "evidence_digest": digest,
            "baseline_sha256": baseline.sha256,
            "observed_at": observed_at,
        }
        for _attempt in range(3):
            current = await self.store.read_state(key)
            if current is None:
                if await self.store.write_state_with_audit_if_absent(
                    key, {**payload, "revision": 1}, audit
                ):
                    return
                continue
            previous_time = datetime.fromisoformat(current["observed_at"])
            if previous_time > report.observed_at:
                return
            if current["evidence_digest"] == digest:
                return
            if previous_time == report.observed_at:
                raise ValueError("configuration projection has conflicting observation evidence")
            revision = current["revision"]
            if await self.store.compare_and_set_state_with_audit(
                key,
                {**payload, "revision": revision + 1},
                expected_revision=revision,
                audit_entry=audit,
            ):
                return
        raise RuntimeError("configuration projection update conflicted; retry the check")
