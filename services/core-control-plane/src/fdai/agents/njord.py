"""Njord - Cost / FinOps advisory ingress and sole cost-finding publisher."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    capped_list,
    mentioned,
    semantic_intents,
)
from fdai.agents._framework.pantheon import _NJORD
from fdai.agents._framework.specialist_ingress import COST_SAMPLE_EVENT, parse_cost_sample
from fdai.shared.providers.cost_governance import (
    CostAdvisoryProvider,
    CostAnalysisSample,
    CostPackageActivationReader,
)

_PACKAGE_ID = "cost-governance"
_MAX_TRACKED_SCOPES = 512


@dataclass(frozen=True, slots=True)
class CostEstimate:
    action_type: str
    monthly_delta_usd: float
    confidence: float


class Njord(Agent):
    """Cost ingress shell; package providers own every calculation."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        advisory_provider: CostAdvisoryProvider | None = None,
        activation_reader: CostPackageActivationReader | None = None,
        package_enabled: bool = False,
    ) -> None:
        super().__init__(spec=_NJORD)
        self.bus = bus
        self._advisory_provider = advisory_provider
        self._activation_reader = activation_reader
        self._package_enabled = package_enabled
        self._latest: dict[str, tuple[float, str]] = {}
        self._counts: dict[str, int] = {}

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic != "object.event" or payload.get("event_type") != COST_SAMPLE_EVENT:
            return
        signal = parse_cost_sample(payload)
        if signal is None:
            self.record_behavior("cost_sample:invalid")
            return
        accepted_at = _parse_time(signal.observed_at)
        if accepted_at is None:
            self.record_behavior("cost_sample:disabled")
            return
        attributes = payload.get("attributes")
        if not isinstance(attributes, dict):
            self.record_behavior("cost_sample:invalid")
            return
        activation_revision = attributes.get("activation_revision")
        source_authority = attributes.get("source_authority")
        release_digest = attributes.get("ontology_release_digest")
        completeness = attributes.get("completeness")
        if (
            (
                self._activation_reader is not None
                and (
                    isinstance(activation_revision, bool)
                    or not isinstance(activation_revision, int)
                    or activation_revision < 0
                )
            )
            or not isinstance(source_authority, str)
            or not source_authority.strip()
            or not isinstance(release_digest, str)
        ):
            self.record_behavior("cost_sample:invalid_evidence")
            return
        if not await self._message_enabled(activation_revision):
            self.record_behavior("cost_sample:disabled")
            return
        try:
            sample = CostAnalysisSample(
                scope_id=signal.scope,
                resource_id=signal.resource_id or signal.scope,
                amount_usd=Decimal(str(signal.amount_usd)),
                correlation_id=signal.correlation_id or signal.scope,
                observed_at=accepted_at,
                source_authority=source_authority,
                completeness=Decimal(str(completeness)),
                ontology_release_digest=release_digest,
            )
        except (ValueError, InvalidOperation):
            self.record_behavior("cost_sample:invalid_evidence")
            return
        self.record_behavior("cost_sample:accepted")
        await self._analyze(sample)

    # ---- ingestion -----------------------------------------------------

    async def ingest_cost_sample(
        self,
        *,
        scope: str,
        amount_usd: float,
        correlation_id: str = "",
        resource_id: str | None = None,
        observed_at: str = "",
        source_authority: str = "",
        completeness: float = 1.0,
        ontology_release_digest: str = "",
    ) -> dict[str, Any] | None:
        parsed_at = _parse_time(observed_at)
        if (
            not self._package_enabled
            or self._advisory_provider is None
            or parsed_at is None
            or not source_authority
            or not ontology_release_digest
        ):
            self.record_behavior("cost_sample:disabled")
            return None
        sample = CostAnalysisSample(
            scope_id=scope,
            resource_id=resource_id or scope,
            amount_usd=Decimal(str(amount_usd)),
            correlation_id=correlation_id or scope,
            observed_at=parsed_at,
            source_authority=source_authority,
            completeness=Decimal(str(completeness)),
            ontology_release_digest=ontology_release_digest,
        )
        return await self._analyze(sample)

    async def _analyze(self, sample: CostAnalysisSample) -> dict[str, Any] | None:
        if self._advisory_provider is None:
            self.record_behavior("cost_sample:provider_absent")
            return None
        finding = await self._advisory_provider.analyze_cost_sample(sample)
        if len(self._latest) >= _MAX_TRACKED_SCOPES and sample.scope_id not in self._latest:
            oldest = next(iter(self._latest))
            self._latest.pop(oldest, None)
            self._counts.pop(oldest, None)
        self._latest[sample.scope_id] = (float(sample.amount_usd), sample.observed_at.isoformat())
        self._counts[sample.scope_id] = self._counts.get(sample.scope_id, 0) + 1
        if finding is None:
            return None
        payload = {
            "producer_principal": "Njord",
            "correlation_id": finding.correlation_id,
            "scope": finding.scope_id,
            "resource_id": finding.resource_id,
            "amount_usd": float(finding.amount_usd),
            "baseline_usd": float(finding.baseline_usd),
            "ratio": float(finding.ratio),
            "impact": float(finding.impact),
            "recommendation": finding.recommendation,
            "observed_at": finding.observed_at.isoformat(),
        }
        await self._publish_proposal("object.cost-anomaly", payload)
        return payload

    async def _message_enabled(self, activation_revision: object) -> bool:
        if not self._package_enabled or self._advisory_provider is None:
            return False
        if self._activation_reader is None:
            return True
        if isinstance(activation_revision, bool) or not isinstance(activation_revision, int):
            return False
        snapshot = await self._activation_reader.read_cost_activation(_PACKAGE_ID)
        if snapshot is None:
            return False
        permitted = snapshot.permits_activation_revision(activation_revision)
        if permitted and activation_revision != snapshot.revision:
            self.record_behavior("cost_sample:drained_after_disable")
        return permitted

    # ---- advisor hook --------------------------------------------------

    def cost_impact(self, action_type: str) -> CostEstimate:
        """Return a package advisory or a zero-confidence abstention."""
        estimate = (
            self._advisory_provider.estimate_cost_effect(action_type)
            if self._package_enabled and self._advisory_provider is not None
            else None
        )
        return CostEstimate(
            action_type=action_type,
            monthly_delta_usd=float(estimate.monthly_delta_usd) if estimate else 0.0,
            confidence=float(estimate.confidence) if estimate else 0.0,
        )

    # ---- conversational port -------------------------------------------

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Cost answers rest on package-analyzed samples."""
        return bool(self._latest)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "tracked_scopes": capped_list(sorted(self._latest)),
            "tracked_scopes_count": len(self._latest),
            "anomaly_ratio": None,
            "known_action_costs": {},
            "package_enabled": self._package_enabled,
            "advisory_provider_bound": self._advisory_provider is not None,
            "budget_data_available": False,
        }
        if "budget_status" in semantic_intents(context):
            return IntrospectionResult(
                answer="No budget projection is bound to this conversational port.",
                facts=facts,
            )
        scopes = mentioned(question, self._latest)
        if scopes:
            scope = scopes[0]
            latest, observed_at = self._latest[scope]
            facts.update(
                {
                    "scope": scope,
                    "sample_count": self._counts[scope],
                    "latest_usd": latest,
                    "observed_at": observed_at,
                }
            )
            answer = (
                f"Scope {scope!r}: latest analyzed sample {latest:.2f} USD "
                f"over {self._counts[scope]} accepted finding(s)."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        if not self._latest:
            answer = (
                "No package-analyzed cost samples are available; disabled or "
                "unbound Cost Governance produces no analysis."
            )
        else:
            answer = (
                f"Tracking cost findings for {len(self._latest)} scope(s): "
                f"{', '.join(sorted(self._latest))}."
            )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Njord", "CostEstimate"]


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)
