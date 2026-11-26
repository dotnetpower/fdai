"""Read-only WARA report material shared by every registered export format."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fdai.core.reporting.models import RenderedReport, RenderedWidget
from fdai.rule_catalog.schema.wara_assessment import WaraAssessmentCatalog, canonical_digest

from .models import WaraAssessmentResult

SUPPLEMENTAL_SOURCES = ("advisor", "outages", "retirements", "support_tickets", "service_health")


def build_wara_report(
    result: WaraAssessmentResult,
    catalog: WaraAssessmentCatalog,
    *,
    supplemental: Sequence[Mapping[str, object]] = (),
) -> RenderedReport:
    """Keep unknowns, source identity and errors separate from actual satisfaction."""

    if (
        result.execution_authority
        or result.mode != "shadow"
        or result.framework_revision != catalog.source_revision
        or result.crosswalk_digest != catalog.crosswalk_digest
        or canonical_digest(result.to_dict(include_digest=False)) != result.result_digest
    ):
        raise ValueError("WARA report requires an intact pinned shadow assessment")
    by_id = {record.aprl_guid: record for record in catalog.recommendations}
    if len(result.controls) != len(by_id) or {
        control.recommendation_id for control in result.controls
    } != set(by_id):
        raise ValueError("WARA report must account for every active recommendation")
    supplemental_by_source = {str(item.get("source")): dict(item) for item in supplemental}
    if len(supplemental_by_source) != len(supplemental) or set(supplemental_by_source) - set(
        SUPPLEMENTAL_SOURCES
    ):
        raise ValueError("WARA report supplemental source identities are invalid")
    rows = []
    for control in result.controls:
        record = by_id[control.recommendation_id]
        rows.append(
            {
                **control.to_dict(),
                "title": record.title,
                "provider_resource_type": record.provider_resource_type,
                "impact": record.impact,
                "source_path": record.source_path,
                "source_digest": record.source_digest,
            }
        )
    contexts = [
        supplemental_by_source.get(
            name,
            {
                "source": name,
                "status": "unavailable",
                "count": None,
                "complete": False,
                "limitation": "supplemental_source_not_connected",
            },
        )
        for name in SUPPLEMENTAL_SOURCES
    ]
    return RenderedReport(
        id="wara-assessment",
        version="1.0.0",
        name="WARA assessment",
        description="Read-only reliability assessment. No execution authority is granted.",
        generated_at=result.recorded_at,
        time_range=(result.evaluated_at, result.recorded_at),
        variables={
            "workload_id": result.workload_id,
            "scope_digest": result.scope_digest,
            "framework_revision": result.framework_revision,
            "crosswalk_digest": result.crosswalk_digest,
            "inventory_generation": result.inventory_generation,
            "result_digest": result.result_digest,
            "execution_authority": "false",
        },
        tags=("wara", "reliability", "shadow"),
        widgets=(
            RenderedWidget(
                id="coverage",
                type="table",
                title="Assessment coverage, not a compliance score",
                data={
                    "columns": ["state", "count"],
                    "rows": [
                        {"state": key, "count": count}
                        for key, count in sorted(result.aggregate_counts.items())
                    ],
                },
            ),
            RenderedWidget(
                id="recommendations",
                type="table",
                title="Every active recommendation",
                data={"columns": list(rows[0]), "rows": rows},
            ),
            RenderedWidget(
                id="supplemental",
                type="table",
                title="Supplemental context, not recommendation evidence",
                data={
                    "columns": [
                        "source",
                        "status",
                        "count",
                        "complete",
                        "scope",
                        "source_digest",
                        "limitation",
                    ],
                    "rows": contexts,
                },
            ),
        ),
    )


__all__ = ["SUPPLEMENTAL_SOURCES", "build_wara_report"]
