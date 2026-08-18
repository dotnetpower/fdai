"""Venue selection is one contract, not a comparison repeated at every binding site.

FDAI-CONST-001 allows a venue to differ only in credentials, endpoints, scale, and provider
scope. The risk this file removes is an unrecorded venue-sensitive binding: before the
contract existed, every service read the environment variable and applied its own default,
so nothing could fail when one more appeared.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai_service_contracts.venue import (
    EXECUTION_VENUE_ENV,
    VENUE_CAPABILITIES,
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

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Every source tree that composes an FDAI process. A capability must be read in at least
#: one of them, otherwise the table documents intent instead of selecting behavior.
PRODUCTION_TREES = (
    "packages/service-contracts/src/fdai_service_contracts",
    "services/core-control-plane/src/fdai",
    "services/operator-service/src/fdai_operator_service",
    "services/document-ingestion-api/src/fdai_ingestion_api_service",
    "services/document-processing-worker/src/fdai_document_worker_service",
    "services/isolated-executor/src/fdai_executor_service",
)

#: The accessor each capability is read through. The test below fails when a capability has
#: no entry here, so a new capability cannot be added without naming its reader.
ACCESSOR_NAMES = {
    VenueCapability.BUS_SECURITY_PROTOCOL: "bus_security_protocol",
    VenueCapability.BUS_IDENTITY_BINDING: "uses_workload_identity",
    VenueCapability.WORKLOAD_IDENTITY_SOURCE: "uses_developer_identity",
    VenueCapability.DOCUMENT_PROVIDER_BINDING: "uses_local_document_providers",
}


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
    assert uses_developer_identity(ExecutionVenue.LOCAL) is True
    assert uses_developer_identity(ExecutionVenue.DEPLOYED) is False
    assert uses_managed_identity(ExecutionVenue.DEPLOYED) is True
    assert uses_managed_identity(ExecutionVenue.LOCAL) is False
    assert uses_local_document_providers(ExecutionVenue.LOCAL) is True
    assert uses_local_document_providers(ExecutionVenue.DEPLOYED) is False
    assert (
        select_capability(VenueCapability.WORKLOAD_IDENTITY_SOURCE, ExecutionVenue.LOCAL)
        == "azure_cli"
    )
    assert (
        select_capability(VenueCapability.WORKLOAD_IDENTITY_SOURCE, ExecutionVenue.DEPLOYED)
        == "managed_identity"
    )
    assert (
        select_capability(VenueCapability.DOCUMENT_PROVIDER_BINDING, ExecutionVenue.DEPLOYED)
        == "azure_managed"
    )


def test_every_declared_capability_has_a_production_consumer() -> None:
    """A capability nothing reads makes this table documentation, not a contract."""

    contract = Path(__file__).resolve().parents[1] / "src/fdai_service_contracts/venue.py"
    re_export = REPO_ROOT / "services/core-control-plane/src/fdai/runtime/venue.py"
    sources: list[str] = []
    for tree in PRODUCTION_TREES:
        root = REPO_ROOT / tree
        assert root.is_dir(), tree
        modules = [
            path
            for path in sorted(root.rglob("*.py"))
            if path not in {contract, re_export} and "__pycache__" not in path.parts
        ]
        assert modules, tree
        sources.extend(path.read_text(encoding="utf-8") for path in modules)
    body = "\n".join(sources)

    assert set(ACCESSOR_NAMES) == set(VenueCapability)
    for capability, accessor in ACCESSOR_NAMES.items():
        assert accessor in body, f"{capability.value} has no production consumer"


def test_the_capability_table_is_immutable() -> None:
    with pytest.raises(TypeError):
        VENUE_CAPABILITIES[VenueCapability.BUS_SECURITY_PROTOCOL] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        VENUE_CAPABILITIES[VenueCapability.BUS_SECURITY_PROTOCOL][  # type: ignore[index]
            ExecutionVenue.LOCAL
        ] = "SASL_SSL"
