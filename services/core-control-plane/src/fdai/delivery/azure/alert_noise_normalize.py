"""Mechanical decoders for pinned Azure wire shapes; unknown semantics never become facts.

The 2021-08-08 AlertProcessingRules swagger uses conditions as an array and
ISO timestamps WITHOUT a suffix, interpreted in the separate schedule timeZone.
Only finite UTC schedules and exact AlertRuleId filters are represented here.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.alert_noise import AlertRule, AudienceKind, Evaluation, ProcessingRule

_GUID = r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}"
_SCOPE = re.compile(
    rf"/subscriptions/{_GUID}(?:/resourceGroups/[A-Za-z0-9_.()-]{{1,90}})?"
    r"(?:/providers/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.()-]+/[A-Za-z0-9_.()-]+)+)?",
    re.IGNORECASE,
)
NOTIFICATION_FIELDS = {
    "emailReceivers": ("name", "emailAddress"),
    "smsReceivers": ("name", "countryCode", "phoneNumber"),
    "voiceReceivers": ("name", "countryCode", "phoneNumber"),
    "azureAppPushReceivers": ("name", "emailAddress"),
    "armRoleReceivers": ("name", "roleId"),
}


def canonical_json(value: object) -> str:
    """Encode private native content deterministically, rejecting non-JSON/non-finite data."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("provider JSON is malformed") from None


def text(value: object) -> str:
    """Require a bounded native string; never stringify a list, boolean or object."""
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 2048
        or value != value.strip()
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("provider text is malformed")
    return value


