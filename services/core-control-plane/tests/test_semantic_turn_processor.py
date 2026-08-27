"""Focused Core semantic-turn v1.2 processor and lifecycle tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from typing import Any, cast

import pytest
from fdai.core.conversation.semantic_investigation import InvestigationEntityRole
from fdai.core.conversation.semantic_judgment import SemanticJudgmentObservation
from fdai.core.conversation.semantic_planning_cascade import (
    NO_T2_ESCALATION_POLICY,
    SemanticPlanningEscalationPolicy,
)
from fdai.core.conversation.semantic_planning_models import (
    BoundIncident,
    BoundInvestigationContinuation,
)
from fdai.core.conversation.semantic_runtime import (
    SemanticTurnResult as RuntimeSemanticTurnResult,
)
from fdai.core.conversation.session import Principal, Role, Turn
from fdai.core.ontology_platform import (
    CausalEvidenceJoin,
    CausalJoinStatus,
    MetricWindow,
    MetricWindowComparison,
    QueryNodeResult,
    QueryPlanExecution,
    TopologyDiff,
    TopologyGraphAt,
)
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.rule_catalog.schema.rule_semantic_generation import (
    CatalogRetrievalReceipt,
    RetrievalOperation,
    RetrievalRank,
    SemanticAvailability,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_core_service.semantic_turn_consumer import (
    StateStoreSemanticTurnResultStore,
    consume_semantic_turns,
    semantic_turn_binding_from_config,
)
from fdai_core_service.semantic_turn_processor import (
    SemanticTurnProcessor,
    SemanticTurnRejectedError,
    _answer_row_values,
    _incident_next_step_text,
    _project_investigation_continuation,
    _render_general_query_answer,
    _render_query_answer,
    _typed_extension_answer_output,
    incident_next_step_actions,
    incident_profile_facts,
    incident_timeline_rows,
)
from fdai_service_contracts import (
    RuleSearchReceipt,
    SemanticDirectResponseIntent,
    SemanticTurnRequest,
    rule_search_query_digest,
)
from fdai_service_contracts.ontology_query import (
    GoalEvidenceMode,
    GoalTaskReceipt,
    SemanticOperation,
    TaskStatus,
)

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
RELEASE_DIGEST = "sha256:" + ("a" * 64)
MANIFEST_DIGEST = "sha256:" + ("b" * 64)
PLAN_DIGEST = "sha256:" + ("c" * 64)
GENERATION_DIGEST = "sha256:" + ("d" * 64)
RULE_QUERY = {
    "query": "zone resilience",
    "operation": "discover",
    "corpus": "active",
    "limit": 10,
}
RULE_QUERY_DIGEST = (
    "sha256:"
    + hashlib.sha256(
        json.dumps(RULE_QUERY, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
)


def test_answer_row_values_lifts_display_fields_without_provider_payloads() -> None:
    values = {
        "id": "resource-1",
        "object_type": "Resource",
        "properties": {
            "name": "app-one",
            "type": "compute.container-app",
            "properties": {
                "location": "example-region",
                "configuration": {"ingress": {"external": True}},
            },
        },
    }

    assert _answer_row_values(values) == {
        "id": "resource-1",
        "object_type": "Resource",
        "name": "app-one",
        "type": "compute.container-app",
        "location": "example-region",
    }


def test_impact_answer_separates_observed_scope_inference_and_gaps() -> None:
    request = _request(locale="en")
    semantic_request = cast(dict[str, object], request["semantic_turn"])

    answer = _render_general_query_answer(
        SemanticTurnRequest.model_validate(semantic_request),
        [
            {
                "node_id": "impact-services",
                "rows": [],
                "returned_rows": 0,
                "total_rows": 0,
                "source_complete": True,
                "source_truncation_reason": None,
                "display_truncated": False,
            }
        ],
        output_shape="inventory_impact",
    )

    assert "Observed impacted services: 0" in answer
    assert "BusinessService -> implemented_by -> Workload" in answer
    assert "Services promoted from inference alone: 0" in answer
    assert "Zero rows do not prove zero real-world impact" in answer
    assert "`execution_authority=false`" in answer


def test_health_answer_separates_lifecycle_readiness_application_and_gaps() -> None:
    request = _request(locale="en")
    semantic_request = cast(dict[str, object], request["semantic_turn"])

    answer = _render_general_query_answer(
        SemanticTurnRequest.model_validate(semantic_request),
        [
            {
                "node_id": "target-health-assessment",
                "rows": [
                    {
                        "row_id": "target-health-assessment",
                        "values": {
                            "target": "app-example",
                            "evidence_sufficient": False,
                            "platform_lifecycle": "observed_running",
                            "readiness": "not_proven",
                            "application_service_health": "not_proven",
                            "stability": "process_stability_not_proven",
                            "resource_pressure": "cpu_observed_capacity_unknown",
                            "request_telemetry": "zero_observed_requests_not_health_proof",
                            "source_observed_at": "2026-08-21T00:09:00Z",
                            "inventory_read_at": "2026-08-21T00:10:00Z",
                            "metric_window_end": "2026-08-21T00:10:00Z",
                            "evidence_gaps": (
                                "process_restart_count_unavailable, runtime_logs_unavailable"
                            ),
                            "execution_authority": False,
                        },
                    }
                ],
                "returned_rows": 1,
                "total_rows": 1,
                "source_complete": False,
                "source_truncation_reason": "health_claim_evidence_incomplete",
                "display_truncated": False,
            }
        ],
        output_shape="target_health_assessment",
    )

    assert "insufficient to claim full application-service health" in answer
    assert "Platform lifecycle: observed running" in answer
    assert "Readiness: not proven" in answer
    assert "Application service: not proven" in answer
    assert "Zero observed requests" not in answer
    assert "zero observed requests not health proof" in answer
    assert "Source observation: 2026-08-21T00:09:00Z" in answer
    assert "process restart count unavailable" in answer
    assert "runtime logs unavailable" in answer
    assert "`execution_authority=false`" in answer


def test_pod_evidence_answer_does_not_turn_missing_recovery_into_success() -> None:
    request = _request(locale="en")
    semantic_request = cast(dict[str, object], request["semantic_turn"])

    answer = _render_general_query_answer(
        SemanticTurnRequest.model_validate(semantic_request),
        [
            {
                "node_id": "pod-recovery-evidence",
                "rows": [
                    {
                        "row_id": "pod-recovery-evidence",
                        "values": {
                            "status": "insufficient_evidence",
                            "complete": False,
                            "recovery_verified": False,
                            "evidence_gaps": ["lifecycle_cursor_unavailable"],
                            "execution_authority": False,
                        },
                    }
                ],
            }
        ],
    )

    assert "Kubernetes Pod evidence" in answer
    assert "incomplete or unverified" in answer
    assert "lifecycle cursor unavailable" in answer
    assert "`execution_authority=false`" in answer


def _current_state_outputs(
    values: dict[str, object],
    reason: str | None,
) -> list[dict[str, object]]:
    return [
        {
            "node_id": "resource-current-state",
            "rows": [{"row_id": "resource-current-state", "values": values}],
            "returned_rows": 1,
            "total_rows": 1,
            "source_complete": reason is None,
            "source_truncation_reason": reason,
            "display_truncated": False,
        }
    ]


def test_current_state_answer_reports_read_fields_unobserved_fields_and_gaps() -> None:
    request = _request(locale="en")
    semantic_request = cast(dict[str, object], request["semantic_turn"])

    answer = _render_general_query_answer(
        SemanticTurnRequest.model_validate(semantic_request),
        _current_state_outputs(
            {
                "name": "cluster-example",
                "provisioning_status": "Succeeded",
                "running_status": None,
                "revision_name": None,
                "ready_revision_name": None,
                "target_state_assessment": "observed_running",
                "assessment_scope": "exact_target_only",
                "related_resources_assessed": False,
                "source_observed_at": None,
                "inventory_read_at": "2026-08-26T08:29:23Z",
                "execution_authority": False,
            },
            "revision_name_unavailable+source_observed_at_unavailable",
        ),
        output_shape="target_current_state",
    )

    assert "Verified current state for `cluster-example`" in answer
    assert "Provisioning status: Succeeded." in answer
    assert "Running status: not observed." in answer
    assert "Ready revision: not observed." in answer
    assert "Inventory read: 2026-08-26T08:29:23Z." in answer
    assert "Source observation: not observed." in answer
    assert "revision name unavailable" in answer
    assert "source observed at unavailable" in answer
    assert "no abnormal provider lifecycle state was observed" in answer
    assert "absence of abnormal resources is not proven" in answer
    assert "does not judge whether any resource outside that scope is healthy" in answer
    assert "Provider-reported status is an observation, not a cause." in answer
    assert "`execution_authority=false`" in answer
    assert "Verified 1 of 1 rows" not in answer


def test_current_state_answer_states_a_complete_read_without_inventing_a_gap() -> None:
    request = _request(locale="en")
    semantic_request = cast(dict[str, object], request["semantic_turn"])

    answer = _render_general_query_answer(
        SemanticTurnRequest.model_validate(semantic_request),
        _current_state_outputs(
            {
                "name": "app-example",
                "provisioning_status": "Succeeded",
                "running_status": "Running",
                "revision_name": "app-example--0000002",
                "ready_revision_name": "app-example--0000002",
                "target_state_assessment": "observed_running",
                "assessment_scope": "exact_target_only",
                "related_resources_assessed": False,
                "source_observed_at": "2026-08-26T08:20:00Z",
                "inventory_read_at": "2026-08-26T08:29:23Z",
                "execution_authority": False,
            },
            None,
        ),
        output_shape="target_current_state",
    )

    assert "Running status: Running." in answer
    assert "Latest revision: app-example--0000002." in answer
    assert "not observed" not in answer
    assert "No gap was recorded for the requested current-state fields." in answer
    assert "Related nodes, workloads, and resources: not included" in answer


def test_resource_event_answer_preserves_retention_unknown_zero_rows() -> None:
    request = _request(locale="en")
    semantic_request = cast(dict[str, object], request["semantic_turn"])

    answer = _render_general_query_answer(
        SemanticTurnRequest.model_validate(semantic_request),
        [
            {
                "node_id": "resource-events",
                "rows": [],
                "returned_rows": 0,
                "total_rows": 0,
                "source_complete": False,
                "source_truncation_reason": "source_retention_unverified",
            }
        ],
        output_shape="resource_event_history",
    )

    assert "No Resource Events were returned" in answer
    assert "Source completeness: incomplete" in answer
    assert "`source_retention_unverified`" in answer
    assert "zero rows do not prove historical absence" in answer
    assert "`execution_authority=false`" in answer
    assert "Verified 0 of 0 rows" not in answer


def test_resource_event_answer_lists_observed_rows_without_causal_claims() -> None:
    request = _request(locale="ko")
    semantic_request = cast(dict[str, object], request["semantic_turn"])

    answer = _render_general_query_answer(
        SemanticTurnRequest.model_validate(semantic_request),
        [
            {
                "node_id": "resource-events",
                "rows": [
                    {
                        "row_id": "resource-event-0001",
                        "values": {
                            "name": "api-example",
                            "type": "kubernetes.deployment",
                            "event_kind": "scalingreplicaset",
                            "status": "normal",
                            "classification": "kubernetes_deployment",
                            "occurred_at": "2026-08-27T03:00:00+00:00",
                            "execution_authority": False,
                        },
                    }
                ],
                "returned_rows": 1,
                "total_rows": 1,
                "source_complete": False,
                "source_truncation_reason": "source_retention_unverified",
            }
        ],
        output_shape="resource_event_history",
    )

    assert "## 관측된 Resource Event" in answer
    assert "api-example" in answer
    assert "scalingreplicaset / normal / kubernetes_deployment" in answer
    assert "행 0개는 과거 Event 부재를 증명하지 않습니다" in answer
    assert "원인" not in answer
    assert "복구" not in answer
    assert "`execution_authority=false`" in answer


def test_resource_event_answer_discloses_latest_bounded_display() -> None:
    request = _request(locale="en")
    semantic_request = cast(dict[str, object], request["semantic_turn"])
    rows = tuple(
        QueryRow.from_values(
            f"resource-event-{index:04d}",
            {
                "name": f"event-{index:02d}",
                "type": "kubernetes.pod",
                "event_kind": "test",
                "status": "normal",
                "classification": "kubernetes_pod",
                "occurred_at": f"2026-08-27T03:{index:02d}:00+00:00",
                "execution_authority": False,
            },
        )
        for index in range(24)
    )
    execution = QueryPlanExecution(
        plan_digest=PLAN_DIGEST,
        status="completed",
        results=MappingProxyType(
            {
                "resource-events": QueryNodeResult(
                    value=QueryTable(
                        rows=rows,
                        complete=False,
                        truncation_reason="source_retention_unverified",
                    ),
                    evidence_refs=("kubernetes-resource-event:attempt",),
                )
            }
        ),
        receipts=(),
        output_node_ids=("resource-events",),
    )

    answer, _details = _render_query_answer(
        SemanticTurnRequest.model_validate(semantic_request),
        execution,
        operation="select",
        output_shape="resource_event_history",
    )

    assert answer is not None
    assert "`event-23`" in answer
    assert "`event-16`" in answer
    assert "`event-15`" not in answer
    assert "`event-00`" not in answer
    assert "Displayed Resource Events: 8 of 24." in answer
    assert "`display_truncated`" in answer
    assert "most recent 8 in chronological order" in answer


def test_error_activity_answer_separates_windows_gaps_and_causation() -> None:
    request = _request(locale="en")
    semantic_request = cast(dict[str, object], request["semantic_turn"])

    answer = _render_general_query_answer(
        SemanticTurnRequest.model_validate(semantic_request),
        [
            {
                "node_id": "target-error-activity-correlation",
                "rows": [
                    {
                        "row_id": "target-error-activity-correlation",
                        "values": {
                            "error_trend": "increased",
                            "baseline_error_total": 1.0,
                            "current_error_total": 3.0,
                            "baseline_window_start": "2026-08-20T23:10:00Z",
                            "baseline_window_end": "2026-08-20T23:40:00Z",
                            "current_window_start": "2026-08-20T23:40:00Z",
                            "current_window_end": "2026-08-21T00:10:00Z",
                            "activity_state": "changes_observed",
                            "activity_change_count": 1,
                            "correlation_assessment": ("cooccurrence_observed_not_causation"),
                            "causal_claim_supported": False,
                            "evidence_gaps": "runtime_logs_unavailable",
                            "execution_authority": False,
                        },
                    }
                ],
                "returned_rows": 1,
                "total_rows": 1,
                "source_complete": True,
                "source_truncation_reason": None,
                "display_truncated": False,
            }
        ],
        output_shape="target_error_activity_correlation",
    )

    assert "Request error trend is increased" in answer
    assert "Baseline errors: 1.0" in answer
    assert "Current errors: 3.0" in answer
    assert "Activity Log: changes observed" in answer
    assert "Baseline window start: 2026-08-20T23:10:00Z" in answer
    assert "runtime logs unavailable" in answer
    assert "does not establish causation" in answer
    assert "`execution_authority=false`" in answer


def test_causal_answer_reports_measured_change_competing_evidence_and_limits() -> None:
    request = _request(locale="ko")
    semantic_request = cast(dict[str, object], request["semantic_turn"])
    outputs = [
        {
            "node_id": "symptom-change",
            "result_kind": "metric.comparison",
            "evidence_refs": ["metric-provider:service-latency"],
            "summary": {
                "concept_id": "service.latency",
                "resource_id": "service-example-api",
                "unit": "ms",
                "baseline_start": "2026-08-20T00:00:00Z",
                "baseline_end": "2026-08-20T00:10:00Z",
                "current_start": "2026-08-20T00:10:00Z",
                "current_end": "2026-08-20T00:20:00Z",
                "baseline_value": 100,
                "current_value": 250,
                "absolute_change": 150,
                "reason": "source_stale",
            },
        },
        {
            "node_id": "hypothesis-dependency-latency",
            "result_kind": "causal.join",
            "evidence_refs": ["causal-evidence:dependency-latency"],
            "summary": {
                "hypothesis_id": "dependency-latency",
                "status": "supported",
                "limitations": [],
                "temporal_claim": {
                    "evidence_grade": "predictive_precedence",
                    "sample_count": 12,
                    "correlation": 0.82,
                    "lag_seconds": 30,
                    "falsifiers": ["reverse-ordering"],
                },
            },
        },
        {
            "node_id": "hypothesis-resource-saturation",
            "result_kind": "causal.join",
            "summary": {
                "hypothesis_id": "resource-saturation",
                "status": "refuted",
                "limitations": ["evidence_conflict"],
                "temporal_claim": {
                    "evidence_grade": "association",
                    "sample_count": 12,
                    "correlation": 0.14,
                    "lag_seconds": 0,
                    "falsifiers": ["no-saturation-change"],
                },
            },
        },
        {
            "node_id": "hypothesis-deployment-change",
            "result_kind": "causal.join",
            "summary": {
                "hypothesis_id": "deployment-change",
                "status": "unresolved",
                "limitations": ["metric_window_incomplete"],
                "temporal_claim": None,
            },
        },
        {
            "node_id": "change-activity",
            "rows": [
                {
                    "row_id": "activity-1",
                    "values": {
                        "occurred_at": "2026-08-20T00:12:00Z",
                        "operation": "microsoft_app_containerapps_write",
                        "status": "succeeded",
                        "actor_kind": "service_principal",
                        "actor_ref": "principal-example",
                        "correlation_ref": "correlation-example",
                        "evidence_refs": ["azure-activity:evidence-example"],
                        "execution_authority": False,
                    },
                }
            ],
            "returned_rows": 1,
            "total_rows": 1,
            "source_complete": True,
            "source_truncation_reason": None,
            "display_truncated": False,
        },
    ]

    answer = _render_general_query_answer(
        SemanticTurnRequest.model_validate(semantic_request),
        outputs,
    )

    assert "정확한 대상: `service-example-api`" in answer
    assert "기준 구간: 2026-08-20T00:00:00Z to 2026-08-20T00:10:00Z" in answer
    assert "현재 구간: 2026-08-20T00:10:00Z to 2026-08-20T00:20:00Z" in answer
    assert "실제 측정 변화: 150 ms" in answer
    assert "가장 강한 원인 후보: `dependency-latency`" in answer
    assert "신뢰도 근거: supported=1, refuted=1, unresolved=1" in answer
    assert "`resource-saturation` - `refuted`" in answer
    assert "`deployment-change` - `unresolved`" in answer
    assert "samples=12" in answer
    assert "falsifiers=reverse-ordering" in answer
    assert "source_stale" in answer
    assert "evidence_conflict" in answer
    assert "metric_window_incomplete" in answer
    assert "변경 및 배포 근거" in answer
    assert "microsoft_app_containerapps_write" in answer
    assert "service_principal/principal-example" in answer
    assert "azure-activity:evidence-example" in answer
    assert "metric-provider:service-latency" in answer
    assert "causal-evidence:dependency-latency" in answer
    assert "다음 안전 단계" in answer
    assert "`execution_authority=false`" in answer


def test_causal_answer_does_not_claim_unmeasured_slowdown() -> None:
    request = _request(locale="ko")
    semantic_request = cast(dict[str, object], request["semantic_turn"])
    outputs = [
        {
            "node_id": "symptom-change",
            "result_kind": "metric.comparison",
            "evidence_refs": ["metric-provider-unavailable:service.latency"],
            "summary": {
                "concept_id": "service.latency",
                "resource_id": "service-example-api",
                "unit": "ms",
                "baseline_start": "2026-08-20T00:00:00Z",
                "baseline_end": "2026-08-20T00:10:00Z",
                "current_start": "2026-08-20T00:10:00Z",
                "current_end": "2026-08-20T00:20:00Z",
                "baseline_value": None,
                "current_value": None,
                "absolute_change": None,
                "complete": False,
                "reason": "provider_unavailable",
            },
        },
        {
            "node_id": "hypothesis-dependency-latency",
            "result_kind": "causal.join",
            "evidence_refs": [],
            "summary": {
                "hypothesis_id": "dependency-latency",
                "status": "unresolved",
                "limitations": ["metric_window_incomplete"],
                "temporal_claim": None,
            },
        },
        {
            "node_id": "hypothesis-resource-saturation",
            "result_kind": "causal.join",
            "evidence_refs": ["metric-provider:resource.saturation"],
            "summary": {
                "hypothesis_id": "resource-saturation",
                "status": "unresolved",
                "limitations": ["effect_window_incomplete"],
                "temporal_claim": None,
            },
        },
    ]

    answer = _render_general_query_answer(
        SemanticTurnRequest.model_validate(semantic_request),
        outputs,
    )

    assert "요청된 증상 방향: `service.latency` 증가; 측정 근거: unavailable" in answer
    assert "검증된 증상: `service.latency` 증가" not in answer
    assert "실제 측정 변화: unavailable ms" in answer
    assert "request 및 dependency duration telemetry" in answer
    assert "metric-provider:resource.saturation" in answer
    assert "`execution_authority=false`" in answer


@pytest.mark.parametrize(
    ("value", "result_kind"),
    (
        (
            TopologyGraphAt(
                as_of=NOW,
                known_at=NOW,
                graph=OntologyGraphSnapshot(),
                complete=True,
                revision_ids=("revision-1",),
                provider_generation_refs=("generation-1",),
                evidence_refs=("topology:evidence-1",),
                digest=RELEASE_DIGEST,
            ),
            "topology.graph",
        ),
        (
            TopologyDiff(
                before_digest=MANIFEST_DIGEST,
                after_digest=RELEASE_DIGEST,
                added_object_ids=("resource-1",),
                removed_object_ids=(),
                changed_object_ids=(),
                added_link_keys=(),
                removed_link_keys=(),
                changed_link_keys=(),
                complete=True,
                evidence_refs=("topology:evidence-1",),
                digest=PLAN_DIGEST,
            ),
            "topology.diff",
        ),
        (
            MetricWindow(
                concept_id="request_count",
                resource_id="resource-1",
                unit="count",
                start=NOW - timedelta(minutes=5),
                end=NOW,
                samples=(),
                complete=True,
                evidence_refs=("metric:evidence-1",),
            ),
            "metric.window",
        ),
        (
            MetricWindowComparison(
                concept_id="service.latency",
                resource_id="service:a",
                unit="ms",
                baseline_start=NOW - timedelta(minutes=10),
                baseline_end=NOW - timedelta(minutes=5),
                current_start=NOW - timedelta(minutes=5),
                current_end=NOW,
                baseline_value=10.0,
                current_value=25.0,
                absolute_change=15.0,
                relative_change=1.5,
                complete=True,
                reason=None,
                evidence_refs=("metric:evidence-1",),
            ),
            "metric.comparison",
        ),
        (
            CausalEvidenceJoin(
                status=CausalJoinStatus.UNRESOLVED,
                temporal_claim=None,
                topology_diff_digest=None,
                competing_explanations=("credential_change",),
                limitations=("metric_window_incomplete",),
                evidence_refs=("metric:evidence-1",),
            ),
            "causal.join",
        ),
    ),
)
def test_typed_extension_answer_output_is_bounded_and_authority_free(
    value: object,
    result_kind: str,
) -> None:
    output = _typed_extension_answer_output("result", value)

    assert output is not None
    assert output["result_kind"] == result_kind
    assert output["summary"]["execution_authority"] is False
    assert "evidence_refs" not in output["summary"]


class _Runtime:
    def __init__(
        self,
        result: RuntimeSemanticTurnResult | None = None,
        *,
        failure: Exception | None = None,
        wait_for_cancel: bool = False,
    ) -> None:
        self.result = result or _runtime_result("held")
        self.failure = failure
        self.wait_for_cancel = wait_for_cancel
        self.calls = 0
        self.principals: list[Principal] = []
        self.prior_turns: tuple[Turn, ...] = ()
        self.bound_incidents: list[BoundIncident | None] = []
        self.bound_investigation_continuations: list[BoundInvestigationContinuation | None] = []
        self.escalation_policies: list[SemanticPlanningEscalationPolicy | None] = []

    async def handle(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        cancelled: asyncio.Event | None = None,
        bound_incident: BoundIncident | None = None,
        bound_investigation_continuation: BoundInvestigationContinuation | None = None,
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
    ) -> RuntimeSemanticTurnResult:
        assert utterance == "Show current operations evidence."
        self.calls += 1
        self.principals.append(principal)
        self.prior_turns = prior_turns
        self.bound_incidents.append(bound_incident)
        self.bound_investigation_continuations.append(bound_investigation_continuation)
        self.escalation_policies.append(escalation_policy)
        if self.failure is not None:
            raise self.failure
        if self.wait_for_cancel:
            assert cancelled is not None
            await cancelled.wait()
            return _runtime_result("cancelled")
        return self.result


class _ContendedRuntime(_Runtime):
    def __init__(self) -> None:
        super().__init__(_runtime_result("answered"))
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def handle(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        cancelled: asyncio.Event | None = None,
        bound_incident: BoundIncident | None = None,
        bound_investigation_continuation: BoundInvestigationContinuation | None = None,
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
    ) -> RuntimeSemanticTurnResult:
        self.calls += 1
        self.principals.append(principal)
        self.prior_turns = prior_turns
        self.bound_incidents.append(bound_incident)
        self.bound_investigation_continuations.append(bound_investigation_continuation)
        self.escalation_policies.append(escalation_policy)
        self.entered.set()
        await self.release.wait()
        return self.result


class _BlockingResultStore:
    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def get(self, idempotency_key: str) -> bytes | None:
        self.entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def claim(self, idempotency_key: str, request_digest: str) -> str | None:
        raise AssertionError("blocked get MUST prevent claim")

    async def release(
        self,
        idempotency_key: str,
        request_digest: str,
        claim_id: str,
    ) -> bool:
        raise AssertionError("blocked get MUST prevent release")

    async def put_if_absent(self, idempotency_key: str, projection: bytes) -> bool:
        raise AssertionError("blocked get MUST prevent put")


def _request(
    *,
    roles: list[str] | None = None,
    purpose: str = "operations-review",
    deadline_at: datetime | None = None,
    cancelled: bool = False,
    idempotency_key: str = "semantic-turn-1",
    prior_turns: list[dict[str, str]] | None = None,
    bound_context: dict[str, str] | None = None,
    investigation_continuation: dict[str, object] | None = None,
    locale: str = "en",
    planning_profile: str = "interactive",
    include_model_trace: bool = False,
) -> dict[str, object]:
    semantic_turn: dict[str, object] = {
        "utterance": "Show current operations evidence.",
        "principal": {
            "subject_id": "operator-1",
            "roles": roles or ["Reader"],
        },
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_sequence": 3,
        "locale": locale,
        "purpose": purpose,
        "deadline_at": (deadline_at or NOW + timedelta(seconds=30)).isoformat(),
        "prior_turns": prior_turns or [],
        "cancelled": cancelled,
        "execution_authority": False,
    }
    if planning_profile != "interactive":
        semantic_turn["planning_profile"] = planning_profile
    if bound_context is not None:
        semantic_turn["bound_context"] = bound_context
    if investigation_continuation is not None:
        semantic_turn["investigation_continuation"] = investigation_continuation
    if include_model_trace:
        semantic_turn["include_model_trace"] = True
    return {
        "schema_version": (
            "1.5.0"
            if investigation_continuation is not None
            else "1.4.0"
            if include_model_trace
            else "1.3.0"
            if bound_context is not None or planning_profile != "interactive"
            else "1.2.0"
        ),
        "request_id": "00000000-0000-0000-0000-000000000101",
        "correlation_id": "semantic-correlation-1",
        "idempotency_key": idempotency_key,
        "resource_ref": "operator-conversation:example",
        "request_kind": "semantic_query",
        "requested_at": NOW.isoformat(),
        "semantic_turn": semantic_turn,
    }


def _continuation_request_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "source_session_id": "session-1",
        "source_turn_id": "turn-prior",
        "source_turn_sequence": 2,
        "target_type": "BusinessService",
        "target_value": "service-example-api",
        "recovery_measure_concepts": ["dependency.latency", "service.latency"],
        "baseline_start": (NOW - timedelta(minutes=20)).isoformat(),
        "baseline_end": (NOW - timedelta(minutes=10)).isoformat(),
        "initial_observation_cutoff": NOW.isoformat(),
        "ontology_release_digest": RELEASE_DIGEST,
        "principal_manifest_digest": MANIFEST_DIGEST,
        "source_frame_digest": f"sha256:{'f' * 64}",
        "source_plan_digest": PLAN_DIGEST,
        "source_execution_receipt_digest": f"sha256:{'e' * 64}",
        "execution_authority": False,
    }


def _processor(
    runtime: _Runtime | None,
    *,
    now: Any = lambda: NOW,
) -> SemanticTurnProcessor:
    return SemanticTurnProcessor(
        runtime=runtime,
        results=StateStoreSemanticTurnResultStore(InMemoryStateStore()),
        now=now,
    )


def _projection(encoded: bytes) -> dict[str, Any]:
    loaded = json.loads(encoded)
    assert isinstance(loaded, dict)
    return cast(dict[str, Any], loaded)


def _runtime_result(
    disposition: str,
    *,
    reason: str = "provider detail must not escape",
    direct_response_intent: SemanticDirectResponseIntent = SemanticDirectResponseIntent.GREETING,
    model_observations: tuple[SemanticJudgmentObservation, ...] = (),
) -> RuntimeSemanticTurnResult:
    plan = SimpleNamespace(
        ontology_release_digest=RELEASE_DIGEST,
        semantic_catalog_digest=MANIFEST_DIGEST,
        plan_digest=PLAN_DIGEST,
    )
    planning = SimpleNamespace(
        plan=plan,
        frame=SimpleNamespace(
            operation=SemanticOperation.SELECT,
            output_shape="resource_list",
        ),
        manifest_digest=MANIFEST_DIGEST,
        direct_response_intent=(
            direct_response_intent if disposition == "direct_response" else None
        ),
        model_observations=model_observations,
    )
    if disposition != "answered":
        return RuntimeSemanticTurnResult(
            disposition=cast(Any, disposition),
            reason=reason,
            planning=cast(Any, planning),
        )
    receipt = GoalTaskReceipt(
        task_id="query:resources",
        goal_id="resources",
        intent="object_set",
        capability="query.object_set",
        evidence_mode=GoalEvidenceMode.OPERATIONAL,
        status=TaskStatus.COMPLETED,
        duration_ms=5,
        evidence_refs=("inventory:evidence-1",),
        started_at=NOW,
        completed_at=NOW,
    )
    execution = QueryPlanExecution(
        plan_digest=PLAN_DIGEST,
        status="completed",
        results=MappingProxyType(
            {
                "resources": QueryNodeResult(
                    value=QueryTable(
                        rows=(QueryRow.from_values("resource-1", {"state": "ready"}),),
                        complete=True,
                    ),
                    evidence_refs=("inventory:evidence-1",),
                )
            }
        ),
        receipts=(receipt,),
        output_node_ids=("resources",),
    )
    return RuntimeSemanticTurnResult(
        disposition="answered",
        reason="semantic_execution_completed",
        planning=cast(Any, planning),
        execution=execution,
        intent_graph={
            "schema_version": 2,
            "goals": [
                {
                    "goal_id": "goal-1",
                    "intent": "object_set",
                    "capability": "query.object_set",
                    "arguments": {},
                    "depends_on": [],
                    "evidence_mode": "operational",
                    "freshness_required": True,
                    "confidence": 1.0,
                    "alternatives": [],
                }
            ],
            "clarification": None,
            "confidence": 1.0,
            "action_posture": "advise_only",
        },
        intent_graph_evidence={
            "schema_version": 1,
            "status": "completed",
            "evidence_mode": "operational_grounded",
            "goals": [
                {
                    "task_id": "query:resources",
                    "goal_id": "goal-1",
                    "intent": "object_set",
                    "capability": "query.object_set",
                    "evidence_mode": "operational",
                    "status": "completed",
                    "duration_ms": 5,
                    "depends_on": [],
                    "started_at": NOW.isoformat(),
                    "completed_at": NOW.isoformat(),
                    "evidence_refs": ["inventory:evidence-1"],
                }
            ],
        },
    )


def test_s3_answer_projects_exact_no_authority_continuation() -> None:
    target = SimpleNamespace(
        role=InvestigationEntityRole.AFFECTED_TARGET,
        object_type_candidates=("BusinessService",),
        span=SimpleNamespace(text="service-example-api"),
    )
    primary = SimpleNamespace(measure_id="latency", concept_id="service.latency")
    intent = SimpleNamespace(
        entities=(target,),
        symptom_measures=(primary,),
        primary_symptom_measure_id="latency",
        hypotheses=(SimpleNamespace(cause_measure_concept="dependency.latency"),),
    )
    plan = SimpleNamespace(
        ontology_release_digest=RELEASE_DIGEST,
        plan_digest=PLAN_DIGEST,
        nodes=(
            SimpleNamespace(
                node_id="symptom-baseline",
                arguments={
                    "start": "2026-08-11T11:40:00+00:00",
                    "end": "2026-08-11T11:50:00+00:00",
                },
            ),
            SimpleNamespace(
                node_id="symptom-current",
                arguments={
                    "start": "2026-08-11T11:50:00+00:00",
                    "end": "2026-08-11T12:00:00+00:00",
                },
            ),
        ),
    )
    result = SimpleNamespace(
        planning=SimpleNamespace(
            investigation_intent=intent,
            plan=plan,
            frame=SimpleNamespace(frame_digest=f"sha256:{'f' * 64}"),
            manifest_digest=MANIFEST_DIGEST,
        )
    )
    request = SemanticTurnRequest.model_validate(
        cast(dict[str, object], _request()["semantic_turn"])
    )

    continuation = _project_investigation_continuation(
        request,
        cast(Any, result),
        execution_receipt_digest=f"sha256:{'e' * 64}",
    )

    assert continuation is not None
    assert continuation.source_session_id == "session-1"
    assert continuation.target_type == "BusinessService"
    assert continuation.target_value == "service-example-api"
    assert continuation.recovery_measure_concepts == (
        "dependency.latency",
        "service.latency",
    )
    assert continuation.initial_observation_cutoff == NOW
    assert continuation.execution_authority is False


def test_non_s3_answer_does_not_project_investigation_continuation() -> None:
    result = _runtime_result("answered")
    request = SemanticTurnRequest.model_validate(
        cast(dict[str, object], _request()["semantic_turn"])
    )

    continuation = _project_investigation_continuation(
        request,
        result,
        execution_receipt_digest=f"sha256:{'e' * 64}",
    )

    assert continuation is None


def _rule_search_runtime_result(*, execution_authority: bool = False) -> RuntimeSemanticTurnResult:
    result = _runtime_result("answered")
    assert result.execution is not None
    receipt = CatalogRetrievalReceipt(
        query_digest=RULE_QUERY_DIGEST,
        operation=RetrievalOperation.DISCOVER,
        corpus=RuleCorpus.ACTIVE,
        catalog_digest=MANIFEST_DIGEST,
        semantic_state=SemanticAvailability.AVAILABLE,
        results=(RetrievalRank("rule.one", 1, (("hybrid", 0.9),)),),
        generation_digest=GENERATION_DIGEST,
    )
    output = {
        "candidates": [
            {
                "rule_ref": "rule.one",
                "rank": 1,
                "components": {"hybrid": 0.9},
                "authority": "candidate_only",
            }
        ],
        "retrieval_receipt": {
            "schema_version": receipt.schema_version,
            "query_digest": receipt.query_digest,
            "operation": receipt.operation.value,
            "corpus": receipt.corpus.value,
            "catalog_digest": receipt.catalog_digest,
            "semantic_state": receipt.semantic_state.value,
            "generation_digest": receipt.generation_digest,
            "results": [
                {
                    "rule_ref": "rule.one",
                    "rank": 1,
                    "components": {"hybrid": 0.9},
                }
            ],
            "degraded_reason": None,
            "unresolved_terms": [],
            "clarification_required": False,
            "truncated": False,
            "execution_authority": False,
        },
        "retrieval_receipt_digest": receipt.digest,
        "authority": "candidate_only",
        "execution_authority": execution_authority,
    }
    node = SimpleNamespace(
        node_id="resources",
        kind=SimpleNamespace(value="function"),
        arguments={
            "function_name": "catalog.search_rules",
            "arguments": RULE_QUERY,
        },
    )
    plan = SimpleNamespace(
        ontology_release_digest=RELEASE_DIGEST,
        semantic_catalog_digest=MANIFEST_DIGEST,
        plan_digest=PLAN_DIGEST,
        nodes=(node,),
    )
    planning = SimpleNamespace(
        plan=plan,
        frame=SimpleNamespace(
            operation=SemanticOperation.SELECT,
            output_shape="resource_list",
        ),
        manifest_digest=MANIFEST_DIGEST,
    )
    function_receipt = result.execution.receipts[0].model_copy(
        update={
            "goal_id": "resources",
            "intent": "function",
            "capability": "query.function",
        }
    )
    execution = QueryPlanExecution(
        plan_digest=PLAN_DIGEST,
        status="completed",
        results=MappingProxyType(
            {
                "resources": QueryNodeResult(
                    value=output,
                    evidence_refs=("inventory:evidence-1",),
                )
            }
        ),
        receipts=(function_receipt,),
        output_node_ids=("resources",),
    )
    return RuntimeSemanticTurnResult(
        disposition="answered",
        reason=result.reason,
        planning=cast(Any, planning),
        execution=execution,
        intent_graph={
            **cast(dict[str, object], result.intent_graph),
            "goals": [
                {
                    **cast(dict[str, object], result.intent_graph)["goals"][0],
                    "intent": "function",
                    "capability": "query.function",
                }
            ],
        },
        intent_graph_evidence={
            **cast(dict[str, object], result.intent_graph_evidence),
            "goals": [
                {
                    **cast(dict[str, object], result.intent_graph_evidence)["goals"][0],
                    "intent": "function",
                    "capability": "query.function",
                }
            ],
        },
    )


def _incident_evidence_runtime_result(
    *,
    inject_cause: bool = False,
    recorded_rca: bool = False,
    empty_evidence: bool = False,
    output_correlation_id: str = "incident-correlation-301",
    profile_incident_id: str | None = "00000000-0000-0000-0000-000000000301",
    profile_status: str | None = "triaging",
    records: int = 1,
    incident_id: str = "00000000-0000-0000-0000-000000000301",
) -> RuntimeSemanticTurnResult:
    result = _runtime_result("answered")
    assert result.execution is not None
    correlation_id = "incident-correlation-301"
    output = {
        "incident_id": incident_id,
        "correlation_id": output_correlation_id,
        "incident_profile": {
            "correlation_id": correlation_id,
            "incident_id": profile_incident_id,
            "ticket_id": None,
            "title": None,
            "severity": "sev2",
            "status": profile_status,
            "vertical": None,
            "opened_at": "2026-08-14T09:00:00Z",
            "last_updated_at": "2026-08-14T09:05:00Z",
            "duration_seconds": 300.0,
            "audit_records": 2,
            "actors": ["Heimdall", "operator@example.com"],
            "modes": ["shadow"],
        },
        "correlated_evidence": [
            {
                "audit_ref": f"audit:{index}",
                "event_id": "00000000-0000-0000-0000-000000000401",
                "action_kind": "incident.open",
                "mode": "shadow",
                "recorded_at": "2026-08-14T09:00:00Z",
            }
            for index in range(1, records + 1)
        ],
        "root_cause": None,
        "impact_evidence": [],
        "grounded_citations": [],
        "evidence_gaps": [
            "root_cause_missing",
            "impact_evidence_missing",
            "grounded_citations_missing",
        ],
        "evidence_refs": [f"audit:{index}" for index in range(1, records + 1)],
        "truncated": False,
        "authority": "audit_projection",
        "cause_claim_supported": False,
        "execution_authority": False,
    }
    if recorded_rca:
        output["root_cause"] = {
            "tier": "t0",
            "outcome": "grounded",
            "cause": "A required owner tag was absent.",
            "confidence": 0.95,
            "reason": "Matched the deterministic owner-tag rule.",
            "recorded_at": "2026-08-14T09:06:00Z",
            "causal_hops": [],
        }
        output["impact_evidence"] = [
            {
                "metric": "noncompliant_resources",
                "baseline": 0,
                "observed": 1,
                "threshold": 0,
                "unit": "resources",
                "impact": "One resource is outside the required baseline.",
                "evidence_ref": "audit:1",
            }
        ]
        output["grounded_citations"] = [
            {
                "tier": "t0",
                "kind": "rule",
                "ref": "object-storage.owner-tag.required",
                "summary": None,
                "recorded_at": "2026-08-14T09:06:00Z",
            }
        ]
        output["evidence_gaps"] = []
        output["cause_claim_supported"] = True
    if inject_cause:
        output["cause"] = "unsupported causal claim"
    if empty_evidence:
        output["incident_profile"] = None
        output["correlated_evidence"] = []
        output["evidence_gaps"] = [
            "incident_profile_missing",
            "root_cause_missing",
            "impact_evidence_missing",
            "grounded_citations_missing",
        ]
        output["evidence_refs"] = []
    node = SimpleNamespace(
        node_id="incident-evidence",
        kind=SimpleNamespace(value="function"),
        arguments={
            "function_name": "query.incident_evidence",
            "arguments": {
                "incident_id": incident_id,
                "correlation_id": correlation_id,
                "limit": 100,
            },
        },
    )
    plan = SimpleNamespace(
        ontology_release_digest=RELEASE_DIGEST,
        semantic_catalog_digest=MANIFEST_DIGEST,
        plan_digest=PLAN_DIGEST,
        nodes=(node,),
    )
    planning = SimpleNamespace(
        plan=plan,
        frame=SimpleNamespace(
            operation=SemanticOperation.SELECT,
            output_shape="incident_evidence",
        ),
        manifest_digest=MANIFEST_DIGEST,
    )
    function_receipt = result.execution.receipts[0].model_copy(
        update={
            "task_id": "query:incident-evidence",
            "goal_id": "incident-evidence",
            "intent": "function",
            "capability": "query.function",
            "evidence_refs": ("ontology-function:incident-evidence",),
        }
    )
    execution = QueryPlanExecution(
        plan_digest=PLAN_DIGEST,
        status="completed",
        results=MappingProxyType(
            {
                "incident-evidence": QueryNodeResult(
                    value=output,
                    evidence_refs=("ontology-function:incident-evidence",),
                )
            }
        ),
        receipts=(function_receipt,),
        output_node_ids=("incident-evidence",),
    )
    graph_goal = cast(dict[str, object], result.intent_graph)["goals"][0]
    evidence_goal = cast(dict[str, object], result.intent_graph_evidence)["goals"][0]
    return RuntimeSemanticTurnResult(
        disposition="answered",
        reason=result.reason,
        planning=cast(Any, planning),
        execution=execution,
        intent_graph={
            **cast(dict[str, object], result.intent_graph),
            "goals": [
                {
                    **cast(dict[str, object], graph_goal),
                    "goal_id": "incident-evidence",
                    "intent": "function",
                    "capability": "query.function",
                }
            ],
        },
        intent_graph_evidence={
            **cast(dict[str, object], result.intent_graph_evidence),
            "goals": [
                {
                    **cast(dict[str, object], evidence_goal),
                    "task_id": "query:incident-evidence",
                    "goal_id": "incident-evidence",
                    "intent": "function",
                    "capability": "query.function",
                    "evidence_refs": ["ontology-function:incident-evidence"],
                }
            ],
        },
    )


def _ontology_relationship_runtime_result(
    *,
    output_release_digest: str = RELEASE_DIGEST,
) -> RuntimeSemanticTurnResult:
    result = _runtime_result("answered")
    assert result.execution is not None
    output = {
        "object_types": ["PythonTask", "VmTaskRun"],
        "relationships": [
            {
                "link_type": "executes_task",
                "from_type": "VmTaskRun",
                "to_type": "PythonTask",
                "cardinality": "many_to_one",
                "description": "The immutable PythonTask artifact selected by a VM task run.",
            }
        ],
        "complete": True,
        "authority": "ontology_release",
        "ontology_release_digest": output_release_digest,
        "execution_authority": False,
    }
    node = SimpleNamespace(
        node_id="relationships",
        kind=SimpleNamespace(value="function"),
        arguments={
            "function_name": "query.ontology_relationships",
            "arguments": {
                "object_types": ["PythonTask", "VmTaskRun"],
                "limit": 100,
            },
        },
    )
    plan = SimpleNamespace(
        ontology_release_digest=RELEASE_DIGEST,
        semantic_catalog_digest=MANIFEST_DIGEST,
        plan_digest=PLAN_DIGEST,
        nodes=(node,),
    )
    planning = SimpleNamespace(
        plan=plan,
        frame=SimpleNamespace(
            operation=SemanticOperation.SELECT,
            output_shape="ontology_relationships",
        ),
        manifest_digest=MANIFEST_DIGEST,
    )
    function_receipt = result.execution.receipts[0].model_copy(
        update={
            "task_id": "query:relationships",
            "goal_id": "relationships",
            "intent": "function",
            "capability": "query.function",
            "evidence_refs": ("ontology-function:relationships",),
        }
    )
    execution = QueryPlanExecution(
        plan_digest=PLAN_DIGEST,
        status="completed",
        results=MappingProxyType(
            {
                "relationships": QueryNodeResult(
                    value=output,
                    evidence_refs=("ontology-function:relationships",),
                )
            }
        ),
        receipts=(function_receipt,),
        output_node_ids=("relationships",),
    )
    graph_goal = cast(dict[str, object], result.intent_graph)["goals"][0]
    evidence_goal = cast(dict[str, object], result.intent_graph_evidence)["goals"][0]
    return RuntimeSemanticTurnResult(
        disposition="answered",
        reason=result.reason,
        planning=cast(Any, planning),
        execution=execution,
        intent_graph={
            **cast(dict[str, object], result.intent_graph),
            "goals": [
                {
                    **cast(dict[str, object], graph_goal),
                    "goal_id": "relationships",
                    "intent": "function",
                    "capability": "query.function",
                }
            ],
        },
        intent_graph_evidence={
            **cast(dict[str, object], result.intent_graph_evidence),
            "goals": [
                {
                    **cast(dict[str, object], evidence_goal),
                    "task_id": "query:relationships",
                    "goal_id": "relationships",
                    "intent": "function",
                    "capability": "query.function",
                    "evidence_refs": ["ontology-function:relationships"],
                }
            ],
        },
    )


async def test_malformed_semantic_request_goes_to_dlq() -> None:
    bus = InMemoryEventBus()
    await bus.publish("operator.request", "bad", {"schema_version": "1.2.0"})

    await consume_semantic_turns(
        bus=bus,
        request_topic="operator.request",
        projection_topic="operator.projection",
        group_id="core-semantic",
        processor=_processor(None),
        stop=asyncio.Event(),
    )

    dlq = [item async for item in bus.subscribe("operator.request.dlq", "assert")]
    assert len(dlq) == 1
    assert dlq[0].payload["reason"] == "semantic_turn_rejected"


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (["Reader"], Role.READER),
        (["Reader", "Contributor"], Role.CONTRIBUTOR),
        (["Reader", "Approver"], Role.APPROVER),
        (["BreakGlass", "Owner"], Role.OWNER),
    ],
)
async def test_authenticated_role_order_selects_highest_ordinary_role(
    roles: list[str],
    expected: Role,
) -> None:
    runtime = _Runtime()

    await _processor(runtime).process(_request(roles=roles))

    assert runtime.principals[0].role is expected


async def test_break_glass_only_and_caller_purpose_widening_are_rejected() -> None:
    processor = _processor(_Runtime())

    with pytest.raises(SemanticTurnRejectedError, match="semantic_break_glass_only"):
        await processor.process(_request(roles=["BreakGlass"]))
    with pytest.raises(SemanticTurnRejectedError, match="semantic_purpose_not_allowed"):
        await processor.process(_request(purpose="execution"))


async def test_prior_turns_map_to_existing_turn_without_content_rewrite() -> None:
    runtime = _Runtime()

    await _processor(runtime).process(
        _request(
            prior_turns=[
                {"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"},
            ]
        )
    )

    assert [(turn.direction, turn.content) for turn in runtime.prior_turns] == [
        ("inbound", "Earlier question"),
        ("outbound", "Earlier answer"),
    ]
    assert [turn.turn_id for turn in runtime.prior_turns] == [
        "turn-1:prior:0",
        "turn-1:prior:1",
    ]
    assert all(turn.timestamp == NOW for turn in runtime.prior_turns)


async def test_bound_incident_context_reaches_runtime_as_last_system_turn() -> None:
    runtime = _Runtime()

    await _processor(runtime).process(
        _request(
            prior_turns=[{"role": "user", "content": "Earlier question"}],
            bound_context={
                "kind": "incident",
                "incident_id": "incident-42",
                "correlation_id": "correlation-7",
            },
        )
    )

    anchor = runtime.prior_turns[-1]
    assert anchor.direction == "system"
    assert anchor.turn_id == "turn-1:bound-context"
    assert anchor.content == (
        "Bound conversation context: kind=incident, "
        "incident_id=incident-42, correlation_id=correlation-7"
    )
    assert runtime.bound_incidents == [
        BoundIncident(incident_id="incident-42", correlation_id="correlation-7")
    ]


async def test_investigation_continuation_reaches_runtime_as_typed_binding() -> None:
    runtime = _Runtime()

    await _processor(runtime).process(
        _request(investigation_continuation=_continuation_request_payload())
    )

    assert runtime.bound_investigation_continuations == [
        BoundInvestigationContinuation(
            source_session_id="session-1",
            source_turn_id="turn-prior",
            source_turn_sequence=2,
            target_type="BusinessService",
            target_value="service-example-api",
            recovery_measure_concepts=("dependency.latency", "service.latency"),
            baseline_start=NOW - timedelta(minutes=20),
            baseline_end=NOW - timedelta(minutes=10),
            initial_observation_cutoff=NOW,
            ontology_release_digest=RELEASE_DIGEST,
            principal_manifest_digest=MANIFEST_DIGEST,
            source_frame_digest=f"sha256:{'f' * 64}",
            source_plan_digest=PLAN_DIGEST,
            source_execution_receipt_digest=f"sha256:{'e' * 64}",
        )
    ]
    assert all(turn.direction != "system" for turn in runtime.prior_turns)


@pytest.mark.parametrize(
    ("field", "value"),
    (("source_session_id", "other-session"), ("source_turn_sequence", 3)),
)
async def test_investigation_continuation_mismatch_is_rejected_before_runtime(
    field: str,
    value: object,
) -> None:
    runtime = _Runtime()
    continuation = _continuation_request_payload()
    continuation[field] = value

    with pytest.raises(
        SemanticTurnRejectedError,
        match="semantic_investigation_continuation_mismatched",
    ):
        await _processor(runtime).process(_request(investigation_continuation=continuation))

    assert runtime.calls == 0


async def test_absent_bound_context_adds_no_anchor_turn() -> None:
    runtime = _Runtime()

    await _processor(runtime).process(
        _request(prior_turns=[{"role": "user", "content": "Earlier question"}])
    )

    assert [turn.direction for turn in runtime.prior_turns] == ["inbound"]


async def test_golden_campaign_profile_injects_no_t2_policy_only_for_campaign() -> None:
    runtime = _Runtime()
    processor = _processor(runtime)

    await processor.process(_request(idempotency_key="interactive-turn"))
    await processor.process(
        _request(
            idempotency_key="golden-turn",
            planning_profile="golden_campaign_no_t2",
        )
    )

    assert runtime.escalation_policies == [None, NO_T2_ESCALATION_POLICY]


async def test_clarification_projection_preserves_specific_question() -> None:
    runtime_result = _runtime_result("clarification")
    runtime_result.planning.clarification = "Which incident should I investigate?"

    projection = _projection(await _processor(_Runtime(runtime_result)).process(_request()))

    assert projection["status"] == "clarification"
    assert projection["semantic_result"]["answer"] == "Which incident should I investigate?"
    assert projection["semantic_result"]["reason_code"] == ("semantic_clarification_required")


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("en", "Hello. What would you like to inspect on this screen or in current operations?"),
        ("ko", "안녕하세요. 현재 화면이나 운영 상태에 대해 무엇을 확인할까요?"),
    ],
)
async def test_direct_greeting_projection_has_no_query_or_evidence_claims(
    locale: str,
    expected: str,
) -> None:
    projection = _projection(
        await _processor(_Runtime(_runtime_result("direct_response"))).process(
            _request(locale=locale)
        )
    )

    semantic = projection["semantic_result"]
    assert projection["schema_version"] == "1.4.0"
    assert projection["status"] == "direct_response"
    assert semantic == {
        "disposition": "direct_response",
        "reason_code": "semantic_direct_response",
        "semantic_route": "semantic_direct_response",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "turn_sequence": 3,
        "evidence_refs": [],
        "checks_completed": 0,
        "checks_total": 0,
        "answer": expected,
        "direct_response_intent": "greeting",
        "execution_authority": False,
    }
    assert projection["payload"].get("technical_details") is None


@pytest.mark.parametrize("include_model_trace", [False, True])
async def test_direct_greeting_projects_measured_usage_and_opt_in_trace(
    include_model_trace: bool,
) -> None:
    trace_call: dict[str, object] = {
        "call_id": "adapter-call",
        "kind": "semantic-judgment",
        "model": "semantic-test",
        "status": "completed",
        "started_at": "2026-08-11T12:00:00+00:00",
        "completed_at": "2026-08-11T12:00:00.025000+00:00",
        "duration_ms": 25,
        "request": {"messages": [], "sha256": "a" * 64},
        "response": {"role": "assistant", "content": "{}", "sha256": "b" * 64},
        "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        "redactions": [],
    }
    runtime_result = _runtime_result(
        "direct_response",
        model_observations=(
            SemanticJudgmentObservation(
                model="semantic-test",
                usage={"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
                trace_call=trace_call,
            ),
        ),
    )

    projection = _projection(
        await _processor(_Runtime(runtime_result)).process(
            _request(include_model_trace=include_model_trace)
        )
    )

    payload = projection["payload"]
    assert payload["model"] == "semantic-test"
    assert payload["latency_ms"] == 25
    assert payload["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }
    if include_model_trace:
        trace = payload["model_trace"]
        assert trace["redacted"] is True
        assert trace["calls"][0]["call_id"] == "semantic-judgment-1"
    else:
        assert "model_trace" not in payload
    semantic = projection["semantic_result"]
    assert semantic["evidence_refs"] == []
    assert semantic["checks_total"] == 0


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        (
            "en",
            "I am Bragi, the FDAI Console conversation interface. I explain questions about the "
            "current screen and operational state from verified evidence. I do not execute changes "
            "directly; requested work follows FDAI approval and safety paths.",
        ),
        (
            "ko",
            "저는 FDAI Console의 대화 인터페이스 Bragi입니다. 화면과 운영 상태에 관한 질문을 "
            "검증된 근거에 맞춰 설명합니다. 직접 변경을 실행하지 않으며, 필요한 작업은 FDAI의 "
            "승인 및 안전 경로로 전달합니다.",
        ),
    ],
)
async def test_self_introduction_projection_has_no_query_or_evidence_claims(
    locale: str,
    expected: str,
) -> None:
    projection = _projection(
        await _processor(
            _Runtime(
                _runtime_result(
                    "direct_response",
                    direct_response_intent=SemanticDirectResponseIntent.SELF_INTRODUCTION,
                )
            )
        ).process(_request(locale=locale))
    )

    semantic = projection["semantic_result"]
    assert projection["status"] == "direct_response"
    assert semantic["answer"] == expected
    assert semantic["direct_response_intent"] == "self_introduction"
    assert semantic["evidence_refs"] == []
    assert projection["payload"].get("technical_details") is None


async def test_expired_deadline_and_pre_cancel_never_call_runtime() -> None:
    runtime = _Runtime()
    processor = _processor(runtime)

    expired = _projection(await processor.process(_request(deadline_at=NOW - timedelta(seconds=1))))
    cancelled = _projection(
        await _processor(runtime).process(_request(cancelled=True, idempotency_key="cancelled"))
    )

    assert expired["semantic_result"]["reason_code"] == "semantic_deadline_exceeded"
    assert cancelled["status"] == "cancelled"
    assert runtime.calls == 0


async def test_overlong_deadline_is_rejected_before_runtime() -> None:
    runtime = _Runtime(_runtime_result("answered"))
    processor = _processor(runtime)

    with pytest.raises(SemanticTurnRejectedError, match="semantic_deadline_too_far"):
        await processor.process(_request(deadline_at=NOW + timedelta(seconds=91)))

    assert runtime.calls == 0


async def test_deadline_and_cancellation_interrupt_inflight_runtime() -> None:
    timeout_runtime = _Runtime(wait_for_cancel=True)
    realtime = datetime.now(UTC)
    timed_out = await _processor(
        timeout_runtime,
        now=lambda: datetime.now(UTC),
    ).process(_request(deadline_at=realtime + timedelta(milliseconds=20)))

    cancel_runtime = _Runtime(wait_for_cancel=True)
    cancel_event = asyncio.Event()
    pending = asyncio.create_task(
        _processor(cancel_runtime).process(
            _request(idempotency_key="inflight-cancel"),
            cancelled=cancel_event,
        )
    )
    await asyncio.sleep(0)
    cancel_event.set()
    cancelled = await pending

    assert _projection(timed_out)["semantic_result"]["reason_code"] == (
        "semantic_deadline_exceeded"
    )
    assert _projection(cancelled)["status"] == "cancelled"


async def test_deadline_bounds_result_store_wait() -> None:
    store = _BlockingResultStore()
    realtime = datetime.now(UTC)
    processor = SemanticTurnProcessor(
        runtime=_Runtime(),
        results=store,
        now=lambda: datetime.now(UTC),
    )

    encoded = await asyncio.wait_for(
        processor.process(_request(deadline_at=realtime + timedelta(milliseconds=20))),
        timeout=0.2,
    )

    assert _projection(encoded)["semantic_result"]["reason_code"] == ("semantic_deadline_exceeded")


async def test_cancellation_interrupts_result_store_wait() -> None:
    store = _BlockingResultStore()
    cancelled = asyncio.Event()
    processor = SemanticTurnProcessor(
        runtime=_Runtime(),
        results=store,
        now=lambda: datetime.now(UTC),
    )
    pending = asyncio.create_task(
        processor.process(
            _request(deadline_at=datetime.now(UTC) + timedelta(seconds=1)),
            cancelled=cancelled,
        )
    )
    await store.entered.wait()

    cancelled.set()
    encoded = await asyncio.wait_for(pending, timeout=0.2)

    assert _projection(encoded)["status"] == "cancelled"


async def test_duplicate_returns_exact_prior_projection_without_reexecution() -> None:
    runtime = _Runtime(_runtime_result("answered"))
    processor = _processor(runtime)
    request = _request()

    first = await processor.process(request)
    second = await processor.process(request)

    assert second == first
    assert runtime.calls == 1


async def test_concurrent_duplicate_executes_runtime_once() -> None:
    runtime = _ContendedRuntime()
    state_store = InMemoryStateStore()
    first_processor = SemanticTurnProcessor(
        runtime=runtime,
        results=StateStoreSemanticTurnResultStore(state_store),
        now=lambda: NOW,
    )
    second_processor = SemanticTurnProcessor(
        runtime=runtime,
        results=StateStoreSemanticTurnResultStore(state_store),
        now=lambda: NOW,
    )
    request = _request()

    first = asyncio.create_task(first_processor.process(request))
    await runtime.entered.wait()
    second = asyncio.create_task(second_processor.process(request))
    await asyncio.sleep(0)
    runtime.release.set()

    first_projection, second_projection = await asyncio.gather(first, second)

    assert second_projection == first_projection
    assert runtime.calls == 1


async def test_abandoned_claim_is_recovered_only_after_lease_expiry() -> None:
    state_store = InMemoryStateStore()
    before_expiry = StateStoreSemanticTurnResultStore(
        state_store,
        claim_lease_seconds=30,
        now=lambda: NOW,
    )
    after_expiry = StateStoreSemanticTurnResultStore(
        state_store,
        claim_lease_seconds=30,
        now=lambda: NOW + timedelta(seconds=31),
    )

    original_claim = await before_expiry.claim("turn-1", "sha256:request")

    assert original_claim is not None
    assert await before_expiry.claim("turn-1", "sha256:request") is None
    recovered_claim = await after_expiry.claim("turn-1", "sha256:request")
    assert recovered_claim is not None
    assert recovered_claim != original_claim
    assert not await after_expiry.release(
        "turn-1",
        "sha256:request",
        original_claim,
    )
    assert await after_expiry.release(
        "turn-1",
        "sha256:request",
        recovered_claim,
    )
    assert await after_expiry.claim("turn-1", "sha256:request") is not None


async def test_default_claim_lease_covers_healthy_request_deadline() -> None:
    state_store = InMemoryStateStore()
    owner = StateStoreSemanticTurnResultStore(state_store, now=lambda: NOW)
    contender = StateStoreSemanticTurnResultStore(
        state_store,
        now=lambda: NOW + timedelta(seconds=90),
    )

    assert await owner.claim("turn-1", "sha256:request") is not None
    assert await contender.claim("turn-1", "sha256:request") is None


async def test_result_persistence_failure_releases_owned_claim() -> None:
    class FailingResultStore:
        released_claims: list[str]

        def __init__(self) -> None:
            self.released_claims = []

        async def get(self, idempotency_key: str) -> bytes | None:
            return None

        async def claim(self, idempotency_key: str, request_digest: str) -> str | None:
            return "claim-1"

        async def release(
            self,
            idempotency_key: str,
            request_digest: str,
            claim_id: str,
        ) -> bool:
            self.released_claims.append(claim_id)
            return True

        async def put_if_absent(self, idempotency_key: str, projection: bytes) -> bool:
            raise RuntimeError("state store unavailable")

    store = FailingResultStore()
    processor = SemanticTurnProcessor(
        runtime=_Runtime(_runtime_result("answered")),
        results=store,
        now=lambda: NOW,
    )

    projection = _projection(await processor.process(_request()))

    assert projection["semantic_result"]["reason_code"] == "semantic_result_store_unavailable"
    assert store.released_claims == ["claim-1"]


async def test_reused_idempotency_key_for_different_turn_is_rejected() -> None:
    runtime = _Runtime(_runtime_result("answered"))
    processor = _processor(runtime)
    await processor.process(_request())
    conflicting = _request()
    semantic_turn = cast(dict[str, object], conflicting["semantic_turn"])
    semantic_turn["turn_id"] = "turn-2"

    with pytest.raises(SemanticTurnRejectedError, match="semantic_idempotency_conflict"):
        await processor.process(conflicting)

    assert runtime.calls == 1


async def test_answered_projection_requires_complete_exact_evidence() -> None:
    answered = _projection(
        await _processor(_Runtime(_runtime_result("answered"))).process(_request())
    )
    semantic = answered["semantic_result"]

    assert answered["status"] == "answered"
    assert semantic["ontology_release_digest"] == RELEASE_DIGEST
    assert semantic["principal_manifest_digest"] == MANIFEST_DIGEST
    assert semantic["plan_digest"] == PLAN_DIGEST
    assert semantic["execution_receipt_digest"].startswith("sha256:")
    assert semantic["evidence_refs"] == ["inventory:evidence-1"]
    assert semantic["checks_completed"] == semantic["checks_total"] == 1
    assert semantic["semantic_route"] == "verified_query_plan"
    assert semantic["execution_authority"] is False


async def test_answered_projection_keeps_a_complete_small_resource_list() -> None:
    result = _runtime_result("answered")
    assert result.execution is not None
    rows = tuple(
        QueryRow.from_values(
            f"resource-{index}",
            {
                "id": f"resource-{index}",
                "object_type": "Resource",
                "properties": {
                    "name": f"app-{index}",
                    "type": "compute.container-app",
                    "properties": {
                        "location": "example-region",
                        "configuration": {"large": "x" * 10_000},
                    },
                },
            },
        )
        for index in range(9)
    )
    execution = replace(
        result.execution,
        results=MappingProxyType(
            {
                "resources": QueryNodeResult(
                    value=QueryTable(rows=rows, complete=True),
                    evidence_refs=("inventory:evidence-1",),
                )
            }
        ),
    )

    projection = _projection(
        await _processor(_Runtime(replace(result, execution=execution))).process(_request())
    )

    output = projection["payload"]["technical_details"]["outputs"][0]
    assert output["returned_rows"] == output["total_rows"] == 9
    assert output["display_truncated"] is False
    assert [row["values"]["name"] for row in output["rows"]] == [
        f"app-{index}" for index in range(9)
    ]
    assert all("configuration" not in row["values"] for row in output["rows"])


async def test_target_candidates_answer_names_verified_choices_in_korean() -> None:
    result = _runtime_result("answered")
    planning = SimpleNamespace(
        plan=result.planning.plan,
        frame=SimpleNamespace(
            operation=SemanticOperation.SELECT,
            output_shape="resource_target_candidates",
        ),
        manifest_digest=result.planning.manifest_digest,
    )
    assert result.execution is not None
    rows = tuple(
        QueryRow.from_values(
            f"resource-{index}",
            {
                "id": f"resource-{index}",
                "object_type": "Resource",
                "properties": {
                    "name": name,
                    "type": "compute.container-app",
                },
            },
        )
        for index, name in enumerate(("app-api", "app-worker"), start=1)
    )
    execution = replace(
        result.execution,
        results=MappingProxyType(
            {
                "resources": QueryNodeResult(
                    value=QueryTable(rows=rows, complete=True),
                    evidence_refs=("inventory:evidence-1",),
                )
            }
        ),
    )

    projection = _projection(
        await _processor(_Runtime(replace(result, planning=planning, execution=execution))).process(
            _request(locale="ko")
        )
    )

    answer = projection["semantic_result"]["answer"]
    assert "app-api" in answer
    assert "app-worker" in answer
    assert "정확한 이름 또는 리소스 ID" in answer
    assert "execution_authority=false" in answer


async def test_incident_evidence_answer_reports_missing_recorded_rca() -> None:
    encoded = await _processor(_Runtime(_incident_evidence_runtime_result())).process(
        _request(
            bound_context={
                "kind": "incident",
                "incident_id": "00000000-0000-0000-0000-000000000301",
                "correlation_id": "incident-correlation-301",
            }
        )
    )

    projection = _projection(encoded)
    semantic = projection["semantic_result"]
    assert semantic["disposition"] == "answered"
    answer = semantic["answer"]
    assert answer.startswith("## Verified incident evidence")
    assert "1 correlated audit record was verified." in answer
    assert "causal analysis hasn't been implemented" not in answer
    assert "a grounded root-cause hypothesis" in answer
    assert "impact evidence" in answer
    assert "grounded citations" in answer
    assert (
        "Before proposing a change, confirm that an RCA hypothesis with grounded citations "
        "has been recorded, collect impact evidence for the affected resources, "
        "and collect grounded citations that link each claim to an audit record." in answer
    )
    assert "```json" not in answer
    payload = projection["payload"]
    technical_details = payload["technical_details"]
    assert technical_details["schema_version"] == 1
    assert technical_details["kind"] == "semantic_query_outputs"
    assert technical_details["presentation_context"] == {
        "operation": "select",
        "output_shape": "incident_evidence",
    }
    incident = technical_details["outputs"][0]
    assert incident["incident_profile"]["correlation_id"] == "incident-correlation-301"
    assert incident["incident_profile"]["status"] == "triaging"
    assert incident["correlated_evidence"][0]["audit_ref"] == "audit:1"
    assert incident["evidence_gaps"] == [
        "root_cause_missing",
        "impact_evidence_missing",
        "grounded_citations_missing",
    ]
    assert incident["root_cause"] is None
    assert incident["impact_evidence"] == []
    assert incident["grounded_citations"] == []
    assert incident["next_safe_step"] == {
        "operation": "collect_evidence",
        "authority": "read_only",
        "execution_authority": False,
    }
    assert '"cause":' not in answer


async def test_incident_evidence_answer_renders_recorded_rca_impact_and_citations() -> None:
    encoded = await _processor(
        _Runtime(_incident_evidence_runtime_result(recorded_rca=True))
    ).process(_request())

    projection = _projection(encoded)
    answer = projection["semantic_result"]["answer"]
    assert "## Root cause" in answer
    assert "A required owner tag was absent." in answer
    assert "## Impact evidence" in answer
    assert "noncompliant_resources" in answer
    assert "## Grounded citations" in answer
    assert "object-storage.owner-tag.required" in answer
    assert "Missing evidence: none" in answer
    incident = projection["payload"]["technical_details"]["outputs"][0]
    assert incident["root_cause"]["outcome"] == "grounded"
    assert incident["impact_evidence"][0]["evidence_ref"] == "audit:1"
    assert incident["grounded_citations"][0]["kind"] == "rule"


async def test_incident_evidence_answer_is_localized_without_changing_machine_output() -> None:
    encoded = await _processor(_Runtime(_incident_evidence_runtime_result())).process(
        _request(
            locale="ko",
            bound_context={
                "kind": "incident",
                "incident_id": "00000000-0000-0000-0000-000000000301",
                "correlation_id": "incident-correlation-301",
            },
        )
    )

    projection = _projection(encoded)
    answer = projection["semantic_result"]["answer"]
    assert answer.startswith("## 검증된 인시던트 근거")
    assert "감사 기록 1건을 검증했습니다." in answer
    assert "인과 분석이 구현되지 않아" not in answer
    assert "근거에 기반한 근본 원인 가설, 영향 근거, 근거 인용" in answer
    assert "```json" not in answer
    assert (
        projection["payload"]["technical_details"]["outputs"][0]["correlated_evidence"][0][
            "audit_ref"
        ]
        == "audit:1"
    )


async def test_incident_evidence_with_cause_claim_is_held() -> None:
    encoded = await _processor(
        _Runtime(_incident_evidence_runtime_result(inject_cause=True))
    ).process(_request())

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "held"
    assert semantic["reason_code"] == "semantic_evidence_incomplete"


async def test_incident_evidence_with_mismatched_correlation_is_held() -> None:
    encoded = await _processor(
        _Runtime(
            _incident_evidence_runtime_result(output_correlation_id="incident-correlation-other")
        )
    ).process(_request())

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "held"
    assert semantic["reason_code"] == "semantic_evidence_incomplete"


async def test_incident_evidence_answers_when_the_window_omits_the_identity_anchor() -> None:
    encoded = await _processor(
        _Runtime(_incident_evidence_runtime_result(profile_incident_id=None))
    ).process(_request())

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "answered"


async def test_incident_answer_separates_an_unrecorded_status_from_a_missing_profile() -> None:
    result = _incident_evidence_runtime_result(profile_status=None)
    encoded = await _processor(_Runtime(result)).process(_request())

    answer = _projection(encoded)["semantic_result"]["answer"]
    assert "The audit records read for this incident record no status." in answer
    assert "the incident profile is missing" not in answer


async def test_incident_bound_turn_accepts_a_case_different_identical_identity() -> None:
    """A hexadecimal case difference denotes the same incident, not a different one."""
    canonical = "00000000-0000-0000-0000-0000000003ab"
    encoded = await _processor(
        _Runtime(
            _incident_evidence_runtime_result(
                incident_id=canonical,
                profile_incident_id=canonical,
            )
        )
    ).process(
        _request(
            bound_context={
                "kind": "incident",
                "incident_id": canonical.upper(),
                "correlation_id": "incident-correlation-301",
            }
        )
    )

    assert _projection(encoded)["semantic_result"]["disposition"] == "answered"


async def test_incident_answer_reports_the_verified_total_not_the_displayed_slice() -> None:
    """Reporting the displayed slice as the verified count understates the evidence."""
    encoded = await _processor(_Runtime(_incident_evidence_runtime_result(records=31))).process(
        _request()
    )

    projection = _projection(encoded)
    answer = projection["semantic_result"]["answer"]
    assert "31 correlated audit records were verified." in answer
    assert "Only the most recent 20 are carried below." in answer
    output = projection["payload"]["technical_details"]["outputs"][0]
    assert output["verified_records"] == 31
    assert len(output["correlated_evidence"]) == 20
    assert output["display_truncated"] is True


async def test_incident_answer_omits_the_truncation_line_when_nothing_is_hidden() -> None:
    encoded = await _processor(_Runtime(_incident_evidence_runtime_result(records=3))).process(
        _request()
    )

    answer = _projection(encoded)["semantic_result"]["answer"]
    assert "3 correlated audit records were verified." in answer
    assert "Only the most recent" not in answer


async def test_incident_evidence_out_of_order_by_time_is_held() -> None:
    """The answer names the latest records by slicing the tail, so order is a claim."""
    result = _incident_evidence_runtime_result(records=3)
    output = result.execution.results["incident-evidence"].value  # type: ignore[union-attr]
    output["correlated_evidence"][0]["recorded_at"] = "2026-08-14T23:59:00Z"  # type: ignore[index]

    encoded = await _processor(_Runtime(result)).process(_request())

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "held"
    assert semantic["reason_code"] == "semantic_evidence_incomplete"


async def test_incident_evidence_with_a_conflicting_profile_identity_is_held() -> None:
    encoded = await _processor(
        _Runtime(
            _incident_evidence_runtime_result(
                profile_incident_id="00000000-0000-0000-0000-000000000999"
            )
        )
    ).process(_request())

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "held"
    assert semantic["reason_code"] == "semantic_evidence_incomplete"


async def test_incident_answer_states_an_empty_correlation_without_a_raw_gap_key() -> None:
    result = _incident_evidence_runtime_result(empty_evidence=True)
    encoded = await _processor(_Runtime(result)).process(
        _request(
            bound_context={
                "kind": "incident",
                "incident_id": "00000000-0000-0000-0000-000000000301",
                "correlation_id": "incident-correlation-301",
            }
        )
    )

    answer = _projection(encoded)["semantic_result"]["answer"]
    assert "No audit record was found for this correlation." in answer
    assert "Status can't be reported because the incident profile is missing." in answer
    assert "the incident profile" in answer
    assert "incident_profile_missing" not in answer


async def test_incident_bound_turn_without_incident_evidence_still_answers() -> None:
    encoded = await _processor(_Runtime(_runtime_result("answered"))).process(
        _request(
            bound_context={
                "kind": "incident",
                "incident_id": "00000000-0000-0000-0000-000000000301",
                "correlation_id": "incident-correlation-301",
            }
        )
    )

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "answered"


async def test_incident_bound_turn_reading_another_incident_is_held() -> None:
    encoded = await _processor(_Runtime(_incident_evidence_runtime_result())).process(
        _request(
            bound_context={
                "kind": "incident",
                "incident_id": "00000000-0000-0000-0000-000000000999",
                "correlation_id": "incident-correlation-999",
            }
        )
    )

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "held"
    assert semantic["reason_code"] == "incident_evidence_mismatched_binding"
    assert semantic["unavailable_reason"] == "authoritative_evidence_unavailable"
    assert semantic["answer"].startswith("## Evidence from a different incident was read")


async def test_exact_source_unavailable_is_projected_as_blocked() -> None:
    encoded = await _processor(
        _Runtime(
            _runtime_result(
                "held",
                reason="semantic_exact_source_unavailable",
            )
        )
    ).process(_request(locale="en"))

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "held"
    assert semantic["reason_code"] == "semantic_exact_source_unavailable"
    assert semantic["unavailable_reason"] == "authoritative_evidence_unavailable"
    assert semantic["answer"] == "Blocked: the exact source is unavailable."


async def test_knowledge_source_status_unavailable_is_projected_exactly() -> None:
    encoded = await _processor(
        _Runtime(
            _runtime_result(
                "held",
                reason="semantic_knowledge_source_status_unavailable",
            )
        )
    ).process(_request(locale="en"))

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "held"
    assert semantic["reason_code"] == "semantic_knowledge_source_status_unavailable"
    assert semantic["unavailable_reason"] == "authoritative_evidence_unavailable"
    assert semantic["answer"] == (
        "Unavailable: no verified knowledge-source status capability is bound."
    )


async def test_unbound_turn_without_incident_evidence_still_answers() -> None:
    encoded = await _processor(_Runtime(_runtime_result("answered"))).process(_request())

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "answered"


@pytest.mark.parametrize(
    ("locale", "heading", "limitation"),
    [
        ("en", "## Ontology relationships", "grants no execution authority"),
        ("ko", "## 온톨로지 관계", "실행 권한을 부여하지 않습니다"),
    ],
)
async def test_ontology_relationship_answer_is_exact_and_localized(
    locale: str,
    heading: str,
    limitation: str,
) -> None:
    encoded = await _processor(_Runtime(_ontology_relationship_runtime_result())).process(
        _request(locale=locale)
    )

    projection = _projection(encoded)
    semantic = projection["semantic_result"]
    assert semantic["disposition"] == "answered"
    answer = semantic["answer"]
    assert answer.startswith(heading)
    assert "`VmTaskRun` --`executes_task`--> `PythonTask` (`many_to_one`)" in answer
    assert "immutable PythonTask artifact selected by a VM task run" in answer
    assert limitation in answer
    relationships = projection["payload"]["technical_details"]["outputs"][0][
        "ontology_relationships"
    ]
    assert relationships["ontology_release_digest"] == RELEASE_DIGEST
    assert relationships["execution_authority"] is False


async def test_ontology_relationship_answer_rejects_stale_release_output() -> None:
    encoded = await _processor(
        _Runtime(
            _ontology_relationship_runtime_result(output_release_digest="sha256:" + ("f" * 64))
        )
    ).process(_request())

    semantic = _projection(encoded)["semantic_result"]
    assert semantic["disposition"] == "held"
    assert semantic["reason_code"] == "semantic_evidence_incomplete"


async def test_answered_rule_search_projects_exact_candidate_receipt() -> None:
    projection = _projection(
        await _processor(_Runtime(_rule_search_runtime_result())).process(_request())
    )

    rule_search = projection["payload"]["rule_search"]
    assert projection["status"] == "answered"
    assert rule_search["query_digest"].startswith("sha256:")
    assert rule_search["retrieval_receipt"]["generation_digest"] == GENERATION_DIGEST
    assert rule_search["function_invocation_receipt_digest"].startswith("sha256:")
    assert rule_search["function_invocation_receipt"] == {
        "blocked_by": [],
        "capability": "query.function",
        "completed_at": NOW.isoformat().replace("+00:00", "Z"),
        "depends_on": [],
        "duration_ms": 5,
        "evidence_mode": "operational",
        "evidence_refs": ["inventory:evidence-1"],
        "goal_id": "resources",
        "intent": "function",
        "reason": None,
        "started_at": NOW.isoformat().replace("+00:00", "Z"),
        "status": "completed",
        "task_id": "query:resources",
    }
    assert rule_search["candidates"] == [
        {
            "authority": "candidate_only",
            "components": {"hybrid": 0.9},
            "rank": 1,
            "rule_ref": "rule.one",
        }
    ]
    assert rule_search["authority"] == "candidate_only"
    assert rule_search["execution_authority"] is False


async def test_authority_bearing_rule_search_output_is_held() -> None:
    projection = _projection(
        await _processor(_Runtime(_rule_search_runtime_result(execution_authority=True))).process(
            _request()
        )
    )

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"
    assert (
        projection["semantic_result"]["unavailable_reason"] == "authoritative_evidence_unavailable"
    )
    assert "rule_search" not in projection["payload"]


async def test_rule_search_receipt_must_bind_exact_function_capability() -> None:
    runtime_result = _rule_search_runtime_result()
    assert runtime_result.execution is not None
    assert runtime_result.intent_graph is not None
    assert runtime_result.intent_graph_evidence is not None
    receipt = runtime_result.execution.receipts[0].model_copy(
        update={"intent": "object_set", "capability": "query.object_set"}
    )
    execution = QueryPlanExecution(
        plan_digest=runtime_result.execution.plan_digest,
        status=runtime_result.execution.status,
        results=runtime_result.execution.results,
        receipts=(receipt,),
        output_node_ids=runtime_result.execution.output_node_ids,
    )
    graph = {
        **runtime_result.intent_graph,
        "goals": [
            {
                **runtime_result.intent_graph["goals"][0],
                "intent": "object_set",
                "capability": "query.object_set",
            }
        ],
    }
    evidence = {
        **runtime_result.intent_graph_evidence,
        "goals": [
            {
                **runtime_result.intent_graph_evidence["goals"][0],
                "intent": "object_set",
                "capability": "query.object_set",
            }
        ],
    }
    tampered = RuntimeSemanticTurnResult(
        disposition=runtime_result.disposition,
        reason=runtime_result.reason,
        planning=runtime_result.planning,
        execution=execution,
        intent_graph=graph,
        intent_graph_evidence=evidence,
    )

    projection = _projection(await _processor(_Runtime(tampered)).process(_request()))

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"
    assert "rule_search" not in projection["payload"]


async def test_rule_search_receipt_must_match_function_operation_and_corpus() -> None:
    runtime_result = _rule_search_runtime_result()
    assert runtime_result.execution is not None
    node_result = runtime_result.execution.results["resources"]
    output = cast(dict[str, object], node_result.value)
    receipt = RuleSearchReceipt.model_validate(output["retrieval_receipt"]).model_copy(
        update={"operation": "explain", "corpus": "discovery"}
    )
    output["retrieval_receipt"] = receipt.model_dump(mode="json")
    output["retrieval_receipt_digest"] = receipt.digest

    projection = _projection(await _processor(_Runtime(runtime_result)).process(_request()))

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"
    assert "rule_search" not in projection["payload"]


async def test_rule_search_candidates_must_not_exceed_function_limit() -> None:
    runtime_result = _rule_search_runtime_result()
    assert runtime_result.execution is not None
    assert runtime_result.planning.plan is not None
    original_node = runtime_result.planning.plan.nodes[0]
    query = {**RULE_QUERY, "limit": 1}
    node = SimpleNamespace(
        node_id=original_node.node_id,
        kind=original_node.kind,
        arguments={"function_name": "catalog.search_rules", "arguments": query},
    )
    plan = SimpleNamespace(
        ontology_release_digest=runtime_result.planning.plan.ontology_release_digest,
        semantic_catalog_digest=runtime_result.planning.plan.semantic_catalog_digest,
        plan_digest=runtime_result.planning.plan.plan_digest,
        nodes=(node,),
    )
    output = cast(dict[str, object], runtime_result.execution.results["resources"].value)
    candidates = cast(list[dict[str, object]], output["candidates"])
    candidates.append(
        {
            "rule_ref": "rule.two",
            "rank": 2,
            "components": {"hybrid": 0.8},
            "authority": "candidate_only",
        }
    )
    receipt_payload = cast(dict[str, object], output["retrieval_receipt"])
    receipt_results = cast(list[dict[str, object]], receipt_payload["results"])
    receipt_results.append(
        {
            "rule_ref": "rule.two",
            "rank": 2,
            "components": {"hybrid": 0.8},
        }
    )
    receipt_payload["query_digest"] = rule_search_query_digest(query)
    receipt = RuleSearchReceipt.model_validate(receipt_payload)
    output["retrieval_receipt"] = receipt.model_dump(mode="json")
    output["retrieval_receipt_digest"] = receipt.digest
    tampered = RuntimeSemanticTurnResult(
        disposition=runtime_result.disposition,
        reason=runtime_result.reason,
        planning=SimpleNamespace(
            plan=plan,
            frame=SimpleNamespace(
                operation=SemanticOperation.SELECT,
                output_shape="resource_list",
            ),
            manifest_digest=MANIFEST_DIGEST,
        ),
        execution=runtime_result.execution,
        intent_graph=runtime_result.intent_graph,
        intent_graph_evidence=runtime_result.intent_graph_evidence,
    )

    projection = _projection(await _processor(_Runtime(tampered)).process(_request()))

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"
    assert "rule_search" not in projection["payload"]


async def test_answered_runtime_without_evidence_is_held() -> None:
    runtime_result = _runtime_result("answered")
    assert runtime_result.execution is not None
    incomplete_execution = QueryPlanExecution(
        plan_digest=runtime_result.execution.plan_digest,
        status="completed",
        results=runtime_result.execution.results,
        receipts=tuple(
            receipt.model_copy(update={"evidence_refs": ()})
            for receipt in runtime_result.execution.receipts
        ),
        output_node_ids=runtime_result.execution.output_node_ids,
    )
    incomplete = RuntimeSemanticTurnResult(
        disposition="answered",
        reason=runtime_result.reason,
        planning=runtime_result.planning,
        execution=incomplete_execution,
        intent_graph=runtime_result.intent_graph,
        intent_graph_evidence=runtime_result.intent_graph_evidence,
    )

    projection = _projection(await _processor(_Runtime(incomplete)).process(_request()))

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"


async def test_answered_runtime_with_inconsistent_projected_evidence_is_held() -> None:
    runtime_result = _runtime_result("answered")
    assert runtime_result.intent_graph_evidence is not None
    inconsistent_evidence = {
        **runtime_result.intent_graph_evidence,
        "status": "partial",
    }
    inconsistent = RuntimeSemanticTurnResult(
        disposition="answered",
        reason=runtime_result.reason,
        planning=runtime_result.planning,
        execution=runtime_result.execution,
        intent_graph=runtime_result.intent_graph,
        intent_graph_evidence=inconsistent_evidence,
    )

    projection = _projection(await _processor(_Runtime(inconsistent)).process(_request()))

    assert projection["status"] == "held"
    assert projection["semantic_result"]["reason_code"] == "semantic_evidence_incomplete"


async def test_execution_hold_preserves_verified_attempts_and_limitations() -> None:
    runtime_result = _runtime_result("answered")
    assert runtime_result.execution is not None
    assert runtime_result.intent_graph_evidence is not None
    unavailable_receipt = runtime_result.execution.receipts[0].model_copy(
        update={
            "status": TaskStatus.UNAVAILABLE,
            "reason": "capability_unavailable",
            "evidence_refs": (),
        }
    )
    execution = QueryPlanExecution(
        plan_digest=runtime_result.execution.plan_digest,
        status="failed",
        results=MappingProxyType({}),
        receipts=(unavailable_receipt,),
        output_node_ids=runtime_result.execution.output_node_ids,
    )
    evidence_goal = {
        **runtime_result.intent_graph_evidence["goals"][0],
        "status": "unavailable",
        "reason": "capability_unavailable",
        "evidence_refs": [],
    }
    held = RuntimeSemanticTurnResult(
        disposition="held",
        reason="semantic_execution_failed",
        planning=runtime_result.planning,
        execution=execution,
        intent_graph=runtime_result.intent_graph,
        intent_graph_evidence={
            **runtime_result.intent_graph_evidence,
            "status": "unavailable",
            "evidence_mode": "held_for_review",
            "goals": [evidence_goal],
        },
    )

    projection = _projection(await _processor(_Runtime(held)).process(_request(locale="ko")))

    semantic = projection["semantic_result"]
    assert projection["status"] == "held"
    assert semantic["reason_code"] == "semantic_evidence_held"
    assert semantic["unavailable_reason"] == "authoritative_evidence_unavailable"
    assert semantic["plan_digest"] == PLAN_DIGEST
    assert semantic["checks_completed"] == 0
    assert semantic["checks_total"] == 1
    assert semantic["intent_graph_evidence"]["goals"][0]["reason"] == ("capability_unavailable")
    assert "`query.object_set` - `unavailable`" in semantic["answer"]
    assert "`query.object_set`: `capability_unavailable`" in semantic["answer"]
    assert "실제로 시도한 읽기 전용 조사" in semantic["answer"]
    assert "다음 안전 단계" in semantic["answer"]
    assert "`execution_authority=false`" in semantic["answer"]


async def test_s3_execution_hold_projects_recovery_continuation() -> None:
    runtime_result = _runtime_result("answered")
    assert runtime_result.execution is not None
    target = SimpleNamespace(
        role=InvestigationEntityRole.AFFECTED_TARGET,
        object_type_candidates=("BusinessService",),
        span=SimpleNamespace(text="service-example-api"),
    )
    runtime_result.planning.investigation_intent = SimpleNamespace(
        entities=(target,),
        symptom_measures=(SimpleNamespace(measure_id="latency", concept_id="service.latency"),),
        primary_symptom_measure_id="latency",
        hypotheses=(SimpleNamespace(cause_measure_concept="dependency.latency"),),
    )
    runtime_result.planning.frame.frame_digest = f"sha256:{'f' * 64}"
    runtime_result.planning.plan.nodes = (
        SimpleNamespace(
            node_id="symptom-baseline",
            arguments={"start": "2026-08-11T11:40:00Z", "end": "2026-08-11T11:50:00Z"},
        ),
        SimpleNamespace(
            node_id="symptom-current",
            arguments={"start": "2026-08-11T11:50:00Z", "end": NOW.isoformat()},
        ),
    )
    unavailable_receipt = runtime_result.execution.receipts[0].model_copy(
        update={"status": TaskStatus.UNAVAILABLE, "reason": "capability_unavailable"}
    )
    execution = replace(
        runtime_result.execution,
        status="failed",
        receipts=(unavailable_receipt,),
    )
    held = replace(
        runtime_result,
        disposition="held",
        reason="semantic_execution_failed",
        execution=execution,
    )

    projection = _projection(await _processor(_Runtime(held)).process(_request()))

    continuation = projection["payload"]["investigation_continuation"]
    assert continuation["source_session_id"] == "session-1"
    assert continuation["source_turn_sequence"] == 3
    assert continuation["target_value"] == "service-example-api"
    assert continuation["execution_authority"] is False


async def test_unavailable_and_internal_failure_are_detail_free_holds() -> None:
    unavailable = _projection(await _processor(None).process(_request()))
    failed = _projection(
        await _processor(_Runtime(failure=RuntimeError("secret provider response"))).process(
            _request(idempotency_key="failed")
        )
    )

    assert unavailable["semantic_result"]["reason_code"] == "semantic_runtime_unavailable"
    assert failed["semantic_result"]["reason_code"] == "semantic_runtime_failed"
    assert "secret" not in json.dumps(failed)


async def test_consumer_publishes_projection_and_dlqs_publish_failure() -> None:
    class _FailingProjectionBus(InMemoryEventBus):
        projection_failures_remaining = 0

        async def publish(
            self,
            topic: str,
            key: str,
            payload: Mapping[str, Any],
        ) -> PublishReceipt:
            if self.projection_failures_remaining and topic == "operator.projection":
                self.projection_failures_remaining -= 1
                raise RuntimeError("synthetic publish failure")
            return await super().publish(topic, key, payload)

    bus = _FailingProjectionBus()
    await bus.publish("operator.request", "one", _request(idempotency_key="one"))
    await consume_semantic_turns(
        bus=bus,
        request_topic="operator.request",
        projection_topic="operator.projection",
        group_id="core-semantic",
        processor=_processor(None),
        stop=asyncio.Event(),
    )
    projections = [item async for item in bus.subscribe("operator.projection", "assert")]
    assert projections[0].payload["status"] == "held"

    await bus.publish("operator.request", "retry", _request(idempotency_key="retry"))
    bus.projection_failures_remaining = 2
    await consume_semantic_turns(
        bus=bus,
        request_topic="operator.request",
        projection_topic="operator.projection",
        group_id="core-semantic",
        processor=_processor(None),
        stop=asyncio.Event(),
        publish_retry_delay_seconds=0,
    )
    retried = [item async for item in bus.subscribe("operator.projection", "retry-assert")]
    assert retried[-1].payload["idempotency_key"] == "retry"

    await bus.publish("operator.request", "two", _request(idempotency_key="two"))
    bus.projection_failures_remaining = 3
    await consume_semantic_turns(
        bus=bus,
        request_topic="operator.request",
        projection_topic="operator.projection",
        group_id="core-semantic",
        processor=_processor(None),
        stop=asyncio.Event(),
        publish_retry_delay_seconds=0,
    )
    dlq = [item async for item in bus.subscribe("operator.request.dlq", "assert")]
    assert dlq[-1].payload["reason"] == "semantic_turn_publish_failed"


def test_runtime_binding_is_optional_explicit_and_rejects_partial_transport() -> None:
    state_store = InMemoryStateStore()

    assert (
        semantic_turn_binding_from_config(
            state_store=state_store,
            runtime=None,
            config={},
        )
        is None
    )
    with pytest.raises(RuntimeError, match="topics MUST be configured together"):
        semantic_turn_binding_from_config(
            state_store=state_store,
            runtime=None,
            config={"FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.request"},
        )
    binding = semantic_turn_binding_from_config(
        state_store=state_store,
        runtime=None,
        config={
            "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.request",
            "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "operator.projection",
        },
    )
    assert binding is not None
    assert binding.available is False
    assert binding.unavailable_reason == "semantic_runtime_unavailable"


def test_incident_profile_facts_surface_every_populated_field() -> None:
    facts = incident_profile_facts(
        {
            "title": "Trace propagation gap",
            "severity": "sev2",
            "status": "triaging",
            "vertical": "resilience",
            "opened_at": "2026-08-14T09:00:00Z",
            "last_updated_at": "2026-08-14T09:05:00Z",
            "actors": ["Heimdall", "operator@example.com"],
            "correlation_id": "incident-correlation-301",
        },
        korean=False,
    )

    assert facts == (
        ("Title", "Trace propagation gap"),
        ("Severity", "sev2"),
        ("Status", "triaging"),
        ("Vertical", "resilience"),
        ("First recorded", "2026-08-14T09:00:00Z"),
        ("Last recorded", "2026-08-14T09:05:00Z"),
        ("Actors", "Heimdall, operator@example.com"),
    )


def test_incident_profile_facts_omit_absent_fields_without_inventing_values() -> None:
    assert incident_profile_facts({"status": "open", "severity": None}, korean=False) == (
        ("Status", "open"),
    )
    assert incident_profile_facts({"title": "   "}, korean=False) == ()
    assert incident_profile_facts(None, korean=False) == ()


def test_incident_timeline_keeps_the_most_recent_bounded_records() -> None:
    evidence = [
        {
            "audit_ref": f"audit:{index}",
            "actor": "Heimdall",
            "action_kind": "incident.transition",
            "mode": "shadow",
            "recorded_at": f"2026-08-14T09:{index:02d}:00Z",
        }
        for index in range(14)
    ]

    rows = incident_timeline_rows(evidence)

    assert len(rows) == 10
    assert rows[0]["audit_ref"] == "audit:4"
    assert rows[-1]["audit_ref"] == "audit:13"
    assert rows[-1]["actor"] == "Heimdall"


def test_incident_timeline_skips_records_without_an_audit_anchor() -> None:
    """An invented anchor would make an unattributable record look cited."""
    rows = incident_timeline_rows(
        [
            {"actor": "Heimdall", "recorded_at": "2026-08-14T09:00:00Z"},
            {"audit_ref": "audit:2", "recorded_at": "2026-08-14T09:05:00Z"},
        ]
    )

    assert len(rows) == 1
    assert rows[0]["audit_ref"] == "audit:2"
    assert rows[0]["actor"] == "-"


def test_incident_next_step_actions_follow_the_measured_gaps() -> None:
    assert incident_next_step_actions(["impact_evidence_missing"], korean=False) == (
        "collect impact evidence for the affected resources",
    )
    assert incident_next_step_actions(
        ["correlated_audit_truncated", "incident_profile_missing"],
        korean=False,
    ) == (
        "confirm an incident record exists for this correlation",
        "re-run this query with a higher record limit",
    )
    assert incident_next_step_actions((), korean=False) == ()
    assert incident_next_step_actions(["impact_evidence_missing"], korean=True) == (
        "영향받은 리소스의 영향 근거를 수집하세요",
    )


def test_korean_next_step_reads_as_korean_when_several_steps_apply() -> None:
    """Chaining polite imperatives with a comma is not a Korean sentence."""
    text = _incident_next_step_text(
        ["impact_evidence_missing", "grounded_citations_missing"],
        korean=True,
    )

    assert text == (
        "변경을 제안하기 전에 다음을 수행하세요. "
        "영향받은 리소스의 영향 근거를 수집하세요. "
        "각 주장을 감사 기록에 연결하는 근거 인용을 수집하세요."
    )
    assert "수집하세요," not in text
    assert (
        _incident_next_step_text(["impact_evidence_missing"], korean=True)
        == "변경을 제안하기 전에 영향받은 리소스의 영향 근거를 수집하세요."
    )


def test_incident_next_step_names_notification_route_configuration() -> None:
    root_cause = {"next_safe_step": "configure_notification_route"}

    assert _incident_next_step_text((), korean=False, root_cause=root_cause) == (
        "Before retrying delivery, configure at least one operational-alert channel in the "
        "notification registry."
    )
    assert _incident_next_step_text((), korean=True, root_cause=root_cause) == (
        "알림 전달을 다시 시도하기 전에 notification registry에 운영 알림 채널을 하나 이상 "
        "구성하세요."
    )
