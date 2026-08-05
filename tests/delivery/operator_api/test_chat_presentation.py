from __future__ import annotations

from collections.abc import Mapping

from fdai.core.conversation.answer_plan import (
    AnswerFormat,
    AnswerIntent,
    AnswerPlan,
    AnswerSection,
    AudienceLevel,
    DetailLevel,
    DiscussPolicy,
    EvidenceRequirement,
)
from fdai.delivery.operator_api.routes.chat_presentation import (
    adapt_answer_plan_for_presentation,
    select_answer_presentation,
)
from fdai.delivery.operator_api.routes.chat_presentation_artifact import (
    response_presentation_artifact,
)
from fdai.delivery.operator_api.routes.chat_presentation_contract import (
    PresentationProfile,
    PresentationSlot,
    default_presentation_plan,
    parse_presentation_plan,
    presentation_plan_schema,
)
from fdai.delivery.operator_api.routes.chat_presentation_profiles import (
    presentation_profile,
)


class _StructuredBackend:
    def __init__(self, result: Mapping[str, object]) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def complete_structured(self, **kwargs: object) -> Mapping[str, object]:
        self.calls.append(dict(kwargs))
        return self.result


def _presentation_profile() -> PresentationProfile:
    return PresentationProfile(
        kind="subscription_health",
        slots=(
            PresentationSlot(
                slot_id="overview",
                role="summary",
                allowed_components=("summary_band",),
                default_component="summary_band",
                default_emphasis="primary",
                default_collapsed=False,
                can_collapse=False,
                record_count_bucket="one",
                coverage_state="complete",
            ),
            PresentationSlot(
                slot_id="findings",
                role="attention",
                allowed_components=("status_table", "detail_list"),
                default_component="status_table",
                default_emphasis="primary",
                default_collapsed=False,
                can_collapse=False,
                record_count_bucket="few",
                coverage_state="limited",
            ),
        ),
    )


def _plan(
    *,
    format_: AnswerFormat = AnswerFormat.PROSE,
    overrides: tuple[str, ...] = (),
    preference_applied: bool = False,
) -> AnswerPlan:
    return AnswerPlan(
        intent=AnswerIntent.DEFINITION,
        detail_level=DetailLevel.STANDARD,
        format=format_,
        sections=(AnswerSection.DEFINITION,),
        evidence_requirement=EvidenceRequirement.SERVER_READ_MODEL,
        audience_level=AudienceLevel.GENERAL,
        clarification=None,
        max_words=260,
        discuss=DiscussPolicy.SKIP,
        subject="FDAI databases",
        explicit_overrides=overrides,
        preference_applied=preference_applied,
    )


def _inventory_context() -> dict[str, object]:
    return {
        "_tool_evidence": {
            "tool": "query_inventory",
            "result": {
                "status": "matched",
                "query_kind": "list",
                "matched_count": 3,
                "resources": [
                    {
                        "name": "db-one",
                        "type": "postgresql-server",
                        "status": "Running",
                        "location": "example-region",
                        "resource_group": "example-group",
                    },
                    {
                        "name": "db-two",
                        "type": "mysql-server",
                        "status": "Stopped",
                        "location": "example-region",
                        "resource_group": "example-group",
                    },
                    {
                        "name": "db-three",
                        "type": "postgresql-server",
                        "status": "Stopped",
                        "location": "example-region",
                        "resource_group": "example-group",
                    },
                ],
                "matched_type_counts": {
                    "postgresql-server": 2,
                    "mysql-server": 1,
                },
                "source": "inventory",
                "snapshot_at": "2026-08-05T00:00:00Z",
                "freshness": "fresh",
            },
        }
    }


def _health_context() -> dict[str, object]:
    return {
        "_tool_evidence": {
            "tool": "query_subscription_health",
            "result": {
                "status": "partial",
                "resource_count": 454,
                "resource_health_unavailable": 0,
                "service_health_unavailable": 0,
                "metric_checked": 11,
                "metric_unavailable": 5,
                "unsupported_metric_resources": 413,
                "truncated": True,
                "findings": [
                    {
                        "resource_name": "vm-sensitive-example",
                        "status": "Unavailable",
                    }
                ],
                "metric_observations": [
                    {
                        "resource_name": "storage-sensitive-example",
                        "metric": "Availability",
                        "value": 100.0,
                        "threshold": 99.0,
                    }
                ],
            },
        }
    }


async def test_structured_model_selects_supported_chart_without_receiving_row_values() -> None:
    backend = _StructuredBackend({"format": "chart"})
    context = _inventory_context()
    evidence = context["_tool_evidence"]
    assert isinstance(evidence, dict)
    result = evidence["result"]
    assert isinstance(result, dict)
    result["query_kind"] = "types"

    selected = await adapt_answer_plan_for_presentation(
        backend=backend,
        prompt="DB 종류별 분포를 보기 좋게 보여줘",
        plan=_plan(),
        view_context=context,
    )

    assert selected.format is AnswerFormat.CHART
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call["schema_name"] == "fdai_presentation_selection"
    assert "db-one" not in str(call["user_content"])
    assert "record_count" in str(call["user_content"])


