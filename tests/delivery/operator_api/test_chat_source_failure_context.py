from fdai.delivery.operator_api.application.conversation.capabilities.data_sources import (
    needs_read_source_evidence,
    render_read_source_answer,
)
from fdai.delivery.operator_api.projections.conversation.terminal import (
    parse_source_failure_context,
    response_source_failure_context,
    source_failure_evidence_refs,
)


def _view_context() -> dict[str, object]:
    return {
        "_tool_evidence": {
            "tool": "describe_read_sources",
            "authority": "server_read_source_manifest",
            "result": {
                "status": "matched",
                "truncated": False,
                "sources": [
                    {
                        "key": "audit",
                        "source": "postgres-audit",
                        "availability": "available",
                        "configured": True,
                        "reachable": True,
                        "authoritative": True,
                        "durable": True,
                        "synthetic": False,
                        "reason": None,
                        "last_observed_at": "2026-07-20T10:00:00Z",
                        "routes": ["/audit"],
                    },
                    {
                        "key": "inventory",
                        "source": "azure-resource-graph",
                        "availability": "unavailable",
                        "configured": True,
                        "reachable": False,
                        "authoritative": True,
                        "durable": False,
                        "synthetic": False,
                        "reason": "reader_unauthorized",
                        "last_observed_at": "2026-07-20T09:00:00Z",
                        "routes": ["/inventory"],
                    },
                ],
            },
        }
    }


def test_source_failure_precursor_routes_to_manifest() -> None:
    prompts = (
        "현재 사용할 수 없는 데이터 원본과 확인 가능한 사실을 분리해서 보여줘.",
        "Show unavailable data sources and their status.",
        "Which required source is missing?",
    )

    assert all(needs_read_source_evidence(prompt) for prompt in prompts)


def test_verified_manifest_projects_strict_source_failure_receipt() -> None:
    context = response_source_failure_context(_view_context(), verification_status="verified")

    assert context is not None
    assert context["gaps"] == [
        {
            "key": "inventory",
            "source": "azure-resource-graph",
            "availability": "unavailable",
            "reason": "reader_unauthorized",
            "last_observed_at": "2026-07-20T09:00:00Z",
            "configured": True,
            "reachable": False,
            "authoritative": True,
            "durable": False,
            "synthetic": False,
        }
    ]
    assert parse_source_failure_context(context) == context
    assert source_failure_evidence_refs(context) == (
        "read-source:audit:postgres-audit:available",
        "read-source:inventory:azure-resource-graph:unavailable",
    )


def test_unverified_or_malformed_manifest_does_not_create_receipt() -> None:
    assert (
        response_source_failure_context(_view_context(), verification_status="unverified") is None
    )
    assert parse_source_failure_context({"schema_version": 1, "sources": []}) is None


def test_receipt_rejects_gap_outside_source_manifest() -> None:
    context = response_source_failure_context(_view_context(), verification_status="verified")
    assert context is not None
    context["gaps"] = [
        {
            "key": "metrics",
            "source": "azure-monitor",
            "availability": "unavailable",
            "reason": "source_unavailable",
        }
    ]

    assert parse_source_failure_context(context) is None
    assert source_failure_evidence_refs(context) == ()


def test_receipt_rejects_missing_gap_for_unavailable_source() -> None:
    context = response_source_failure_context(_view_context(), verification_status="verified")
    assert context is not None
    context["gaps"] = []

    assert parse_source_failure_context(context) is None


def test_receipt_rejects_gap_with_forged_observation_details() -> None:
    context = response_source_failure_context(_view_context(), verification_status="verified")
    assert context is not None
    gap = context["gaps"][0]
    assert isinstance(gap, dict)
    gap["reason"] = "provider_timeout"
    gap["last_observed_at"] = "2026-07-20T08:00:00Z"

    assert parse_source_failure_context(context) is None


def test_receipt_rejects_unavailable_source_without_reason() -> None:
    context = response_source_failure_context(_view_context(), verification_status="verified")
    assert context is not None
    for collection in (context["sources"], context["gaps"]):
        item = collection[-1]
        assert isinstance(item, dict)
        item.pop("reason")

    assert parse_source_failure_context(context) is None


def test_receipt_rejects_duplicate_source_key() -> None:
    context = response_source_failure_context(_view_context(), verification_status="verified")
    assert context is not None
    duplicate = dict(context["sources"][0])
    duplicate["source"] = "another-audit-source"
    context["sources"].append(duplicate)

    assert parse_source_failure_context(context) is None


def test_manifest_answer_includes_unavailable_reason_and_observation() -> None:
    evidence = _view_context()["_tool_evidence"]
    assert isinstance(evidence, dict)

    answer = render_read_source_answer(evidence, locale="en")

    assert answer is not None
    assert "reason reader_unauthorized" in answer
    assert "last observed 2026-07-20T09:00:00Z" in answer
