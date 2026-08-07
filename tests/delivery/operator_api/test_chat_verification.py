"""Progressive Command Deck terminal answer verification."""

from __future__ import annotations

import unicodedata

from fdai.delivery.operator_api.application.conversation.verification import verify_answer
from fdai.delivery.operator_api.application.conversation.verification.verifier import _changed
from fdai.delivery.operator_api.projections.conversation.terminal import (
    response_incident_candidates,
)


def _context(evidence: dict[str, object]) -> dict[str, object]:
    return {"routeId": "dashboard", "_operational_evidence": evidence}


def test_screen_only_answer_is_consistent_not_server_verified() -> None:
    result = verify_answer(
        "The screen shows 12 events.",
        {
            "routeId": "dashboard",
            "facts": [{"key": "event_count", "value": 12}],
        },
        locale="en",
    )

    assert result.status == "consistent"
    assert result.answer == "The screen shows 12 events."
    assert result.authority == "client_snapshot"
    assert result.reason_code == "screen_claims_supported"
    assert result.claims[0].status == "supported"
    assert result.evidence_manifest is not None


def test_screen_ratio_fact_supports_displayed_percentage() -> None:
    result = verify_answer(
        "The current auto-resolution rate is 41%.",
        {
            "routeId": "operating-outcomes",
            "facts": [
                {
                    "key": "current_rate",
                    "label": "Current auto-resolution",
                    "value": 0.41,
                }
            ],
        },
        locale="en",
    )

    assert result.status == "consistent"
    assert result.reason_code == "screen_claims_supported"
    assert result.claims[0].raw_value == "41%"
    assert result.claims[0].status == "supported"


def test_screen_unsupported_number_revises_to_unverified_abstention() -> None:
    result = verify_answer(
        "The screen shows 99 events.",
        {
            "routeId": "dashboard",
            "facts": [{"key": "event_count", "value": 12}],
        },
        locale="en",
    )

    assert result.status == "unverified"
    assert "99 events" not in result.answer
    assert result.reason_code == "screen_claim_mismatch"
    assert result.failed_claim_ids == ("c001",)


def test_screen_partial_mismatch_removes_only_unsupported_sentence() -> None:
    answer = (
        "The screen shows 22 ObjectTypes. "
        "It shows 99 LinkTypes. "
        "The selected Process has 10 properties."
    )
    result = verify_answer(
        answer,
        {
            "routeId": "ontology",
            "facts": [
                {"key": "object_type_count", "value": 22},
                {"key": "link_type_count", "value": 33},
                {"key": "selected_process_property_count", "value": 10},
            ],
        },
        locale="en",
    )

    assert result.status == "corrected"
    assert result.reason_code == "screen_unsupported_sentences_removed"
    assert "22 ObjectTypes" in result.answer
    assert "10 properties" in result.answer
    assert "99 LinkTypes" not in result.answer
    assert result.checks_completed == 2
    assert result.checks_total == 2


def test_screen_qualitative_answer_has_no_checkable_claims() -> None:
    result = verify_answer(
        "Operations need attention.",
        {"routeId": "dashboard", "facts": []},
        locale="en",
    )

    assert result.status == "consistent"
    assert result.reason_code == "screen_no_checkable_claims"
    assert result.checks_total == 0


def test_agent_handoff_without_evidence_is_not_salvaged_from_screen_facts() -> None:
    result = verify_answer(
        "No high-severity problems were found. The latest item is low severity.",
        {
            "routeId": "agents",
            "facts": [{"key": "latest_severity", "value": "low"}],
            "_agent_evidence": {
                "primary_agent": "Bragi",
                "answer": None,
                "facts": {},
                "contributors": [],
                "handoff_from": "Heimdall",
                "handoff_reason": "insufficient_agent_evidence",
            },
        },
        locale="ko",
    )

    assert result.status == "unverified"
    assert result.authority == "pantheon_runtime"
    assert result.reason_code == "agent_evidence_unavailable"
    assert result.checks_completed == 0
    assert result.checks_total == 1
    assert "Heimdall" in result.answer
    assert "low" not in result.answer