async def test_model_selects_table_for_comparable_rows() -> None:
    backend = _StructuredBackend({"format": "table"})

    selected = await adapt_answer_plan_for_presentation(
        backend=backend,
        prompt="FDAI가 사용하는 DB가 뭐야?",
        plan=_plan(),
        view_context=_inventory_context(),
    )

    assert selected.format is AnswerFormat.TABLE
    assert len(backend.calls) == 1


async def test_model_cannot_select_bullets_for_comparable_rows() -> None:
    backend = _StructuredBackend({"format": "bullets"})

    selected = await adapt_answer_plan_for_presentation(
        backend=backend,
        prompt="FDAI가 사용하는 DB가 뭐야?",
        plan=_plan(),
        view_context=_inventory_context(),
    )

    assert selected.format is AnswerFormat.TABLE
    assert len(backend.calls) == 1


async def test_explicit_format_override_skips_model_selection() -> None:
    backend = _StructuredBackend({"format": "chart"})

    selected = await adapt_answer_plan_for_presentation(
        backend=backend,
        prompt="표로 보여줘",
        plan=_plan(format_=AnswerFormat.TABLE, overrides=("table",)),
        view_context=_inventory_context(),
    )

    assert selected.format is AnswerFormat.TABLE
    assert backend.calls == []


async def test_saved_preference_skips_model_selection() -> None:
    backend = _StructuredBackend({"format": "chart"})

    selected = await adapt_answer_plan_for_presentation(
        backend=backend,
        prompt="DB를 보여줘",
        plan=_plan(format_=AnswerFormat.BULLETS, preference_applied=True),
        view_context=_inventory_context(),
    )

    assert selected.format is AnswerFormat.BULLETS
    assert backend.calls == []


async def test_non_inventory_evidence_keeps_existing_plan() -> None:
    backend = _StructuredBackend({"format": "table"})
    plan = _plan()

    selected = await adapt_answer_plan_for_presentation(
        backend=backend,
        prompt="설명해줘",
        plan=plan,
        view_context={"_tool_evidence": {"tool": "query_audit", "result": {}}},
    )

    assert selected is plan
    assert backend.calls == []


async def test_specialized_inventory_coverage_keeps_its_deterministic_renderer() -> None:
    backend = _StructuredBackend({"format": "table"})
    plan = _plan()
    context = _inventory_context()
    evidence = context["_tool_evidence"]
    assert isinstance(evidence, dict)
    result = evidence["result"]
    assert isinstance(result, dict)
    result["scope_counts"] = True

    selected = await adapt_answer_plan_for_presentation(
        backend=backend,
        prompt="Azure 관리 범위 합계를 보여줘",
        plan=plan,
        view_context=context,
    )

    assert selected is plan
    assert backend.calls == []


def test_presentation_schema_uses_supported_structured_output_subset() -> None:
    schema = presentation_plan_schema(_presentation_profile())

    assert "maxLength" not in str(schema)
    assert "maxItems" not in str(schema)
    assert "minimum" not in str(schema)
    assert schema["additionalProperties"] is False


def test_presentation_plan_requires_every_slot_once_with_allowed_component() -> None:
    profile = _presentation_profile()
    raw = {
        "schema_version": 1,
        "layout": "stack",
        "placements": [
            {
                "slot_id": "findings",
                "component": "detail_list",
                "emphasis": "primary",
                "collapsed": False,
                "rationale": "attention",
            },
            {
                "slot_id": "overview",
                "component": "summary_band",
                "emphasis": "secondary",
                "collapsed": False,
                "rationale": "summary",
            },
        ],
    }

    parsed = parse_presentation_plan(raw, profile)

    assert parsed is not None
    assert [placement.slot_id for placement in parsed.placements] == ["findings", "overview"]


def test_presentation_plan_rejects_duplicate_missing_and_forbidden_slots() -> None:
    profile = _presentation_profile()
    base = {
        "schema_version": 1,
        "layout": "stack",
        "placements": [
            {
                "slot_id": "overview",
                "component": "summary_band",
                "emphasis": "primary",
                "collapsed": False,
                "rationale": "summary",
            },
            {
                "slot_id": "findings",
                "component": "status_table",
                "emphasis": "primary",
                "collapsed": False,
                "rationale": "attention",
            },
        ],
    }

    duplicate = {**base, "placements": [base["placements"][0], base["placements"][0]]}
    missing = {**base, "placements": [base["placements"][0]]}
    forbidden_rows = [dict(item) for item in base["placements"]]
    forbidden_rows[1]["component"] = "line_chart"
    forbidden = {**base, "placements": forbidden_rows}

    assert parse_presentation_plan(duplicate, profile) is None
    assert parse_presentation_plan(missing, profile) is None
    assert parse_presentation_plan(forbidden, profile) is None


