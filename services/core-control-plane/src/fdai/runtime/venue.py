"""Core control plane's view of the shared venue contract.

The contract itself lives in ``fdai_service_contracts.venue`` because every FDAI service
resolves ``FDAI_EXECUTION_VENUE``, and an independent service cannot import ``fdai.*``. This
module re-exports it so core bindings keep one stable import path and the venue gate has
exactly one exempt module per source tree.
"""

from __future__ import annotations

from fdai_service_contracts.venue import (
    EXECUTION_VENUE_ENV,
    VENUE_CAPABILITIES,
    BusSecurityProtocol,
    ExecutionVenue,
    ExecutionVenueError,
    VenueCapability,
    bus_security_protocol,
    resolve_execution_venue,
    select_capability,
    uses_developer_identity,
    uses_local_document_providers,
    uses_managed_identity,
    uses_workload_identity,
)

__all__ = [
    "EXECUTION_VENUE_ENV",
    "VENUE_CAPABILITIES",
    "BusSecurityProtocol",
    "ExecutionVenue",
    "ExecutionVenueError",
    "VenueCapability",
    "bus_security_protocol",
    "resolve_execution_venue",
    "select_capability",
    "uses_developer_identity",
    "uses_local_document_providers",
    "uses_managed_identity",
    "uses_workload_identity",
]
