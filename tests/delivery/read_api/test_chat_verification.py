"""Progressive Command Deck terminal answer verification."""

from __future__ import annotations

import unicodedata

from fdai.delivery.read_api.routes.chat_verification import _changed, verify_answer


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
            "facts": [{"key": "read_api", "value": "http://127.0.0.1:8010"}],
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


def test_unavailable_state_is_explicitly_unverified() -> None:
    result = verify_answer(
        "Everything is healthy.",
        _context({"status": "unavailable"}),
        locale="en",
    )

    assert result.status == "unverified"
    assert "could not be retrieved" in result.answer
    assert result.reason_code == "evidence_unavailable"
