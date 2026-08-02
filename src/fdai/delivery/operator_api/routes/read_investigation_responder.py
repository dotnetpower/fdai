"""Heimdall conversational adapter for bounded read investigations."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol

from fdai.agents import Bragi, Heimdall
from fdai.core.read_investigation import (
    InvestigationExecutionPolicy,
    ReadInvestigationBudget,
    ReadInvestigationExecutionMode,
    ReadInvestigationPlan,
    ReadInvestigationProgressKind,
    ReadInvestigationRequest,
    classify_read_investigation_intent,
    estimate_plan_latency,
    latency_profile,
    plan_read_investigation,
    read_tool_spec,
    resource_name_from_question,
)
from fdai.delivery.operator_api.routes.chat_preincident_activity import (
    ScopeActivityProvider,
    parse_preincident_activity,
    resolve_preincident_activity,
)
from fdai.delivery.operator_api.routes.read_investigations import (
    ReadInvestigationDirectExecution,
    ReadInvestigationRunRejectedError,
)
from fdai.shared.providers.conversation_channel import (
    ConversationExecutionStatus,
    ObservedExecutionActivity,
)
from fdai.shared.providers.read_investigation import (
    ReadEvidenceEnvelope,
    ReadInvestigationIntent,
    ReadLatencyProfileStore,
    ReadToolId,
    ResourceSelector,
)

_HISTORY_LOOKBACK_SECONDS = 30 * 24 * 3_600
_LATEST_CHANGE_SUFFIX = "change history: show the most recent successful operation"


class ReadInvestigationDirectExecutor(Protocol):
    @property
    def transport(self) -> str: ...

    def execute(
        self,
        plan: ReadInvestigationPlan,
        *,
        owner_principal_id: str,
        progress_observer: Callable[[ReadInvestigationProgressKind], Awaitable[None]] | None = None,
    ) -> Awaitable[ReadInvestigationDirectExecution]: ...


class HeimdallReadInvestigationResponder:
    """Resolve measured-fast reads and hand longer work to the durable route."""

    def __init__(
        self,
        *,
        executor: ReadInvestigationDirectExecutor,
        latency_store: ReadLatencyProfileStore,
        scope_ref: str,
        policy: InvestigationExecutionPolicy | None = None,
        scope_activity_provider: ScopeActivityProvider | None = None,
    ) -> None:
        if not scope_ref.strip() or len(scope_ref) > 256:
            raise ValueError("scope_ref MUST be a bounded identifier")
        self._executor = executor
        self._latency_store = latency_store
        self._scope_ref = scope_ref
        self._policy = policy or InvestigationExecutionPolicy(streamed_max_ms=20_000)
        self._scope_activity_provider = scope_activity_provider

    async def __call__(
        self,
        question: str,
        context: dict[str, object],
        *,
        progress_observer: Callable[[ReadInvestigationProgressKind], Awaitable[None]] | None = None,
    ) -> dict[str, object] | None:
        preincident = parse_preincident_activity(question)
        if preincident is not None:
            return await resolve_preincident_activity(preincident, self._scope_activity_provider)
        intent = classify_read_investigation_intent(question)
        resource_name = resource_name_from_question(question)
        if intent is None or resource_name is None:
            return None
        user_id = context.get("user_id")
        session_id = context.get("session_id")
        if not isinstance(user_id, str) or not isinstance(session_id, str):
            return {
                "answer": "Read investigation requires an authenticated user and session.",
                "facts": {"status": "unavailable", "reason": "identity_context_missing"},
            }
        digest = hashlib.sha256(f"{user_id}:{session_id}:{question}".encode()).hexdigest()
        request = ReadInvestigationRequest(
            requester_ref=user_id,
            conversation_ref=session_id,
            correlation_ref=f"read:sha256:{digest}",
            intent=intent,
            selector=ResourceSelector(name=resource_name, scope_ref=self._scope_ref),
            lookback_seconds=(
                _HISTORY_LOOKBACK_SECONDS
                if intent
                in {
                    ReadInvestigationIntent.CHANGE_ATTRIBUTION,
                    ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY,
                }
                else 3_600
            ),
            requested_evidence=(
                (ReadToolId.QUERY_RESOURCE_ACTIVITY,)
                if intent is ReadInvestigationIntent.CHANGE_ATTRIBUTION
                else ()
            ),
            budget=ReadInvestigationBudget(),
            idempotency_key=f"read:sha256:{digest}",
            created_at=datetime.now(UTC),
        )
        plan = plan_read_investigation(request)
        profiles = {}
        for step in plan.steps:
            spec = read_tool_spec(step.tool_id)
            samples = await self._latency_store.recent(
                tool_id=step.tool_id,
                transport=self._executor.transport,
                operation_class=spec.operation_class,
                limit=200,
            )
            profiles[step.tool_id] = latency_profile(samples)
        estimate = estimate_plan_latency(
            plan,
            profiles,
            minimum_samples=self._policy.minimum_profile_samples,
        )
        mode = self._policy.select(plan, estimate)
        if mode is ReadInvestigationExecutionMode.DETACHED:
            return {
                "answer": (
                    "This investigation requires the durable read-investigation route "
                    f"({mode.value}, estimated upper bound {estimate.upper_ms} ms)."
                ),
                "facts": {
                    "status": "handoff_required",
                    "mode": mode.value,
                    "intent": intent.value,
                    "resource_name": resource_name,
                    "estimated_upper_ms": estimate.upper_ms,
                },
            }
        try:
            execution = await self._executor.execute(
                plan,
                owner_principal_id=user_id,
                progress_observer=progress_observer,
            )
        except ReadInvestigationRunRejectedError as exc:
            return {
                "answer": "This read investigation is already active or cannot be replayed.",
                "facts": {
                    "status": "unavailable",
                    "reason": "idempotency_rejected",
                    "retry_after_seconds": exc.retry_after_seconds,
                    "intent": intent.value,
                    "resource_name": resource_name,
                },
            }
        result = execution.result
        answer = _render_answer(
            resource_name=resource_name,
            intent=intent,
            outcome=result.outcome.value,
            evidence=result.evidence,
            korean=_is_korean(question),
            latest_change_only=question.endswith(_LATEST_CHANGE_SUFFIX),
        )
        return {
            "answer": answer,
            "facts": {
                "status": result.outcome.value,
                "mode": mode.value,
                "intent": intent.value,
                "resource_name": resource_name,
                "replayed": execution.replayed,
                "evidence_refs": result.evidence_refs,
                "evidence_sources": tuple(item.authority for item in result.evidence),
                "records": tuple(
                    {
                        "authority": envelope.authority,
                        "status": record.status,
                        "details": dict(record.details),
                    }
                    for envelope in result.evidence
                    for record in envelope.records
                ),
            },
        }


def _render_answer(
    *,
    resource_name: str,
    intent: ReadInvestigationIntent,
    outcome: str,
    evidence: tuple[ReadEvidenceEnvelope, ...],
    korean: bool,
    latest_change_only: bool,
) -> str:
    records = tuple(record for envelope in evidence for record in envelope.records)
    if intent is ReadInvestigationIntent.NETWORK_SECURITY and records:
        allowed = [
            record
            for record in records
            if record.status.casefold() == "allow"
            and dict(record.details).get("direction", "").casefold() == "inbound"
        ]
        if not allowed:
            return (
                f"{resource_name}에서 확인된 inbound 허용 규칙이 없습니다."
                if korean
                else f"No inbound allow rules were observed for {resource_name}."
            )
        rendered = "; ".join(_render_nsg_rule(record.details) for record in allowed)
        caveat = (
            " 이 결과는 NSG 구성 규칙이며 end-to-end 도달 가능성을 단독으로 증명하지 않습니다."
            if korean
            else " These are configured NSG rules and do not alone prove end-to-end reachability."
        )
        prefix = "확인된 inbound 허용 규칙" if korean else "observed inbound allow rules"
        return f"{resource_name} {prefix}: {rendered}.{caveat}"
    if intent is ReadInvestigationIntent.NETWORK_PEERING and records:
        rendered = "; ".join(_render_peering(record.details, record.status) for record in records)
        caveat = (
            " 반대편 VNet과 effective route를 확인하지 않은 연결은 단방향 증거입니다."
            if korean
            else (
                " A connection not verified from the remote VNet and effective routes "
                "is one-sided evidence."
            )
        )
        prefix = "피어링" if korean else "peerings"
        return f"{resource_name} {prefix}: {rendered}.{caveat}"
    if intent is ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY and latest_change_only:
        successful_changes = sorted(
            (
                record
                for record in records
                if record.status == "succeeded" and record.operation_kind is not None
            ),
            key=lambda record: record.occurred_at,
            reverse=True,
        )
        if successful_changes:
            latest = successful_changes[0]
            observed = latest.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            operation = latest.operation_kind or "unknown"
            actor = (
                f"{latest.actor_kind.value} ({latest.actor_ref})"
                if latest.actor_kind is not None and latest.actor_ref is not None
                else None
            )
            if korean:
                actor_label = actor or "Activity Log에서 확인되지 않은 주체"
                return (
                    f"{resource_name}의 가장 최근 성공한 변경은 {observed}의 {operation}입니다. "
                    f"호출 주체는 {actor_label}입니다."
                )
            actor_label = actor or "a caller not present in the Activity Log evidence"
            return (
                f"The most recent successful change for {resource_name} was {operation} at "
                f"{observed}. The caller was {actor_label}."
            )
        return (
            f"최근 30일 Azure Activity Log에서 {resource_name}의 성공한 변경을 찾지 못했습니다."
            if korean
            else (
                f"No successful change for {resource_name} was found in the last 30 days of "
                "Azure Activity Log."
            )
        )
    if intent in {
        ReadInvestigationIntent.CHANGE_ATTRIBUTION,
        ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY,
    }:
        successful_stops = sorted(
            (
                record
                for record in records
                if record.status == "succeeded"
                and record.operation_kind in {"stop", "deallocate", "power_off"}
            ),
            key=lambda record: record.occurred_at,
            reverse=True,
        )
        if successful_stops:
            latest = successful_stops[0]
            observed = latest.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            operation = latest.operation_kind or "stop"
            actor = (
                f"{latest.actor_kind.value} ({latest.actor_ref})"
                if latest.actor_kind is not None and latest.actor_ref is not None
                else None
            )
            if korean:
                actor_sentence = (
                    f" 호출 주체는 {actor}입니다."
                    if actor is not None
                    else " 호출 주체는 Activity Log에서 확인되지 않았습니다."
                )
                return (
                    f"{resource_name}의 최근 성공한 중지 작업은 {observed}에 Azure Activity Log에 "
                    f"기록되었습니다. 작업 종류는 {operation}입니다.{actor_sentence} "
                    "현재 중지 상태는 적어도 이 "
                    "시점부터 이어진 것으로 확인됩니다."
                )
            actor_sentence = (
                f" The caller was {actor}."
                if actor is not None
                else " The caller was not present in the Activity Log evidence."
            )
            return (
                f"The latest successful stop for {resource_name} was recorded in Azure Activity "
                f"Log at {observed}. The operation was {operation}.{actor_sentence} "
                "The current stopped state is "
                "confirmed from at least that time."
            )
        if korean:
            return (
                f"최근 30일 Azure Activity Log에서 {resource_name}의 성공한 중지 작업을 "
                "찾지 못해 시작 시각을 확정할 수 없습니다."
            )
        return (
            f"No successful stop operation for {resource_name} was found in the last 30 days of "
            "Azure Activity Log, so the start time is unconfirmed."
        )
    return f"Read investigation for {resource_name}: {outcome}; evidence sources={len(evidence)}."


def _render_nsg_rule(details: tuple[tuple[str, str], ...]) -> str:
    values = dict(details)
    return (
        f"{values.get('protocol', 'unknown').upper()} "
        f"{values.get('destination_ports', 'unknown')} from "
        f"{values.get('source_prefixes', 'unknown')} "
        f"(priority {values.get('priority', 'unknown')}, "
        f"rule {values.get('rule_name', 'unknown')})"
    )


def _render_peering(details: tuple[tuple[str, str], ...], status: str) -> str:
    values = dict(details)
    return (
        f"{values.get('peering_name', 'unknown')} -> {values.get('remote_vnet', 'unknown')} "
        f"[{status}, sync={values.get('sync_level', 'unknown')}, "
        f"access={values.get('allow_vnet_access', 'unknown')}, "
        f"forwarded={values.get('allow_forwarded_traffic', 'unknown')}, "
        f"gateway-transit={values.get('allow_gateway_transit', 'unknown')}, "
        f"remote-gateway={values.get('use_remote_gateways', 'unknown')}]"
    )


def _is_korean(value: str) -> bool:
    return any("가" <= character <= "힣" for character in value)


class HeimdallReadInvestigationChatDelegate:
    """Expose only supported read investigations to Command Deck evidence enrichment."""

    def __init__(self, *, responder: HeimdallReadInvestigationResponder) -> None:
        self._responder = responder
        self._bragi = Bragi()
        heimdall = Heimdall(read_investigation_hook=responder)
        self._bragi.register_responder("Heimdall", heimdall.on_conversation_turn)

    async def delegate(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, object] | None:
        preincident = parse_preincident_activity(prompt)
        if preincident is not None:
            result = await self._responder(
                prompt,
                {"user_id": user_id, "session_id": session_id},
            )
            if result is None:
                return None
            answer = result.get("answer")
            facts = result.get("facts")
            if not isinstance(answer, str) or not isinstance(facts, dict):
                return None
            return {
                "primary_agent": "Heimdall",
                "answer": answer,
                "facts": facts,
                "contributors": [],
                "contributor_answers": [],
                "trace_ref": "read-investigation",
            }
        if classify_read_investigation_intent(prompt) is None:
            return None
        scoped_session = hashlib.sha256(f"{user_id}:{session_id}".encode()).hexdigest()
        turn = await self._bragi.ask(
            session_id=f"read:sha256:{scoped_session}",
            user_id=user_id,
            question=prompt,
            allow_action_proposal=False,
        )
        if turn is None or turn.primary_agent != "Heimdall":
            return None
        answer = turn.answer.get("answer")
        facts = turn.answer.get("facts")
        if not isinstance(answer, str) or not isinstance(facts, dict):
            return None
        return {
            "primary_agent": "Heimdall",
            "answer": answer,
            "facts": facts,
            "contributors": [],
            "contributor_answers": [],
            "trace_ref": str(turn.answer.get("trace_ref") or "read-investigation")[:256],
        }

    async def delegate_with_progress(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
        progress_observer: Callable[[Mapping[str, object]], Awaitable[None]],
    ) -> dict[str, object] | None:
        if parse_preincident_activity(prompt) is not None:
            return await self.delegate(prompt=prompt, user_id=user_id, session_id=session_id)
        intent = classify_read_investigation_intent(prompt)
        resource_name = resource_name_from_question(prompt)
        if intent is None or resource_name is None:
            return await self.delegate(prompt=prompt, user_id=user_id, session_id=session_id)
        korean = _is_korean(prompt)
        started_at = datetime.now(UTC)
        started = time.monotonic()

        await progress_observer(
            {
                "event": "milestone",
                "message_id": "handoff-bragi-heimdall",
                "text": (
                    "@Heimdall, 이 리소스의 읽기 전용 상태 근거를 확인해 주세요."
                    if korean
                    else "@Heimdall, please inspect the read-only state evidence for this resource."
                ),
                "agent": "Bragi",
            }
        )

        async def observe(kind: ReadInvestigationProgressKind) -> None:
            for event in _progress_events(kind, korean=korean):
                await progress_observer(event)

        result = await self._responder(
            prompt,
            {"user_id": user_id, "session_id": session_id},
            progress_observer=observe,
        )
        if result is None:
            return None
        facts = result.get("facts")
        execution = _read_execution_activity(
            intent=intent,
            facts=facts if isinstance(facts, Mapping) else {},
            started_at=started_at,
            duration_ms=max(0, round((time.monotonic() - started) * 1_000)),
            korean=korean,
        )
        await progress_observer(_execution_progress_event(execution))
        return {
            "primary_agent": "Heimdall",
            "answer": result["answer"],
            "facts": result["facts"],
            "contributors": [],
            "contributor_answers": [],
            "trace_ref": "read-investigation",
        }


_PROGRESS_ACTIVITY: dict[
    ReadInvestigationProgressKind,
    tuple[str, str, str],
] = {
    ReadInvestigationProgressKind.PLANNED: (
        "plan",
        "completed",
        "Investigation planned",
    ),
    ReadInvestigationProgressKind.RESOURCE_RESOLVING: (
        "resource",
        "running",
        "Resolving resource",
    ),
    ReadInvestigationProgressKind.RESOURCE_RESOLVED: (
        "resource",
        "completed",
        "Resource resolved",
    ),
    ReadInvestigationProgressKind.RESOURCE_NOT_FOUND: (
        "resource",
        "unavailable",
        "Resource not found",
    ),
    ReadInvestigationProgressKind.RESOURCE_AMBIGUOUS: (
        "resource",
        "unavailable",
        "Resource is ambiguous",
    ),
    ReadInvestigationProgressKind.RESOURCE_UNAVAILABLE: (
        "resource",
        "unavailable",
        "Resource lookup unavailable",
    ),
    ReadInvestigationProgressKind.STATE_QUERYING: (
        "state",
        "running",
        "Checking resource state",
    ),
    ReadInvestigationProgressKind.STATE_COMPLETED: (
        "state",
        "completed",
        "Resource state checked",
    ),
    ReadInvestigationProgressKind.STATE_UNAVAILABLE: (
        "state",
        "unavailable",
        "Resource state unavailable",
    ),
    ReadInvestigationProgressKind.ACTIVITY_QUERYING: (
        "activity-log",
        "running",
        "Checking Activity Log",
    ),
    ReadInvestigationProgressKind.ACTIVITY_COMPLETED: (
        "activity-log",
        "completed",
        "Activity Log checked",
    ),
    ReadInvestigationProgressKind.ACTIVITY_UNAVAILABLE: (
        "activity-log",
        "unavailable",
        "Activity Log unavailable",
    ),
    ReadInvestigationProgressKind.HEALTH_QUERYING: (
        "resource-health",
        "running",
        "Checking Resource Health",
    ),
    ReadInvestigationProgressKind.HEALTH_COMPLETED: (
        "resource-health",
        "completed",
        "Resource Health checked",
    ),
    ReadInvestigationProgressKind.HEALTH_UNAVAILABLE: (
        "resource-health",
        "unavailable",
        "Resource Health unavailable",
    ),
    ReadInvestigationProgressKind.GUEST_QUERYING: (
        "guest-log",
        "running",
        "Checking guest shutdown logs",
    ),
    ReadInvestigationProgressKind.GUEST_COMPLETED: (
        "guest-log",
        "completed",
        "Guest shutdown logs checked",
    ),
    ReadInvestigationProgressKind.GUEST_UNAVAILABLE: (
        "guest-log",
        "unavailable",
        "Guest shutdown logs unavailable",
    ),
    ReadInvestigationProgressKind.NETWORK_SECURITY_QUERYING: (
        "network-security",
        "running",
        "Checking network security",
    ),
    ReadInvestigationProgressKind.NETWORK_SECURITY_COMPLETED: (
        "network-security",
        "completed",
        "Network security checked",
    ),
    ReadInvestigationProgressKind.NETWORK_SECURITY_UNAVAILABLE: (
        "network-security",
        "unavailable",
        "Network security unavailable",
    ),
    ReadInvestigationProgressKind.NETWORK_PEERING_QUERYING: (
        "network-peering",
        "running",
        "Checking network peerings",
    ),
    ReadInvestigationProgressKind.NETWORK_PEERING_COMPLETED: (
        "network-peering",
        "completed",
        "Network peerings checked",
    ),
    ReadInvestigationProgressKind.NETWORK_PEERING_UNAVAILABLE: (
        "network-peering",
        "unavailable",
        "Network peerings unavailable",
    ),
    ReadInvestigationProgressKind.EVIDENCE_CORRELATING: (
        "correlation",
        "running",
        "Correlating evidence",
    ),
    ReadInvestigationProgressKind.DELAYED: (
        "delay",
        "running",
        "Investigation is taking longer than estimated",
    ),
    ReadInvestigationProgressKind.COMPLETED: (
        "correlation",
        "completed",
        "Investigation completed",
    ),
}


def _progress_events(
    kind: ReadInvestigationProgressKind,
    *,
    korean: bool,
) -> tuple[dict[str, object], ...]:
    activity_id, status, label = _PROGRESS_ACTIVITY[kind]
    localized_label = _korean_progress_label(kind) if korean else label
    events: list[dict[str, object]] = [
        {
            "event": "activity",
            "activity_id": activity_id,
            "kind": kind.value,
            "status": status,
            "label": localized_label,
            "detail": "<redacted-resource>",
            "completed": None,
            "total": None,
            "agent": "Heimdall",
        }
    ]
    if kind is ReadInvestigationProgressKind.RESOURCE_RESOLVED:
        events.append(
            {
                "event": "milestone",
                "message_id": "resource-resolved",
                "text": (
                    "대상 리소스를 확인했습니다. 관련 근거를 병렬로 조회합니다."
                    if korean
                    else (
                        "Resolved the target resource. I am checking its evidence sources "
                        "in parallel."
                    )
                ),
                "agent": "Bragi",
            }
        )
    if kind is ReadInvestigationProgressKind.EVIDENCE_CORRELATING:
        events.append(
            {
                "event": "milestone",
                "message_id": "evidence-correlating",
                "text": (
                    "근거 수집을 마쳤습니다. 결과와 누락된 출처를 함께 정리합니다."
                    if korean
                    else "Evidence collection finished. I am correlating results and gaps."
                ),
                "agent": "Bragi",
            }
        )
    return tuple(events)


def _read_execution_activity(
    *,
    intent: ReadInvestigationIntent,
    facts: Mapping[str, object],
    started_at: datetime,
    duration_ms: int,
    korean: bool,
) -> ObservedExecutionActivity:
    raw_status = facts.get("status")
    evidence_status = (
        str(raw_status)
        if raw_status in {"matched", "ambiguous", "none", "unavailable"}
        else "unavailable"
    )
    execution_status = (
        ConversationExecutionStatus.UNAVAILABLE
        if evidence_status == "unavailable"
        else ConversationExecutionStatus.COMPLETED
    )
    evidence_refs = facts.get("evidence_refs")
    evidence_ref_count = len(evidence_refs) if isinstance(evidence_refs, (list, tuple)) else 0
    completed_at = datetime.now(UTC)
    return ObservedExecutionActivity(
        agent="Heimdall",
        label="읽기 조사 근거 확인" if korean else "Inspect read investigation evidence",
        tool="FDAI read investigation",
        command=json.dumps(
            {
                "operation": "read_investigation",
                "intent": intent.value,
                "resource": "<redacted>",
            },
            indent=2,
            sort_keys=True,
        ),
        status=execution_status,
        redacted=True,
        input_kind="query",
        output=json.dumps(
            {"evidence_ref_count": evidence_ref_count, "status": evidence_status},
            sort_keys=True,
            separators=(",", ":"),
        ),
        exit_code=None,
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat(),
        duration_ms=duration_ms,
        authority="server_read_model",
    )


def _execution_progress_event(activity: ObservedExecutionActivity) -> dict[str, object]:
    return {
        "event": "activity",
        "activity_id": "read-execution",
        "kind": "read.execution",
        "status": activity.status.value,
        "label": activity.label,
        "completed": 1,
        "total": 1,
        "agent": activity.agent,
        "authority": activity.authority,
        "observed_at": activity.completed_at,
        "execution": {
            "tool": activity.tool,
            "command": activity.command,
            "input_kind": activity.input_kind,
            "redacted": activity.redacted,
            "output": activity.output,
            "output_truncated": activity.output_truncated,
            "exit_code": activity.exit_code,
            "started_at": activity.started_at,
            "completed_at": activity.completed_at,
            "duration_ms": activity.duration_ms,
        },
    }


def _korean_progress_label(kind: ReadInvestigationProgressKind) -> str:
    labels = {
        ReadInvestigationProgressKind.PLANNED: "조사 계획 완료",
        ReadInvestigationProgressKind.RESOURCE_RESOLVING: "리소스 확인 중",
        ReadInvestigationProgressKind.RESOURCE_RESOLVED: "리소스 확인 완료",
        ReadInvestigationProgressKind.RESOURCE_NOT_FOUND: "리소스를 찾을 수 없음",
        ReadInvestigationProgressKind.RESOURCE_AMBIGUOUS: "리소스를 하나로 특정할 수 없음",
        ReadInvestigationProgressKind.RESOURCE_UNAVAILABLE: "리소스 조회 불가",
        ReadInvestigationProgressKind.STATE_QUERYING: "리소스 상태 확인 중",
        ReadInvestigationProgressKind.STATE_COMPLETED: "리소스 상태 확인 완료",
        ReadInvestigationProgressKind.STATE_UNAVAILABLE: "리소스 상태 조회 불가",
        ReadInvestigationProgressKind.ACTIVITY_QUERYING: "Activity Log 확인 중",
        ReadInvestigationProgressKind.ACTIVITY_COMPLETED: "Activity Log 확인 완료",
        ReadInvestigationProgressKind.ACTIVITY_UNAVAILABLE: "Activity Log 조회 불가",
        ReadInvestigationProgressKind.HEALTH_QUERYING: "Resource Health 확인 중",
        ReadInvestigationProgressKind.HEALTH_COMPLETED: "Resource Health 확인 완료",
        ReadInvestigationProgressKind.HEALTH_UNAVAILABLE: "Resource Health 조회 불가",
        ReadInvestigationProgressKind.GUEST_QUERYING: "게스트 종료 로그 확인 중",
        ReadInvestigationProgressKind.GUEST_COMPLETED: "게스트 종료 로그 확인 완료",
        ReadInvestigationProgressKind.GUEST_UNAVAILABLE: "게스트 종료 로그 조회 불가",
        ReadInvestigationProgressKind.NETWORK_SECURITY_QUERYING: "네트워크 보안 확인 중",
        ReadInvestigationProgressKind.NETWORK_SECURITY_COMPLETED: "네트워크 보안 확인 완료",
        ReadInvestigationProgressKind.NETWORK_SECURITY_UNAVAILABLE: "네트워크 보안 조회 불가",
        ReadInvestigationProgressKind.NETWORK_PEERING_QUERYING: "네트워크 피어링 확인 중",
        ReadInvestigationProgressKind.NETWORK_PEERING_COMPLETED: "네트워크 피어링 확인 완료",
        ReadInvestigationProgressKind.NETWORK_PEERING_UNAVAILABLE: "네트워크 피어링 조회 불가",
        ReadInvestigationProgressKind.EVIDENCE_CORRELATING: "근거 상관분석 중",
        ReadInvestigationProgressKind.DELAYED: "예상보다 조사가 오래 걸리는 중",
        ReadInvestigationProgressKind.COMPLETED: "조사 완료",
    }
    return labels[kind]


__all__ = [
    "HeimdallReadInvestigationChatDelegate",
    "HeimdallReadInvestigationResponder",
]
