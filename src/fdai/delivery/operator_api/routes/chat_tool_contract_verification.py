"""Deterministic verification handlers for tool and catalog evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fdai.delivery.operator_api.routes.chat_action_context import (
    action_context_evidence_refs,
    render_action_context_answer,
)
from fdai.delivery.operator_api.routes.chat_conversation_context import (
    conversation_context_evidence_refs,
    render_conversation_context_answer,
)
from fdai.delivery.operator_api.routes.chat_current_time import (
    current_time_evidence_refs,
    render_current_time_answer,
)
from fdai.delivery.operator_api.routes.chat_data_sources import (
    read_source_evidence_refs,
    render_read_source_answer,
)
from fdai.delivery.operator_api.routes.chat_detection_readiness import (
    detection_readiness_evidence_refs,
    render_detection_readiness_answer,
)
from fdai.delivery.operator_api.routes.chat_inventory import (
    inventory_evidence_refs,
    partial_inventory_findings_are_grounded,
    render_inventory_answer,
)
from fdai.delivery.operator_api.routes.chat_knowledge_context import (
    knowledge_context_evidence_refs,
    render_knowledge_context_answer,
)
from fdai.delivery.operator_api.routes.chat_llm_usage_rendering import (
    llm_usage_evidence_refs,
    render_llm_usage_answer,
)
from fdai.delivery.operator_api.routes.chat_log_query import (
    log_query_evidence_refs,
    render_log_query_answer,
)
from fdai.delivery.operator_api.routes.chat_network_reachability import (
    network_reachability_evidence_refs,
    render_network_reachability_answer,
)
from fdai.delivery.operator_api.routes.chat_prompt_ontology import (
    _render_ontology_storage_answer,
)
from fdai.delivery.operator_api.routes.chat_subscription_health import (
    render_subscription_health_answer,
    render_subscription_scope_answer,
    requested_subscription_health_findings_are_grounded,
    subscription_health_evidence_refs,
    subscription_scope_evidence_refs,
)
from fdai.delivery.operator_api.routes.chat_t2_recovery import (
    render_t2_recovery_answer,
    t2_recovery_evidence_refs,
)
from fdai.delivery.operator_api.routes.chat_tools import (
    read_model_evidence_refs,
    render_read_model_answer,
)
from fdai.delivery.operator_api.routes.chat_verification_result import (
    VerificationPayload,
    VerificationStatus,
)

Changed = Callable[[str, str], VerificationStatus]


def verify_tool_contract(
    provisional: str,
    view_context: Mapping[str, Any],
    *,
    locale: str | None,
    changed: Changed,
) -> VerificationPayload | None:
    """Verify one supported tool or ontology contract, if present."""

    ontology_storage = view_context.get("_ontology_storage_contract")
    if isinstance(ontology_storage, Mapping):
        ontology_answer = _render_ontology_storage_answer(ontology_storage, locale=locale)
        evidence_ref = ontology_storage.get("evidence_ref")
        if ontology_answer is None or not isinstance(evidence_ref, str):
            return VerificationPayload(
                status="unverified",
                answer="Ontology catalog storage evidence could not be rendered.",
                authority="ontology_catalog",
                checks_completed=0,
                checks_total=1,
                reason_code="ontology_storage_evidence_invalid",
            )
        return VerificationPayload(
            status=changed(provisional, ontology_answer),
            answer=ontology_answer,
            authority="ontology_catalog",
            checks_completed=1,
            checks_total=1,
            evidence_refs=(evidence_ref,),
            reason_code="ontology_storage_contract",
        )

    tool = view_context.get("_tool_evidence")
    if not isinstance(tool, Mapping):
        return None

    tool_name = tool.get("tool")
    if tool_name == "query_t2_recovery":
        recovery_answer = render_t2_recovery_answer(tool, locale=locale)
        recovery_refs = t2_recovery_evidence_refs(tool)
        if recovery_answer is None:
            return VerificationPayload(
                status="unverified",
                answer="T2 proposer recovery evidence could not be rendered.",
                authority="server_t2_recovery_ledger",
                checks_completed=0,
                checks_total=1,
                reason_code="t2_recovery_evidence_invalid",
            )
        return VerificationPayload(
            status=changed(provisional, recovery_answer),
            answer=recovery_answer,
            authority="server_t2_recovery_ledger",
            checks_completed=len(recovery_refs),
            checks_total=len(recovery_refs),
            evidence_refs=recovery_refs,
            reason_code=("t2_recovery_grounded" if recovery_refs else "t2_recovery_not_observed"),
        )

    if tool_name == "get_current_time":
        time_answer = render_current_time_answer(tool, locale=locale)
        if time_answer is None:
            return VerificationPayload(
                status="unverified",
                answer="Server-clock evidence could not be rendered.",
                authority="server_clock",
                checks_completed=0,
                checks_total=1,
                reason_code="current_time_evidence_invalid",
            )
        return VerificationPayload(
            status=changed(provisional, time_answer),
            answer=time_answer,
            authority="server_clock",
            checks_completed=1,
            checks_total=1,
            evidence_refs=current_time_evidence_refs(tool),
            reason_code="current_time_grounded",
        )

    if tool_name == "query_action_context":
        action_answer = render_action_context_answer(tool, locale=locale)
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        action_refs = action_context_evidence_refs(tool)
        if state == "matched" and action_answer is not None and action_refs:
            intent = result.get("intent") if isinstance(result, Mapping) else None
            return VerificationPayload(
                status=changed(provisional, action_answer),
                answer=action_answer,
                authority="server_action_context",
                checks_completed=1,
                checks_total=1,
                evidence_refs=action_refs,
                reason_code=f"action_{intent}_grounded",
            )
        return VerificationPayload(
            status="unverified",
            answer=action_answer or "Exact governed action context is required.",
            authority="server_action_context",
            checks_completed=0,
            checks_total=1,
            reason_code="exact_action_context_required",
        )

    if tool_name in {"get_kpi", "list_hil", "list_incidents", "query_audit"}:
        read_answer = render_read_model_answer(tool, locale=locale)
        read_refs = read_model_evidence_refs(tool)
        if read_answer is None or not read_refs:
            return VerificationPayload(
                status="unverified",
                answer="Server read-model evidence could not be rendered.",
                authority="server_read_model",
                checks_completed=0,
                checks_total=1,
                reason_code="read_model_evidence_invalid",
            )
        return VerificationPayload(
            status=changed(provisional, read_answer),
            answer=read_answer,
            authority="server_read_model",
            checks_completed=1,
            checks_total=1,
            evidence_refs=read_refs,
            reason_code=f"read_model_{tool_name}_grounded",
        )

    if tool_name == "query_conversation_context":
        context_answer = render_conversation_context_answer(tool, locale=locale)
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        context_refs = conversation_context_evidence_refs(tool)
        if state == "matched" and context_answer is not None:
            return VerificationPayload(
                status=changed(provisional, context_answer),
                answer=context_answer,
                authority="server_conversation_context",
                checks_completed=1,
                checks_total=1,
                evidence_refs=context_refs,
                reason_code="prior_context_grounded",
            )
        return VerificationPayload(
            status="unverified",
            answer=context_answer or "Verified prior conversation context is required.",
            authority="server_conversation_context",
            checks_completed=0,
            checks_total=1,
            reason_code="prior_context_required",
        )

    if tool_name == "query_llm_usage":
        answer_plan = view_context.get("_answer_plan")
        usage_format = (
            str(answer_plan.get("format")) if isinstance(answer_plan, Mapping) else "prose"
        )
        usage_answer = render_llm_usage_answer(
            tool,
            locale=locale,
            answer_format=usage_format,
        )
        usage_refs = llm_usage_evidence_refs(tool)
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        if usage_answer is None or state not in {"matched", "none"} or not usage_refs:
            return VerificationPayload(
                status="unverified",
                answer="Measured LLM usage evidence could not be rendered.",
                authority="server_metering",
                checks_completed=0,
                checks_total=1,
                evidence_refs=usage_refs,
                reason_code="llm_usage_evidence_invalid",
            )
        return VerificationPayload(
            status=changed(provisional, usage_answer),
            answer=usage_answer,
            authority="server_metering",
            checks_completed=1,
            checks_total=1,
            evidence_refs=usage_refs,
            reason_code="llm_usage_grounded",
        )

    if tool_name == "query_knowledge_context":
        knowledge_answer = render_knowledge_context_answer(tool, locale=locale)
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        knowledge_refs = knowledge_context_evidence_refs(tool)
        if state in {"matched", "empty"} and knowledge_answer is not None and knowledge_refs:
            intent = result.get("intent") if isinstance(result, Mapping) else None
            return VerificationPayload(
                status=changed(provisional, knowledge_answer),
                answer=knowledge_answer,
                authority="server_knowledge_context",
                checks_completed=1,
                checks_total=1,
                evidence_refs=knowledge_refs,
                reason_code=f"knowledge_{intent}_grounded",
            )
        return VerificationPayload(
            status="unverified",
            answer=knowledge_answer or "Knowledge context could not be verified.",
            authority="server_knowledge_context",
            checks_completed=0,
            checks_total=1,
            evidence_refs=knowledge_refs,
            reason_code="knowledge_context_unavailable",
        )

    if tool_name == "describe_read_sources":
        source_answer = render_read_source_answer(tool, locale=locale)
        if source_answer is None:
            return VerificationPayload(
                status="unverified",
                answer="Read-source manifest evidence could not be rendered.",
                authority="server_read_source_manifest",
                checks_completed=0,
                checks_total=1,
                reason_code="read_source_manifest_invalid",
            )
        source_refs = read_source_evidence_refs(tool)
        return VerificationPayload(
            status=changed(provisional, source_answer),
            answer=source_answer,
            authority="server_read_source_manifest",
            checks_completed=len(source_refs),
            checks_total=len(source_refs),
            evidence_refs=source_refs,
            reason_code="read_source_manifest_grounded",
        )

    if tool_name == "query_log":
        log_answer = render_log_query_answer(tool, locale=locale)
        if log_answer is None:
            return VerificationPayload(
                status="unverified",
                answer="Azure Monitor Logs evidence could not be rendered.",
                authority="server_log_query",
                checks_completed=0,
                checks_total=1,
                reason_code="log_query_evidence_invalid",
            )
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        log_refs = log_query_evidence_refs(tool)
        if state in {"matched", "empty"}:
            return VerificationPayload(
                status=changed(provisional, log_answer),
                answer=log_answer,
                authority="server_log_query",
                checks_completed=1,
                checks_total=1,
                evidence_refs=log_refs,
                reason_code="log_query_bounded",
            )
        return VerificationPayload(
            status="unverified",
            answer=log_answer,
            authority="server_log_query",
            checks_completed=0,
            checks_total=1,
            evidence_refs=log_refs,
            reason_code="log_query_unavailable",
        )

    if tool_name == "query_detection_readiness":
        readiness_answer = render_detection_readiness_answer(tool, locale=locale)
        if readiness_answer is None:
            return VerificationPayload(
                status="unverified",
                answer="Detection readiness evidence could not be rendered.",
                authority="server_detection_readiness",
                checks_completed=0,
                checks_total=1,
                reason_code="detection_readiness_evidence_invalid",
            )
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        readiness_refs = detection_readiness_evidence_refs(tool)
        grounded = state in {"matched", "empty"}
        return VerificationPayload(
            status=changed(provisional, readiness_answer) if grounded else "unverified",
            answer=readiness_answer,
            authority="server_detection_readiness",
            checks_completed=1 if grounded else 0,
            checks_total=1,
            evidence_refs=readiness_refs,
            reason_code=(
                "detection_readiness_snapshot_grounded"
                if grounded
                else "detection_readiness_unavailable"
            ),
        )

    if tool_name == "query_network_reachability":
        reachability_answer = render_network_reachability_answer(tool, locale=locale)
        if reachability_answer is None:
            return VerificationPayload(
                status="unverified",
                answer="Network reachability evidence could not be rendered.",
                authority="server_network_probe",
                checks_completed=0,
                checks_total=1,
                reason_code="network_reachability_evidence_invalid",
            )
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        reachability_refs = network_reachability_evidence_refs(tool)
        verified = state == "matched" and bool(reachability_refs)
        return VerificationPayload(
            status=changed(provisional, reachability_answer) if verified else "unverified",
            answer=reachability_answer,
            authority="server_network_probe",
            checks_completed=1 if verified else 0,
            checks_total=1,
            evidence_refs=reachability_refs,
            reason_code=(
                "network_reachability_active_probe_grounded"
                if verified
                else "network_reachability_probe_unavailable"
            ),
        )

    if tool_name == "query_inventory":
        plan = view_context.get("_answer_plan")
        answer_format = str(plan.get("format")) if isinstance(plan, Mapping) else None
        inventory_answer = render_inventory_answer(
            tool,
            locale=locale,
            answer_format=answer_format,
        )
        if inventory_answer is None:
            return VerificationPayload(
                status="unverified",
                answer="Azure inventory evidence could not be rendered.",
                authority="server_inventory_graph",
                checks_completed=0,
                checks_total=1,
                reason_code="inventory_evidence_invalid",
            )
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        inventory_activity = bool(
            isinstance(result, Mapping) and result.get("query_source") == "activity"
        )
        authority = "server_inventory_activity" if inventory_activity else "server_inventory_graph"
        inventory_refs = inventory_evidence_refs(tool)
        if state == "matched":
            return VerificationPayload(
                status=changed(provisional, inventory_answer),
                answer=inventory_answer,
                authority=authority,
                checks_completed=1,
                checks_total=1,
                evidence_refs=inventory_refs,
                reason_code=(
                    "inventory_activity_grounded"
                    if inventory_activity
                    else "inventory_snapshot_grounded"
                ),
            )
        if state == "partial":
            if inventory_refs and partial_inventory_findings_are_grounded(tool):
                return VerificationPayload(
                    status=changed(provisional, inventory_answer),
                    answer=inventory_answer,
                    authority=authority,
                    checks_completed=1,
                    checks_total=1,
                    evidence_refs=inventory_refs,
                    reason_code="inventory_findings_grounded_partial",
                )
            return VerificationPayload(
                status="unverified",
                answer=inventory_answer,
                authority="server_inventory_graph",
                checks_completed=1,
                checks_total=2,
                evidence_refs=inventory_refs,
                reason_code="inventory_workload_coverage_gap",
            )
        return VerificationPayload(
            status="unverified",
            answer=inventory_answer,
            authority=authority,
            checks_completed=0,
            checks_total=1,
            evidence_refs=inventory_refs,
            reason_code="inventory_evidence_unavailable",
        )

    if tool_name == "query_subscription_scope":
        scope_answer = render_subscription_scope_answer(tool, locale=locale)
        if scope_answer is None:
            return VerificationPayload(
                status="unverified",
                answer="Azure subscription scope evidence could not be rendered.",
                authority="server_subscription_scope",
                checks_completed=0,
                checks_total=1,
                reason_code="subscription_scope_evidence_invalid",
            )
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        scope_refs = subscription_scope_evidence_refs(tool)
        if state == "matched":
            return VerificationPayload(
                status=changed(provisional, scope_answer),
                answer=scope_answer,
                authority="server_subscription_scope",
                checks_completed=1,
                checks_total=1,
                evidence_refs=scope_refs,
                reason_code="subscription_scope_grounded",
            )
        return VerificationPayload(
            status="unverified",
            answer=scope_answer,
            authority="server_subscription_scope",
            checks_completed=0,
            checks_total=1,
            evidence_refs=scope_refs,
            reason_code="subscription_scope_unavailable",
        )

    if tool_name == "query_subscription_health":
        health_answer = render_subscription_health_answer(tool, locale=locale)
        if health_answer is None:
            return VerificationPayload(
                status="unverified",
                answer="Azure subscription health evidence could not be rendered.",
                authority="server_subscription_health",
                checks_completed=0,
                checks_total=1,
                reason_code="subscription_health_evidence_invalid",
            )
        result = tool.get("result")
        state = result.get("status") if isinstance(result, Mapping) else None
        health_refs = subscription_health_evidence_refs(tool)
        if state == "matched":
            return VerificationPayload(
                status=changed(provisional, health_answer),
                answer=health_answer,
                authority="server_subscription_health",
                checks_completed=1,
                checks_total=1,
                evidence_refs=health_refs,
                reason_code="subscription_health_grounded",
            )
        if state == "partial":
            if health_refs and requested_subscription_health_findings_are_grounded(tool):
                return VerificationPayload(
                    status=changed(provisional, health_answer),
                    answer=health_answer,
                    authority="server_subscription_health",
                    checks_completed=1,
                    checks_total=1,
                    evidence_refs=health_refs,
                    reason_code="subscription_health_findings_grounded_partial",
                )
            return VerificationPayload(
                status="unverified",
                answer=health_answer,
                authority="server_subscription_health",
                checks_completed=0,
                checks_total=1,
                evidence_refs=health_refs,
                reason_code="subscription_health_partial",
            )
        return VerificationPayload(
            status="unverified",
            answer=health_answer,
            authority="server_subscription_health",
            checks_completed=0,
            checks_total=1,
            evidence_refs=health_refs,
            reason_code="subscription_health_unavailable",
        )

    return None