def test_default_presentation_plan_never_omits_available_slots() -> None:
    plan = default_presentation_plan(_presentation_profile())

    assert [placement.slot_id for placement in plan.placements] == ["overview", "findings"]
    assert plan.placements[1].component == "status_table"


async def test_health_presentation_selects_mixed_slots_without_evidence_values() -> None:
    backend = _StructuredBackend(
        {
            "schema_version": 1,
            "layout": "stack",
            "placements": [
                {
                    "slot_id": "overview",
                    "component": "summary_band",
                    "emphasis": "primary",
                    "collapsed": False,
                    "rationale": "summary",
                },
                {
                    "slot_id": "limitations",
                    "component": "callout",
                    "emphasis": "primary",
                    "collapsed": False,
                    "rationale": "limitation",
                },
                {
                    "slot_id": "findings",
                    "component": "status_table",
                    "emphasis": "primary",
                    "collapsed": False,
                    "rationale": "attention",
                },
                {
                    "slot_id": "coverage",
                    "component": "coverage_bar",
                    "emphasis": "secondary",
                    "collapsed": False,
                    "rationale": "coverage",
                },
                {
                    "slot_id": "metrics",
                    "component": "threshold_table",
                    "emphasis": "supporting",
                    "collapsed": True,
                    "rationale": "detail",
                },
                {
                    "slot_id": "evidence",
                    "component": "evidence_footer",
                    "emphasis": "supporting",
                    "collapsed": False,
                    "rationale": "provenance",
                },
            ],
        }
    )

    decision = await select_answer_presentation(
        backend=backend,
        prompt="현재 구독 상태를 시각적으로 보여줘",
        plan=_plan(),
        view_context=_health_context(),
    )

    assert decision.answer_plan.format is AnswerFormat.MIXED
    assert decision.presentation_plan is not None
    assert [item.slot_id for item in decision.presentation_plan.placements] == [
        "overview",
        "limitations",
        "findings",
        "coverage",
        "metrics",
        "evidence",
    ]
    call = backend.calls[0]
    assert call["schema_name"] == "fdai_presentation_plan"
    assert "vm-sensitive-example" not in str(call["user_content"])
    assert "storage-sensitive-example" not in str(call["user_content"])
    assert "100.0" not in str(call["user_content"])
    assert '"coverage_state":"limited"' in str(call["user_content"])


async def test_invalid_health_plan_falls_back_without_omitting_available_slots() -> None:
    backend = _StructuredBackend(
        {
            "schema_version": 1,
            "layout": "stack",
            "placements": [],
        }
    )

    decision = await select_answer_presentation(
        backend=backend,
        prompt="show health",
        plan=_plan(),
        view_context=_health_context(),
    )

    assert decision.presentation_plan is not None
    assert [item.slot_id for item in decision.presentation_plan.placements] == [
        "overview",
        "limitations",
        "findings",
        "coverage",
        "metrics",
        "evidence",
    ]


async def test_saved_plain_preference_suppresses_structured_artifact() -> None:
    decision = await select_answer_presentation(
        backend=_StructuredBackend({}),
        prompt="show health",
        plan=_plan(format_=AnswerFormat.BULLETS, preference_applied=True),
        view_context=_health_context(),
    )

    assert decision.answer_plan.format is AnswerFormat.BULLETS
    assert decision.presentation_plan is None


async def test_unsupported_saved_chart_preference_reports_actual_table_shape() -> None:
    decision = await select_answer_presentation(
        backend=_StructuredBackend({}),
        prompt="show databases",
        plan=_plan(format_=AnswerFormat.CHART, preference_applied=True),
        view_context=_inventory_context(),
    )

    assert decision.answer_plan.format is AnswerFormat.TABLE
    assert decision.presentation_plan is not None
    assert any(
        placement.component == "data_table" for placement in decision.presentation_plan.placements
    )


async def test_health_plan_compiles_every_available_slot_into_grounded_blocks() -> None:
    context = _health_context()
    decision = await select_answer_presentation(
        backend=object(),
        prompt="show health",
        plan=_plan(),
        view_context=context,
    )
    assert decision.presentation_plan is not None
    context["_presentation_plan"] = decision.presentation_plan.to_dict()

    artifact = response_presentation_artifact(
        context,
        answer_plan=decision.answer_plan,
        verification_status="unverified",
        evidence_refs=("subscription-health:test@2026-08-05T00:00:00Z",),
        locale="ko",
    )

    assert artifact is not None
    blocks = artifact["blocks"]
    assert isinstance(blocks, list)
    assert [block["slot_id"] for block in blocks] == [
        "overview",
        "limitations",
        "findings",
        "coverage",
        "metrics",
        "evidence",
    ]
    assert blocks[1]["kind"] == "callout"
    assert "전체 결론은 검증되지 않았습니다" in str(blocks[1])
    assert blocks[3]["data"]["items"][2]["value"] == 413


