"""Atomic screen-claim extraction and deterministic evidence verification."""

from __future__ import annotations

from fdai.delivery.read_api.routes.chat_claims import verify_screen_claims


def _context(*, facts: list[dict] | None = None, records: dict | None = None) -> dict:
    return {
        "routeId": "dashboard",
        "capturedAt": "2026-07-15T00:00:00Z",
        "facts": facts or [],
        "records": records or {},
    }


def test_supports_exact_id_and_builds_hashed_manifest() -> None:
    result = verify_screen_claims(
        "Incident corr-memory-1 is selected.",
        _context(facts=[{"key": "correlation_id", "value": "corr-memory-1"}]),
    )

    assert result.supported is True
    assert len(result.claims) == 1
    assert result.claims[0].kind == "id"
    assert result.claims[0].status == "supported"
    assert result.claims[0].evidence_refs == ("snapshot:fact:correlation_id",)
    assert result.manifest.manifest_id.startswith("sha256:")
    assert result.manifest.route_id == "dashboard"
    assert len(result.manifest.entries) == 1


def test_supports_anchored_number_and_rejects_unknown_number() -> None:
    context = _context(
        facts=[
            {"key": "event_count", "value": 24},
            {"key": "approval_count", "value": 1},
        ]
    )

    supported = verify_screen_claims("There are 24 events.", context)
    unsupported = verify_screen_claims("There are 25 events.", context)

    assert supported.claims[0].status == "supported"
    assert supported.claims[0].evidence_refs == ("snapshot:fact:event_count",)
    assert unsupported.claims[0].status == "unsupported"
    assert unsupported.failed_claim_ids == ("c001",)


def test_marks_duplicate_unanchored_number_ambiguous() -> None:
    result = verify_screen_claims(
        "The value is 12.",
        _context(
            facts=[
                {"key": "active_count", "value": 12},
                {"key": "resolved_count", "value": 12},
            ]
        ),
    )

    assert result.claims[0].status == "ambiguous"
    assert result.claims[0].reason_code == "multiple_unanchored_evidence"


def test_supports_display_percentage_derived_from_ratio_fact() -> None:
    result = verify_screen_claims(
        "Auto resolution is 92%.",
        _context(facts=[{"key": "auto_resolution_rate", "value": 0.92}]),
    )

    assert result.supported is True
    assert result.claims[0].kind == "percentage"
    assert result.claims[0].normalized_value == "92"
    assert result.claims[0].evidence_refs == ("snapshot:fact:auto_resolution_rate:percent",)


def test_supports_numeric_and_percentage_string_facts() -> None:
    context = _context(
        facts=[
            {"key": "eps", "value": "4.2"},
            {"key": "tier.t0", "value": "78%"},
        ]
    )

    result = verify_screen_claims("EPS is 4.2 and T0 is 78%.", context)

    assert result.supported is True
    assert [claim.status for claim in result.claims] == ["supported", "supported"]


def test_supports_headline_number_and_korean_percentage_suffix() -> None:
    result = verify_screen_claims(
        "1200 events, T2\ub294 5%\uc785\ub2c8\ub2e4.",
        {
            **_context(facts=[{"key": "tier.t2", "value": "5%"}]),
            "headline": "1200 events - 5% T2",
        },
    )

    assert result.supported is True
    assert [claim.kind for claim in result.claims] == ["number", "percentage"]


def test_supports_decimal_followed_by_korean_suffix() -> None:
    result = verify_screen_claims(
        "\ud604\uc7ac \uc815\ud655\ub3c4\ub294 0.8\uc785\ub2c8\ub2e4.",
        _context(facts=[{"key": "accuracy", "value": 0.8}]),
    )

    assert result.supported is True
    assert result.claims[0].normalized_value == "0.8"


def test_camel_case_anchor_disambiguates_headline_and_fact_duplicate() -> None:
    result = verify_screen_claims(
        "There are 13 ObjectTypes registered.",
        {
            **_context(facts=[{"key": "object_type_count", "value": 13}]),
            "headline": "13 ObjectTypes - 19 LinkTypes",
        },
    )

    assert result.supported is True


def test_unique_structured_fact_wins_over_duplicate_headline_for_localized_text() -> None:
    result = verify_screen_claims(
        "\u30ea\u30f3\u30af\u30bf\u30a4\u30d7\u306f 19 \u3067\u3059\u3002",
        {
            **_context(facts=[{"key": "link_type_count", "value": 19}]),
            "headline": "13 ObjectTypes - 19 LinkTypes",
        },
    )

    assert result.supported is True
    assert result.claims[0].evidence_refs == ("snapshot:fact:link_type_count",)


def test_headline_text_disambiguates_failed_count() -> None:
    result = verify_screen_claims(
        "There are 3 failed tiles.",
        {
            **_context(facts=[{"key": "attention.total", "value": 3}]),
            "headline": "60 tiles - 4.2 eps - 3 failed",
        },
    )

    assert result.supported is True


def test_supports_action_type_id_and_scalar_list_evidence() -> None:
    result = verify_screen_claims(
        "remediate.enable-tde needs 50 more shadow samples.",
        _context(
            records={
                "rows": [
                    {
                        "action_type_name": "remediate.enable-tde",
                        "gaps": ["needs 50 more shadow samples"],
                    }
                ]
            }
        ),
    )

    assert result.supported is True
    assert [claim.kind for claim in result.claims] == ["id", "number"]


def test_causal_claim_accepts_embedded_exact_evidence_text() -> None:
    result = verify_screen_claims(
        "It is blocked because it needs 50 more shadow samples.",
        _context(records={"rows": [{"gaps": ["needs 50 more shadow samples"]}]}),
    )

    assert result.supported is True


