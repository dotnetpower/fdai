"""Reviewed Azure running/stopped semantics over full inventory observations."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_service_contracts.recorded_resource_state import operational_state_paths

from fdai.core.ontology_platform.resource_availability_evidence import ResourceOperationalState
from fdai.core.readiness.resource_availability_settings import (
    RESOURCE_AVAILABILITY_RESOURCE_TYPES,
)
from fdai.shared.providers.inventory import ResourceRecord

AZURE_AVAILABILITY_RESOURCE_TYPES = RESOURCE_AVAILABILITY_RESOURCE_TYPES


def azure_resource_operational_state(record: ResourceRecord) -> ResourceOperationalState:
    """Use only reviewed per-type paths, not provisioning success or Resource Health.

    ARG's lifted ``status`` is usable only when the reviewed source property
    agrees or is absent. Conflicting state paths remain unknown.
    VMSS parent state is intentionally unsupported: provisioning success does
    not establish that its instances are running.
    """

    if record.type not in AZURE_AVAILABILITY_RESOURCE_TYPES:
        return ResourceOperationalState.UNKNOWN
    states: set[ResourceOperationalState] = set()
    nested = record.props.get("properties")
    provider_props = nested if isinstance(nested, Mapping) else {}
    for path in operational_state_paths(record.type):
        for owner in (record.props, provider_props):
            value: object = owner
            for key in path.split("."):
                value = value.get(key) if isinstance(value, Mapping) else None
            state = _state(value, record.type)
            if state is not None:
                states.add(state)
    # These are service operational states projected by ARG, not provisioningState.
    lifted = _state(record.props.get("status"), record.type)
    if lifted is not None:
        states.add(lifted)
    return next(iter(states)) if len(states) == 1 else ResourceOperationalState.UNKNOWN


def _state(value: object, resource_type: str) -> ResourceOperationalState | None:
    if isinstance(value, Mapping):
        value = value.get("code")
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold().removeprefix("powerstate/")
    if normalized == "running" or (normalized == "ready" and resource_type == "mysql-server"):
        return ResourceOperationalState.RUNNING
    if normalized in {"stopped", "deallocated"}:
        return ResourceOperationalState.STOPPED
    return ResourceOperationalState.UNKNOWN
