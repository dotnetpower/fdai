"""Validate and project one analyzer run's cross-resource coverage section."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from fdai_operator_service.families.operations import ProjectionUnavailableError

_EVALUATION_STATES = frozenset(
    {"evaluated_no_finding", "finding", "evaluation_error", "unsupported"}
)
_PUBLICATION_STATES = (
    "published",
    "published_receipt_unrecorded",
    "duplicate_suppressed",
    "reconciled_duplicate",
    "publish_uncertain",
    "awaiting_reconciliation",
    "failed",
)
_MAX_RESOURCE_TYPES = 32
_MAX_RESOURCES = 1_000


def project_analyzer_coverage(
    value: object,
    *,
    run_attempt_id: str,
) -> dict[str, object]:
    """Return one strictly reconciled no-authority coverage section."""

    root = _mapping(value, "analyzer coverage")
    schema_version = root.get("schema_version")
    if schema_version not in {"1.0.0", "1.1.0"}:
        raise ProjectionUnavailableError("analyzer coverage schema is unsupported")
    legacy = schema_version == "1.0.0"
    if root.get("cause_claim_supported") is not False:
        raise ProjectionUnavailableError("analyzer coverage claims a cause")
    if root.get("execution_authority") is not False:
        raise ProjectionUnavailableError("analyzer coverage widened its authority")
    status = _text(root.get("status"), "analyzer coverage status")
    reason = root.get("unavailable_reason")
    if status == "unavailable":
        return unavailable_analyzer_coverage(
            _text(reason, "analyzer coverage unavailable reason"),
            run_attempt_id=run_attempt_id,
        )
    if status != "available" or reason is not None:
        raise ProjectionUnavailableError("analyzer coverage availability is malformed")

    resource_type_values = _sequence(
        root.get("resource_types"),
        "analyzer coverage resource types",
        maximum=_MAX_RESOURCE_TYPES,
    )
    resource_values = _sequence(
        root.get("resources"),
        "analyzer coverage resources",
        maximum=_MAX_RESOURCES,
    )
    resource_types = [_resource_type(item, legacy=legacy) for item in resource_type_values]
    resources = [_resource(item, legacy=legacy) for item in resource_values]
    if len({row["resource_type"] for row in resource_types}) != len(resource_types):
        raise ProjectionUnavailableError("analyzer coverage resource types are duplicated")
    if len({row["resource_ref"] for row in resources}) != len(resources):
        raise ProjectionUnavailableError("analyzer coverage resource identities are duplicated")

    projected: dict[str, object] = {
        "schema_version": "1.1.0",
        "status": "available",
        "unavailable_reason": None,
        "run_attempt_id": _text(run_attempt_id, "analyzer coverage run attempt"),
        "candidate_count": _count(root, "candidate_count", "analyzer coverage"),
        "selected_count": _count(root, "selected_count", "analyzer coverage"),
        "evaluated_count": _count(root, "evaluated_count", "analyzer coverage"),
        "held_count": _count(root, "held_count", "analyzer coverage"),
        "finding_count": _count(root, "finding_count", "analyzer coverage"),
        "unsupported_count": _count(root, "unsupported_count", "analyzer coverage"),
        "error_count": _count(root, "error_count", "analyzer coverage"),
        "unattributed_error_count": _count(
            root,
            "unattributed_error_count",
            "analyzer coverage",
        ),
        "unattributed_error_codes": (
            ["legacy_unspecified"]
            if legacy and _count(root, "unattributed_error_count", "analyzer coverage") > 0
            else []
            if legacy
            else _string_list(
                root.get("unattributed_error_codes"),
                "analyzer coverage unattributed error codes",
                maximum=8,
            )
        ),
        "publication_counts": _publication_counts(
            root.get("publication_counts"),
            "analyzer coverage publication counts",
        ),
        "resource_types": resource_types,
        "resources": resources,
        "cause_claim_supported": False,
        "execution_authority": False,
    }
    _reconcile(projected)
    return projected


def unavailable_analyzer_coverage(
    reason: str,
    *,
    run_attempt_id: str | None,
) -> dict[str, object]:
    """Return a named section-local unavailable result."""

    return {
        "schema_version": "1.1.0",
        "status": "unavailable",
        "unavailable_reason": _text(reason, "analyzer coverage unavailable reason"),
        "run_attempt_id": (
            None
            if run_attempt_id is None
            else _text(run_attempt_id, "analyzer coverage run attempt")
        ),
        "cause_claim_supported": False,
        "execution_authority": False,
    }


def _resource_type(value: object, *, legacy: bool) -> dict[str, object]:
    row = _mapping(value, "analyzer coverage resource type")
    candidate_count = _count(row, "candidate_count", "analyzer coverage resource type")
    selected_count = _count(row, "selected_count", "analyzer coverage resource type")
    held_count = _count(row, "held_count", "analyzer coverage resource type")
    if candidate_count != selected_count + held_count:
        raise ProjectionUnavailableError(
            "analyzer coverage resource type candidate totals do not reconcile"
        )
    held_reason_counts = (
        {"legacy_unspecified": held_count}
        if legacy and held_count > 0
        else {}
        if legacy
        else _count_mapping(
            row.get("held_reason_counts"),
            "analyzer coverage held reason counts",
        )
    )
    if sum(held_reason_counts.values()) != held_count:
        raise ProjectionUnavailableError("analyzer coverage held reason totals do not reconcile")
    return {
        "resource_type": _text(
            row.get("resource_type"),
            "analyzer coverage resource type",
        ),
        "candidate_count": candidate_count,
        "selected_count": selected_count,
        "evaluated_count": _count(
            row,
            "evaluated_count",
            "analyzer coverage resource type",
        ),
        "held_count": held_count,
        "held_reason_counts": held_reason_counts,
        "finding_count": _count(
            row,
            "finding_count",
            "analyzer coverage resource type",
        ),
        "unsupported_count": _count(
            row,
            "unsupported_count",
            "analyzer coverage resource type",
        ),
        "error_count": _count(row, "error_count", "analyzer coverage resource type"),
        "error_codes": _legacy_error_codes(row, legacy=legacy, label="resource type"),
        "publication_counts": _publication_counts(
            row.get("publication_counts"),
            "analyzer coverage resource type publication counts",
        ),
    }


def _resource(value: object, *, legacy: bool) -> dict[str, object]:
    row = _mapping(value, "analyzer coverage resource")
    state = _text(row.get("evaluation_state"), "analyzer coverage evaluation state")
    if state not in _EVALUATION_STATES:
        raise ProjectionUnavailableError("analyzer coverage evaluation state is unsupported")
    finding_count = _count(row, "finding_count", "analyzer coverage resource")
    unsupported_count = _count(row, "unsupported_count", "analyzer coverage resource")
    error_count = _count(row, "error_count", "analyzer coverage resource")
    error_codes = _legacy_error_codes(row, legacy=legacy, label="resource")
    if (error_count == 0) != (len(error_codes) == 0):
        raise ProjectionUnavailableError("analyzer coverage resource error codes are inconsistent")
    publications = _publication_counts(
        row.get("publication_counts"),
        "analyzer coverage resource publication counts",
    )
    if sum(publications.values()) != finding_count:
        raise ProjectionUnavailableError(
            "analyzer coverage resource publication totals do not reconcile"
        )
    if state == "evaluated_no_finding" and (
        finding_count != 0 or error_count != 0 or unsupported_count != 0
    ):
        raise ProjectionUnavailableError("analyzer coverage no-finding evaluation is inconsistent")
    if state == "finding" and finding_count == 0:
        raise ProjectionUnavailableError("analyzer coverage finding state has no finding")
    if state == "evaluation_error" and error_count == 0:
        raise ProjectionUnavailableError("analyzer coverage error state has no error")
    if state == "unsupported" and unsupported_count == 0:
        raise ProjectionUnavailableError("analyzer coverage unsupported state is inconsistent")
    return {
        "resource_ref": _text(
            row.get("resource_ref"),
            "analyzer coverage resource reference",
            maximum=512,
        ),
        "resource_type": _text(
            row.get("resource_type"),
            "analyzer coverage resource type",
        ),
        "resource_kind": _text(
            row.get("resource_kind"),
            "analyzer coverage resource kind",
        ),
        "evaluation_state": state,
        "finding_count": finding_count,
        "unsupported_count": unsupported_count,
        "error_count": error_count,
        "error_codes": error_codes,
        "publication_counts": publications,
    }


def _reconcile(coverage: Mapping[str, object]) -> None:
    resource_types = coverage["resource_types"]
    resources = coverage["resources"]
    if not isinstance(resource_types, list) or not isinstance(resources, list):
        raise ProjectionUnavailableError("analyzer coverage rows are malformed")
    by_type = {str(row["resource_type"]): row for row in resource_types if isinstance(row, Mapping)}
    observed: dict[str, Counter[str]] = {resource_type: Counter() for resource_type in by_type}
    observed_publications: dict[str, Counter[str]] = {
        resource_type: Counter() for resource_type in by_type
    }
    for resource in resources:
        if not isinstance(resource, Mapping):
            raise ProjectionUnavailableError("analyzer coverage resource is malformed")
        resource_type = str(resource["resource_type"])
        if resource_type not in by_type:
            raise ProjectionUnavailableError("analyzer coverage resource type row is missing")
        counts = observed[resource_type]
        counts["selected"] += 1
        if resource["evaluation_state"] in {"evaluated_no_finding", "finding"}:
            counts["evaluated"] += 1
        counts["finding"] += int(resource["finding_count"])
        counts["unsupported"] += int(resource["unsupported_count"])
        counts["error"] += int(resource["error_count"])
        publications = resource["publication_counts"]
        if not isinstance(publications, Mapping):
            raise ProjectionUnavailableError(
                "analyzer coverage resource publication counts are malformed"
            )
        observed_publications[resource_type].update(
            {state: int(publications[state]) for state in _PUBLICATION_STATES}
        )

    for resource_type, row in by_type.items():
        counts = observed[resource_type]
        if (
            counts["selected"] != row["selected_count"]
            or counts["evaluated"] != row["evaluated_count"]
            or counts["finding"] != row["finding_count"]
            or counts["unsupported"] != row["unsupported_count"]
            or counts["error"] != row["error_count"]
            or sorted(
                {
                    code
                    for resource in resources
                    if isinstance(resource, Mapping)
                    and resource.get("resource_type") == resource_type
                    for code in _string_list(
                        resource.get("error_codes"),
                        "analyzer coverage resource error codes",
                        maximum=8,
                    )
                }
            )
            != row["error_codes"]
            or {state: observed_publications[resource_type][state] for state in _PUBLICATION_STATES}
            != _row_publication_counts(row)
        ):
            raise ProjectionUnavailableError(
                "analyzer coverage resource type totals do not reconcile"
            )

    totals = {
        "candidate_count": sum(
            _count(row, "candidate_count", "analyzer coverage resource type")
            for row in by_type.values()
        ),
        "selected_count": sum(
            _count(row, "selected_count", "analyzer coverage resource type")
            for row in by_type.values()
        ),
        "evaluated_count": sum(
            _count(row, "evaluated_count", "analyzer coverage resource type")
            for row in by_type.values()
        ),
        "held_count": sum(
            _count(row, "held_count", "analyzer coverage resource type") for row in by_type.values()
        ),
        "finding_count": sum(
            _count(row, "finding_count", "analyzer coverage resource type")
            for row in by_type.values()
        ),
        "unsupported_count": sum(
            _count(row, "unsupported_count", "analyzer coverage resource type")
            for row in by_type.values()
        ),
    }
    if any(coverage[key] != value for key, value in totals.items()):
        raise ProjectionUnavailableError("analyzer coverage global totals do not reconcile")
    candidate_count = _count(coverage, "candidate_count", "analyzer coverage")
    selected_count = _count(coverage, "selected_count", "analyzer coverage")
    held_count = _count(coverage, "held_count", "analyzer coverage")
    if candidate_count != selected_count + held_count:
        raise ProjectionUnavailableError("analyzer coverage candidate totals do not reconcile")
    resource_error_count = sum(
        _count(row, "error_count", "analyzer coverage resource type") for row in by_type.values()
    )
    if _count(coverage, "error_count", "analyzer coverage") != (
        resource_error_count + _count(coverage, "unattributed_error_count", "analyzer coverage")
    ):
        raise ProjectionUnavailableError("analyzer coverage error totals do not reconcile")
    attributed_codes = {
        code
        for row in by_type.values()
        for code in _string_list(
            row.get("error_codes"),
            "analyzer coverage resource type error codes",
            maximum=8,
        )
    }
    unattributed_codes = _string_list(
        coverage.get("unattributed_error_codes"),
        "analyzer coverage unattributed error codes",
        maximum=8,
    )
    if (_count(coverage, "unattributed_error_count", "analyzer coverage") == 0) != (
        len(unattributed_codes) == 0
    ):
        raise ProjectionUnavailableError(
            "analyzer coverage unattributed error codes are inconsistent"
        )
    if any(not code for code in attributed_codes):
        raise ProjectionUnavailableError("analyzer coverage error codes are malformed")
    global_publications = coverage["publication_counts"]
    if not isinstance(global_publications, Mapping):
        raise ProjectionUnavailableError("analyzer coverage publication counts are malformed")
    for state in _PUBLICATION_STATES:
        global_value = global_publications.get(state)
        if not isinstance(global_value, int) or global_value != sum(
            _row_publication_counts(row)[state] for row in by_type.values()
        ):
            raise ProjectionUnavailableError(
                "analyzer coverage publication totals do not reconcile"
            )


def _publication_counts(value: object, label: str) -> dict[str, int]:
    root = _mapping(value, label)
    if set(root) != set(_PUBLICATION_STATES):
        raise ProjectionUnavailableError(f"{label} keys are malformed")
    return {state: _count(root, state, label) for state in _PUBLICATION_STATES}


def _row_publication_counts(row: Mapping[str, object]) -> dict[str, int]:
    return _publication_counts(
        row.get("publication_counts"),
        "analyzer coverage resource type publication counts",
    )


def _legacy_error_codes(
    row: Mapping[str, object],
    *,
    legacy: bool,
    label: str,
) -> list[str]:
    if legacy:
        return (
            ["legacy_unspecified"]
            if _count(row, "error_count", f"analyzer coverage {label}") > 0
            else []
        )
    return _string_list(
        row.get("error_codes"),
        f"analyzer coverage {label} error codes",
        maximum=8,
    )


def _count_mapping(value: object, label: str) -> dict[str, int]:
    root = _mapping(value, label)
    if len(root) > 16:
        raise ProjectionUnavailableError(f"{label} is malformed")
    result: dict[str, int] = {}
    for key in root:
        if not key or len(key) > 128:
            raise ProjectionUnavailableError(f"{label} is malformed")
        count = _count(root, key, label)
        if count == 0:
            raise ProjectionUnavailableError(f"{label} is malformed")
        result[key] = count
    return dict(sorted(result.items()))


def _string_list(value: object, label: str, *, maximum: int) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > maximum
        or len(value) != len(set(value))
        or any(not isinstance(item, str) or not item or len(item) > 128 for item in value)
    ):
        raise ProjectionUnavailableError(f"{label} is malformed")
    return sorted(value)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProjectionUnavailableError(f"{label} is malformed")
    return value


def _sequence(value: object, label: str, *, maximum: int) -> Sequence[object]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ProjectionUnavailableError(f"{label} is malformed")
    return value


def _count(value: Mapping[str, object], key: str, label: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ProjectionUnavailableError(f"{label} {key} is malformed")
    return item


def _text(value: object, label: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ProjectionUnavailableError(f"{label} is malformed")
    return value


__all__ = ["project_analyzer_coverage", "unavailable_analyzer_coverage"]
