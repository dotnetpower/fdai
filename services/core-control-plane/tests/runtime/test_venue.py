"""Venue selection is one contract, not a comparison repeated at every binding site.

FDAI-CONST-001 allows a venue to differ only in credentials, endpoints, scale, and provider
scope. The risk this file removes is an unrecorded venue-sensitive binding: before the
contract existed, seven call sites each read the environment variable and applied their own
default, so nothing could fail when an eighth appeared.
"""

from __future__ import annotations

import pytest
from fdai.runtime.venue import (
    EXECUTION_VENUE_ENV,
    VENUE_CAPABILITIES,
    ExecutionVenue,
    ExecutionVenueError,
    VenueCapability,
    bus_security_protocol,
    resolve_execution_venue,
    select_capability,
    uses_workload_identity,
)


def test_every_capability_is_defined_for_every_venue() -> None:
    assert set(VENUE_CAPABILITIES) == set(VenueCapability)
    for capability, bindings in VENUE_CAPABILITIES.items():
        assert set(bindings) == set(ExecutionVenue), capability
        assert all(value.strip() for value in bindings.values()), capability


def test_an_absent_venue_resolves_to_the_stricter_deployed_binding() -> None:
    assert resolve_execution_venue({}) is ExecutionVenue.DEPLOYED
    assert resolve_execution_venue({EXECUTION_VENUE_ENV: ""}) is ExecutionVenue.DEPLOYED
    assert resolve_execution_venue({EXECUTION_VENUE_ENV: "   "}) is ExecutionVenue.DEPLOYED


@pytest.mark.parametrize("venue", list(ExecutionVenue))
def test_a_declared_venue_round_trips(venue: ExecutionVenue) -> None:
    assert resolve_execution_venue({EXECUTION_VENUE_ENV: venue.value}) is venue
    assert resolve_execution_venue({EXECUTION_VENUE_ENV: f"  {venue.value}  "}) is venue


@pytest.mark.parametrize("raw", ["Local", "DEPLOYED", "staging", "local ,deployed", "0"])
def test_an_unknown_venue_value_is_rejected_rather_than_defaulted(raw: str) -> None:
    with pytest.raises(ExecutionVenueError, match="MUST be one of"):
        resolve_execution_venue({EXECUTION_VENUE_ENV: raw})


def test_capability_values_match_the_shipped_bindings() -> None:
    """Pin the exact values so a refactor cannot silently change a deployed binding."""

    assert bus_security_protocol(ExecutionVenue.LOCAL) == "PLAINTEXT"
    assert bus_security_protocol(ExecutionVenue.DEPLOYED) == "SASL_SSL"
    assert uses_workload_identity(ExecutionVenue.DEPLOYED) is True
    assert uses_workload_identity(ExecutionVenue.LOCAL) is False
    assert (
        select_capability(VenueCapability.INVENTORY_SOURCE, ExecutionVenue.LOCAL)
        == "declarative_file"
    )
    assert (
        select_capability(VenueCapability.INVENTORY_SOURCE, ExecutionVenue.DEPLOYED)
        == "azure_resource_graph"
    )


def test_the_capability_table_is_immutable() -> None:
    with pytest.raises(TypeError):
        VENUE_CAPABILITIES[VenueCapability.BUS_SECURITY_PROTOCOL] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        VENUE_CAPABILITIES[VenueCapability.BUS_SECURITY_PROTOCOL][  # type: ignore[index]
            ExecutionVenue.LOCAL
        ] = "SASL_SSL"
