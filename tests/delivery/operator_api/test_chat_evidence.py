"""Operational evidence retrieval for cross-screen Command Deck questions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.routes.chat_evidence import (
    OperationalEvidenceResolver,
    _is_memory_incident_text,
    needs_operational_evidence,
)
from fdai.delivery.operator_api.routes.chat_freshness_context import (
    response_evidence_freshness_context,
)
from fdai.delivery.operator_api.routes.chat_incident_dossier import (
    IncidentDossierIntent,
    classify_incident_dossier_intent,
)
from fdai.delivery.operator_api.routes.chat_verification import verify_answer


@dataclass(frozen=True, slots=True)
class OperationalWeaknessCase:
    prompt: str
    expects_operational: bool
    korean: bool = False
    view_context: dict[str, Any] | None = None


OPERATIONAL_WEAKNESS_CASES = (
    OperationalWeaknessCase("what caused the recent memory issue?", True),
    OperationalWeaknessCase("latest host memory incident cause", True),
    OperationalWeaknessCase("root cause of the last OOM incident", True),
    OperationalWeaknessCase("recent memory failure", True),
    OperationalWeaknessCase("why did the recent memory outage happen?", True),
    OperationalWeaknessCase("latest available memory problem cause", True),
    OperationalWeaknessCase("최근 메모리 이슈 원인이 뭐야?", True, korean=True),
    OperationalWeaknessCase("직전 메모리 장애 근본 원인", True, korean=True),
    OperationalWeaknessCase("최근 OOM 인시던트 왜 발생했어?", True, korean=True),
    OperationalWeaknessCase("최신 host memory 실패 원인", True, korean=True),
    OperationalWeaknessCase("last memory pressure incident", True),
    OperationalWeaknessCase("recent incident caused by memory leak", True),
    OperationalWeaknessCase("why is this screen showing attention?", False),
    OperationalWeaknessCase("이 화면의 수치는 왜 이래?", False, korean=True),
    OperationalWeaknessCase("what is Issue?", False, view_context={"routeId": "ontology"}),
    OperationalWeaknessCase(
        "Agent와 연결된 Issue는 뭐야?",
        False,
        korean=True,
        view_context={"routeId": "ontology"},
    ),
    OperationalWeaknessCase("db 에는 어떤 데이터가 있어?", False, korean=True),
    OperationalWeaknessCase("overall system health", False),
    OperationalWeaknessCase("restart the database", False),
    OperationalWeaknessCase("show Azure resources", False),
)

OPERATIONAL_RUBRIC_NAMES = (
    "intent-classification",
    "resolver-selection",
    "authority-selection",
    "matched-state",
    "selected-correlation",
    "selected-title",
    "grounded-hypothesis",
    "grounded-cause",
    "citation-present",
    "ungrounded-excluded",
    "audit-evidence-bounded",
    "candidate-count",
    "verification-authority",
    "verification-reason",
    "terminal-trust",
    "locale-aligned",
    "canonical-cause-present",
    "incident-reference",
    "telemetry-reference",
    "no-unsupported-guess",
)


def _seed_memory_incident(
    model: InMemoryConsoleReadModel, correlation: str = "corr-memory"
) -> None:
    model.record_audit_entry(
        {
            "event_id": "evt-memory",
            "correlation_id": correlation,
            "recorded_at": "2026-07-15T00:00:00+00:00",
            "summary": "Host memory pressure triggered an incident",
            "detail": "Available memory fell below the configured threshold.",
            "metric": "available_memory_bytes",
        },
        action_kind="incident.open",
    )
    model.record_audit_entry(
        {
            "event_id": "evt-memory",
            "correlation_id": correlation,
            "recorded_at": "2026-07-15T00:01:00+00:00",
            "rca_outcome": "grounded",
            "rca_tier": "t0",
            "rca_cause": "A workload memory leak exhausted available host memory.",
            "rca_confidence": 0.96,
            "rca_reason": "The allocation increase preceded the pressure signal.",
            "rca_citations": [{"kind": "telemetry", "ref": "metric:available_memory_bytes"}],
        },
        action_kind="rca.hypothesis",
    )


def _seed_memory_dossier(model: InMemoryConsoleReadModel) -> None:
    _seed_memory_incident(model)
    model.record_audit_entry(
        {
            "event_id": "evt-memory",
            "correlation_id": "corr-memory",
            "recorded_at": "2026-07-15T00:02:00+00:00",
            "affected_count": 12,
            "customer_impact": "Elevated request latency for the bounded service cohort.",
            "slo_impact": "Latency objective breached for 5 minutes.",
        },
        action_kind="impact.observed",
    )
    model.record_audit_entry(
        {
            "event_id": "evt-memory",
            "correlation_id": "corr-memory",
            "recorded_at": "2026-07-15T00:03:00+00:00",
            "decision": "Inspect the leaking workload before drafting mitigation.",
            "gate_decision": "hil",
        },
        action_kind="risk_gate.decided",
    )
    model.record_audit_entry(
        {
            "event_id": "evt-memory",
            "correlation_id": "corr-memory",
            "recorded_at": "2026-07-15T00:04:00+00:00",
            "status": "completed",
            "run_id": "investigation-run-memory",
            "phase": "evidence_collection",
        },
        action_kind="investigation.evidence_collected",
    )


def _seed_prior_recovered_memory_incident(model: InMemoryConsoleReadModel) -> None:
    model.record_audit_entry(
        {
            "event_id": "evt-prior-memory",
            "correlation_id": "corr-prior-memory",
            "recorded_at": "2026-07-10T00:00:00+00:00",
            "summary": "Prior host memory pressure incident",
            "detail": "Available memory fell below the threshold.",
        },
        action_kind="incident.open",
    )
    model.record_audit_entry(
        {
            "event_id": "evt-prior-memory",
            "correlation_id": "corr-prior-memory",
            "recorded_at": "2026-07-10T00:05:00+00:00",
            "outcome": "resolved",
            "summary": (
                "The workload was isolated; memory pressure and request latency recovered."
            ),
        },
        action_kind="remediation.verified",
    )


def test_detects_cross_screen_operational_question_but_not_current_screen_cause() -> None:
    assert needs_operational_evidence("what caused the recent memory issue?") is True
    korean_recent = "최근 메모리 이슈 원인이 뭐야?"
    korean_screen = "이 화면의 이 수치는 왜 이래?"
    assert needs_operational_evidence(korean_recent) is True
    assert needs_operational_evidence("why is this screen showing attention?") is False
    assert needs_operational_evidence(korean_screen) is False


def test_dossier_classifier_preserves_korean_similarity_and_evidence_precedence() -> None:
    assert (
        classify_incident_dossier_intent("이전 인시던트에서 효과 있었던 복구 알려줘")
        is IncidentDossierIntent.SIMILAR
    )
    assert (
        classify_incident_dossier_intent("다음 단계 결정에 사용한 근거만 보여줘")
        is IncidentDossierIntent.CONSUMED_EVIDENCE
    )


@pytest.mark.parametrize(
    "prompt",
    (
        "vscode 최신버전은?",
        "VS Code latest version?",
        "Python 최신버전은?",
        "latest Kubernetes release?",
    ),
)
def test_public_software_freshness_does_not_trigger_incident_lookup(prompt: str) -> None:
    assert needs_operational_evidence(prompt) is False


@pytest.mark.parametrize(
    "prompt",
    (
        "latest memory incident",
        "recent deployment failure",
        "최신 메모리 인시던트 원인은?",
        "최근 배포 실패를 보여줘",
    ),
)
def test_operational_recency_with_incident_context_still_resolves(prompt: str) -> None:
    assert needs_operational_evidence(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    (
        "Build an ordered timeline from first signal through recovery.",
        "Show the incident chronology from alert to recovery.",
        "경고부터 복구까지 타임라인을 보여줘.",
        "Rank the causal hypotheses with supporting and contradictory evidence.",
        "가능한 원인을 근거와 반증까지 포함해 순위를 매겨줘.",
        "Has this happened before, and which prior recovery actually worked?",
        "Which earlier incident had an effective remediation?",
        "Quantify the customer and service-level impact of this incident.",
        "What is the safest highest-value next step?",
        "그 결론을 뒷받침하는 증거만 보여줘.",
        "Show only the evidence consumed by the conclusion.",
        "What remains unknown, and which evidence would resolve it?",
        "List unresolved unknowns and the evidence needed to decide.",
        "Start a bounded deep investigation and report each evidence phase.",
    ),
)
def test_incident_analysis_language_triggers_operational_lookup(prompt: str) -> None:
    assert needs_operational_evidence(prompt) is True


def test_ontology_issue_terms_alone_do_not_trigger_incident_lookup() -> None:
    ontology = {"routeId": "ontology"}
    assert needs_operational_evidence("what is Issue?", ontology) is False
    assert needs_operational_evidence("Agent와 연결된 Issue는 뭐야?", ontology) is False
    assert needs_operational_evidence("이슈는 뭐야?", ontology) is False
    assert needs_operational_evidence("recent memory issue cause", ontology) is True
    assert needs_operational_evidence("what issue happened?") is True


def test_memory_signal_tokens_do_not_match_headroom() -> None:
    assert _is_memory_incident_text("capacity has ample headroom") is False
    assert _is_memory_incident_text("the process was OOM killed") is True


async def test_resolves_recent_memory_incident_with_grounded_rca() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model)

    evidence = await OperationalEvidenceResolver(model).resolve("최근 메모리 이슈 원인이 뭐야?")

    assert evidence is not None
    assert evidence["status"] == "matched"
    assert evidence["selected_incident"]["correlation_id"] == "corr-memory"
    assert evidence["grounded_hypotheses"][0]["cause"].startswith("A workload memory leak")
    assert evidence["grounded_hypotheses"][0]["citations"] == [
        {"kind": "telemetry", "ref": "metric:available_memory_bytes"}
    ]
    freshness = response_evidence_freshness_context({"_operational_evidence": evidence})
    assert freshness is not None
    assert freshness.source == "server-read-model-incident"
    assert freshness.window_start.isoformat() == "2026-07-15T00:00:00+00:00"
    assert freshness.observed_at.isoformat() == "2026-07-15T00:01:00+00:00"
    assert evidence["evidence_cutoff_seq"] == 2


async def test_excludes_ungrounded_rca_from_cause_evidence() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model)
    model.record_audit_entry(
        {
            "event_id": "evt-memory",
            "correlation_id": "corr-memory",
            "recorded_at": "2026-07-15T00:02:00+00:00",
            "rca_outcome": "abstained",
            "rca_tier": "t2",
            "rca_cause": "Unsupported guess must not be presented.",
            "rca_reason": "No citations.",
            "rca_citations": [],
        },
        action_kind="rca.hypothesis",
    )

    evidence = await OperationalEvidenceResolver(model).resolve("recent memory issue cause")

    assert evidence is not None
    causes = [item["cause"] for item in evidence["grounded_hypotheses"]]
    assert "Unsupported guess must not be presented." not in causes
    assert evidence["ungrounded_hypothesis_count"] == 1


@pytest.mark.parametrize(
    ("prompt", "locale", "reason_code", "answer_token"),
    (
        (
            "Build an ordered timeline from first signal through recovery.",
            "en",
            "incident_timeline_grounded",
            "ordered by audit sequence",
        ),
        (
            "경고부터 복구까지 타임라인을 보여줘.",
            "ko",
            "incident_timeline_grounded",
            "인과관계를 의미하지 않습니다",
        ),
        (
            "Rank the causal hypotheses with supporting and contradictory evidence.",
            "en",
            "incident_hypotheses_grounded",
            "No separately structured contradictory evidence",
        ),
        (
            "가능한 원인을 근거와 반증까지 포함해 순위를 매겨줘.",
            "ko",
            "incident_hypotheses_grounded",
            "반증 근거",
        ),
    ),
)
async def test_incident_dossier_intents_render_from_bounded_server_evidence(
    prompt: str,
    locale: str,
    reason_code: str,
    answer_token: str,
) -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model)

    evidence = await OperationalEvidenceResolver(model).resolve(prompt)

    assert evidence is not None
    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale=locale)
    assert verified.reason_code == reason_code
    assert verified.status == "corrected"
    assert verified.checks_completed == 1
    assert answer_token in verified.answer
    assert "incident:corr-memory" in verified.evidence_refs


@pytest.mark.parametrize(
    ("prompt", "locale", "reason_code", "answer_token"),
    (
        (
            "Quantify the customer and service-level impact of this incident.",
            "en",
            "incident_impact_grounded",
            "affected_count: 12",
        ),
        (
            "이 장애가 사용자와 서비스 수준 목표에 미친 영향은 뭐야?",
            "ko",
            "incident_impact_grounded",
            "slo_impact",
        ),
        (
            "What is the safest highest-value next step?",
            "en",
            "incident_next_action_grounded",
            "does not grant execution authority",
        ),
        (
            "지금 가장 먼저 확인하거나 완화해야 할 것은 뭐야?",
            "ko",
            "incident_next_action_grounded",
            "실행 권한을 부여하지 않습니다",
        ),
        (
            "Show only the evidence consumed by the conclusion.",
            "en",
            "incident_consumed_evidence_grounded",
            "telemetry:metric:available_memory_bytes",
        ),
        (
            "그 결론을 뒷받침하는 증거만 보여줘.",
            "ko",
            "incident_consumed_evidence_grounded",
            "incident:corr-memory",
        ),
        (
            "What remains unknown, and which evidence would resolve it?",
            "en",
            "incident_unknowns_grounded",
            "Unresolved evidence gaps",
        ),
        (
            "아직 확인하지 못한 부분과 필요한 추가 증거는 뭐야?",
            "ko",
            "incident_unknowns_grounded",
            "아직 확인되지 않은 항목",
        ),
        (
            "Start a bounded deep investigation and report each evidence phase.",
            "en",
            "deep_investigation_progress_grounded",
            "investigation.evidence_collected",
        ),
        (
            "이 문제를 깊이 조사하고 진행 단계를 알려줘.",
            "ko",
            "deep_investigation_progress_grounded",
            "기록된 investigation phase",
        ),
    ),
)
async def test_remaining_incident_dossier_questions_use_explicit_evidence(
    prompt: str,
    locale: str,
    reason_code: str,
    answer_token: str,
) -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_dossier(model)

    evidence = await OperationalEvidenceResolver(model).resolve(
        prompt,
        conversation_context={
            "incident_id": "INC-corr-memory",
            "correlation_id": "corr-memory",
        },
    )

    assert evidence is not None
    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale=locale)
    assert verified.reason_code == reason_code
    assert verified.status == "corrected"
    assert verified.checks_completed == 1
    assert answer_token in verified.answer


@pytest.mark.parametrize(
    ("prompt", "locale"),
    (
        ("Has this happened before, and which prior recovery actually worked?", "en"),
        ("이전에도 같은 문제가 있었고 무엇이 효과가 있었어?", "ko"),
    ),
)
async def test_similar_incident_requires_matching_domain_and_successful_recovery(
    prompt: str,
    locale: str,
) -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_dossier(model)
    _seed_prior_recovered_memory_incident(model)

    evidence = await OperationalEvidenceResolver(model).resolve(
        prompt,
        conversation_context={
            "incident_id": "INC-corr-memory",
            "correlation_id": "corr-memory",
        },
    )

    assert evidence is not None
    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale=locale)
    assert verified.reason_code == "similar_incident_grounded"
    assert verified.status == "corrected"
    assert "corr-prior-memory" in verified.answer
    assert "remediation.verified" in verified.answer
    assert "incident:corr-prior-memory" in verified.evidence_refs
    assert any(ref.startswith("audit:corr-prior-memory:") for ref in verified.evidence_refs)


async def test_synthetic_incident_id_cannot_override_concrete_incident_identity() -> None:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "event_id": "evt-concrete",
            "correlation_id": "corr-concrete",
            "incident_id": "incident-concrete-v2",
            "recorded_at": "2026-07-15T00:00:00+00:00",
            "summary": "Concrete incident identity",
        },
        action_kind="incident.open",
    )

    evidence = await OperationalEvidenceResolver(model).resolve(
        "Build an ordered timeline from first signal through recovery.",
        conversation_context={
            "incident_id": "INC-corr-concrete",
            "correlation_id": "corr-concrete",
        },
    )

    assert evidence is not None
    assert evidence["status"] == "none"
    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")
    assert verified.reason_code == "selected_incident_context_unavailable"


def test_consumed_evidence_uses_only_primary_grounded_conclusion() -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "consumed_evidence",
        "selected_incident": {"correlation_id": "corr-memory"},
        "grounded_hypotheses": [
            {
                "cause": "Primary cause",
                "citations": [{"kind": "telemetry", "ref": "metric:primary"}],
            },
            {
                "cause": "Alternative cause",
                "citations": [{"kind": "telemetry", "ref": "metric:alternative"}],
            },
        ],
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert "telemetry:metric:primary" in verified.evidence_refs
    assert "telemetry:metric:alternative" not in verified.evidence_refs


def test_similar_incident_lookup_failure_is_not_rendered_as_empty_history() -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "similar",
        "selected_incident": {
            "correlation_id": "corr-memory",
            "title": "Memory incident",
            "status": "resolved",
            "last_updated_at": "2026-07-15T00:04:00+00:00",
        },
        "similar_incident_status": "unavailable",
        "similar_incidents": [],
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert verified.status == "unverified"
    assert verified.reason_code == "similar_incident_lookup_unavailable"
    assert verified.checks_completed == 0
    assert "was not confirmed" in verified.answer
    assert verified.evidence_refs == ()


def test_deep_investigation_phase_without_run_receipt_does_not_claim_progress() -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "deep_investigation",
        "selected_incident": {"correlation_id": "corr-memory"},
        "audit_evidence": [
            {
                "seq": 4,
                "recorded_at": "2026-07-15T00:04:00+00:00",
                "action_kind": "investigation.evidence_collected",
                "fields": {"status": "completed"},
            }
        ],
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert verified.status == "unverified"
    assert verified.reason_code == "deep_investigation_receipt_required"
    assert verified.checks_completed == 0
    assert "No durable receipt" in verified.answer


async def test_returns_none_when_topic_does_not_match_recent_incidents() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model)

    evidence = await OperationalEvidenceResolver(model).resolve("recent network issue cause")

    assert evidence is not None
    assert evidence["status"] == "none"
    assert evidence["searched_recent_incidents"] == 1


async def test_incident_memory_index_is_not_a_host_memory_issue() -> None:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "event_id": "evt-recall",
            "correlation_id": "corr-recall",
            "recorded_at": "2026-07-15T00:00:00+00:00",
            "summary": "Recalled a resolved incident",
            "detail": "Searched incident_memory with cosine similarity.",
        },
        action_kind="similarity.recall",
    )

    evidence = await OperationalEvidenceResolver(model).resolve("recent memory issue cause")

    assert evidence is not None
    assert evidence["status"] == "none"


async def test_returns_ambiguous_candidates_without_recency_tiebreak() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model, "corr-memory-a")
    _seed_memory_incident(model, "corr-memory-b")

    evidence = await OperationalEvidenceResolver(model).resolve("memory issue cause")

    assert evidence is not None
    assert evidence["status"] == "ambiguous"
    assert len(evidence["candidates"]) == 2


async def test_summary_request_returns_all_matching_incidents_without_selection() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model, "corr-memory-a")
    _seed_memory_incident(model, "corr-memory-b")

    evidence = await OperationalEvidenceResolver(model).resolve("인시던트를 요약해줘")

    assert evidence is not None
    assert evidence["status"] == "summary"
    assert {item["correlation_id"] for item in evidence["incidents"]} == {
        "corr-memory-a",
        "corr-memory-b",
    }
    assert evidence["searched_recent_incidents"] == 2

    english_evidence = await OperationalEvidenceResolver(model).resolve(
        "please summarize all the incidents"
    )

    assert english_evidence is not None
    assert english_evidence["status"] == "summary"
    assert len(english_evidence["incidents"]) == 2


async def test_latest_summary_selects_one_incident() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model, "corr-memory-a")
    _seed_memory_incident(model, "corr-memory-b")

    evidence = await OperationalEvidenceResolver(model).resolve(
        "Summarize the latest incident, impact, status, and outcome."
    )

    assert evidence is not None
    assert evidence["status"] == "matched"
    assert evidence["candidate_count"] == 2


async def test_generic_timeline_language_requires_incident_selection() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model, "corr-memory-a")
    _seed_memory_incident(model, "corr-memory-b")

    evidence = await OperationalEvidenceResolver(model).resolve(
        "Build an ordered timeline from first signal through recovery."
    )

    assert evidence is not None
    assert evidence["status"] == "ambiguous"
    assert len(evidence["candidates"]) == 2

    root_cause = await OperationalEvidenceResolver(model).resolve(
        "What is the strongest supported root cause for this incident?"
    )

    assert root_cause is not None
    assert root_cause["status"] == "ambiguous"
    assert len(root_cause["candidates"]) == 2


async def test_exact_incident_binding_wins_over_equal_topic_matches() -> None:
    class RecordingReadModel(InMemoryConsoleReadModel):
        incident_queries: list[dict[str, Any]]

        def __init__(self) -> None:
            super().__init__()
            self.incident_queries = []

        async def list_incidents(self, **kwargs):  # type: ignore[no-untyped-def]
            self.incident_queries.append(dict(kwargs))
            return await super().list_incidents(**kwargs)

    model = RecordingReadModel()
    _seed_memory_incident(model, "corr-memory-a")
    _seed_memory_incident(model, "corr-memory-b")

    evidence = await OperationalEvidenceResolver(model).resolve(
        "what is happening?",
        conversation_context={
            "kind": "incident",
            "incident_id": "INC-corr-memory-b",
            "correlation_id": "corr-memory-b",
            "selected_agent": "Var",
        },
    )

    assert evidence is not None
    assert evidence["status"] == "matched"
    assert evidence["selected_incident"]["correlation_id"] == "corr-memory-b"
    assert evidence["candidate_count"] == 1
    assert evidence["selected_agent_context"] == "Var"
    assert evidence["selected_incident"]["involved_agents"] == ["Forseti"]
    assert evidence["audit_evidence"][0]["agent"] == "Forseti"
    assert model.incident_queries == [
        {
            "status": "all",
            "limit": 1,
            "cursor": None,
            "correlation_id": "corr-memory-b",
        }
    ]


async def test_stale_incident_binding_never_falls_back_to_fuzzy_match() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model, "corr-memory-a")

    evidence = await OperationalEvidenceResolver(model).resolve(
        "memory issue cause",
        conversation_context={
            "kind": "incident",
            "incident_id": "INC-missing",
            "correlation_id": "corr-missing",
        },
    )

    assert evidence is not None
    assert evidence["status"] == "none"
    assert "selected_incident" not in evidence
    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")
    assert verified.status == "unverified"
    assert verified.reason_code == "selected_incident_context_unavailable"
    assert "Select the incident again" in verified.answer


async def test_malformed_incident_binding_returns_typed_context_hold() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model)

    evidence = await OperationalEvidenceResolver(model).resolve(
        "What remains unknown?",
        conversation_context={"incident_id": "INC-corr-memory"},
    )

    assert evidence == {
        "authority": "server_read_model",
        "status": "none",
        "reason": "selected incident context is invalid",
    }
    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")
    assert verified.status == "unverified"
    assert verified.reason_code == "selected_incident_context_unavailable"
    assert verified.checks_completed == 0


def test_consumed_evidence_requires_an_actual_citation() -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "consumed_evidence",
        "selected_incident": {"correlation_id": "corr-memory"},
        "grounded_hypotheses": [],
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert verified.status == "unverified"
    assert verified.reason_code == "incident_consumed_evidence_unavailable"
    assert verified.checks_completed == 0
    assert verified.evidence_refs == ()


def test_korean_unknowns_localize_each_gap_not_only_the_heading() -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "unknowns",
        "selected_incident": {"correlation_id": "corr-memory"},
        "grounded_hypotheses": [],
        "audit_evidence": [],
        "ungrounded_hypothesis_count": 1,
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="ko")

    assert verified.status == "corrected"
    assert "사용자 및 SLO 영향 측정값" in verified.answer
    assert "customer and SLO impact measurements" not in verified.answer


def test_dossier_rejects_missing_selected_incident_identity() -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "timeline",
        "audit_evidence": [{"seq": 1, "action_kind": "incident.open"}],
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert verified.status == "unverified"
    assert verified.reason_code == "incident_dossier_context_invalid"
    assert verified.evidence_refs == ()


@pytest.mark.parametrize("intent", ("hypotheses", "consumed_evidence"))
def test_dossier_rejects_malformed_citation_refs(intent: str) -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": intent,
        "selected_incident": {"correlation_id": "corr-memory"},
        "grounded_hypotheses": [
            {
                "cause": "Unsupported without a valid citation ref.",
                "citations": [{"kind": "telemetry", "ref": ""}],
            }
        ],
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert verified.status == "unverified"
    assert verified.checks_completed == 0
    assert verified.evidence_refs == ()


@pytest.mark.parametrize("confidence", (float("nan"), float("inf"), -0.1, 1.1))
def test_dossier_hides_invalid_grounded_hypothesis_confidence(confidence: float) -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "hypotheses",
        "selected_incident": {"correlation_id": "corr-memory"},
        "grounded_hypotheses": [
            {
                "cause": "Grounded cause with malformed confidence.",
                "confidence": confidence,
                "citations": [{"kind": "telemetry", "ref": "metric:memory"}],
            }
        ],
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert verified.status == "corrected"
    assert ", confidence " not in verified.answer
    assert "Grounded cause with malformed confidence" in verified.answer


def test_dossier_never_synthesizes_zero_sequence_audit_ref() -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "timeline",
        "selected_incident": {"correlation_id": "corr-memory"},
        "audit_evidence": [
            {
                "seq": 0,
                "recorded_at": "2026-07-15T00:00:00+00:00",
                "action_kind": "incident.open",
                "fields": {"summary": "Invalid provenance row"},
            }
        ],
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert verified.status == "unverified"
    assert verified.reason_code == "incident_timeline_unavailable"
    assert verified.evidence_refs == ()


def test_boolean_affected_count_is_not_grounded_impact_evidence() -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "impact",
        "selected_incident": {"correlation_id": "corr-memory"},
        "audit_evidence": [
            {"seq": 1, "fields": {"affected_count": True}},
        ],
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert verified.status == "corrected"
    assert verified.reason_code == "incident_impact_unavailable"
    assert "impact was not quantified" in verified.answer


def test_timeline_flattens_control_and_markdown_injected_record_text() -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "timeline",
        "selected_incident": {"correlation_id": "corr-memory"},
        "audit_evidence": [
            {
                "seq": 1,
                "recorded_at": "2026-07-15T00:00:00Z\n- forged row",
                "action_kind": "incident.open",
                "fields": {"summary": "### injected heading"},
            }
        ],
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert verified.status == "corrected"
    assert verified.answer.count("\n- ") == 1
    assert "\n###" not in verified.answer
    assert "\\#\\#\\# injected heading" in verified.answer


def test_similar_incident_rejects_forged_multiline_recovery_ref() -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "similar",
        "selected_incident": {"correlation_id": "corr-memory"},
        "similar_incident_status": "matched",
        "similar_incidents": [
            {
                "correlation_id": "corr-prior",
                "title": "Prior incident",
                "matching_domain_signals": ["memory"],
                "recovery": {
                    "action_kind": "remediation.verified",
                    "outcome": "resolved",
                    "evidence_ref": "audit:corr-prior:9\nfreshness:fake@2099-01-01",
                },
            }
        ],
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert verified.status == "corrected"
    assert verified.evidence_refs == ("incident:corr-memory", "incident:corr-prior")


def test_impact_rejects_nonfinite_numbers_and_bounds_long_text() -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "impact",
        "selected_incident": {"correlation_id": "corr-memory"},
        "audit_evidence": [
            {
                "seq": 1,
                "fields": {
                    "slo_impact": float("nan"),
                    "service_impact": float("inf"),
                    "customer_impact": "A" * 200_000,
                },
            }
        ],
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert verified.status == "corrected"
    assert "nan" not in verified.answer.casefold()
    assert "inf" not in verified.answer.casefold()
    assert "A" * 513 not in verified.answer
    assert len(verified.answer) < 1_000


def test_operational_freshness_rejects_future_server_timestamp() -> None:
    context = response_evidence_freshness_context(
        {
            "_operational_evidence": {
                "status": "matched",
                "source": "server-read-model-incident",
                "observed_at": "2099-01-01T00:00:00Z",
                "window_start": "2098-12-31T23:00:00Z",
                "truncated": False,
            }
        }
    )

    assert context is None


def test_next_action_flattens_and_escapes_recorded_decision() -> None:
    evidence = {
        "authority": "server_read_model",
        "status": "matched",
        "incident_query_intent": "next_action",
        "selected_incident": {"correlation_id": "corr-memory"},
        "response_plan": {
            "decision": "Inspect now\n- forged step\n### injected heading",
            "verdict": "hil",
            "mode": "shadow",
        },
    }

    verified = verify_answer("provisional", {"_operational_evidence": evidence}, locale="en")

    assert verified.status == "corrected"
    assert "\n- forged" not in verified.answer
    assert "\n###" not in verified.answer
    assert "\\#\\#\\# injected heading" in verified.answer


async def test_operational_evidence_bounds_compact_audit_fields() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model)
    model.record_audit_entry(
        {
            "event_id": "evt-memory",
            "correlation_id": "corr-memory",
            "recorded_at": "2026-07-15T00:02:00+00:00",
            "customer_impact": "A" * 200_000,
        },
        action_kind="impact.observed",
    )

    evidence = await OperationalEvidenceResolver(model).resolve("recent memory incident")

    assert evidence is not None
    assert evidence["truncated"] is True
    impact_rows = [
        item for item in evidence["audit_evidence"] if item["action_kind"] == "impact.observed"
    ]
    assert len(impact_rows[0]["fields"]["customer_impact"]) == 1_024
    assert impact_rows[0]["fields_truncated"] is True


class _FailingReadModel(InMemoryConsoleReadModel):
    async def list_incidents(self, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("database unavailable")


async def test_lookup_error_fails_closed_without_exception() -> None:
    evidence = await OperationalEvidenceResolver(_FailingReadModel()).resolve(
        "recent memory issue cause"
    )

    assert evidence == {
        "authority": "server_read_model",
        "status": "unavailable",
        "reason": "operational evidence lookup failed",
    }


async def test_twenty_operational_weaknesses_pass_twenty_answer_rubrics() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model)
    model.record_audit_entry(
        {
            "event_id": "evt-memory",
            "correlation_id": "corr-memory",
            "recorded_at": "2026-07-15T00:02:00+00:00",
            "rca_outcome": "abstained",
            "rca_tier": "t2",
            "rca_cause": "Unsupported guess must not be presented.",
            "rca_reason": "No citations.",
            "rca_citations": [],
        },
        action_kind="rca.hypothesis",
    )
    resolver = OperationalEvidenceResolver(model)
    failures: list[str] = []
    passed = 0
    total = len(OPERATIONAL_WEAKNESS_CASES) * len(OPERATIONAL_RUBRIC_NAMES)

    for case_number, case in enumerate(OPERATIONAL_WEAKNESS_CASES, 1):
        selected = needs_operational_evidence(case.prompt, case.view_context)
        evidence = await resolver.resolve(case.prompt) if selected else None
        verification = (
            verify_answer(
                "Unsupported guess must not be presented.",
                {"_operational_evidence": evidence},
                locale="ko" if case.korean else "en",
            )
            if evidence is not None
            else None
        )
        results = _score_operational_answer(
            case,
            selected=selected,
            evidence=evidence,
            verification=verification,
        )
        assert len(results) == len(OPERATIONAL_RUBRIC_NAMES)
        for rubric, result in zip(OPERATIONAL_RUBRIC_NAMES, results, strict=True):
            if result:
                passed += 1
            else:
                failures.append(f"Q{case_number:02d} {rubric}: {case.prompt}")

    assert not failures, f"operational rubric score {passed}/{total}\n" + "\n".join(failures)


def _score_operational_answer(
    case: OperationalWeaknessCase,
    *,
    selected: bool,
    evidence: Any,
    verification: Any,
) -> tuple[bool, ...]:
    applicable = case.expects_operational
    safe_evidence = evidence if isinstance(evidence, dict) else {}
    selected_incident = safe_evidence.get("selected_incident")
    incident = selected_incident if isinstance(selected_incident, dict) else {}
    raw_hypotheses = safe_evidence.get("grounded_hypotheses")
    hypotheses = raw_hypotheses if isinstance(raw_hypotheses, list) else []
    hypothesis = hypotheses[0] if hypotheses and isinstance(hypotheses[0], dict) else {}
    raw_citations = hypothesis.get("citations")
    citations = raw_citations if isinstance(raw_citations, list) else []
    audit = safe_evidence.get("audit_evidence")
    answer = verification.answer if verification is not None else ""
    refs = verification.evidence_refs if verification is not None else ()
    korean_rendered = "검증된 원인" in answer
    return (
        selected == applicable,
        (evidence is not None) == applicable,
        (safe_evidence.get("authority") == "server_read_model") == applicable,
        (safe_evidence.get("status") == "matched") == applicable,
        (incident.get("correlation_id") == "corr-memory") == applicable,
        ("memory" in str(incident.get("title", "")).casefold()) == applicable,
        bool(hypotheses) == applicable,
        ("memory leak" in str(hypothesis.get("cause", "")).casefold()) == applicable,
        bool(citations) == applicable,
        "Unsupported guess" not in str(hypotheses),
        (isinstance(audit, list) and 0 < len(audit) <= 20) == applicable,
        (safe_evidence.get("candidate_count") == 1) == applicable,
        (verification is not None and verification.authority == "server_read_model") == applicable,
        (verification is not None and verification.reason_code == "grounded_rca") == applicable,
        (verification is not None and verification.status in {"verified", "corrected"})
        == applicable,
        not applicable or korean_rendered == case.korean,
        ("memory leak" in answer.casefold()) == applicable,
        ("incident:corr-memory" in refs) == applicable,
        ("telemetry:metric:available_memory_bytes" in refs) == applicable,
        "Unsupported guess" not in answer,
    )
