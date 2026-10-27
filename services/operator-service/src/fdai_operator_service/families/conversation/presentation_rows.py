"""Project verified query rows into bounded operator-readable scalar fields."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

_LIFTED_ROW_FIELDS = (
    "name",
    "revision_name",
    "ready_revision_name",
    "running_status",
    "source_observed_at",
    "inventory_read_at",
    "provisioning_status",
    "provisioning_state",
    "model_name",
    "model_version",
    "model_format",
    "sku_name",
    "capacity_units",
    "current_capacity_units",
    "capacity_transitioning",
    "capacity_tpm",
    "capacity_tpm_source",
    "type",
    "status",
    "location",
)
_GROUP_FIELD = "group"
_AGGREGATE_MEASURE_FIELDS = frozenset({"operation", "value"})
_TECHNICAL_IDENTITY_FIELDS = frozenset({"id", "object_type"})
_INTERNAL_ROW_FIELDS = frozenset(
    {
        "catalog_digest",
        "declaration_digest",
        "execution_authority",
        "revision",
        "type_version",
    }
)
_MAX_NESTED_DEPTH = 2
_SENSITIVE_FIELDS = frozenset(
    {
        "access_token",
        "authorization",
        "client_secret",
        "credential",
        "password",
        "resource_id",
        "subscription_id",
        "tenant_id",
        "token",
    }
)
_SENSITIVE_VALUE_MARKERS = ("http://", "https://", "bearer ", "/subscriptions/")
_REDACTED_VALUE = "<redacted>"


def readable_row(values: Mapping[str, object]) -> dict[str, object]:
    """Keep direct scalars and lift allowlisted leaves from bounded nested bags."""
    readable: dict[str, object] = {}
    # An aggregate row names its group in a mapping, so its scalar fields lead the row.
    group = values.get(_GROUP_FIELD)
    if isinstance(group, Mapping):
        for field, value in group.items():
            if isinstance(field, str) and field and not isinstance(value, Mapping | list):
                readable[field] = _redact_scalar(field, value)
    for field, value in values.items():
        if not isinstance(field, str) or not field or isinstance(value, Mapping | list):
            continue
        readable[field] = _redact_scalar(field, value)
    for bag in _nested_mappings(values, depth=_MAX_NESTED_DEPTH):
        for field in _LIFTED_ROW_FIELDS:
            candidate = bag.get(field)
            if candidate is None or isinstance(candidate, Mapping | list):
                continue
            readable.setdefault(field, _redact_scalar(field, candidate))
    return readable


def _redact_scalar(field: str, value: object) -> object:
    if not isinstance(value, str):
        return value
    folded_field = field.casefold()
    folded_value = value.casefold()
    if (
        folded_field in _SENSITIVE_FIELDS
        or folded_field.endswith(("_token", "_secret", "_credential"))
        or any(marker in folded_value for marker in _SENSITIVE_VALUE_MARKERS)
    ):
        return _REDACTED_VALUE
    return value


def ordered_columns(fields: Sequence[str]) -> list[str]:
    """Lead with readable fields and omit opaque identity when richer facts exist."""
    readable = [field for field in fields if field not in _INTERNAL_ROW_FIELDS]
    selected = readable or list(fields)
    business_fields = [field for field in selected if field not in _TECHNICAL_IDENTITY_FIELDS]
    if business_fields:
        selected = business_fields
    leading = [field for field in _LIFTED_ROW_FIELDS if field in selected]
    ordered = leading + [field for field in selected if field not in leading]
    # An aggregate row reads its measure after the group it measures.
    if _AGGREGATE_MEASURE_FIELDS <= set(ordered) and len(ordered) > len(_AGGREGATE_MEASURE_FIELDS):
        return [field for field in ordered if field not in _AGGREGATE_MEASURE_FIELDS] + [
            "operation",
            "value",
        ]
    return ordered


def _nested_mappings(
    values: Mapping[str, object],
    *,
    depth: int,
) -> Iterator[Mapping[str, object]]:
    if depth <= 0:
        return
    for value in values.values():
        if not isinstance(value, Mapping):
            continue
        yield value
        yield from _nested_mappings(value, depth=depth - 1)


__all__ = ["ordered_columns", "readable_row"]