def test_invalid_answer_characters_fail_closed_before_claim_verification() -> None:
    invalid_answers = (
        "broken \ufffd output",
        "broken \ud800 output",
        "broken \x00 output",
        "spoofed \u202e output",
        "isolated \u2066 output",
    )

    for answer in invalid_answers:
        result = verify_answer(answer, {"routeId": "dashboard", "facts": []}, locale="en")

        assert result.status == "unverified"
        assert result.authority == "answer_text_integrity"
        assert result.reason_code == "answer_text_invalid"
        assert result.checks_completed == 0
        assert result.checks_total == 1
        assert answer not in result.answer


def test_answer_integrity_allows_layout_and_script_shaping_characters() -> None:
    answer = "line one\nline two\tjoined \u200d text"

    result = verify_answer(answer, {"routeId": "dashboard", "facts": []}, locale="en")

    assert result.status == "consistent"
    assert result.answer == answer


def test_invalid_answer_character_abstention_follows_korean_locale() -> None:
    result = verify_answer(
        "깨진 \ufffd 응답",
        {"routeId": "dashboard", "facts": []},
        locale="ko",
    )

    assert result.status == "unverified"
    assert result.reason_code == "answer_text_invalid"
    assert "유효하지 않은 문자" in result.answer
    assert "\ufffd" not in result.answer


def test_canonically_equivalent_korean_text_does_not_trigger_correction() -> None:
    canonical = "한글 답변"
    decomposed = unicodedata.normalize("NFD", canonical)

    assert decomposed != canonical
    assert _changed(decomposed, canonical) == "verified"


def test_unicode_normalization_does_not_hide_real_text_changes() -> None:
    canonical = "한글 답변"
    different = unicodedata.normalize("NFD", "한글 수정")

    assert _changed(different, canonical) == "corrected"


def test_korean_settings_explanation_does_not_false_reject_universal_prose() -> None:
    answer = (
        "이 화면은 모든 콘솔 표시 설정을 보여주며, 모든 변경은 브라우저 "
        "로컬에만 저장됩니다. 런타임 주소는 http://127.0.0.1:8010입니다."
    )
    result = verify_answer(
        answer,
        {
            "routeId": "settings",
            "purpose": "Browser-local console display preferences and runtime information.",
            "facts": [{"key": "operator_api", "value": "http://127.0.0.1:8010"}],
        },
        locale="ko",
    )

    assert result.status == "consistent"
    assert result.answer == answer
    assert result.checks_completed == 2
    assert result.checks_total == 2


def test_korean_dashboard_explanation_disambiguates_repeated_zero_facts() -> None:
    answer = "이 화면에는 4개의 주요 영역이 있습니다. 감사 이벤트는 0건이고 승인 대기는 0건입니다."
    result = verify_answer(
        answer,
        {
            "routeId": "dashboard",
            "facts": [
                {
                    "key": "section_count",
                    "aliases": ["primary sections", "주요 영역"],
                    "value": 4,
                },
                {
                    "key": "event_count",
                    "label": "Events (audit)",
                    "aliases": ["audit events", "감사 이벤트"],
                    "value": 0,
                },
                {
                    "key": "hil_pending",
                    "label": "Approvals pending",
                    "aliases": ["pending approvals", "승인 대기"],
                    "value": 0,
                },
            ],
        },
        locale="ko",
    )

    assert result.status == "consistent"
    assert result.answer == answer
    assert result.reason_code == "screen_claims_supported"
    assert result.failed_claim_ids == ()


def test_glossary_answer_removes_unsupported_screen_scope_addition() -> None:
    answer = (
        "에이전트는 typed port와 conversational port를 "
        "각각 사용합니다. 이 화면에는 "
        "자동 실행 조건이 없습니다."
    )
    result = verify_answer(
        answer,
        {
            "routeId": "ontology",
            "facts": [],
            "_concept_evidence": {
                "authority": "fdai_glossary",
                "entries": [
                    {
                        "term": "Two-port model",
                        "definition": (
                            "Agents expose a typed pub/sub port and a conversational port."
                        ),
                    }
                ],
            },
        },
        locale="ko",
    )

    assert result.status == "corrected"
    assert result.authority == "fdai_glossary"
    assert result.reason_code == "concept_scope_claims_removed"
    assert "typed port" in result.answer
    assert "자동 실행 조건" not in result.answer


