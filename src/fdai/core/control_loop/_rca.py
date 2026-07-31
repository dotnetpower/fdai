"""Best-effort root-cause analysis stages for the control loop."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.control_loop._helpers import _extract_resource_id
from fdai.core.event_ingest import EventCorrelator
from fdai.core.rca import (
    CausalRuntimeCoordinator,
    Citation,
    CitationKind,
    IncidentMemberSource,
    RcaCoordinator,
    RcaResult,
)
from fdai.core.trust_router import RoutingDecision
from fdai.shared.contracts.models import Event, Mode, Rule
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.core.control_loop.orchestrator")


class ControlLoopRcaMixin:
    """Correlate incidents and append shadow-only RCA evidence."""

    _audit_store: StateStore
    _rca_coordinator: RcaCoordinator | None
    _event_correlator: EventCorrelator | None
    _incident_member_source: IncidentMemberSource | None
    _causal_runtime_coordinator: CausalRuntimeCoordinator | None
    _causal_chain_window: timedelta
    _resource_dependency_graph: Mapping[str, Iterable[str]] | None

    def _correlate_incident_id(self, event: Event) -> str | None:
        """Anchor an event to a deterministic incident id, or ``None``."""
        if self._event_correlator is None:
            return None
        result = self._event_correlator.correlate(event)
        return result.incident_id if result.correlated else None

    async def _analyze_and_audit_rca(
        self,
        *,
        event: Event,
        finding: Any,
        rule: Rule,
        resource_type: str | None,
        incident_id: str | None = None,
    ) -> None:
        """Append a deterministic T0 root-cause hypothesis to the audit."""
        if self._rca_coordinator is None:
            return
        try:
            result = self._rca_coordinator.analyze_t0(
                rule=rule,
                resource_type=resource_type or "unknown",
                event_id=str(event.event_id),
            )
            hypothesis = result.hypothesis
            await self._audit_store.append_audit_entry(
                {
                    "event_id": str(event.event_id),
                    "correlation_id": event.correlation_id or str(event.event_id),
                    "idempotency_key": f"{event.idempotency_key}:rca:{finding.rule_id}",
                    "actor": "fdai.core.rca",
                    "producer_principal": "Forseti",
                    "action_kind": "rca.hypothesis",
                    "mode": Mode.SHADOW.value,
                    "rule_id": finding.rule_id,
                    "incident_id": incident_id,
                    "rca_outcome": result.outcome.value,
                    "rca_reason": result.reason,
                    "rca_tier": hypothesis.tier.value if hypothesis else None,
                    "rca_cause": hypothesis.cause if hypothesis else None,
                    "rca_confidence": hypothesis.confidence if hypothesis else None,
                    "rca_citations": (
                        [{"kind": c.kind.value, "ref": c.ref} for c in hypothesis.citations]
                        if hypothesis
                        else []
                    ),
                    "rca_remediation_ref": hypothesis.remediation_ref if hypothesis else None,
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                }
            )
        except Exception:  # noqa: BLE001 - RCA is best-effort; decision path unaffected
            _LOGGER.warning(
                "rca_analyze_failed",
                extra={"event_id": str(event.event_id), "rule_id": finding.rule_id},
                exc_info=True,
            )

    async def _analyze_and_audit_t1_causal_chain(
        self,
        *,
        event: Event,
        incident_id: str | None,
    ) -> None:
        """Append a T1 temporal causal-chain hypothesis to the audit."""
        if (
            self._rca_coordinator is None
            or self._incident_member_source is None
            or incident_id is None
            or not event.resource_ref
        ):
            return
        try:
            members = await self._incident_member_source.members(incident_id=incident_id)
            if not members:
                return
            result = self._rca_coordinator.analyze_t1_causal_chain(
                failure_event_id=str(event.event_id),
                failure_at=event.detected_at,
                failure_resource_ref=event.resource_ref,
                correlated_events=members,
                window=self._causal_chain_window,
                depends_on=self._resource_dependency_graph,
            )
            hypothesis = result.hypothesis
            await self._audit_store.append_audit_entry(
                {
                    "event_id": str(event.event_id),
                    "correlation_id": event.correlation_id or str(event.event_id),
                    "idempotency_key": f"{event.idempotency_key}:rca_t1_chain",
                    "actor": "fdai.core.rca",
                    "producer_principal": "Forseti",
                    "action_kind": "rca.hypothesis",
                    "mode": Mode.SHADOW.value,
                    "incident_id": incident_id,
                    "rca_outcome": result.outcome.value,
                    "rca_reason": result.reason,
                    "rca_tier": hypothesis.tier.value if hypothesis else "t1",
                    "rca_cause": hypothesis.cause if hypothesis else None,
                    "rca_confidence": hypothesis.confidence if hypothesis else None,
                    "rca_citations": (
                        [{"kind": c.kind.value, "ref": c.ref} for c in hypothesis.citations]
                        if hypothesis
                        else []
                    ),
                    "rca_causal_chain": (
                        hypothesis.causal_chain.to_dict()
                        if hypothesis and hypothesis.causal_chain
                        else None
                    ),
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                }
            )
        except Exception:  # noqa: BLE001 - T1 causal-chain RCA best-effort
            _LOGGER.warning(
                "rca_t1_chain_analyze_failed",
                extra={"event_id": str(event.event_id), "incident_id": incident_id},
                exc_info=True,
            )

    async def _analyze_and_audit_temporal_causality(
        self,
        *,
        event: Event,
        incident_id: str | None,
    ) -> None:
        """Project and audit bounded temporal causality in shadow mode."""
        if self._causal_runtime_coordinator is None or incident_id is None:
            return
        try:
            result = await self._causal_runtime_coordinator.analyze(
                event=event,
                incident_id=incident_id,
            )
            claim = result.claim
            hypothesis = result.hypothesis
            await self._audit_store.append_audit_entry(
                {
                    "event_id": str(event.event_id),
                    "correlation_id": event.correlation_id or str(event.event_id),
                    "idempotency_key": f"{event.idempotency_key}:rca_temporal_causality",
                    "actor": "fdai.core.rca",
                    "producer_principal": "Forseti",
                    "action_kind": "rca.temporal_causality",
                    "mode": Mode.SHADOW.value,
                    "incident_id": incident_id,
                    "causal_runtime_outcome": result.outcome.value,
                    "causal_claim_id": claim.claim_id if claim else None,
                    "causal_evidence_grade": claim.evidence_grade.value if claim else None,
                    "causal_falsifiers": list(claim.falsifiers) if claim else [],
                    "causal_hypothesis_id": hypothesis.hypothesis_id if hypothesis else None,
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                }
            )
        except Exception:  # noqa: BLE001 - causal side path never changes the decision
            _LOGGER.warning(
                "rca_temporal_causality_failed",
                extra={"event_id": str(event.event_id), "incident_id": incident_id},
                exc_info=True,
            )

    async def _analyze_t2_rca_on_abstain(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        incident_id: str | None,
    ) -> RcaResult | None:
        """Append and return a grounded T2 root-cause hypothesis for a novel case."""
        if self._rca_coordinator is None or not self._rca_coordinator.has_t2:
            return None
        resource = event.resource_ref or _extract_resource_id(event, decision)
        candidates = [Citation(kind=CitationKind.EVENT, ref=str(event.event_id))]
        if resource:
            candidates.append(Citation(kind=CitationKind.TELEMETRY, ref=resource))
        evidence = event.payload.get("evidence")
        if isinstance(evidence, Mapping):
            candidates.extend(
                Citation(kind=CitationKind.TELEMETRY, ref=f"evaluation:{capability_id}")
                for capability_id, value in sorted(evidence.items())
                if isinstance(capability_id, str)
                and isinstance(value, Mapping)
                and value.get("status") == "available"
            )
        try:
            summary = _incident_summary(event, decision)
            result = await self._rca_coordinator.analyze_t2(
                incident_summary=summary,
                candidate_citations=tuple(candidates),
            )
            hypothesis = result.hypothesis
            await self._audit_store.append_audit_entry(
                {
                    "event_id": str(event.event_id),
                    "correlation_id": event.correlation_id or str(event.event_id),
                    "idempotency_key": f"{event.idempotency_key}:rca_t2",
                    "actor": "fdai.core.rca",
                    "producer_principal": "Forseti",
                    "action_kind": "rca.hypothesis",
                    "mode": Mode.SHADOW.value,
                    "incident_id": incident_id,
                    "rca_outcome": result.outcome.value,
                    "rca_reason": result.reason,
                    "rca_tier": hypothesis.tier.value if hypothesis else "t2",
                    "rca_cause": hypothesis.cause if hypothesis else None,
                    "rca_confidence": hypothesis.confidence if hypothesis else None,
                    "rca_citations": (
                        [{"kind": c.kind.value, "ref": c.ref} for c in hypothesis.citations]
                        if hypothesis
                        else []
                    ),
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                }
            )
            return result
        except Exception:  # noqa: BLE001 - T2 RCA best-effort; decision path unaffected
            _LOGGER.warning(
                "rca_t2_analyze_failed",
                extra={"event_id": str(event.event_id)},
                exc_info=True,
            )
            return None


def _incident_summary(event: Event, decision: RoutingDecision) -> str:
    objective = event.payload.get("objective")
    objective_text = objective[:4_000] if isinstance(objective, str) else ""
    evidence = event.payload.get("evidence")
    evidence_text = "{}"
    if isinstance(evidence, Mapping):
        evidence_text = json.dumps(
            evidence,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )[:16_000]
    return (
        f"Event type: {event.event_type}. Resource type: "
        f"{decision.resource_type or 'unknown'}. Objective: {objective_text}. "
        f"Untrusted bounded evidence: {evidence_text}"
    )


__all__ = ["ControlLoopRcaMixin"]