def object_value(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Require a native object without accepting a stringified configuration."""
    result = value.get(key)
    if not isinstance(result, Mapping):
        raise ValueError("provider object is malformed")
    return result


def list_value(value: object, *, maximum: int = 2000) -> list[Any]:
    """Require a bounded native array; tuples and JSON text are not native arrays."""
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("provider array is malformed or exceeds its bound")
    return value


def native_scope(value: object) -> str:
    """Normalize a narrow ARM scope without allowing URLs, encoded separators or dot paths."""
    result = text(value)
    if _SCOPE.fullmatch(result) is None or any(part in {".", ".."} for part in result.split("/")):
        raise ValueError("provider ARM scope is malformed or unsupported")
    return result.casefold()


def within_scope(resource: str, scope: str) -> bool:
    """Compare canonical ARM segments, not ambiguous resource-group name prefixes."""
    return resource == scope or resource.startswith(scope + "/")


def native_resource(raw: Mapping[str, Any], expected_type: str) -> str:
    """Verify both the native resource ID and type against its pinned collection."""
    resource = native_scope(raw.get("id"))
    parts = resource.split("/")
    if (
        len(parts) != 9
        or parts[3] != "resourcegroups"
        or parts[5] != "providers"
        or "/".join(parts[6:8]) != expected_type.casefold()
        or text(raw.get("type")).casefold() != expected_type.casefold()
    ):
        raise ValueError("provider resource identity/type mismatch")
    if "name" in raw and text(raw["name"]).casefold() != parts[-1]:
        raise ValueError("provider resource name mismatch")
    return resource


def group_id(value: object) -> str:
    """Require a real ARM action-group identifier, not an arbitrary named destination."""
    resource = native_scope(value)
    parts = resource.split("/")
    if len(parts) != 9 or parts[5:8] != ["providers", "microsoft.insights", "actiongroups"]:
        raise ValueError("provider action-group identifier is malformed")
    return resource


def rule_groups(properties: Mapping[str, Any], kind: str) -> tuple[str, ...]:
    """Decode the distinct metric, scheduled-query and activity-log action shapes."""
    if kind == "activity" and "actions" not in properties:
        raise ValueError("activity alert actions are missing")
    actions = properties.get("actions", [] if kind == "metric" else {})
    if kind == "metric":
        rows = list_value(actions, maximum=5)
    else:
        if not isinstance(actions, Mapping):
            raise ValueError("provider rule actions are malformed")
        rows = list_value(actions.get("actionGroups", []), maximum=5)
    result: list[str] = []
    for row in rows:
        if kind == "log":
            result.append(group_id(row))
        elif isinstance(row, Mapping):
            result.append(group_id(row.get("actionGroupId")))
        else:
            raise ValueError("provider rule action is malformed")
    if len(set(result)) != len(result):
        raise ValueError("provider rule action is duplicated")
    return tuple(sorted(result))


def notification_kind(key: str, receiver: Mapping[str, Any]) -> AudienceKind:
    """Validate native recipient syntax only; role identity never proves membership/authority.

    An injected resolver must verify supported built-in roles, subscription-level assignment,
    tenant/purpose, propagation and reachability separately. No directory permission is requested.
    """
    required = NOTIFICATION_FIELDS[key]
    allowed = set(required) | {"useCommonAlertSchema", "status"}
    if set(receiver) - allowed:
        raise ValueError("provider notification receiver has unsupported fields")
    for name in required:
        text(receiver.get(name))
    if "useCommonAlertSchema" in receiver and type(receiver["useCommonAlertSchema"]) is not bool:
        raise ValueError("provider common-schema flag is malformed")
    if "status" in receiver:
        text(receiver["status"])
    if key == "armRoleReceivers":
        if re.fullmatch(_GUID, text(receiver["roleId"])) is None or "status" in receiver:
            raise ValueError("provider ARM role receiver is malformed")
        return "role"
    return "direct"


def metric_evaluation(
    properties: Mapping[str, Any],
    opaque: Callable[[str, str], str],
) -> Evaluation | None:
    """Decode one static criterion on one actual resource; unsupported semantics stay absent."""
    try:
        scopes = [native_scope(value) for value in list_value(properties.get("scopes"))]
        if len(scopes) != 1 or "/providers/" not in scopes[0]:
            return None
        criteria = object_value(properties, "criteria")
        if criteria.get("odata.type") not in (
            "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria",
            "Microsoft.Azure.Monitor.MultipleResourceMultipleMetricCriteria",
        ) or set(criteria) != {"odata.type", "allOf"}:
            return None
        rows = list_value(criteria.get("allOf"))
        if len(rows) != 1 or not isinstance(rows[0], Mapping):
            return None
        criterion = rows[0]
        known = {
            "criterionType",
            "name",
            "metricName",
            "metricNamespace",
            "operator",
            "timeAggregation",
            "threshold",
            "dimensions",
            "skipMetricValidation",
        }
        if (
            set(criterion) - known
            or criterion.get("criterionType") != "StaticThresholdCriterion"
            or list_value(criterion.get("dimensions", []))
        ):
            return None
        if (
            "skipMetricValidation" in criterion
            and type(criterion["skipMetricValidation"]) is not bool
        ):
            return None
        text(criterion.get("name"))
        metric = text(criterion.get("metricName"))
        namespace = text(criterion["metricNamespace"]) if "metricNamespace" in criterion else None
        operator = {"GreaterThan": "above", "LessThan": "below"}.get(
            text(criterion.get("operator")),
        )
        aggregation = {"Average": "average", "Maximum": "maximum", "Minimum": "minimum"}.get(
            text(criterion.get("timeAggregation")),
        )
        threshold = criterion.get("threshold")
        if (
            not operator
            or not aggregation
            or not isinstance(threshold, (int, float))
            or isinstance(threshold, bool)
            or not math.isfinite(threshold)
        ):
            return None
        if type(threshold) is int and float(threshold) != threshold:
            return None
        window = duration_seconds(properties.get("windowSize"))
        frequency = duration_seconds(properties.get("evaluationFrequency"))
        if frequency > window:
            return None
        return Evaluation.model_validate(
            {
                "metric_ref": opaque("metric", canonical_json([namespace, metric])),
                "operator": operator,
                "aggregation": aggregation,
                "threshold": float(threshold),
                "window_seconds": window,
                "frequency_seconds": frequency,
            }
        )
    except (ValueError, OverflowError):
        return None


def duration_seconds(raw: object) -> int:
    """Decode the closed Azure metric evaluation duration set."""
    values = {
        "PT1M": 60,
        "PT5M": 300,
        "PT15M": 900,
        "PT30M": 1800,
        "PT1H": 3600,
        "PT6H": 21600,
        "PT12H": 43200,
        "P1D": 86400,
    }
    if not isinstance(raw, str) or raw not in values:
        raise ValueError("unsupported metric duration")
    return values[raw]


def alert_rule(
    raw: Mapping[str, Any],
    *,
    native: str,
    kind: str,
    bindings: tuple[str, ...],
    opaque: Callable[[str, str], str],
    revision: str,
    authorized_scope: str,
    reasons: set[str],
) -> tuple[AlertRule, tuple[str, ...]]:
    """Project native configuration only; missing authority and incident state remain holds."""
    properties = object_value(raw, "properties")
    scope_values = list_value(properties.get("scopes"))
    # ActivityLogAlerts 2020-10-01 examples also return subscription prefixes without '/'.
    scopes = tuple(
        native_scope(
            "/" + value
            if kind == "activity"
            and isinstance(value, str)
            and value.casefold().startswith("subscriptions/")
            else value,
        )
        for value in scope_values
    )
    if not scopes or (kind == "log" and text(raw.get("kind", "LogAlert")) != "LogAlert"):
        raise ValueError("rule scope/kind is unsupported")
    object_value(properties, "condition" if kind == "activity" else "criteria")
    exact = scopes if kind == "metric" and len(scopes) == 1 and "/providers/" in scopes[0] else ()
    if not exact or not all(within_scope(value, authorized_scope) for value in scopes):
        reasons.add("rule_targets_unrepresented_or_outside_scope")
    evaluation = metric_evaluation(properties, opaque) if kind == "metric" else None
    if kind != "activity" and evaluation is None:
        reasons.add("evaluation_semantics_unavailable")
    rule = AlertRule.model_validate(
        {
            "ref": opaque("rule", native),
            "resource_ref": opaque("resource", exact[0]) if exact else "resource:unknown",
            "service_ref": "service:unknown",
            "revision": revision,
            "kind": kind,
            "severity": properties.get("severity") if kind != "activity" else None,
            "classification": "unknown",
            "group_refs": tuple(opaque("group", value) for value in bindings),
            "enabled": properties.get("enabled", True if kind == "activity" else None),
            "stateful": properties.get("autoMitigate", True) if kind != "activity" else False,
            "ownership_verified": False,
            "iac_owned": False,
            "active_incident": True,  # Conservative hold; incident state was not observed.
            "evaluation": evaluation,
        }
    )
    return rule, exact


def processing_rule(
    raw: Mapping[str, Any],
    *,
    native_rules: Mapping[str, str],
    opaque: Callable[[str, str], str],
    revision: str,
    now: datetime,
    native_targets: Mapping[str, tuple[str, ...]] | None = None,
    native_groups: Mapping[str, str] | None = None,
    authorized_scope: str | None = None,
) -> ProcessingRule | None:
    """Project observed finite UTC actions only; never fabricate an action or time interval.

    Unknown representable filters carry semantics_complete=False. Missing/unsupported actions
    or schedules return None and must produce a partial reason at the collecting boundary.
    """
    del now
    native = native_resource(raw, "Microsoft.AlertsManagement/actionRules")
    properties = object_value(raw, "properties")
    enabled = properties.get("enabled", True)  # Documented native default, not an authority flag.
    if type(enabled) is not bool:
        raise ValueError("processing enabled flag is malformed")
    scopes = tuple(native_scope(value) for value in list_value(properties.get("scopes")))
    if not scopes or len(set(scopes)) != len(scopes):
        raise ValueError("processing scopes are missing or duplicated")
    actions = list_value(properties.get("actions"), maximum=5)
    if any(not isinstance(value, Mapping) for value in actions):
        raise ValueError("processing action is malformed")
    if len(actions) != 1:
        return None
    action_row = actions[0]
    action_type = text(action_row.get("actionType"))
    groups: tuple[str, ...] = ()
    complete = True
    if action_type == "RemoveAllActionGroups":
        if set(action_row) != {"actionType"}:
            return None  # Suppression cannot mean removing selected groups.
        action = "suppress"
    elif action_type == "AddActionGroups":
        ids = tuple(
            group_id(value)
            for value in list_value(
                action_row.get("actionGroupIds"),
                maximum=5,
            )
        )
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("processing additions are missing or duplicated")
        known_groups = native_groups or {}
        groups = tuple(sorted(known_groups[value] for value in ids if value in known_groups))
        complete = len(groups) == len(ids) and set(action_row) == {"actionType", "actionGroupIds"}
        action = "add"
    else:
        return None
    schedule = properties.get("schedule")
    if schedule is None:
        return None
    if not isinstance(schedule, Mapping):
        raise ValueError("processing schedule is malformed")
    if text(schedule.get("timeZone")) != "UTC":
        return None
    if "effectiveFrom" not in schedule or "effectiveUntil" not in schedule:
        return None
    starts, ends = _utc_time(schedule["effectiveFrom"]), _utc_time(schedule["effectiveUntil"])
    if starts >= ends:
        raise ValueError("processing interval MUST be positive")
    recurrences = list_value(schedule.get("recurrences", []))
    for recurrence in recurrences:
        if not isinstance(recurrence, Mapping):
            raise ValueError("processing recurrence is malformed")
        text(recurrence.get("recurrenceType"))
    complete = (
        complete
        and not recurrences
        and not set(schedule)
        - {
            "effectiveFrom",
            "effectiveUntil",
            "timeZone",
            "recurrences",
        }
    )
    conditions = list_value(properties.get("conditions", []))
    selected_ids: tuple[str, ...] = ()
    for condition in conditions:
        if not isinstance(condition, Mapping):
            raise ValueError("processing condition is malformed")
        text(condition.get("field"))
        text(condition.get("operator"))
        for value in list_value(condition.get("values"), maximum=5):
            text(value)
    if (
        len(conditions) == 1
        and conditions[0].get("field") == "AlertRuleId"
        and conditions[0].get("operator") == "Equals"
        and set(conditions[0]) == {"field", "operator", "values"}
    ):
        selected_ids = tuple(native_scope(value) for value in conditions[0]["values"])
    complete = complete and bool(selected_ids) and len(set(selected_ids)) == len(selected_ids)
    targets = native_targets or {}
    if authorized_scope is None:
        complete = False
    else:
        bound_scope = native_scope(authorized_scope)
        complete = complete and all(
            within_scope(scope, bound_scope) and scope.split("/")[2] == native.split("/")[2]
            for scope in scopes
        )
    selected: list[str] = []
    for rule_id in selected_ids:
        observed_targets = targets.get(rule_id, ())
        if (
            rule_id not in native_rules
            or not observed_targets
            or not all(
                any(within_scope(target, scope) for scope in scopes) for target in observed_targets
            )
        ):
            complete = False
        else:
            selected.append(native_rules[rule_id])
    complete = complete and not set(properties) - {
        "scopes",
        "conditions",
        "schedule",
        "actions",
        "description",
        "enabled",
    }
    return ProcessingRule.model_validate(
        {
            "ref": opaque("processing", native),
            "revision": revision,
            "rule_refs": tuple(sorted(set(selected))),
            "action": action,
            "group_refs": groups,
            "enabled": enabled,
            "effective_from": starts,
            "effective_to": ends,
            "semantics_complete": complete,
        }
    )


def _utc_time(value: object) -> datetime:
    raw = text(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", raw) is None:
        raise ValueError("processing time MUST use the native suffix-free ISO format")
    return datetime.fromisoformat(raw).replace(tzinfo=UTC)