def test_health_artifact_applies_typed_resource_filter() -> None:
    context = _health_context()
    evidence = context["_tool_evidence"]
    assert isinstance(evidence, dict)
    evidence["query"] = {"requested_resource_types": ["Microsoft.Storage/storageAccounts"]}
    result = evidence["result"]
    assert isinstance(result, dict)
    result["findings"] = [
        {
            "resource_name": "storage-example",
            "resource_type": "Microsoft.Storage/storageAccounts",
            "status": "Unavailable",
            "resource_group": "rg-example",
            "reason": "Platform Initiated",
        },
        {
            "resource_name": "vm-must-not-leak",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "status": "Unavailable",
            "resource_group": "rg-example",
            "reason": "Platform Initiated",
        },
    ]
    profile = presentation_profile(context, _plan())
    assert profile is not None
    context["_presentation_plan"] = default_presentation_plan(profile).to_dict()

    artifact = response_presentation_artifact(
        context,
        answer_plan=_plan(format_=AnswerFormat.MIXED),
        verification_status="verified",
        evidence_refs=("subscription-health:test@2026-08-05T00:00:00Z",),
        locale="en",
    )

    assert artifact is not None
    assert "storage-example" in str(artifact)
    assert "vm-must-not-leak" not in str(artifact)


async def test_health_artifact_compiles_every_allowed_alternate_component() -> None:
    context = _health_context()
    profile = presentation_profile(context, _plan())
    assert profile is not None
    placements = default_presentation_plan(profile).to_dict()["placements"]
    assert isinstance(placements, list)
    for placement in placements:
        if placement["slot_id"] == "findings":
            placement["component"] = "detail_list"
        elif placement["slot_id"] in {"coverage", "metrics"}:
            placement["component"] = "data_table"
    context["_presentation_plan"] = {
        "schema_version": 1,
        "layout": "stack",
        "placements": placements,
    }

    artifact = response_presentation_artifact(
        context,
        answer_plan=_plan(format_=AnswerFormat.MIXED),
        verification_status="unverified",
        evidence_refs=("subscription-health:test@2026-08-05T00:00:00Z",),
        locale="en",
    )

    assert artifact is not None
    blocks = artifact["blocks"]
    assert isinstance(blocks, list)
    kinds = {block["slot_id"]: block["kind"] for block in blocks}
    assert kinds["findings"] == "list"
    assert kinds["coverage"] == "table"
    assert kinds["metrics"] == "table"


async def test_inventory_plan_preserves_table_fallback_and_compiles_mixed_artifact() -> None:
    context = _inventory_context()
    decision = await select_answer_presentation(
        backend=object(),
        prompt="show databases",
        plan=_plan(),
        view_context=context,
    )
    assert decision.presentation_plan is not None
    assert decision.answer_plan.format is AnswerFormat.TABLE
    context["_presentation_plan"] = decision.presentation_plan.to_dict()

    artifact = response_presentation_artifact(
        context,
        answer_plan=decision.answer_plan,
        verification_status="verified",
        evidence_refs=("inventory:test@2026-08-05T00:00:00Z",),
        locale="en",
    )

    assert artifact is not None
    blocks = artifact["blocks"]
    assert isinstance(blocks, list)
    assert [block["slot_id"] for block in blocks] == ["overview", "records", "evidence"]
    assert blocks[1]["kind"] == "table"
    assert "db-one" in str(blocks[1])


async def test_inventory_distribution_is_bounded_for_terminal_transport() -> None:
    context = _inventory_context()
    evidence = context["_tool_evidence"]
    assert isinstance(evidence, dict)
    result = evidence["result"]
    assert isinstance(result, dict)
    result["query_kind"] = "types"
    result["matched_type_counts"] = {f"type-{index}": index for index in range(100)}
    decision = await select_answer_presentation(
        backend=object(),
        prompt="show types",
        plan=_plan(),
        view_context=context,
    )
    assert decision.presentation_plan is not None
    context["_presentation_plan"] = decision.presentation_plan.to_dict()

    artifact = response_presentation_artifact(
        context,
        answer_plan=decision.answer_plan,
        verification_status="verified",
        evidence_refs=("inventory:test@2026-08-05T00:00:00Z",),
        locale="en",
    )

    assert artifact is not None
    blocks = artifact["blocks"]
    assert isinstance(blocks, list)
    distribution = next(block for block in blocks if block["slot_id"] == "distribution")
    assert len(distribution["data"]["items"]) == 16
