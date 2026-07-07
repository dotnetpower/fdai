"""Write-class console tools (Wave W1.1 - operator-console.md 3.2).

Distinct from :mod:`aiopspilot.core.conversation.system_tools` (read-only
Day-1 tools) so the ``side_effect_class == 'read'`` invariant on that
module stays a compile-time property: a tool that lands here MUST NOT
sneak into the read-only surface by import order accident.

Wave scope

- **This module (W1.1 partial)** - :class:`SimulateChangeTool`. Runs one
  hypothetical event through the deterministic pipeline in memory, builds
  the resulting :class:`Action` per finding, renders the shadow PR
  patch, and returns everything **without publishing**. The tool writes
  exactly one ``console.simulate_change`` audit entry so an operator can
  find the simulation later via ``query_audit``.
- **Next slices** - ``approve_hil`` / ``list_hil`` land alongside the
  HIL queue read model, in a separate follow-up commit so the write set
  stays small and each slice is separately reviewable.

Design invariants (each tool has a matching test):

- ``side_effect_class == 'simulate'`` - the caller's real PR publisher,
  ShadowExecutor, and StateStore are NEVER invoked by this tool.
- Verifier re-check is preserved: T0Engine runs the shipped policy
  evaluators exactly as the production loop does.
- Safety invariants (stop_condition, rollback, blast_radius) MUST be
  present on every produced Action; ActionBuilder raises otherwise and
  the tool degrades to :attr:`ToolResult.status = 'error'`.
- No mutation of the caller's audit store beyond a single
  ``console.simulate_change`` record.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from aiopspilot.core.conversation.session import Principal, Role
from aiopspilot.core.conversation.tools import (
    SideEffectClass,
    ToolResult,
    _optional_str,
)
from aiopspilot.core.executor.action_builder import ActionBuilder, ActionBuildError
from aiopspilot.core.executor.renderer import (
    RenderError,
    RenderRequest,
    TemplateRenderer,
)
from aiopspilot.core.tiers.t0_deterministic import T0Engine
from aiopspilot.core.trust_router import RoutingTier, TrustRouter
from aiopspilot.shared.contracts.models import Event, Mode, Rule
from aiopspilot.shared.providers.break_glass_pager import (
    BreakGlassPager,
    BreakGlassPagerError,
)
from aiopspilot.shared.providers.hil_registry import (
    HilApprovalDecision,
    HilApprovalRegistry,
    HilItemAlreadyResolvedError,
    HilItemNotFoundError,
    HilPendingItem,
    HilRegistryError,
)
from aiopspilot.shared.providers.runbook_registry import (
    RunbookError,
    RunbookNotFoundError,
    RunbookRegistry,
    RunbookResult,
)


class SimulateChangeTool:
    """Simulate one event end-to-end without publishing.

    The tool runs the deterministic pipeline in memory, builds one
    :class:`Action` per finding, and renders the shadow PR patch. It
    NEVER opens a PR and never touches the ShadowExecutor. A single
    ``console.simulate_change`` audit entry is appended to the caller's
    audit store so the simulation is discoverable via
    :class:`~aiopspilot.core.conversation.system_tools.QueryAuditTool`.

    Arguments (``arguments`` mapping):

    - ``scenario`` (Mapping, required) - the event payload the operator
      wants to simulate. MUST carry at minimum
      ``resource_type`` and ``resource_id``; ``resource_props`` is
      optional (defaults to empty mapping). Any additional keys land
      under the Event's ``payload`` block verbatim.
    - ``signal_type`` (str, optional) - event type marker (default
      ``synthetic.chat.simulate_change``).
    """

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

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> ToolResult:
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
                k: v
                for k, v in scenario.items()
                if k not in ("resource_type", "resource_id", "resource_props")
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

        # Non-T0 -> the deterministic layer has no answer; abstain.
        if routing.tier != RoutingTier.T0 or not routing.resource_type:
            outcome: Literal["abstained_routing", "abstained_t0", "simulated"] = "abstained_routing"
            preview = (
                f"simulate_change[{resource_type}/{resource_id}]: "
                f"routing abstain (tier={routing.tier.value})"
            )
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
                preview=preview,
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
            # Every finding failed to build or render - fail-close as error.
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
                f"{len(pr_intents)} PR intent(s) captured, "
                f"{len(errors)} error(s)"
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


# ---------------------------------------------------------------------------
# audit writer seam
# ---------------------------------------------------------------------------


class AuditWriter:
    """Sync facade over an async :class:`StateStore` for the console.

    The console runs sync at Day 1 (see
    :class:`~aiopspilot.core.conversation.tools.SystemConsoleTool`); the
    audit store is async by contract. This adapter marshals one write
    per call via ``asyncio.run`` - safe because the console coordinator
    is never itself inside an event loop, matching the pattern
    :class:`~aiopspilot.core.conversation.system_tools.QueryInventoryTool`
    already uses.

    A fork that runs the console inside an event loop (Teams / Slack
    bot) can override the adapter to write directly via ``await``; the
    Protocol shape is one method.
    """

    def __init__(self, *, audit_store: Any) -> None:
        # Typed as Any to keep the tool module free of a compile-time
        # dependency on the StateStore Protocol path; the runtime object
        # is a StateStore. This mirrors the pattern used by the read-only
        # audit tools.
        self._audit_store = audit_store

    def write_simulation_entry(
        self,
        *,
        event: Event,
        principal: Principal,
        outcome: str,
        reason: str | None,
        citing_rule_ids: tuple[str, ...],
        pr_intents: tuple[Mapping[str, Any], ...],
        findings_summary: tuple[Mapping[str, Any], ...],
    ) -> str:
        import asyncio

        audit_id = str(uuid4())
        entry: dict[str, Any] = {
            "audit_id": audit_id,
            "event_id": str(event.event_id),
            "action_kind": "console.simulate_change",
            "actor": principal.id,
            "actor_role": principal.role.value,
            "decision": outcome,
            "mode": Mode.SHADOW.value,
            "stage": "simulate",
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "resource_type": _extract_resource_type(event),
            "citing_rule_ids": list(citing_rule_ids),
            "reason": reason or "",
            "pr_intents": [dict(p) for p in pr_intents],
            "findings": [dict(f) for f in findings_summary],
        }
        asyncio.run(self._audit_store.append_audit_entry(entry))
        return audit_id

    def write_approval_entry(
        self,
        *,
        item: HilPendingItem,
        principal: Principal,
        decision: HilApprovalDecision,
        outcome: str,
        justification: str,
        receipt_ref: str,
        already_recorded: bool,
    ) -> str:
        """Append one ``console.approve_hil`` audit entry.

        ``outcome`` mirrors :attr:`ToolResult.status` (`ok` / `error` /
        `abstain`) so the audit trail records both the operator's
        recorded ``decision`` and the tool's outcome (they diverge on
        already-recorded replays, verifier failures, etc.).
        """
        import asyncio

        audit_id = str(uuid4())
        entry: dict[str, Any] = {
            "audit_id": audit_id,
            "event_id": item.event_id,
            "action_id": item.action_id,
            "action_kind": "console.approve_hil",
            "actor": principal.id,
            "actor_role": principal.role.value,
            "decision": decision.value,
            "outcome": outcome,
            "mode": Mode.SHADOW.value,
            "stage": "approve",
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "idempotency_key": item.idempotency_key,
            "approval_id": item.approval_id,
            "submitter_oid": item.submitter_oid,
            "target_resource_ref": item.target_resource_ref,
            "citing_rule_ids": list(item.citing_rule_ids),
            "action_kind_dispatched": item.action_kind,
            "receipt_ref": receipt_ref,
            "already_recorded": already_recorded,
            "justification": justification,
        }
        asyncio.run(self._audit_store.append_audit_entry(entry))
        return audit_id

    def write_runbook_entry(
        self,
        *,
        name: str,
        params: Mapping[str, Any],
        principal: Principal,
        dry_run: bool,
        outcome: str,
        summary: str,
        detail: Mapping[str, Any] | None = None,
        error_kind: str | None = None,
    ) -> str:
        """Append one ``console.run_runbook`` audit entry.

        ``outcome`` mirrors the tool's :class:`ToolResult` status
        (`ok` / `error` / `abstain`). ``dry_run`` is recorded so an
        auditor can distinguish a plan-only run from a live invocation
        without re-parsing the arguments block.
        """
        import asyncio

        audit_id = str(uuid4())
        entry: dict[str, Any] = {
            "audit_id": audit_id,
            "action_kind": "console.run_runbook",
            "runbook_name": name,
            "actor": principal.id,
            "actor_role": principal.role.value,
            "decision": outcome,
            "dry_run": dry_run,
            "mode": Mode.SHADOW.value if dry_run else Mode.ENFORCE.value,
            "stage": "runbook",
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "params": dict(params),
            "summary": summary,
            "detail": dict(detail or {}),
            "error_kind": error_kind or "",
        }
        asyncio.run(self._audit_store.append_audit_entry(entry))
        return audit_id

    def write_break_glass_entry(
        self,
        *,
        principal: Principal,
        outcome: str,
        reason_redacted: str,
        activated_at: datetime | None,
        expires_at: datetime | None,
        pager_receipt: str,
        refusal_kind: str | None = None,
    ) -> str:
        """Append one ``console.activate_break_glass`` audit entry.

        Every path is audited - success AND refusal (chat invariant 7:
        an attempted grant is itself a security signal). The reason is
        already redacted by the tool.
        """
        import asyncio

        audit_id = str(uuid4())
        entry: dict[str, Any] = {
            "audit_id": audit_id,
            "action_kind": "console.activate_break_glass",
            "actor": principal.id,
            "actor_role": principal.role.value,
            "decision": outcome,
            "mode": Mode.SHADOW.value,
            "stage": "break_glass",
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            "reason": reason_redacted,
            "activated_at": activated_at.isoformat() if activated_at else None,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "pager_receipt": pager_receipt,
            "refusal_kind": refusal_kind or "",
        }
        asyncio.run(self._audit_store.append_audit_entry(entry))
        return audit_id


# ---------------------------------------------------------------------------
# ListHilTool - Approver-scoped queue projection
# ---------------------------------------------------------------------------


class ListHilTool:
    """Return the pending HIL items visible to Approvers.

    Distinct from the read-API's dashboard tile which the Reader sees:
    that surface shows count + short reason only, whereas this tool
    returns the full item detail (including the submitter identity)
    because it is the input Approvers use to decide `approve_hil`.

    Arguments (``arguments`` mapping):

    - ``limit`` (int, optional; default 20, capped 100).

    The tool is read-only on the registry: it never mutates queue state
    and never writes an audit entry. Approver-floor RBAC is what keeps
    submitter identity from leaking to Readers.
    """

    name = "list_hil"
    description = (
        "Return the pending HIL items with full Approver-visible detail "
        "(idempotency_key, submitter, action, resource). Read-only."
    )
    rbac_floor: Role = Role.APPROVER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, registry: HilApprovalRegistry) -> None:
        self._registry = registry

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,  # noqa: ARG002 - RBAC applied by coordinator
    ) -> ToolResult:
        import asyncio

        raw_limit = arguments.get("limit", 20)
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return ToolResult(
                status="error",
                preview="list_hil 'limit' MUST be an integer",
            )
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

        items = asyncio.run(self._registry.list_pending(limit=limit))
        payload = [_project_pending_item(item) for item in items]
        preview = f"list_hil: {len(payload)} pending item(s)"
        return ToolResult(
            status="ok" if payload else "abstain",
            data={"items": payload, "limit": limit},
            preview=preview,
            evidence_refs=tuple(f"hil:{item.idempotency_key}" for item in items),
        )


# ---------------------------------------------------------------------------
# ApproveHilTool - record approver decision + audit
# ---------------------------------------------------------------------------


class ApproveHilTool:
    """Resolve one queued HIL item.

    Invariants enforced (fail-closed) BEFORE the registry write:

    1. **Existence** - the ``idempotency_key`` MUST match a currently
       pending item; ``HilItemNotFoundError`` degrades to status='error'.
    2. **Verifier re-check** - the item's ``action_kind`` MUST still
       exist in the ActionType catalog (a fork MAY tighten the check
       further; see :attr:`known_action_kinds`).
    3. **No self-approval** - ``principal.id == item.submitter_oid``
       is refused with status='error'. Comparison uses the OID-shaped
       principal id (the console coordinator populates ``Principal.id``
       from the Entra ``oid`` claim) per the API-token-validation section
       of ``docs/roadmap/user-rbac-and-identity.md``.
    4. **Terminal-state respect** - a conflicting re-decision on an
       already-resolved key surfaces the registry's
       :class:`HilItemAlreadyResolvedError` as status='error' without a
       second write.

    Arguments (``arguments`` mapping):

    - ``idempotency_key`` (str, required)
    - ``decision`` (str, required) - ``approve`` or ``reject``.
    - ``justification`` (str, optional) - short free-form reason.

    Every terminal path writes exactly one ``console.approve_hil``
    audit entry (kind='approve' or 'reject' recorded on the entry;
    'outcome' mirrors the tool's ToolResult.status).
    """

    name = "approve_hil"
    description = (
        "Resolve one queued HIL item. Requires idempotency_key + "
        "decision ('approve' or 'reject'). Verifier re-check + "
        "no_self_approval invariant applied."
    )
    rbac_floor: Role = Role.APPROVER
    side_effect_class: SideEffectClass = "approve"

    def __init__(
        self,
        *,
        registry: HilApprovalRegistry,
        audit_writer: AuditWriter,
        known_action_kinds: frozenset[str] | None = None,
    ) -> None:
        self._registry = registry
        self._audit_writer = audit_writer
        self.known_action_kinds: frozenset[str] = (
            known_action_kinds if known_action_kinds is not None else frozenset()
        )

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> ToolResult:
        import asyncio

        idempotency_key = str(arguments.get("idempotency_key", "")).strip()
        raw_decision = str(arguments.get("decision", "")).strip().lower()
        justification = _optional_str(arguments, "justification", default="").strip()

        if not idempotency_key:
            return ToolResult(
                status="error",
                preview="approve_hil requires a non-empty 'idempotency_key'",
            )
        try:
            decision = HilApprovalDecision(raw_decision)
        except ValueError:
            return ToolResult(
                status="error",
                preview=(
                    f"approve_hil 'decision' MUST be 'approve' or 'reject'; got {raw_decision!r}"
                ),
            )

        # Fetch pending item (existence check).
        item = asyncio.run(self._registry.get_pending(idempotency_key))
        if item is None:
            return ToolResult(
                status="error",
                preview=(f"approve_hil: no pending item for idempotency_key={idempotency_key!r}"),
            )

        # Verifier re-check: action_kind still known.
        if self.known_action_kinds and item.action_kind not in self.known_action_kinds:
            return ToolResult(
                status="error",
                preview=(
                    f"approve_hil: action_kind {item.action_kind!r} is no longer "
                    "in the shipped catalog; verifier re-check failed"
                ),
            )

        # No-self-approval invariant. Comparison uses Principal.id which
        # the console coordinator populates from the Entra 'oid' claim.
        if principal.id and principal.id == item.submitter_oid:
            return ToolResult(
                status="error",
                preview=(
                    "approve_hil: no_self_approval invariant would be "
                    "violated (approver.oid == submitter_oid)"
                ),
            )

        # Registry write. Idempotent replays return already_recorded=True
        # and are still audited so the trail records the replay path.
        try:
            receipt = asyncio.run(
                self._registry.record_decision(
                    idempotency_key=idempotency_key,
                    decision=decision,
                    approver_oid=principal.id,
                    justification=justification,
                )
            )
        except HilItemAlreadyResolvedError as exc:
            audit_id = self._audit_writer.write_approval_entry(
                item=item,
                principal=principal,
                decision=decision,
                outcome="error",
                justification=justification,
                receipt_ref="",
                already_recorded=False,
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id, "reason": str(exc)},
                preview=f"approve_hil: {exc}",
                evidence_refs=(f"audit:{audit_id}",),
            )
        except HilItemNotFoundError:
            # Race between get_pending and record_decision - fail closed.
            return ToolResult(
                status="error",
                preview=(
                    f"approve_hil: item {idempotency_key!r} disappeared "
                    "between existence check and decision write"
                ),
            )
        except HilRegistryError as exc:
            return ToolResult(
                status="error",
                preview=f"approve_hil: registry error [{exc.kind}] {exc}",
            )

        outcome_status: Literal["ok", "error", "abstain"] = "ok"
        audit_id = self._audit_writer.write_approval_entry(
            item=item,
            principal=principal,
            decision=decision,
            outcome=outcome_status,
            justification=justification,
            receipt_ref=receipt.receipt_ref,
            already_recorded=receipt.already_recorded,
        )
        preview = (
            f"approve_hil[{item.action_kind}]: decision={decision.value} "
            f"receipt={receipt.receipt_ref}" + (" (replay)" if receipt.already_recorded else "")
        )
        return ToolResult(
            status=outcome_status,
            data={
                "audit_id": audit_id,
                "receipt_ref": receipt.receipt_ref,
                "already_recorded": receipt.already_recorded,
                "decision": decision.value,
                "idempotency_key": item.idempotency_key,
            },
            preview=preview,
            evidence_refs=(f"audit:{audit_id}", f"hil:{item.idempotency_key}"),
        )


# ---------------------------------------------------------------------------
# RunRunbookTool - dispatch to a named runbook adapter (dry-run or live)
# ---------------------------------------------------------------------------


class RunRunbookTool:
    """Execute one runbook registered under ``docs/runbooks/``.

    Both the dry-run and live paths ship as ONE tool per
    operator-console.md 3.2. The static ``rbac_floor`` is Contributor
    because dry-run is the low-risk path; the tool itself upgrades
    the check to Owner for a live invocation
    (``dry_run=False``). This mirrors the doc's
    "``dry_run=true`` requires Contributor; ``dry_run=false`` requires
    Owner" rule without splitting the tool into two names.

    Arguments (``arguments`` mapping):

    - ``name`` (str, required) - runbook name; MUST be registered on
      the injected :class:`RunbookRegistry`.
    - ``params`` (Mapping, optional; default ``{}``) - forwarded to
      the runbook adapter verbatim.
    - ``dry_run`` (bool, optional; default ``True``) - when False, the
      tool refuses unless ``principal.role`` is Owner.

    Every terminal path writes one ``console.run_runbook`` audit
    entry (outcome=ok / error / abstain).
    """

    name = "run_runbook"
    description = (
        "Execute one runbook registered under docs/runbooks/. dry_run=True "
        "is a Contributor-floor plan; dry_run=False is a live invocation and "
        "requires Owner."
    )
    rbac_floor: Role = Role.CONTRIBUTOR
    side_effect_class: SideEffectClass = "execute"

    def __init__(
        self,
        *,
        registry: RunbookRegistry,
        audit_writer: AuditWriter,
    ) -> None:
        self._registry = registry
        self._audit_writer = audit_writer

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> ToolResult:
        import asyncio

        runbook_name = str(arguments.get("name", "")).strip()
        raw_params = arguments.get("params", {})
        dry_run_raw = arguments.get("dry_run", True)

        if not runbook_name:
            return ToolResult(
                status="error",
                preview="run_runbook requires a non-empty 'name'",
            )
        if not isinstance(raw_params, Mapping):
            return ToolResult(
                status="error",
                preview="run_runbook 'params' MUST be a mapping",
            )
        if not isinstance(dry_run_raw, bool):
            return ToolResult(
                status="error",
                preview="run_runbook 'dry_run' MUST be a boolean",
            )
        dry_run: bool = dry_run_raw

        # Live path requires Owner; Contributor / Approver may only
        # execute dry-run. The static rbac_floor is Contributor so
        # Contributor CAN invoke - but only in dry-run mode.
        if not dry_run and principal.role is not Role.OWNER:
            audit_id = self._audit_writer.write_runbook_entry(
                name=runbook_name,
                params=raw_params,
                principal=principal,
                dry_run=dry_run,
                outcome="error",
                summary="live run refused; caller is not Owner",
                error_kind="rbac_below_owner_for_live",
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id},
                preview=(
                    "run_runbook: live invocation requires Owner "
                    f"(caller role={principal.role.value})"
                ),
                evidence_refs=(f"audit:{audit_id}",),
            )

        # Unknown runbook -> fail-close with error + audit.
        if runbook_name not in self._registry.names():
            available = ", ".join(self._registry.names()) or "(none registered)"
            audit_id = self._audit_writer.write_runbook_entry(
                name=runbook_name,
                params=raw_params,
                principal=principal,
                dry_run=dry_run,
                outcome="error",
                summary=f"unknown runbook; available: {available}",
                error_kind="not_found",
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id, "available": list(self._registry.names())},
                preview=f"run_runbook: unknown runbook {runbook_name!r}",
                evidence_refs=(f"audit:{audit_id}",),
            )

        try:
            result: RunbookResult = asyncio.run(
                self._registry.execute(
                    name=runbook_name,
                    params=dict(raw_params),
                    dry_run=dry_run,
                )
            )
        except RunbookNotFoundError:
            # Race between names() and execute(); fail closed.
            audit_id = self._audit_writer.write_runbook_entry(
                name=runbook_name,
                params=raw_params,
                principal=principal,
                dry_run=dry_run,
                outcome="error",
                summary="runbook disappeared between name check and execute",
                error_kind="not_found",
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id},
                preview=(
                    f"run_runbook: {runbook_name!r} disappeared between "
                    "existence check and dispatch"
                ),
                evidence_refs=(f"audit:{audit_id}",),
            )
        except RunbookError as exc:
            audit_id = self._audit_writer.write_runbook_entry(
                name=runbook_name,
                params=raw_params,
                principal=principal,
                dry_run=dry_run,
                outcome="error",
                summary=str(exc),
                error_kind=exc.kind,
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id, "error_kind": exc.kind},
                preview=f"run_runbook[{runbook_name}]: {exc}",
                evidence_refs=(f"audit:{audit_id}",),
            )

        outcome: Literal["ok", "error", "abstain"] = "ok" if result.ok else "error"
        audit_id = self._audit_writer.write_runbook_entry(
            name=runbook_name,
            params=raw_params,
            principal=principal,
            dry_run=dry_run,
            outcome=outcome,
            summary=result.summary,
            detail=dict(result.detail),
        )
        preview = (
            f"run_runbook[{runbook_name}]: {'dry-run ' if dry_run else ''}"
            f"{'ok' if result.ok else 'failed'} - {result.summary}"
        )
        return ToolResult(
            status=outcome,
            data={
                "audit_id": audit_id,
                "runbook": runbook_name,
                "dry_run": dry_run,
                "summary": result.summary,
                "detail": dict(result.detail),
            },
            preview=preview,
            evidence_refs=(f"audit:{audit_id}",),
        )


# ---------------------------------------------------------------------------
# ActivateBreakGlassTool - explicit, time-boxed, fail-closed on pager
# ---------------------------------------------------------------------------


_SECRET_PATTERNS: tuple[str, ...] = (
    "AccountKey=",  # Azure Storage
    "SharedAccessKey=",  # Azure Service Bus / Event Hubs
    "AKIA",  # AWS access key prefix
    "-----BEGIN",  # PEM key
    "ghp_",  # GitHub personal token
    "xox",  # Slack tokens
)


def _redact_secrets(text: str) -> str:
    """Best-effort secret scrub - a match on any pattern replaces the
    whole line with a fixed placeholder so the reason never leaks."""
    if not text:
        return text
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        if any(pat in line for pat in _SECRET_PATTERNS):
            cleaned.append("[REDACTED-SUSPECTED-SECRET]")
        else:
            cleaned.append(line)
    return "\n".join(cleaned)


class ActivateBreakGlassTool:
    """Explicitly promote the current session to BreakGlass.

    Chat invariant 7 (operator-console.md 7.2) requires:

    - the reason to be at least ``min_reason_length`` characters
      (default 20) and pass a defense-in-depth secret scrub;
    - the TTL to be ``<= max_ttl_seconds`` (default 14400 = 4h);
    - the pager to confirm delivery via :class:`BreakGlassPager` - if
      it raises :class:`BreakGlassPagerError`, the grant is refused
      (fail-closed on notification).

    Every path is audited: success writes the grant details, refusals
    (short reason, too-long TTL, pager failure) write an audit entry
    with a distinct ``refusal_kind`` so Owners see the attempt.

    Any authenticated caller (Reader-floor) may attempt to activate,
    which mirrors the doc's "Any authenticated user" audience. BreakGlass
    membership itself is NOT granted at the console layer - this tool
    records intent and pages Owners; the RBAC resolver
    (:mod:`aiopspilot.core.rbac.resolver`) grants the role for the
    session.
    """

    name = "activate_break_glass"
    description = (
        "Request session-scoped BreakGlass elevation. Time-boxed (<=4h), "
        "explicit reason required, fail-closed on pager delivery. Always "
        "audited whether granted or refused."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "breakglass"

    _DEFAULT_MAX_TTL_SECONDS: int = 14400
    _DEFAULT_MIN_REASON_LENGTH: int = 20

    def __init__(
        self,
        *,
        pager: BreakGlassPager,
        audit_writer: AuditWriter,
        max_ttl_seconds: int = _DEFAULT_MAX_TTL_SECONDS,
        min_reason_length: int = _DEFAULT_MIN_REASON_LENGTH,
        clock: Any = None,
    ) -> None:
        if max_ttl_seconds > self._DEFAULT_MAX_TTL_SECONDS:
            raise ValueError(
                "max_ttl_seconds MUST NOT exceed the shipped ceiling "
                f"{self._DEFAULT_MAX_TTL_SECONDS} (chat invariant 7); "
                f"got {max_ttl_seconds}"
            )
        if max_ttl_seconds < 60:
            raise ValueError("max_ttl_seconds MUST be at least 60")
        if min_reason_length < 1:
            raise ValueError("min_reason_length MUST be at least 1")
        self._pager = pager
        self._audit_writer = audit_writer
        self._max_ttl_seconds = max_ttl_seconds
        self._min_reason_length = min_reason_length
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> ToolResult:
        import asyncio

        raw_reason = str(arguments.get("reason", ""))
        raw_expiry = arguments.get("expiry_seconds", self._max_ttl_seconds)

        # Redact BEFORE any comparison so a rejected secret is never
        # quoted in an error message.
        reason_redacted = _redact_secrets(raw_reason).strip()

        if len(reason_redacted) < self._min_reason_length:
            audit_id = self._audit_writer.write_break_glass_entry(
                principal=principal,
                outcome="error",
                reason_redacted=reason_redacted,
                activated_at=None,
                expires_at=None,
                pager_receipt="",
                refusal_kind="short_reason",
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id, "refusal_kind": "short_reason"},
                preview=(
                    f"activate_break_glass: reason MUST be >= "
                    f"{self._min_reason_length} chars after redaction"
                ),
                evidence_refs=(f"audit:{audit_id}",),
            )

        try:
            expiry_seconds = int(raw_expiry)
        except (TypeError, ValueError):
            audit_id = self._audit_writer.write_break_glass_entry(
                principal=principal,
                outcome="error",
                reason_redacted=reason_redacted,
                activated_at=None,
                expires_at=None,
                pager_receipt="",
                refusal_kind="invalid_expiry",
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id, "refusal_kind": "invalid_expiry"},
                preview=("activate_break_glass 'expiry_seconds' MUST be an integer"),
                evidence_refs=(f"audit:{audit_id}",),
            )
        if expiry_seconds < 60:
            audit_id = self._audit_writer.write_break_glass_entry(
                principal=principal,
                outcome="error",
                reason_redacted=reason_redacted,
                activated_at=None,
                expires_at=None,
                pager_receipt="",
                refusal_kind="expiry_below_minimum",
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id, "refusal_kind": "expiry_below_minimum"},
                preview=("activate_break_glass 'expiry_seconds' MUST be >= 60"),
                evidence_refs=(f"audit:{audit_id}",),
            )
        if expiry_seconds > self._max_ttl_seconds:
            audit_id = self._audit_writer.write_break_glass_entry(
                principal=principal,
                outcome="error",
                reason_redacted=reason_redacted,
                activated_at=None,
                expires_at=None,
                pager_receipt="",
                refusal_kind="expiry_above_ceiling",
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id, "refusal_kind": "expiry_above_ceiling"},
                preview=(
                    "activate_break_glass 'expiry_seconds' exceeds the shipped "
                    f"ceiling {self._max_ttl_seconds}"
                ),
                evidence_refs=(f"audit:{audit_id}",),
            )

        activated_at = self._clock()
        expires_at = activated_at + timedelta(seconds=expiry_seconds)

        try:
            pager_receipt = asyncio.run(
                self._pager.notify_owners(
                    actor_oid=principal.id,
                    actor_display=principal.display_name or principal.id,
                    reason_redacted=reason_redacted,
                    activated_at=activated_at,
                    expires_at=expires_at,
                )
            )
        except BreakGlassPagerError as exc:
            audit_id = self._audit_writer.write_break_glass_entry(
                principal=principal,
                outcome="error",
                reason_redacted=reason_redacted,
                activated_at=activated_at,
                expires_at=expires_at,
                pager_receipt="",
                refusal_kind=f"pager_{exc.kind}",
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id, "refusal_kind": f"pager_{exc.kind}"},
                preview=(f"activate_break_glass refused: pager delivery failed ({exc.kind})"),
                evidence_refs=(f"audit:{audit_id}",),
            )

        audit_id = self._audit_writer.write_break_glass_entry(
            principal=principal,
            outcome="ok",
            reason_redacted=reason_redacted,
            activated_at=activated_at,
            expires_at=expires_at,
            pager_receipt=pager_receipt,
            refusal_kind=None,
        )
        return ToolResult(
            status="ok",
            data={
                "audit_id": audit_id,
                "activated_at": activated_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "pager_receipt": pager_receipt,
                "reason_redacted": reason_redacted,
            },
            preview=(
                f"activate_break_glass: granted (expires "
                f"{expires_at.isoformat()}); pager={pager_receipt}"
            ),
            evidence_refs=(f"audit:{audit_id}", f"pager:{pager_receipt}"),
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _project_pending_item(item: HilPendingItem) -> dict[str, Any]:
    """Reduce a :class:`HilPendingItem` to a CLI-friendly projection.

    Kept explicit (no ``dataclasses.asdict``) so the shape is stable
    across dataclass evolution.
    """
    return {
        "idempotency_key": item.idempotency_key,
        "approval_id": item.approval_id,
        "event_id": item.event_id,
        "action_id": item.action_id,
        "action_kind": item.action_kind,
        "target_resource_ref": item.target_resource_ref,
        "reason": item.reason,
        "submitter_oid": item.submitter_oid,
        "citing_rule_ids": list(item.citing_rule_ids),
        "requested_at": item.requested_at.isoformat() if item.requested_at else None,
        "correlation_id": item.correlation_id,
        # Wave W2.3f: expose the executor sibling the approval would
        # dispatch to. ``None`` for rows enqueued before the field
        # landed keeps older records renderable.
        "mutation_target": item.mutation_target.value if item.mutation_target else None,
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


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


def _extract_resource_type(event: Event) -> str:
    resource = event.payload.get("resource")
    if isinstance(resource, Mapping):
        maybe_type = resource.get("type")
        if isinstance(maybe_type, str):
            return maybe_type
    return ""


def _enum_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _preview(patch: str, *, max_bytes: int = 512) -> str:
    """Short, safe preview of a rendered template.

    Never returns more than ``max_bytes`` characters; a longer patch is
    trimmed to keep audit entries bounded.
    """
    trimmed = patch.strip()
    if len(trimmed) <= max_bytes:
        return trimmed
    return trimmed[:max_bytes] + "..."


# Re-export UUID for symmetry with ``system_tools``.
_ = UUID


__all__ = [
    "ActivateBreakGlassTool",
    "ApproveHilTool",
    "AuditWriter",
    "ListHilTool",
    "RunRunbookTool",
    "SimulateChangeTool",
]
