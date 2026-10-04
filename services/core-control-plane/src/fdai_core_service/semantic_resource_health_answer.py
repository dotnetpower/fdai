"""Render Resource Health answers only after typed claim validation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from fdai.core.ontology_platform.resource_health_queries import (
    ResourceHealthAnswerValidation,
    ResourceHealthAvailabilityState,
    ResourceHealthCollection,
    ResourceHealthCoverage,
    ResourceHealthCoverageStatus,
    ResourceHealthNarrationClaims,
    ResourceHealthObservation,
    ResourceHealthTerminalDisposition,
    validate_resource_health_answer,
)

from .semantic_verified_rows import verified_rows_table

_HOLD_NOTICE = (
    "Resource Health 서술은 구조화된 주장 검증을 통과하지 못해 보류되었습니다. "
    "검증된 행과 검증 코드를 기술 근거로 표시합니다.",
    "Resource Health narration was held because structured claim validation did not pass. "
    "Verified rows and validation codes are shown as evidence.",
)
_INVALID_NOTICE = (
    "Resource Health 서술은 구조화된 Resource Health 행을 검증하지 못해 보류되었습니다.",
    "Resource Health narration was held because structured Resource Health rows could not be "
    "verified.",
)
_LEADING_FIELDS = (
    "availability_state",
    "coverage_state",
    "health_concept",
    "matching_health_concepts",
    "health_kind",
)


def attach_resource_health_narration_claims(outputs: list[dict[str, object]]) -> None:
    """Attach deterministic Resource Health claims to technical details when no model wrote them."""

    for output in outputs:
        if isinstance(output.get("resource_health_narration"), str):
            continue
        collection = _collection_from_output(output)
        if collection is None:
            continue
        output["resource_health_narration_claims"] = _claims_json(
            _claims_from_collection(collection)
        )


def render_resource_health_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    """Return accepted Resource Health model narration or a verified-evidence hold."""

    if output_shape != "resource_health_list" or len(outputs) != 1:
        return None
    output = outputs[0]
    collection = _collection_from_output(output)
    raw_narration = output.get("resource_health_narration")
    if isinstance(raw_narration, str):
        if collection is None:
            return _hold_answer(
                output,
                korean=korean,
                validation=None,
                invalid_evidence=True,
            )
        claims = _claims_from_mapping(output.get("resource_health_narration_claims"))
        validation = validate_resource_health_answer(
            collection,
            narration=raw_narration,
            claims=claims,
        )
        output["resource_health_answer_validation"] = _validation_json(validation)
        if validation.accepted:
            return raw_narration
        return _hold_answer(output, korean=korean, validation=validation, invalid_evidence=False)

    if collection is None:
        return None
    claims = _claims_from_collection(collection)
    validation = validate_resource_health_answer(
        collection,
        narration="validated",
        claims=claims,
    )
    output["resource_health_narration_claims"] = _claims_json(claims)
    output["resource_health_answer_validation"] = _validation_json(validation)
    return None


def _collection_from_output(output: Mapping[str, object]) -> ResourceHealthCollection | None:
    rows = output.get("rows")
    if not isinstance(rows, list):
        return None
    health_values = [
        values
        for row in rows
        if isinstance(row, Mapping)
        and isinstance((values := row.get("values")), Mapping)
        and values.get("evidence_family") == "resource_health"
    ]
    if not health_values:
        return None
    coverage: list[ResourceHealthCoverage] = []
    observations: list[ResourceHealthObservation] = []
    starts: list[datetime] = []
    completions: list[datetime] = []
    for values in health_values:
        resource_id = _bounded_text(values.get("resource_id"), maximum=1024)
        coverage_state = _coverage(values.get("coverage_state"))
        if resource_id is None or coverage_state is None:
            return None
        coverage.append(ResourceHealthCoverage(resource_id=resource_id, status=coverage_state))
        started_at = _timestamp(values.get("collection_started_at"))
        completed_at = _timestamp(values.get("collection_completed_at"))
        if started_at is not None:
            starts.append(started_at)
        if completed_at is not None:
            completions.append(completed_at)
        availability = _availability(values.get("availability_state"))
        if availability is None:
            continue
        reason_kind = _bounded_text(values.get("health_kind"), maximum=64) or "status_only"
        evidence_ref = _bounded_text(values.get("evidence_ref"), maximum=256)
        if evidence_ref is None:
            return None
        provider_observed_at = _timestamp(values.get("provider_observed_at"))
        observations.append(
            ResourceHealthObservation(
                resource_id=resource_id,
                availability_state=availability,
                reason_kind=reason_kind,
                provider_observed_at=provider_observed_at,
                evidence_ref=evidence_ref,
            )
        )
    if not starts or not completions:
        return None
    ordered_ids = tuple(sorted(item.resource_id for item in coverage))
    coverage_by_id = {item.resource_id: item for item in coverage}
    observations_by_id = {item.resource_id: item for item in observations}
    if len(coverage_by_id) != len(coverage):
        return None
    try:
        return ResourceHealthCollection(
            resource_ids=ordered_ids,
            observations=tuple(
                observations_by_id[resource_id]
                for resource_id in ordered_ids
                if resource_id in observations_by_id
            ),
            coverage=tuple(coverage_by_id[resource_id] for resource_id in ordered_ids),
            started_at=min(starts),
            completed_at=max(completions),
            attempt_ref="resource-health-answer-composition",
        )
    except ValueError:
        return None


def _claims_from_collection(collection: ResourceHealthCollection) -> ResourceHealthNarrationClaims:
    validation = validate_resource_health_answer(collection, narration="validated", claims=None)
    observed_count = sum(
        1 for item in collection.coverage if item.status is ResourceHealthCoverageStatus.OBSERVED
    )
    return ResourceHealthNarrationClaims(
        terminal_disposition=validation.terminal_disposition,
        all_clear=validation.terminal_disposition is ResourceHealthTerminalDisposition.ALL_CLEAR,
        denominator_count=len(collection.resource_ids),
        observed_count=observed_count,
        reason_codes=validation.preserved_reasons,
        window_started_at=collection.started_at,
        window_completed_at=collection.completed_at,
        execution_authority=False,
    )


def _hold_answer(
    output: Mapping[str, object],
    *,
    korean: bool,
    validation: ResourceHealthAnswerValidation | None,
    invalid_evidence: bool,
) -> str:
    notice = _INVALID_NOTICE if invalid_evidence else _HOLD_NOTICE
    heading = "## Resource Health 답변 보류" if korean else "## Resource Health answer held"
    lines = [heading, "", notice[0 if korean else 1]]
    table = verified_rows_table(output, korean=korean, leading=_LEADING_FIELDS)
    if table:
        lines.extend(["", "## 검증된 근거 행" if korean else "## Verified evidence rows", *table])
    lines.extend(_validation_lines(validation, korean=korean))
    lines.extend(
        [
            "",
            (
                "읽기 전용이며 `execution_authority=false`입니다."
                if korean
                else "Read-only; `execution_authority=false`."
            ),
        ]
    )
    return "\n".join(lines)


def _validation_lines(
    validation: ResourceHealthAnswerValidation | None,
    *,
    korean: bool,
) -> list[str]:
    heading = "## 검증 데이터" if korean else "## Validation data"
    if validation is None:
        return [
            "",
            heading,
            "",
            "- `terminal_disposition`: `unavailable`",
            "- `violations`: `resource_health_evidence_invalid`",
        ]
    reason_codes = ", ".join(f"`{reason}`" for reason in validation.preserved_reasons) or "`none`"
    violations = ", ".join(f"`{item}`" for item in validation.violations) or "`none`"
    return [
        "",
        heading,
        "",
        f"- `terminal_disposition`: `{validation.terminal_disposition.value}`",
        f"- `preserved_reason_codes`: {reason_codes}",
        f"- `violations`: {violations}",
    ]


def _claims_from_mapping(value: object) -> ResourceHealthNarrationClaims | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return ResourceHealthNarrationClaims(
            terminal_disposition=ResourceHealthTerminalDisposition(
                str(value["terminal_disposition"])
            ),
            all_clear=_boolean(value["all_clear"]),
            denominator_count=_integer(value["denominator_count"]),
            observed_count=_integer(value["observed_count"]),
            reason_codes=_string_tuple(value["reason_codes"]),
            window_started_at=_timestamp(value["window_started_at"]) or datetime.min,
            window_completed_at=_timestamp(value["window_completed_at"]) or datetime.min,
            execution_authority=_boolean(value["execution_authority"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _claims_json(claims: ResourceHealthNarrationClaims) -> dict[str, object]:
    return {
        "terminal_disposition": claims.terminal_disposition.value,
        "all_clear": claims.all_clear,
        "denominator_count": claims.denominator_count,
        "observed_count": claims.observed_count,
        "reason_codes": list(claims.reason_codes),
        "window_started_at": claims.window_started_at.isoformat(),
        "window_completed_at": claims.window_completed_at.isoformat(),
        "execution_authority": claims.execution_authority,
    }


def _validation_json(validation: ResourceHealthAnswerValidation) -> dict[str, object]:
    return {
        "accepted": validation.accepted,
        "terminal_disposition": validation.terminal_disposition.value,
        "preserved_reasons": list(validation.preserved_reasons),
        "violations": list(validation.violations),
        "execution_authority": validation.execution_authority,
    }


def _coverage(value: object) -> ResourceHealthCoverageStatus | None:
    try:
        return ResourceHealthCoverageStatus(str(value))
    except ValueError:
        return None


def _availability(value: object) -> ResourceHealthAvailabilityState | None:
    if value is None:
        return None
    try:
        return ResourceHealthAvailabilityState(str(value))
    except ValueError:
        return None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _bounded_text(value: object, *, maximum: int) -> str | None:
    if isinstance(value, str) and value.strip() and len(value) <= maximum:
        return value
    return None


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Resource Health narration count must be an integer")
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError("Resource Health narration boolean field must be boolean")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError("Resource Health narration reason_codes must be a string list")
    return tuple(value)


__all__ = [
    "attach_resource_health_narration_claims",
    "render_resource_health_answer",
]
