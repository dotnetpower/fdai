"""Forseti-owned preparation from signed acceptance evidence and reviewed catalog contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fdai.agents import AnomalyActionCandidate, AnomalyActionPreparation
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.risk_gate.gate import RiskGate
from fdai.core.tiers.t0_deterministic.models import Finding
from fdai.shared.contracts.models import Action, Event, Mode, Rule, TriggerKind
from jsonschema import Draft202012Validator

from fdai_aks_commerce.acceptance_action import ACCEPTANCE_SIGNAL, AcceptanceAnomalyActionSource
from fdai_aks_commerce.acceptance_material import (
    AcceptanceDispatchMaterial,
    StoredAcceptanceDispatchMaterials,
)


class PreparedAcceptanceSource:
    """Prepare only under Forseti; registration neither selects a policy nor promotes an action.

    A reviewed exact acceptance Rule and the existing ActionBuilder/RiskGate are required.
    The shared RiskGate's effective mode can only lower the current Forseti ceiling.
    Current human authority remains a separate mandatory dispatch-time check.
    """

    def __init__(
        self,
        *,
        source: AcceptanceAnomalyActionSource,
        builder: ActionBuilder,
        rule: Rule,
        risk_gate: RiskGate,
        materials: StoredAcceptanceDispatchMaterials,
        refresh_policy: Callable[[], Awaitable[None]],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            rule.remediates != "ops.scale-out"
            or rule.resource_type != "kubernetes.deployment"
            or rule.check_logic.reference != "fdai.aks_commerce.order_acceptance.v1"
        ):
            raise ValueError("acceptance preparation requires a reviewed scale recovery Rule")
        self._source = source
        self._builder = builder
        self._rule = Rule.model_validate_json(rule.model_dump_json())
        self._risk_gate = risk_gate
        self._materials = materials
        self._refresh_policy = refresh_policy
        self._clock = clock or (lambda: datetime.now(UTC))

    async def resolve(self, *, event_type: str, resource_ref: str) -> AnomalyActionCandidate | None:
        """Delegate evidence reads without creating original material before Forseti judgment."""
        return await self._source.resolve(event_type=event_type, resource_ref=resource_ref)

    async def prepare(self, verdict: Mapping[str, Any]) -> AnomalyActionPreparation:
        """Validate the exact decision, build once, and retain before Var sees its Action id."""
        if (
            verdict.get("producer_principal") != "Forseti"
            or verdict.get("initiator_principal") != "Heimdall"
            or verdict.get("risk_verdict") != "hil"
        ):
            raise ValueError(
                "acceptance preparation requires the judge-owned human-review decision"
            )
        candidate = await self.resolve(
            event_type=ACCEPTANCE_SIGNAL, resource_ref=str(verdict.get("resource_id") or "")
        )
        evidence = verdict.get("anomaly_action_evidence")
        if (
            candidate is None
            or not isinstance(evidence, Mapping)
            or evidence.get("evidence_ref") != candidate.evidence_ref
            or verdict.get("action_type") != candidate.action_type
            or verdict.get("params") != candidate.arguments()
            or not candidate.observed_at <= self._clock() < candidate.expires_at
        ):
            raise ValueError("acceptance preparation evidence changed")
        action_type = self._builder.action_types_by_name[candidate.action_type]
        if action_type.trigger_kind is None or action_type.trigger_kind.kind not in {
            TriggerKind.RULE_VIOLATION,
            TriggerKind.BOTH,
        }:
            raise ValueError("acceptance ActionType does not permit automatic rule findings")
        arguments = candidate.arguments()
        if action_type.argument_schema is None:
            raise ValueError("acceptance ActionType argument schema is unavailable")
        Draft202012Validator(action_type.argument_schema).validate(arguments)
        correlation = str(verdict.get("correlation_id") or "")
        idempotency = str(verdict.get("idempotency_key") or "")
        identity = json.dumps(
            [correlation, idempotency, candidate.resource_ref], separators=(",", ":")
        )
        event = Event(
            schema_version="1.0.0",
            event_id=uuid5(NAMESPACE_URL, "acceptance-event:" + identity),
            idempotency_key=idempotency,
            correlation_id=correlation,
            source="aks-commerce.acceptance",
            event_type=ACCEPTANCE_SIGNAL,
            resource_ref=candidate.resource_ref,
            detected_at=candidate.observed_at,
            ingested_at=self._clock(),
            mode=Mode.SHADOW,
        )
        rule = self._rule.model_copy(update={"parameters": arguments})
        finding = Finding(
            finding_id=candidate.evidence_ref,
            rule_id=rule.id,
            rule_version=rule.version,
            resource_id=candidate.resource_ref,
            signal_id=ACCEPTANCE_SIGNAL,
            severity=rule.severity,
            created_at=candidate.observed_at,
        )
        builder = ActionBuilder(
            self._builder.action_types_by_name,
            self._builder.ontology_release,
            lambda: candidate.observed_at,
        )
        built = builder.build_from_finding(event=event, finding=finding, rule=rule)
        await self._refresh_policy()
        if not candidate.observed_at <= self._clock() < candidate.expires_at:
            raise ValueError("acceptance evidence expired during policy refresh")
        risk = self._risk_gate.evaluate(action=built, rule=rule, action_type=action_type)
        if risk.outcome.value not in {"auto", "hil"}:
            raise ValueError("acceptance preparation is not admitted by the current risk policy")
        mode = (
            risk.effective_mode
            if verdict.get("resolved_autonomy_ceiling") in {"enforce_hil", "enforce_auto"}
            else Mode.SHADOW
        )
        action = Action.model_validate({**built.model_dump(mode="json"), "mode": mode.value})
        material = AcceptanceDispatchMaterial(
            action.model_dump_json(),
            correlation,
            idempotency,
            "sha256:" + hashlib.sha256(self._rule.model_dump_json().encode()).hexdigest(),
        )
        existing = await self._materials.read(str(action.action_id))
        if existing is not None:
            prior = existing.action()
            if (
                existing.rule_digest != material.rule_digest
                or existing.correlation_id != correlation
                or existing.action_run_idempotency_key != idempotency
                or prior.model_dump(exclude={"created_at", "event_id"})
                != action.model_dump(exclude={"created_at", "event_id"})
            ):
                raise ValueError("acceptance original Action changed; a new proposal is required")
            material = existing
        await self._materials.retain(material)
        if not candidate.observed_at <= self._clock() < candidate.expires_at:
            raise ValueError("acceptance evidence expired during original Action retention")
        return AnomalyActionPreparation(
            str(action.action_id),
            shadow_only=mode is Mode.SHADOW,
            quorum_required=2 if action_type.irreversible else 1,
        )
