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
)


class _StructuredBackend:
    def __init__(self, result: Mapping[str, object]) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def complete_structured(self, **kwargs: object) -> Mapping[str, object]:
        self.calls.append(dict(kwargs))
        return self.result


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
            },
        }
    }


async def test_structured_model_selects_supported_chart_without_receiving_row_values() -> None:
    backend = _StructuredBackend({"format": "chart"})

    selected = await adapt_answer_plan_for_presentation(
        backend=backend,
        prompt="DB 종류별 분포를 보기 좋게 보여줘",
        plan=_plan(),
        view_context=_inventory_context(),
    )

    assert selected.format is AnswerFormat.CHART
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call["schema_name"] == "fdai_presentation_selection"
    assert "db-one" not in str(call["user_content"])
    assert "record_count" in str(call["user_content"])


async def test_invalid_model_format_falls_back_to_table_for_comparable_rows() -> None:
    backend = _StructuredBackend({"format": "unsupported"})

    selected = await adapt_answer_plan_for_presentation(
        backend=backend,
        prompt="FDAI가 사용하는 DB가 뭐야?",
        plan=_plan(),
        view_context=_inventory_context(),
    )

    assert selected.format is AnswerFormat.TABLE


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
