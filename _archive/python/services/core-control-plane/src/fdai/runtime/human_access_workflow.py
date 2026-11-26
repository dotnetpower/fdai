"""Composition callbacks for current human-access agent ownership and isolated dispatch.

No callback calls a peer agent. The runtime injects each callback into its fixed
owner's declared subscriber; every cross-owner handoff remains typed pub/sub.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.executor_models import executor_action_payload_digest
from fdai_service_contracts.human_access_execution import (
    HumanAccessExecutionMaterial,
    human_access_record_digest,
)
from fdai_service_contracts.human_access_workflow import (
    HumanAccessHandoff,
    HumanAccessMembershipObservation,
    HumanAccessWorkNotice,
)

from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.human_assignment.access_planning import HumanAccessPlanner
from fdai.core.human_assignment.execution_approval import HumanAccessApprovalService
from fdai.core.human_assignment.execution_material import HumanAccessMaterialBuilder
from fdai.core.human_assignment.execution_ports import HumanAccessAgentBindings
from fdai.core.human_assignment.execution_recovery import HumanAccessRecoverySource
from fdai.core.human_assignment.execution_sources import HumanAccessCurrentPublisher
from fdai.core.human_assignment.model import EffectKind, EffectReceipt
from fdai.core.human_assignment.replacement import ReplacementCoveragePlanner
from fdai.core.risk_gate.authority import evaluate_execution_authority
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.gate import RiskGate
from fdai.core.risk_gate.risk_table import RiskTable
from fdai.delivery.human_access_closure import HumanAccessClosureReconciler
from fdai.delivery.identity.human_access_observer import IndependentHumanAccessObserver
from fdai.runtime.human_access_recovery import (
    RECOVERY_SCRIPT_REFERENCE,
    finish_inverse,
    judge_inverse,
    propose_inverse,
)
from fdai.runtime.isolated_executor_receipt_journal import BoundCommandCorrelation
from fdai.runtime.safeguard_isolated_executor import SafeguardBoundEventBusDirectApiExecutionClient
from fdai.shared.contracts.models import (
    Action,
    CeilingRole,
    Event,
    ExecutorEffectReceipt,
    Mode,
    RollbackKind,
    RollbackRef,
    Rule,
    Tier,
)
from fdai.shared.providers.executor_receipt_journal import receipt_matches_command
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class HumanAccessWorkflowRuntime:
    """Independent source-bound callbacks, never shared mutable agent state."""

    builder: HumanAccessMaterialBuilder
    approvals: HumanAccessApprovalService
    current: HumanAccessCurrentPublisher
    action_builder: ActionBuilder
    risk_gate: RiskGate
    risk_table: RiskTable
    dispatch_port: SafeguardBoundEventBusDirectApiExecutionClient
    observer: IndependentHumanAccessObserver
    enforce_ready: Callable[[], bool]
    clock: Callable[[], datetime]
    closure: HumanAccessClosureReconciler | None = None
    recovery: HumanAccessRecoverySource | None = None
    refresh_safety: Callable[[], Awaitable[None]] | None = None
    safety_held: Callable[[], bool] = lambda: False

    def agent_bindings(self) -> HumanAccessAgentBindings:
        """Provide no peer handles; each owner receives only its explicit operation."""
        return HumanAccessAgentBindings(
            self.judge_request,
            self.judge_decision,
            self.judge_effect,
            self.review,
            self.prepare,
            self.record_effect,
            self.dispatch,
            self.observe,
            self.observe_notice,
            self.judge_recovery,
            self.propose_recovery,
            self.finish_recovery,
            self.resume,
            self.record_failure,
        )

    @property
    def store(self) -> StateStore:
        """Use the existing Core-owned source store; no executor writer is injected."""
        return self.builder.cases.store

    async def judge_request(self, notice: HumanAccessWorkNotice) -> HumanAccessHandoff:
        """Forseti constructs the original Action under current promotion and risk."""
        self._fresh(notice)
        cases = self.builder.cases
        case = await cases.get_case(notice.case_id)
        if case.revision != notice.expected_revision:
            raise ValueError("human access request source revision is stale")
        source_type = (
            "ops.revoke-human-access"
            if case.intent.revocation is not None
            else "ops.apply-human-access"
        )
        if not await self.approvals.owners.is_current_owner(
            case.intent.requester_ref, at=self.clock()
        ):
            raise PermissionError("human access requester is no longer an active Owner")
        if case.intent.revocation is None:
            membership = await HumanAccessPlanner(cases, self.builder.role_group_ids).plan(
                case_id=case.case_id, expected_revision=case.revision
            )
        else:
            replacement = await ReplacementCoveragePlanner(
                cases, self.builder.role_group_ids
            ).plan_revocation(case_id=case.case_id, expected_revision=case.revision)
            membership = replacement.removal
        await self.current.source.promotions.refresh(source_type)
        mode = self.current.source.promotions.mode_of(source_type)
        promotion = await self.store.read_state("action_promotion:" + source_type)
        if promotion is None:
            return HumanAccessHandoff(
                notice=notice, stage="held", reason="human_access_promotion_unavailable"
            )
        event = Event(
            schema_version="1.0.0",
            event_id=notice.request_id,
            idempotency_key=f"human-access-request:{notice.request_id}",
            correlation_id=str(notice.request_id),
            source="human-assignment",
            event_type="operator.requested",
            resource_ref=membership.membership_lock_key.removeprefix("fdai:resource:"),
            payload={
                "operator_request": {
                    "action_type": source_type,
                    "initiator_principal": case.intent.requester_ref,
                    "params": {
                        "case_id": case.case_id,
                        "expected_revision": case.revision,
                        **(
                            {
                                "replacement_revisions": dict(
                                    case.intent.revocation.replacement_revisions
                                )
                            }
                            if case.intent.revocation is not None
                            else {}
                        ),
                    },
                }
            },
            detected_at=notice.observed_at,
            ingested_at=self.clock(),
            mode=Mode.SHADOW,
        )
        action_builder = ActionBuilder(
            self.action_builder.action_types_by_name,
            self.action_builder.ontology_release,
            lambda: notice.observed_at,
        )
        candidate, rule = action_builder.build_from_operator_request(event=event)
        payload = candidate.model_dump(mode="json")
        payload.update(
            mode=mode.value,
            executor_identity_ref="identity/human-access",
            rollback_ref=RollbackRef(
                kind=RollbackKind.SCRIPTED, reference=RECOVERY_SCRIPT_REFERENCE
            ).model_dump(mode="json"),
        )
        action = Action.model_validate(payload)
        await self._risk(action, rule)
        material = await self.builder.build(
            action=action, promotion_record=promotion, at=notice.observed_at
        )
        await self.store.write_state_with_audit_if_absent(
            "human_assignment:execution-rule:" + str(action.action_id),
            rule.model_dump(mode="json"),
            {
                "actor": "Forseti",
                "action_kind": "human_access.rule.retained",
                "mode": "shadow",
                "material_digest": material.digest,
            },
        )
        return _result(notice, material, "proposed")

    async def judge_decision(self, notice: HumanAccessWorkNotice) -> HumanAccessHandoff:
        """Forseti verifies the original decision source; Var joins the human quorum."""
        self._fresh(notice)
        material = await self._notice_material(notice)
        if notice.approval_id not in material.approval_ids:
            raise ValueError("human access decision belongs to another original material")
        await self.current.source.check(material)
        return _result(notice, material, "decision_checked")

    async def review(self, handoff: HumanAccessHandoff) -> HumanAccessHandoff:
        """Var parks or checks current exact human slots; it never prepares or executes a case."""
        material = await self._material(handoff)
        if handoff.stage in {"proposed", "recovery_proposed"}:
            await self.approvals.park(material)
            return _result(handoff.notice, material, "awaiting_human")
        if handoff.stage == "effect_recorded" and material.inverse is not None:
            await self._effect(handoff)
            return _result(handoff.notice, material, "recovery_verified", handoff.evidence_ref)
        await self.approvals.read_approvals(material)
        if handoff.stage == "prepared":
            await self.current.observe(material)
        return _result(
            handoff.notice,
            material,
            "dispatch_ready" if handoff.stage == "prepared" else "human_reviewed",
        )

    async def prepare(self, handoff: HumanAccessHandoff) -> HumanAccessHandoff:
        """Muninn records exact preparation only after sealed independent human review."""
        material = await self._material(handoff)
        if (
            material.action().mode.value != "enforce"
            or not self.enforce_ready()
            or self.recovery is None
        ):
            return HumanAccessHandoff(
                notice=handoff.notice, stage="held", reason="human_access_runtime_shadow"
            )
        await self.approvals.read_approvals(material)
        prepared = await self.builder.cases.prepare_human_access(
            material=material, actor_ref="Muninn", now=self.clock()
        )
        preparation = (
            prepared.iam_recovery_preparation
            if material.inverse is not None
            else prepared.iam_preparation
        )
        if preparation is None:
            raise ValueError("human access preparation readback is missing")
        return _result(handoff.notice, material, "prepared", preparation.reference)

    async def dispatch(self, handoff: HumanAccessHandoff) -> HumanAccessHandoff:
        """Thor publishes only through the shared safeguard lifecycle; pending is never success."""
        material = await self._material(handoff)
        action = Action.model_validate_json(material.action_json)
        if not self.enforce_ready() or action.mode is not Mode.ENFORCE:
            return HumanAccessHandoff(
                notice=handoff.notice, stage="held", reason="human_access_runtime_shadow"
            )
        rule = Rule.model_validate(
            await self.store.read_state("human_assignment:execution-rule:" + str(action.action_id))
        )

        async def source_guard() -> None:
            if not self.enforce_ready() or self.recovery is None:
                raise ValueError("human access current execution readiness is unavailable")
            await self.approvals.read_approvals(material)
            await self.current.source.check(material)
            await self._risk(action, rule)

        await source_guard()
        result = await self.dispatch_port.execute(action=action, source_guard=source_guard)
        if result.audit_context.get("dispatch_status") != "pending":
            raise ValueError(
                "human access safeguard publication did not produce an exact pending command"
            )
        return _result(handoff.notice, material, "dispatch_pending")

    async def observe_notice(self, notice: HumanAccessWorkNotice) -> HumanAccessHandoff:
        """Heimdall resumes receipt observation after restart without republishing the effect."""
        self._fresh(notice)
        material = await self._notice_material(notice)
        result = await self.observe(_result(notice, material, "dispatch_pending"))
        if notice.operation == "recovery":
            return _result(notice, material, "recovery_observed", result.evidence_ref)
        return result

    async def resume(self, notice: HumanAccessWorkNotice) -> HumanAccessHandoff:
        """Resume original prepared work without renewing approvals or a prior claim."""
        self._fresh(notice)
        material = await self._notice_material(notice)
        await self.approvals.read_approvals(material)
        return _result(notice, material, "decision_checked")

    async def judge_recovery(self, handoff: HumanAccessHandoff) -> HumanAccessHandoff:
        """Forseti judges a fresh exact inverse; only Vidar may propose its recovery handoff."""
        return await judge_inverse(self, handoff)

    async def propose_recovery(self, handoff: HumanAccessHandoff) -> HumanAccessHandoff:
        """Vidar proposes without bypassing the separate current human review."""
        return await propose_inverse(self, handoff)

    async def finish_recovery(self, handoff: HumanAccessHandoff) -> HumanAccessHandoff:
        """Vidar finishes only a durably observed inverse, never a queued request."""
        return await finish_inverse(self, handoff)

    async def observe(self, handoff: HumanAccessHandoff) -> HumanAccessHandoff:
        """Heimdall reads exact membership only after a real bound dispatch receipt."""
        material = await self._material(handoff)
        receipt = await self._dispatch_receipt(material)
        observed = await self.observer.observe(
            material=material,
            dispatch_receipt_digest=human_access_record_digest(receipt.model_dump(mode="json")),
            dispatch_completed_at=receipt.completed_at,
        )
        reference = "human-access-observation:" + human_access_record_digest(
            observed.model_dump(mode="json")
        )
        value = {
            "observation": observed.model_dump(mode="json"),
            "recorded_at": self.clock().isoformat(),
        }
        created = await self.store.write_state_with_audit_if_absent(
            "human_assignment:" + reference,
            value,
            {
                "actor": "Heimdall",
                "action_kind": "human_access.membership.observed",
                "material_digest": material.digest,
                "observation_ref": reference,
                "mode": "shadow",
            },
        )
        retained = await self.store.read_state("human_assignment:" + reference)
        if (
            retained is None
            or retained.get("observation") != value["observation"]
            or (created and dict(retained) != value)
        ):
            raise ValueError("human access independent observation readback conflicted")
        return _result(handoff.notice, material, "effect_observed", reference)

    async def judge_effect(self, handoff: HumanAccessHandoff) -> HumanAccessHandoff:
        """Forseti checks the original target, current case and independent membership."""
        material, observation = await self._observation(handoff)
        if (
            observation.state == "membership_present"
        ) is not material.membership_plan().desired_membership:
            if material.inverse is not None or self.clock() >= observation.valid_until:
                raise ValueError("human access inverse or stale mismatch requires human review")
            return _result(handoff.notice, material, "effect_mismatch", handoff.evidence_ref)
        await self._effect(handoff)
        return _result(handoff.notice, material, "effect_checked", handoff.evidence_ref)

    async def record_failure(self, handoff: HumanAccessHandoff) -> HumanAccessHandoff:
        """Muninn holds a freshly observed mismatch after Saga; no inverse is dispatched here."""
        material, observed = await self._observation(handoff)
        case = await self.builder.cases.get_case(material.action().params["case_id"])
        if (
            material.inverse is not None
            or self.clock() >= observed.valid_until
            or (observed.state == "membership_present")
            is material.membership_plan().desired_membership
            or case.iam_preparation is None
            or case.iam_preparation.material_digest != material.digest
        ):
            raise ValueError("human access failure requires current independent mismatch evidence")
        if case.state.value == "degraded" and case.degraded_reason == "iam_effect_mismatch":
            return _result(handoff.notice, material, "recovery_held", handoff.evidence_ref)
        if (
            case.state.value != "iam_applying"
            or case.revision != case.iam_preparation.prepared_revision
        ):
            raise ValueError("human access mismatch case changed before hold")
        await self._close(handoff, material, observed)
        await self.builder.cases.mark_degraded(
            case_id=case.case_id,
            expected_revision=case.revision,
            reason_code="iam_effect_mismatch",
            actor_ref="Muninn",
            now=self.clock(),
        )
        return _result(handoff.notice, material, "recovery_held", handoff.evidence_ref)

    async def record_effect(self, handoff: HumanAccessHandoff) -> HumanAccessHandoff:
        """Muninn records only the independently observed effect after Saga's judgment seal."""
        material, observed = await self._effect(handoff)
        if handoff.evidence_ref is None:
            raise ValueError("human access effect reference is unavailable")
        await self._close(handoff, material, observed)
        case = await self.builder.cases.get_case(material.action().params["case_id"])
        receipt = EffectReceipt(
            EffectKind.IAM, handoff.evidence_ref, observed.target_digest, observed.observed_at
        )
        if material.inverse is not None:
            await self.builder.cases.record_human_access_recovery(
                material=material, receipt=receipt, actor_ref="Muninn"
            )
        else:
            await self.builder.cases.record_effect(
                case_id=case.case_id,
                expected_revision=case.revision,
                receipt=receipt,
                actor_ref="Muninn",
            )
        return _result(handoff.notice, material, "effect_recorded", handoff.evidence_ref)

    async def _effect(
        self, handoff: HumanAccessHandoff
    ) -> tuple[HumanAccessExecutionMaterial, HumanAccessMembershipObservation]:
        material, observed = await self._observation(handoff)
        case = await self.builder.cases.get_case(material.action().params["case_id"])
        now = self.clock()
        groups_digest = human_access_record_digest(
            {role.value: group for role, group in self.builder.role_group_ids.items()}
        )
        existing = (
            case.iam_recovery_effect
            if material.inverse is not None
            else next((item for item in case.effect_receipts if item.kind is EffectKind.IAM), None)
        )
        preparation = (
            case.iam_recovery_preparation if material.inverse is not None else case.iam_preparation
        )
        exact_replay = (
            existing is not None
            and existing.receipt_ref == handoff.evidence_ref
            and existing.digest == observed.target_digest
            and existing.received_at == observed.observed_at
        )
        if (
            observed.state
            != (
                "membership_present"
                if material.membership_plan().desired_membership
                else "membership_absent"
            )
            or preparation is None
            or preparation.material_digest != material.digest
            or (
                not exact_replay
                and (
                    now >= observed.valid_until
                    or groups_digest != material.role_groups_digest
                    or case.revision != preparation.prepared_revision
                    or case.state.value
                    != ("degraded" if material.inverse is not None else "iam_applying")
                )
            )
        ):
            raise ValueError(
                "human access independent effect does not match the exact prepared case"
            )
        return material, observed

    async def _observation(
        self, handoff: HumanAccessHandoff
    ) -> tuple[HumanAccessExecutionMaterial, HumanAccessMembershipObservation]:
        """Read independent evidence separately from desired state and case transition."""
        material = await self._material(handoff)
        if handoff.evidence_ref is None:
            raise ValueError("human access independent observation reference is missing")
        raw = await self.store.read_state("human_assignment:" + handoff.evidence_ref)
        observed = HumanAccessMembershipObservation.model_validate(
            raw.get("observation") if raw is not None else None
        )
        receipt = await self._dispatch_receipt(material)
        now = self.clock()
        if (
            observed.material_digest != material.digest
            or observed.action_digest != material.action_digest
            or observed.target_digest != material.membership_plan().target_digest
            or observed.dispatch_receipt_digest
            != human_access_record_digest(receipt.model_dump(mode="json"))
            or observed.observer_identity_ref != self.observer.identity_ref
            or not receipt.completed_at <= observed.observed_at <= now
            or handoff.evidence_ref
            != "human-access-observation:"
            + human_access_record_digest(observed.model_dump(mode="json"))
        ):
            raise ValueError("human access independent observation identity is inconsistent")
        return material, observed

    async def _close(
        self,
        handoff: HumanAccessHandoff,
        material: HumanAccessExecutionMaterial,
        observed: HumanAccessMembershipObservation,
    ) -> None:
        """Resolve the original released command generation through authoritative CAS."""
        if self.closure is None or handoff.evidence_ref is None:
            raise ValueError(
                "human access authoritative post-release reconciliation is unavailable"
            )
        link = await self.store.read_state(
            "runtime:isolated-executor:human-access:" + str(material.action().action_id)
        )
        if link is None:
            raise ValueError("human access original command correlation is unavailable")
        correlation = BoundCommandCorrelation.model_validate(
            await self.store.read_state(
                "runtime:isolated-executor:command:" + str(link["command_id"])
            )
        )
        await self.closure.close(
            closure_key=correlation.closure_key,
            material=material,
            observation=observed,
            observation_ref=handoff.evidence_ref,
        )

    async def _dispatch_receipt(
        self, material: HumanAccessExecutionMaterial
    ) -> ExecutorEffectReceipt:
        link = await self.store.read_state(
            "runtime:isolated-executor:human-access:" + str(material.action().action_id)
        )
        wire_digest = executor_action_payload_digest(
            material.action().model_dump(mode="json", exclude_none=True)
        )
        if link is None or link.get("action_digest") != wire_digest:
            raise ValueError("human access original dispatch is unavailable")
        command_id = str(link["command_id"])
        correlation = BoundCommandCorrelation.model_validate(
            await self.store.read_state("runtime:isolated-executor:command:" + command_id)
        )
        receipt = ExecutorEffectReceipt.model_validate(
            await self.store.read_state("runtime:isolated-executor:terminal-receipt:" + command_id)
        )
        command = correlation.command
        original = Action.model_validate(command.action_payload).model_dump(mode="json")
        if (
            command.action_payload_digest != wire_digest
            or original != material.action().model_dump(mode="json")
            or not receipt_matches_command(command, receipt, partition_key=command.partition_key)
            or receipt.status.value not in {"dispatched", "already_applied"}
            or receipt.effect_applied is not True
        ):
            raise ValueError("human access dispatch acknowledgement is missing or inconsistent")
        return receipt

    async def _risk(self, action: Action, rule: Rule) -> None:
        if self.refresh_safety is not None:
            await self.refresh_safety()
        action_type = self.action_builder.action_types_by_name[action.action_type]
        if action.action_type_ref != self.action_builder._action_type_ref(action_type):
            raise ValueError("human access original ActionType catalog changed")
        safety = self.risk_gate.evaluate(action=action, rule=rule, action_type=action_type)
        authority = evaluate_execution_authority(
            tier=Tier.T0,
            action_type=action_type,
            table=self.risk_table,
            principal_role=CeilingRole.OWNER,
            environment="prod",
            system_degraded=self.safety_held(),
        )
        case = await self.builder.cases.get_case(action.params["case_id"])
        quorum = 2 if case.intent.requested_role.value in {"Approver", "Owner"} else 1
        if (
            safety.outcome.value not in {"auto", "hil"}
            or authority.final_level not in {AxisLevel.ENFORCE_HIL, AxisLevel.ENFORCE_AUTO}
            or authority.quorum > quorum
            or (action.mode is Mode.ENFORCE and safety.effective_mode is not Mode.ENFORCE)
        ):
            raise ValueError("human access current risk policy does not admit human review")

    async def _material(self, handoff: HumanAccessHandoff) -> HumanAccessExecutionMaterial:
        if handoff.action_id is None:
            raise ValueError("human access handoff lacks its exact Action")
        material = await self.builder.materials.read(str(handoff.action_id))
        if (
            material is None
            or material.digest != handoff.material_digest
            or material.action().params["case_id"] != handoff.notice.case_id
            or material.action().params["expected_revision"] != handoff.notice.expected_revision
            or material.action().event_id != handoff.notice.request_id
        ):
            raise ValueError("human access handoff material is inconsistent")
        return material

    async def _notice_material(self, notice: HumanAccessWorkNotice) -> HumanAccessExecutionMaterial:
        if notice.action_id is None:
            raise ValueError("human access notice material identity is missing")
        material = await self.builder.materials.read(str(notice.action_id))
        if (
            material is None
            or material.action().params["case_id"] != notice.case_id
            or material.action().params["expected_revision"] != notice.expected_revision
            or material.action().event_id != notice.request_id
        ):
            raise ValueError("human access notice material identity changed")
        return material

    def _fresh(self, notice: HumanAccessWorkNotice) -> None:
        if not notice.observed_at <= self.clock() < notice.expires_at:
            raise ValueError("human access mechanical notice expired")


def _result(
    notice: HumanAccessWorkNotice,
    material: HumanAccessExecutionMaterial,
    stage: str,
    evidence_ref: str | None = None,
) -> HumanAccessHandoff:
    return HumanAccessHandoff.model_validate(
        {
            "notice": notice,
            "stage": stage,
            "action_id": material.action().action_id,
            "material_digest": material.digest,
            "evidence_ref": evidence_ref,
        }
    )


__all__ = ["HumanAccessWorkflowRuntime"]
