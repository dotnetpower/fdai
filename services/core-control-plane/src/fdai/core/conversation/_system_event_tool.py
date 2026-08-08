"""In-memory deterministic event description console tool."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import SideEffectClass, ToolResult, _optional_str, _require_str
from fdai.core.tiers.t0_deterministic import T0Engine
from fdai.core.trust_router import RoutingTier, TrustRouter
from fdai.shared.contracts.models import Event, Mode


class DescribeEventTool:
    """Run a hypothetical event through routing and T0 in memory."""

    name = "describe_event"
    description = (
        "Run one hypothetical event through EventIngest -> TrustRouter -> T0 in "
        "memory; return the routing tier, decision, candidate rule ids, and any "
        "findings without opening a PR or writing an audit entry."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, trust_router: TrustRouter, t0_engine: T0Engine) -> None:
        self._trust_router = trust_router
        self._t0_engine = t0_engine

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        resource_type = _require_str(arguments, "resource_type").strip()
        resource_id = _require_str(arguments, "resource_id").strip()
        if not resource_type or not resource_id:
            return ToolResult(
                status="error",
                preview="describe_event requires non-empty resource_type and resource_id",
            )
        raw_props = arguments.get("resource_props", {})
        if not isinstance(raw_props, Mapping):
            return ToolResult(
                status="error",
                preview="describe_event 'resource_props' MUST be a mapping",
            )
        signal_type = _optional_str(
            arguments, "signal_type", default="synthetic.chat.describe_event"
        )
        now = datetime.now(tz=UTC)
        event = Event(
            schema_version="1.0.0",
            event_id=uuid4(),
            idempotency_key=f"chat.describe_event.{uuid4().hex[:16]}",
            source="operator-console",
            event_type=signal_type,
            resource_ref=resource_id,
            payload={
                "resource": {"type": resource_type, "id": resource_id},
                "properties": dict(raw_props),
            },
            detected_at=now,
            ingested_at=now,
            mode=Mode.SHADOW,
        )
        routing = self._trust_router.route(event)
        result: dict[str, Any] = {
            "tier": routing.tier.value,
            "resource_type": routing.resource_type,
            "candidate_rule_ids": list(routing.candidate_rule_ids),
            "reason": routing.reason,
            "findings": [],
        }
        evidence: list[str] = []
        if routing.tier == RoutingTier.T0 and routing.resource_type:
            verdict = self._t0_engine.evaluate(
                event_id=str(event.event_id),
                signal_id=str(event.event_id),
                resource_id=resource_id,
                resource_type=routing.resource_type,
                resource_props=dict(raw_props),
                signal_type=signal_type,
            )
            result["decision"] = "match" if verdict.matched else "abstain"
            findings_payload = []
            for finding in verdict.findings:
                findings_payload.append(
                    {
                        "rule_id": finding.rule_id,
                        "resource_id": finding.resource_id,
                        "severity": _enum_value(finding.severity),
                        "reason": getattr(finding, "reason", None),
                    }
                )
                evidence.append(f"rule:{finding.rule_id}")
            result["findings"] = findings_payload
            if verdict.audit_hint:
                result["stage"] = getattr(verdict.audit_hint, "stage", "L1_evaluate")
                result["hint_reason"] = getattr(verdict.audit_hint, "reason", None)
        else:
            result["decision"] = "abstain"
        status: Literal["ok", "error", "abstain"] = "ok" if result["findings"] else "abstain"
        if result["decision"] == "match":
            status = "ok"
        return ToolResult(
            status=status,
            data=result,
            preview=(
                f"describe_event[{resource_type}/{resource_id}]: tier={result['tier']} "
                f"decision={result['decision']} findings={len(result['findings'])}"
            ),
            evidence_refs=tuple(evidence)
            + tuple(f"candidate:{rule_id}" for rule_id in result["candidate_rule_ids"]),
        )


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)
