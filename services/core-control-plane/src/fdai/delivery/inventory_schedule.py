"""Bounded provider projection for recurring VM shutdown schedules."""

from __future__ import annotations

import re
from collections.abc import Mapping
from hashlib import sha256
from typing import Any, Final
from uuid import UUID

from fdai.delivery.azure.windows_timezones import windows_time_zone_to_iana

VM_SHUTDOWN_SCHEDULE_TYPE: Final[str] = "compute.vm-shutdown-schedule"
VM_SHUTDOWN_TASK_TYPE: Final[str] = "ComputeVmShutdownTask"
_TIME = re.compile(r"^(?:[01][0-9]|2[0-3])[0-5][0-9]$")
_TARGET = re.compile(
    r"^/subscriptions/(?P<subscription>[0-9a-f-]{36})/resourceGroups/"
    r"(?P<group>[A-Za-z0-9._()\-]{1,90})/providers/"
    r"Microsoft\.Compute/virtualMachines/(?P<name>[A-Za-z0-9._\-]{1,64})$",
    re.IGNORECASE,
)


def project_vm_shutdown_schedule(props: Mapping[str, Any]) -> dict[str, str] | None:
    """Return safe schedule fields without exposing the target ARM resource ID."""

    provider_type = props.get("providerType")
    nested_value = props.get("properties")
    nested = nested_value if isinstance(nested_value, Mapping) else {}
    task_type = nested.get("taskType")
    if (
        not isinstance(provider_type, str)
        or provider_type.casefold() != "microsoft.devtestlab/schedules"
        or task_type != VM_SHUTDOWN_TASK_TYPE
    ):
        return None
    status = nested.get("status")
    recurrence_value = nested.get("dailyRecurrence")
    recurrence = recurrence_value if isinstance(recurrence_value, Mapping) else {}
    shutdown_time = recurrence.get("time")
    time_zone = nested.get("timeZoneId")
    target = nested.get("targetResourceId")
    subscription_id = props.get("subscriptionId")
    if (
        not isinstance(status, str)
        or status not in {"Enabled", "Disabled"}
        or not isinstance(shutdown_time, str)
        or _TIME.fullmatch(shutdown_time) is None
        or not isinstance(time_zone, str)
        or not 1 <= len(time_zone) <= 128
        or not isinstance(target, str)
        or (target_match := _TARGET.fullmatch(target)) is None
        or not isinstance(subscription_id, str)
    ):
        raise ValueError("VM shutdown schedule properties are invalid")
    try:
        target_subscription = str(UUID(target_match.group("subscription")))
        source_subscription = str(UUID(subscription_id))
    except ValueError as exc:
        raise ValueError("VM shutdown schedule properties are invalid") from exc
    if target_subscription != source_subscription:
        raise ValueError("VM shutdown schedule properties are invalid")
    return {
        "scheduledShutdownStatus": status,
        "scheduledShutdownTime": shutdown_time,
        "scheduledShutdownTimeZone": time_zone,
        "scheduledShutdownTimeZoneIana": windows_time_zone_to_iana(time_zone),
        "scheduledShutdownTargetName": target_match.group("name"),
        "scheduledShutdownTargetResourceGroup": target_match.group("group"),
        "scheduledShutdownTargetSubscriptionDigest": (
            "sha256:" + sha256(source_subscription.encode("ascii")).hexdigest()
        ),
    }


__all__ = [
    "VM_SHUTDOWN_SCHEDULE_TYPE",
    "VM_SHUTDOWN_TASK_TYPE",
    "project_vm_shutdown_schedule",
]
