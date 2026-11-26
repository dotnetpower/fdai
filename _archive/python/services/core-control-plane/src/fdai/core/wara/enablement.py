"""WARA assessment preferences, separate from applicability and authority."""

from fdai_service_contracts.control_enablement import ControlEnablement, resolve_control_enablement

from fdai.rule_catalog.schema.wara_assessment import (
    WaraAssessmentCatalog,
    WaraRecommendationCrosswalk,
)

from .models import WaraAssessmentRequest


def validate_enablement_profile(
    catalog: WaraAssessmentCatalog, request: WaraAssessmentRequest
) -> None:
    if request.enablement_profile is not None:
        request.enablement_profile.validate_binding(
            framework_id="azure-wara",
            source_revision=catalog.source_revision,
            scope_digest=request.scope_digest,
            evaluated_at=request.evaluated_at,
            control_ids={record.aprl_guid for record in catalog.recommendations},
        )


def control_enablement(
    record: WaraRecommendationCrosswalk, request: WaraAssessmentRequest
) -> ControlEnablement:
    return resolve_control_enablement(
        record.impact,
        enabled=(
            request.enablement_profile.override_for(record.aprl_guid)
            if request.enablement_profile is not None
            else None
        ),
    )