def test_none_state_corrects_to_bounded_absence_claim_in_korean() -> None:
    result = verify_answer(
        "관련 장애는 전혀 없습니다.",
        _context(
            {
                "status": "none",
                "topic_terms": ["memory"],
                "searched_recent_incidents": 11,
            }
        ),
        locale="ko",
    )

    assert result.status == "corrected"
    assert "11건" in result.answer
    assert "제한된" in result.answer
    assert "메모리" in result.answer
    assert "memory" not in result.answer
    assert result.evidence_refs == ("incident-search:recent:11",)


def test_ambiguous_state_lists_candidates_instead_of_choosing() -> None:
    result = verify_answer(
        "corr-a caused the outage.",
        _context(
            {
                "status": "ambiguous",
                "candidates": [
                    {"correlation_id": "corr-a", "title": "First"},
                    {"correlation_id": "corr-b", "title": "Second"},
                ],
            }
        ),
        locale="en",
    )

    assert result.status == "corrected"
    assert "Choose one" in result.answer
    assert "corr-a" in result.answer
    assert "corr-b" in result.answer


def test_summary_state_renders_all_incidents_without_requesting_selection() -> None:
    result = verify_answer(
        "Select an incident.",
        _context(
            {
                "status": "summary",
                "searched_recent_incidents": 2,
                "incidents": [
                    {
                        "correlation_id": "corr-a",
                        "title": "Memory pressure",
                        "status": "open",
                        "severity": "high",
                        "last_updated_at": "2026-07-22T01:00:00Z",
                        "involved_agents": ["Huginn", "Forseti"],
                    },
                    {
                        "correlation_id": "corr-b",
                        "title": "Deployment latency",
                        "status": "investigating",
                        "severity": "medium",
                        "last_updated_at": "2026-07-22T00:30:00Z",
                        "involved_agents": [],
                    },
                ],
            }
        ),
        locale="en",
    )

    assert result.status == "corrected"
    assert result.reason_code == "incident_summary"
    assert "Summary of 2 recent incident(s)" in result.answer
    assert "corr-a" in result.answer
    assert "corr-b" in result.answer
    assert "Choose one" not in result.answer
    assert result.evidence_refs == ("incident:corr-a", "incident:corr-b")


def test_operational_summary_remains_authoritative_with_agent_evidence() -> None:
    result = verify_answer(
        "Heimdall found one high-severity signal.",
        {
            "routeId": "agents",
            "_agent_evidence": {
                "primary_agent": "Heimdall",
                "answer": "One high-severity signal is recorded.",
                "facts": {
                    "severity": "high",
                    "evidence_refs": ["agent-state:Heimdall:sha256:" + "a" * 64],
                },
            },
            "_operational_evidence": {
                "status": "summary",
                "searched_recent_incidents": 1,
                "incidents": [
                    {
                        "correlation_id": "corr-high",
                        "title": "Memory pressure",
                        "status": "open",
                        "severity": "high",
                        "last_updated_at": "2026-07-22T01:00:00Z",
                        "involved_agents": ["Heimdall"],
                    }
                ],
            },
        },
        locale="en",
    )

    assert result.status == "corrected"
    assert result.authority == "server_read_model"
    assert result.reason_code == "incident_summary"
    assert "corr-high" in result.answer
    assert result.evidence_refs == ("incident:corr-high",)


def test_selected_agent_role_question_uses_capability_facts_in_korean() -> None:
    evidence_ref = "agent-state:Heimdall:sha256:" + "a" * 64
    result = verify_answer(
        "저는 관찰을 돕습니다.",
        {
            "routeId": "agents",
            "_answer_plan": {"subject": "너는 주로 어떤 일을해?"},
            "_agent_evidence": {
                "primary_agent": "Heimdall",
                "answer": "Watching 0 resources; 0 security events in window.",
                "facts": {
                    "agent": "Heimdall",
                    "layer": "pipeline",
                    "owns": ["Anomaly", "Drift", "Forecast", "ForecastOutcome"],
                    "question_domains": ["anomaly", "drift", "forecast", "discovery_health"],
                    "evidence_refs": [evidence_ref],
                },
            },
        },
        locale="ko",
    )

    assert result.status == "corrected"
    assert result.authority == "pantheon_runtime"
    assert result.reason_code == "agent_capability_facts"
    assert result.evidence_refs == (evidence_ref,)
    assert result.answer.startswith("저는 Heimdall이며 파이프라인 계층의 에이전트입니다.")
    assert "Anomaly, Drift, Forecast, ForecastOutcome" in result.answer
    assert "discovery health" in result.answer


