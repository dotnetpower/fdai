"""Shadow-only change simulation console tool."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fdai.core.conversation._write_audit import AuditWriter
from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import SideEffectClass, ToolResult, _optional_str
from fdai.core.executor.action_builder import ActionBuilder, ActionBuildError
from fdai.core.executor.renderer import RenderError, RenderRequest, TemplateRenderer
from fdai.core.tiers.t0_deterministic import T0Engine
from fdai.core.trust_router import RoutingTier, TrustRouter
from fdai.shared.contracts.models import Event, Mode, Rule


class SimulateChangeTool:
    """Simulate one event end-to-end without publishing."""

    name = "simulate_change"
    description = (
        "Run one hypothetical event through EventIngest -> TrustRouter -> T0 -> "
        "ActionBuilder -> TemplateRenderer in memory; return the outcome and "
        "the generated PR intent(s) without publishing. Writes exactly one "
        "'console.simulate_change' audit entry."
    )
    rbac_floor: Role = Role.CONTRIBUTOR
    side_effect_class: SideEffectClass = "simulate"

    def __init__(
        self,
        *,
        trust_router: TrustRouter,
        t0_engine: T0Engine,
        action_builder: ActionBuilder,
        template_renderer: TemplateRenderer,
        rules_by_id: Mapping[str, Rule],
        audit_writer: AuditWriter,
    ) -> None:
        self._trust_router = trust_router
        self._t0_engine = t0_engine
        self._action_builder = action_builder
        self._template_renderer = template_renderer
        self._rules_by_id = dict(rules_by_id)
        self._audit_writer = audit_writer

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        scenario = arguments.get("scenario")
        if not isinstance(scenario, Mapping) or not scenario:
            return ToolResult(
                status="error",
                preview="simulate_change requires a non-empty 'scenario' mapping",
            )
        resource_type = str(scenario.get("resource_type", "")).strip()
        resource_id = str(scenario.get("resource_id", "")).strip()
        if not resource_type or not resource_id:
            return ToolResult(
                status="error",
                preview=(
                    "simulate_change 'scenario' MUST carry non-empty "
                    "'resource_type' and 'resource_id'"
                ),
            )
        raw_props = scenario.get("resource_props", {})
        if not isinstance(raw_props, Mapping):
            return ToolResult(
                status="error",
                preview="simulate_change 'scenario.resource_props' MUST be a mapping",
            )
        signal_type = _optional_str(
            arguments, "signal_type", default="synthetic.chat.simulate_change"
        )
        event = _build_synthetic_event(
            resource_type=resource_type,
            resource_id=resource_id,
            resource_props=raw_props,
            signal_type=signal_type,
            extra_payload={
                key: value
                for key, value in scenario.items()
                if key not in ("resource_type", "resource_id", "resource_props")
            },
        )
        routing = self._trust_router.route(event)
        result: dict[str, Any] = {
            "tier": routing.tier.value,
            "resource_type": routing.resource_type,
            "candidate_rule_ids": list(routing.candidate_rule_ids),
            "routing_reason": routing.reason,
            "findings": [],
            "actions": [],
            "pr_intents": [],
        }
        evidence: list[str] = []
        if routing.tier != RoutingTier.T0 or not routing.resource_type:
            outcome: Literal["abstained_routing", "abstained_t0", "simulated"] = "abstained_routing"
            audit_id = self._audit_writer.write_simulation_entry(
                event=event,
                principal=principal,
                outcome=outcome,
                reason=routing.reason,
                citing_rule_ids=tuple(routing.candidate_rule_ids),
                pr_intents=(),
                findings_summary=(),
            )
            return ToolResult(
                status="abstain",
                data={**result, "outcome": outcome, "audit_id": audit_id},
                preview=(
                    f"simulate_change[{resource_type}/{resource_id}]: "
                    f"routing abstain (tier={routing.tier.value})"
                ),
                evidence_refs=(f"audit:{audit_id}",),
            )
        verdict = self._t0_engine.evaluate(
            event_id=str(event.event_id),
            signal_id=str(event.event_id),
            resource_id=resource_id,
            resource_type=routing.resource_type,
            resource_props=dict(raw_props),
            signal_type=signal_type,
        )
        findings_summary: list[dict[str, Any]] = []
        pr_intents: list[dict[str, Any]] = []
        errors: list[str] = []
        for finding in verdict.findings:
            summary = {
                "rule_id": finding.rule_id,
                "resource_id": finding.resource_id,
                "severity": _enum_value(finding.severity),
            }
            findings_summary.append(summary)
            evidence.append(f"rule:{finding.rule_id}")
            rule = self._rules_by_id.get(finding.rule_id)
            if rule is None:
                errors.append(
                    f"rule {finding.rule_id!r} not in rules_by_id; cannot render a PR intent"
                )
                continue
            try:
                action = self._action_builder.build_from_finding(
                    event=event, finding=finding, rule=rule
                )
            except ActionBuildError as exc:
                errors.append(f"ActionBuild failed for rule {finding.rule_id!r}: {exc}")
                continue
            try:
                patch = self._template_renderer.render(
                    RenderRequest(
                        rule=rule,
                        resource_id=finding.resource_id,
                        params=dict(action.params),
                    )
                )
            except RenderError as exc:
                errors.append(f"Template render failed for rule {finding.rule_id!r}: {exc}")
                continue
            pr_intents.append(
                {
                    "action_id": str(action.action_id),
                    "action_type": action.action_type,
                    "target_resource_ref": action.target_resource_ref,
                    "citing_rule_ids": list(action.citing_rules),
                    "idempotency_key": action.idempotency_key,
                    "stop_condition": action.stop_condition,
                    "rollback_kind": _enum_value(action.rollback_ref.kind),
                    "patch_preview": _preview(patch),
                    "template_ref": rule.remediation.template_ref,
                }
            )
        result["findings"] = findings_summary
        result["pr_intents"] = pr_intents
        result["errors"] = errors
        if not verdict.findings:
            outcome = "abstained_t0"
            preview = (
                f"simulate_change[{resource_type}/{resource_id}]: T0 abstain "
                f"({len(routing.candidate_rule_ids)} candidate rule(s))"
            )
            status: Literal["ok", "error", "abstain"] = "abstain"
        elif errors and not pr_intents:
            outcome = "abstained_t0"
            preview = (
                f"simulate_change[{resource_type}/{resource_id}]: "
                f"{len(errors)} error(s) building/rendering; no PR intent"
            )
            status = "error"
        else:
            outcome = "simulated"
            preview = (
                f"simulate_change[{resource_type}/{resource_id}]: "
                f"{len(pr_intents)} PR intent(s) captured, {len(errors)} error(s)"
            )
            status = "ok"
        audit_id = self._audit_writer.write_simulation_entry(
            event=event,
            principal=principal,
            outcome=outcome,
            reason=verdict.audit_hint.reason if verdict.audit_hint else None,
            citing_rule_ids=tuple(verdict.audit_hint.citing_rule_ids if verdict.audit_hint else ()),
            pr_intents=tuple(pr_intents),
            findings_summary=tuple(findings_summary),
        )
        result["outcome"] = outcome
        result["audit_id"] = audit_id
        return ToolResult(
            status=status,
            data=result,
            preview=preview,
            evidence_refs=tuple(evidence) + (f"audit:{audit_id}",),
        )


def _build_synthetic_event(
    *,
    resource_type: str,
    resource_id: str,
    resource_props: Mapping[str, Any],
    signal_type: str,
    extra_payload: Mapping[str, Any],
) -> Event:
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "resource": {"type": resource_type, "id": resource_id},
        "properties": dict(resource_props),
    }
    for key, value in extra_payload.items():
        if key not in payload:
            payload[key] = value
    return Event(
        schema_version="1.0.0",
        event_id=uuid4(),
        idempotency_key=f"chat.simulate_change.{uuid4().hex[:16]}",
        source="operator-console",
        event_type=signal_type,
        resource_ref=resource_id,
        payload=payload,
        detected_at=now,
        ingested_at=now,
        mode=Mode.SHADOW,
    )


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _preview(patch: str, *, max_bytes: int = 512) -> str:
    trimmed = patch.strip()
    if len(trimmed) <= max_bytes:
        return trimmed
    return trimmed[:max_bytes] + "..."
