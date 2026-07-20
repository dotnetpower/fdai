"""Progressive Command Deck terminal answer verification."""

from __future__ import annotations

from fdai.delivery.read_api.routes.chat_verification import verify_answer


def _context(evidence: dict) -> dict:
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
        "\uc5d0\uc774\uc804\ud2b8\ub294 typed port\uc640 conversational port\ub97c "
        "\uac01\uac01 \uc0ac\uc6a9\ud569\ub2c8\ub2e4. \uc774 \ud654\uba74\uc5d0\ub294 "
        "\uc790\ub3d9 \uc2e4\ud589 \uc870\uac74\uc774 \uc5c6\uc2b5\ub2c8\ub2e4."
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
    assert "\uc790\ub3d9 \uc2e4\ud589 \uc870\uac74" not in result.answer


def test_none_state_corrects_to_bounded_absence_claim_in_korean() -> None:
    result = verify_answer(
        "\uad00\ub828 \uc7a5\uc560\ub294 \uc804\ud600 \uc5c6\uc2b5\ub2c8\ub2e4.",
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
    assert "11\uac74" in result.answer
    assert "\uc81c\ud55c\ub41c" in result.answer
    assert "\uba54\ubaa8\ub9ac" in result.answer
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


def test_unavailable_state_is_explicitly_unverified() -> None:
    result = verify_answer(
        "Everything is healthy.",
        _context({"status": "unavailable"}),
        locale="en",
    )

    assert result.status == "unverified"
    assert "could not be retrieved" in result.answer
    assert result.reason_code == "evidence_unavailable"