def test_selected_agent_status_question_does_not_use_capability_renderer() -> None:
    result = verify_answer(
        "Heimdall is watching.",
        {
            "routeId": "agents",
            "_answer_plan": {"subject": "지금 뭘 관찰하고 있어?"},
            "_agent_evidence": {
                "primary_agent": "Heimdall",
                "facts": {
                    "agent": "Heimdall",
                    "layer": "pipeline",
                    "owns": ["Anomaly"],
                    "question_domains": ["anomaly"],
                    "evidence_refs": ["agent-state:Heimdall:sha256:" + "a" * 64],
                },
            },
        },
        locale="ko",
    )

    assert result.reason_code != "agent_capability_facts"


def test_selected_agent_role_question_rejects_another_agents_evidence_ref() -> None:
    result = verify_answer(
        "I describe observed signals.",
        {
            "routeId": "agents",
            "_answer_plan": {"subject": "what do you do?"},
            "_agent_evidence": {
                "primary_agent": "Heimdall",
                "facts": {
                    "agent": "Heimdall",
                    "layer": "pipeline",
                    "owns": ["Anomaly"],
                    "question_domains": ["anomaly"],
                    "evidence_refs": ["agent-state:Njord:sha256:" + "a" * 64],
                },
            },
        },
        locale="en",
    )

    assert result.reason_code != "agent_capability_facts"


def test_summary_state_renders_korean_answer_without_requesting_selection() -> None:
    result = verify_answer(
        "인시던트를 선택해 주세요.",
        _context(
            {
                "status": "summary",
                "searched_recent_incidents": 1,
                "incidents": [
                    {
                        "correlation_id": "corr-a",
                        "title": "Memory pressure",
                        "status": "open",
                        "severity": "high",
                        "last_updated_at": "2026-07-22T01:00:00Z",
                        "involved_agents": ["Huginn"],
                    }
                ],
            }
        ),
        locale="ko",
    )

    assert result.reason_code == "incident_summary"
    assert "최근 인시던트 1건 요약" in result.answer
    assert "선택해 주세요" not in result.answer


def test_grounded_match_renders_canonical_cause_and_refs() -> None:
    result = verify_answer(
        "The cause might be load.",
        _context(
            {
                "status": "matched",
                "selected_incident": {
                    "correlation_id": "corr-memory",
                    "title": "Memory pressure",
                    "last_updated_at": "2026-07-15T00:01:00Z",
                },
                "grounded_hypotheses": [
                    {
                        "cause": "A memory leak exhausted host memory.",
                        "citations": [
                            {"kind": "telemetry", "ref": "metric:memory"},
                        ],
                    }
                ],
            }
        ),
        locale="en",
    )

    assert result.status == "corrected"
    assert "memory leak" in result.answer
    assert result.evidence_refs == (
        "incident:corr-memory",
        "telemetry:metric:memory",
    )


def test_matched_without_grounded_rca_refuses_causal_claim() -> None:
    result = verify_answer(
        "The incident was caused by a leak.",
        _context(
            {
                "status": "matched",
                "selected_incident": {
                    "correlation_id": "corr-memory",
                    "title": "Memory pressure",
                    "last_updated_at": "2026-07-15T00:01:00Z",
                },
                "grounded_hypotheses": [],
            }
        ),
        locale="en",
    )

    assert result.status == "corrected"
    assert "cannot be confirmed" in result.answer
    assert "caused by a leak" not in result.answer


def test_matched_without_rca_surfaces_recorded_failure_reason() -> None:
    result = verify_answer(
        "The incident was caused by a network outage.",
        _context(
            {
                "status": "matched",
                "selected_incident": {
                    "correlation_id": "corr-notification",
                    "title": "Notification delivery",
                    "last_updated_at": "2026-07-22T03:11:04Z",
                },
                "grounded_hypotheses": [],
                "audit_evidence": [
                    {
                        "seq": 31,
                        "action_kind": "notification.escalation",
                        "fields": {"reason": "no registered delivery channel is available"},
                    }
                ],
            }
        ),
        locale="en",
    )

    assert result.status == "corrected"
    assert result.reason_code == "recorded_failure_reason"
    assert "notification.escalation: no registered delivery channel" in result.answer
    assert "not a complete RCA" in result.answer
    assert "caused by a network outage" not in result.answer
    assert result.evidence_refs == ("incident:corr-notification", "audit:31")


