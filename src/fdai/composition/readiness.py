"""Application wiring for one operational-readiness review."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.deploy_preflight import PreflightAnalyzer
from fdai.core.readiness import OwnershipTransfer, ReadinessReport, compose_readiness_report
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.feasibility_probe import PreflightTarget
from fdai.shared.providers.projection import Severity
from fdai.shared.providers.readiness import PostureAssessmentProvider, ReadinessReportPublisher
from fdai.shared.providers.state_store import StateStore


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _default_target(signal: OwnershipTransfer) -> PreflightTarget:
    return PreflightTarget(scope=signal.scope)


def _identity(signal: OwnershipTransfer) -> tuple[str, str]:
    material = "|".join(
        (
            signal.correlation_id or "",
            signal.scope,
            signal.submitter,
            signal.target_environment,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    event_id = signal.correlation_id or f"ownership-transfer-{digest[:16]}"
    return event_id, f"orr:{digest}"


@dataclass(frozen=True, slots=True)
class OperationalReadinessService:
    """Run posture and preflight checks, audit the verdict, then publish it."""

    posture: PostureAssessmentProvider
    preflight: PreflightAnalyzer
    publisher: ReadinessReportPublisher
    state_store: StateStore
    mode: Mode = Mode.SHADOW
    blocking_min_severity: Severity = "high"
    clock: Callable[[], str] = _utc_now_iso
    target_factory: Callable[[OwnershipTransfer], PreflightTarget] = _default_target

    async def review(self, signal: OwnershipTransfer) -> ReadinessReport:
        """Run one fail-closed review bound to ``signal``."""

        generated_at = self.clock()
        event_id, idempotency_key = _identity(signal)
        try:
            async with asyncio.TaskGroup() as group:
                posture_task = group.create_task(self.posture.findings_for_scope(signal.scope))
                preflight_task = group.create_task(
                    self.preflight.analyze(self.target_factory(signal))
                )
            report = compose_readiness_report(
                signal=signal,
                posture_findings=posture_task.result(),
                preflight_findings=preflight_task.result().findings,
                mode=self.mode,
                generated_at=generated_at,
                blocking_min_severity=self.blocking_min_severity,
            )
        except Exception as exc:
            await self.state_store.append_audit_entry(
                self._audit_entry(
                    signal=signal,
                    event_id=event_id,
                    idempotency_key=idempotency_key,
                    timestamp=generated_at,
                    decision="abstain",
                    outcome="assessment_failed",
                    detail={"error_type": type(exc).__name__},
                )
            )
            raise

        await self.state_store.append_audit_entry(
            self._audit_entry(
                signal=signal,
                event_id=event_id,
                idempotency_key=idempotency_key,
                timestamp=generated_at,
                decision=report.verdict.value,
                outcome="reviewed",
                detail={
                    "blocks_handoff": report.blocks_handoff,
                    "finding_count": len(report.findings),
                },
            )
        )
        try:
            await self.publisher.publish_readiness_report(report.to_dict())
        except Exception as exc:
            await self.state_store.append_audit_entry(
                self._audit_entry(
                    signal=signal,
                    event_id=event_id,
                    idempotency_key=f"{idempotency_key}:delivery",
                    timestamp=self.clock(),
                    decision="abstain",
                    outcome="delivery_failed",
                    detail={"error_type": type(exc).__name__},
                )
            )
            raise
        return report

    def _audit_entry(
        self,
        *,
        signal: OwnershipTransfer,
        event_id: str,
        idempotency_key: str,
        timestamp: str,
        decision: str,
        outcome: str,
        detail: dict[str, object],
    ) -> dict[str, object]:
        return {
            "kind": "operational_readiness.review",
            "event_id": event_id,
            "correlation_id": signal.correlation_id,
            "tier": "t0",
            "decision": decision,
            "outcome": outcome,
            "idempotency_key": idempotency_key,
            "actor_identity": signal.submitter,
            "timestamp": timestamp,
            "mode": self.mode.value,
            "rollback_reference": None,
            "scope": signal.scope,
            "target_environment": signal.target_environment,
            **detail,
        }


__all__ = ["OperationalReadinessService"]