def test_bounded_screen_absence_is_not_a_global_absence_claim() -> None:
    result = verify_screen_claims(
        "The screen does not show any approver details.",
        _context(facts=[{"key": "step_count", "value": 5}]),
    )

    assert result.supported is True
    assert result.claims[0].kind == "scope"


def test_latest_and_only_wording_do_not_create_global_scope_claims() -> None:
    result = verify_screen_claims(
        "The latest entry has 2 rows and only shows audit data.",
        _context(facts=[{"key": "loaded_rows", "value": 2}]),
    )

    assert result.supported is True
    assert [claim.kind for claim in result.claims] == ["number"]


def test_korean_universal_screen_description_is_qualitative_prose() -> None:
    result = verify_screen_claims(
        (
            "이 화면은 모든 콘솔 표시 설정을 보여주며, 모든 변경은 브라우저 "
            "로컬에만 저장됩니다. 런타임 주소는 http://127.0.0.1:8010입니다."
        ),
        _context(facts=[{"key": "read_api", "value": "http://127.0.0.1:8010"}]),
    )

    assert result.supported is True
    assert [claim.kind for claim in result.claims] == ["number", "number"]


def test_no_approver_details_targets_only_approver_evidence() -> None:
    result = verify_screen_claims(
        "The trace has 5 steps, but no approver details are present.",
        _context(facts=[{"key": "step_count", "value": 5}]),
    )

    assert result.supported is True


def test_collects_server_tool_evidence_with_server_authority() -> None:
    result = verify_screen_claims(
        "There are 42 events.",
        {
            "routeId": "live",
            "facts": [],
            "_tool_evidence": {
                "authority": "server_read_model",
                "tool": "get_kpi",
                "result": {"event_count": 42},
            },
        },
    )

    assert result.supported is True
    assert result.manifest.authority == "server_read_model"
    assert result.claims[0].evidence_refs == ("tool:result:event_count",)


def test_collects_agent_answer_and_contributor_evidence() -> None:
    correlation = "conv-00000000-0000-0000-0000-000000000000"
    result = verify_screen_claims(
        f"Run {correlation} is complete; the anomaly ratio is 1.5.",
        {
            "routeId": "live",
            "facts": [],
            "_agent_evidence": {
                "primary_agent": "Thor",
                "answer": f"Run {correlation} is complete.",
                "facts": {"correlation_id": correlation},
                "contributor_answers": [
                    {
                        "agent": "Njord",
                        "answer": "The anomaly ratio is 1.5.",
                        "facts": {"anomaly_ratio": 1.5},
                    }
                ],
            },
        },
    )

    assert result.supported is True
    assert result.manifest.authority == "pantheon_runtime"


def test_collects_canonical_glossary_number_and_scope_evidence() -> None:
    result = verify_screen_claims(
        "ActionType binds 5 roles and is never a direct executor call.",
        {
            "routeId": "overview",
            "facts": [],
            "_concept_evidence": {
                "authority": "fdai_glossary",
                "entries": [
                    {
                        "term": "ActionType",
                        "definition": (
                            "ActionType binds 5 roles and is never a direct executor call."
                        ),
                    }
                ],
            },
        },
    )

    assert result.supported is True
    assert result.manifest.authority == "fdai_glossary"


def test_timestamp_normalizes_timezone_before_matching() -> None:
    result = verify_screen_claims(
        "The evidence time is 2026-07-15T09:00:00+09:00.",
        _context(facts=[{"key": "recorded_at", "value": "2026-07-15T00:00:00Z"}]),
    )

    assert result.supported is True
    assert result.claims[0].kind == "timestamp"
    assert result.claims[0].normalized_value == "2026-07-15T00:00:00Z"


def test_causal_claim_requires_narrative_evidence() -> None:
    context = _context(
        records={
            "selected_history": [
                {
                    "correlation_id": "corr-memory",
                    "cause": "A memory leak exhausted available host memory",
                }
            ]
        }
    )

    supported = verify_screen_claims(
        "The incident was caused by a memory leak exhausted available host memory.",
        context,
    )
    unsupported = verify_screen_claims(
        "The incident was caused by a traffic burst.",
        context,
    )

    causal = next(claim for claim in supported.claims if claim.kind == "causal")
    assert causal.status == "supported"
    assert causal.evidence_refs == ("snapshot:record:selected_history:0:cause",)
    assert next(claim for claim in unsupported.claims if claim.kind == "causal").status == (
        "unsupported"
    )


def test_bounded_absence_requires_complete_zero_fact() -> None:
    context = _context(facts=[{"key": "pending_approvals", "value": 0}])

    supported = verify_screen_claims("There are no pending approvals.", context)
    truncated = verify_screen_claims(
        "There are no pending approvals.",
        {**context, "_records_truncated": True},
    )

    scope = next(claim for claim in supported.claims if claim.kind == "scope")
    assert scope.status == "supported"
    assert next(claim for claim in truncated.claims if claim.kind == "scope").reason_code == (
        "incomplete_snapshot"
    )
    assert truncated.manifest.complete is False


def test_no_checkable_claims_is_supported_with_empty_manifest_entries() -> None:
    result = verify_screen_claims("Operations need attention.", _context())

    assert result.supported is True
    assert result.claims == ()
    assert result.manifest.entries == ()


def test_more_than_64_claims_fails_closed() -> None:
    answer = " ".join(f"value {index + 100}." for index in range(65))
    result = verify_screen_claims(answer, _context())

    assert result.overflow is True
    assert result.supported is False
    assert len(result.claims) == 64