def test_workload_detection_separates_notification_delivery_failure() -> None:
    result = verify_answer(
        "Check this incident.",
        _context(
            {
                "status": "matched",
                "selected_incident": {
                    "correlation_id": "corr-restart",
                    "title": "Kubernetes pod restart detected - Resource example-app",
                    "status": "open",
                    "last_updated_at": "2026-08-04T00:01:00Z",
                },
                "grounded_hypotheses": [],
                "audit_evidence": [
                    {
                        "seq": 41,
                        "action_kind": "incident.open",
                        "fields": {
                            "detected_signal": "kubernetes.pod_restart_detected",
                            "detected_resource": "kubernetes://example/namespace/example-app",
                            "member_event_count": 5,
                        },
                    },
                    {
                        "seq": 42,
                        "action_kind": "notification.escalation",
                        "fields": {"reason": "no registered delivery channel is available"},
                    },
                ],
            }
        ),
        locale="en",
    )

    assert result.status == "corrected"
    assert result.reason_code == "detected_condition_without_rca"
    assert "Detected workload condition" in result.answer
    assert "kubernetes.pod_restart_detected" in result.answer
    assert "Correlated member events: 5" in result.answer
    assert "confirms the detected condition and target, not its cause" in result.answer
    assert "Notification delivery issue" in result.answer
    assert result.evidence_refs == (
        "incident:corr-restart",
        "audit:41",
        "audit:42",
    )


def test_workload_detection_separation_is_localized_in_korean() -> None:
    result = verify_answer(
        "이 인시던트를 확인해봐.",
        _context(
            {
                "status": "matched",
                "selected_incident": {
                    "correlation_id": "corr-restart",
                    "title": "Kubernetes pod restart detected - Resource example-app",
                    "status": "open",
                    "last_updated_at": "2026-08-04T00:01:00Z",
                },
                "grounded_hypotheses": [],
                "audit_evidence": [
                    {
                        "seq": 41,
                        "action_kind": "incident.open",
                        "fields": {
                            "detected_signal": "kubernetes.pod_restart_detected",
                            "detected_resource": "kubernetes://example/namespace/example-app",
                            "member_event_count": 5,
                        },
                    },
                    {
                        "seq": 42,
                        "action_kind": "notification.escalation",
                        "fields": {"reason": "no registered delivery channel is available"},
                    },
                ],
            }
        ),
        locale="ko",
    )

    assert result.reason_code == "detected_condition_without_rca"
    assert "감지된 workload 상태" in result.answer
    assert "연관된 member event: 5건" in result.answer
    assert "감지된 증상과 대상만 확인하며 원인을 증명하지 않습니다" in result.answer
    assert "알림 전달 문제" in result.answer


def test_ambiguous_incident_candidates_emit_bounded_selection_artifact() -> None:
    candidates = [
        {
            "incident_id": None,
            "correlation_id": "corr-1",
            "title": "Pod restart",
            "severity": "high",
            "status": "open",
            "last_updated_at": "2026-08-04T00:01:00Z",
        },
        {
            "incident_id": "INC-2",
            "correlation_id": "corr-2",
            "title": "Memory pressure",
            "severity": "medium",
            "status": "in_progress",
            "last_updated_at": "2026-08-04T00:02:00Z",
        },
    ]
    verification = verify_answer(
        "Choose one.",
        _context({"status": "ambiguous", "candidates": candidates}),
        locale="en",
    )

    artifact = response_incident_candidates(
        {"_operational_evidence": {"status": "ambiguous", "candidates": candidates}},
        verification=verification,
        locale="ko-KR",
    )

    assert artifact == {
        "schema_version": 1,
        "locale": "ko",
        "candidates": [
            {**candidates[0], "incident_id": "INC-corr-1"},
            candidates[1],
        ],
    }


def test_unavailable_state_is_explicitly_unverified() -> None:
    result = verify_answer(
        "Everything is healthy.",
        _context({"status": "unavailable"}),
        locale="en",
    )

    assert result.status == "unverified"
    assert "could not be retrieved" in result.answer
    assert result.reason_code == "evidence_unavailable"
