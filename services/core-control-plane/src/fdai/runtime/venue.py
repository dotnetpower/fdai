"""One contract for every venue-selected capability flag.

FDAI-CONST-001: *"Execution venue does not change control-plane behavior. Every venue binds
the same authoritative sources, ingress path, contracts, control-loop stages, and surfaces;
only credentials, endpoints, scale, and provider scope may differ."*

Venue used to be a bare environment string compared inline at every binding site, each with
its own default and its own error message. That shape makes venue parity unprovable: a new
venue-sensitive capability can be introduced anywhere and nothing fails. This module is the
single place that resolves the venue and the single table that enumerates what a venue may
select.

A capability listed here may differ only in credentials, endpoints, transport security, or
provider scope. Anything that would change a control-loop stage, contract, or authority
does not belong in this table.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from os import environ
from types import MappingProxyType

#: Environment variable that selects the venue for one process.
EXECUTION_VENUE_ENV = "FDAI_EXECUTION_VENUE"


class ExecutionVenue(StrEnum):
    """Where one control-plane process runs."""

    LOCAL = "local"
    DEPLOYED = "deployed"


class VenueCapability(StrEnum):
    """A capability whose binding may differ by venue.

    Every member has a production consumer. A capability with no consumer would make this
    table documentation rather than a contract, so a new member is added when a binding
    starts reading it, not in anticipation.
    """

    BUS_SECURITY_PROTOCOL = "bus_security_protocol"
    BUS_IDENTITY_BINDING = "bus_identity_binding"
    WORKLOAD_IDENTITY_SOURCE = "workload_identity_source"


#: The complete set of venue-selected values. Every capability declares a value for every
#: venue, so an unmapped combination is a contract error rather than a silent default.
VENUE_CAPABILITIES: Mapping[VenueCapability, Mapping[ExecutionVenue, str]] = MappingProxyType(
    {
        VenueCapability.BUS_SECURITY_PROTOCOL: MappingProxyType(
            {
                ExecutionVenue.LOCAL: "PLAINTEXT",
                ExecutionVenue.DEPLOYED: "SASL_SSL",
            }
        ),
        VenueCapability.BUS_IDENTITY_BINDING: MappingProxyType(
            {
                ExecutionVenue.LOCAL: "none",
                ExecutionVenue.DEPLOYED: "workload_identity",
            }
        ),
        VenueCapability.WORKLOAD_IDENTITY_SOURCE: MappingProxyType(
            {
                ExecutionVenue.LOCAL: "azure_cli",
                ExecutionVenue.DEPLOYED: "managed_identity",
            }
        ),
    }
)


class ExecutionVenueError(RuntimeError, ValueError):
    """Raised when the configured venue is absent or not a declared value.

    It inherits both bases because the call sites this contract replaced raised
    ``RuntimeError`` in one place and ``ValueError`` in another; a caller that caught either
    keeps working.
    """


def resolve_execution_venue(env: Mapping[str, str] | None = None) -> ExecutionVenue:
    """Return the venue for this process, defaulting to ``deployed``.

    An unset or empty variable resolves to ``deployed`` because a deployed process is the
    stricter binding; any other unrecognized value is an error rather than a silent
    fallback to the weaker local transport.
    """

    source = environ if env is None else env
    raw = source.get(EXECUTION_VENUE_ENV, "").strip()
    if not raw:
        return ExecutionVenue.DEPLOYED
    try:
        return ExecutionVenue(raw)
    except ValueError as exc:
        allowed = ", ".join(sorted(venue.value for venue in ExecutionVenue))
        raise ExecutionVenueError(f"{EXECUTION_VENUE_ENV} MUST be one of: {allowed}") from exc


def select_capability(capability: VenueCapability, venue: ExecutionVenue) -> str:
    """Return the value one venue selects for one capability."""

    bindings = VENUE_CAPABILITIES.get(capability)
    if bindings is None:
        raise ExecutionVenueError(f"capability {capability.value!r} declares no venue bindings")
    value = bindings.get(venue)
    if value is None:
        raise ExecutionVenueError(
            f"capability {capability.value!r} declares no value for venue {venue.value!r}"
        )
    return value


def bus_security_protocol(venue: ExecutionVenue) -> str:
    """Return the Kafka security protocol this venue selects."""

    return select_capability(VenueCapability.BUS_SECURITY_PROTOCOL, venue)


def uses_workload_identity(venue: ExecutionVenue) -> bool:
    """Return whether this venue binds a workload identity to its message transport."""

    return select_capability(VenueCapability.BUS_IDENTITY_BINDING, venue) != "none"


def uses_developer_identity(venue: ExecutionVenue) -> bool:
    """Return whether this venue obtains its workload identity from the developer CLI."""

    return select_capability(VenueCapability.WORKLOAD_IDENTITY_SOURCE, venue) == "azure_cli"


__all__ = [
    "EXECUTION_VENUE_ENV",
    "VENUE_CAPABILITIES",
    "ExecutionVenue",
    "ExecutionVenueError",
    "VenueCapability",
    "bus_security_protocol",
    "resolve_execution_venue",
    "select_capability",
    "uses_developer_identity",
    "uses_workload_identity",
]
