from __future__ import annotations

import math

import pytest
from fdai.delivery.azure.wara_observation import (
    _scope_coverage_query,
    _validate_scope_coverage,
)
from fdai.rule_catalog.schema.wara_evaluator_binding import WaraObservationRequirement
from fdai.shared.providers.wara_assessment import WaraObservationError
from pydantic import ValidationError

RESOURCE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/"
    "resourceGroups/rg-example/providers/Microsoft.ContainerService/managedClusters/example"
)


def _validate(requirement: WaraObservationRequirement, value: object) -> list[str]:
    return _validate_scope_coverage(
        ({"id": RESOURCE_ID, "_fdai_requirement_0": value},),
        resource_ids=(RESOURCE_ID,),
        requirements=(requirement,),
    )


@pytest.mark.parametrize("value", (None, "", "false", 0, 1, [], {}))
def test_missing_or_untyped_boolean_is_not_satisfaction(value: object) -> None:
    requirement = WaraObservationRequirement(path="properties.enabled", value_type="boolean")
    with pytest.raises(WaraObservationError, match="required field"):
        _validate(requirement, value)


def test_absent_required_projection_cannot_be_an_empty_success() -> None:
    requirement = WaraObservationRequirement(path="properties.enabled", value_type="boolean")
    with pytest.raises(WaraObservationError, match="column is absent"):
        _validate_scope_coverage(
            ({"id": RESOURCE_ID},), resource_ids=(RESOURCE_ID,), requirements=(requirement,)
        )


@pytest.mark.parametrize("value", ("", None, "unsupported-region", "EastUS"))
def test_regions_outside_reviewed_eligibility_are_unknown(value: object) -> None:
    requirement = WaraObservationRequirement(
        path="location", value_type="string", allowed_values=("eastus",)
    )
    with pytest.raises(WaraObservationError, match="eligible resource set"):
        _validate(requirement, value)


@pytest.mark.parametrize("value", ([], None, [{}], [{"enabled": True}, {}]))
def test_every_array_element_requires_a_real_observation(value: object) -> None:
    requirement = WaraObservationRequirement(
        path="properties.agentPoolProfiles.*.enabled", value_type="boolean"
    )
    with pytest.raises(WaraObservationError, match="required field"):
        _validate(requirement, value)


def test_expanded_arrays_are_checked_beyond_the_first_element() -> None:
    requirement = WaraObservationRequirement(
        path="properties.agentPoolProfiles.*.enabled", value_type="boolean"
    )
    assert _validate(requirement, [{"enabled": True}, {"enabled": False}])
    query = _scope_coverage_query((RESOURCE_ID,), requirements=(requirement,))
    assert "_fdai_requirement_0=properties.agentPoolProfiles" in query
    assert " in~ (" in query
    assert "take 2" in query


def test_excluded_aks_vmss_and_wrong_sku_do_not_satisfy() -> None:
    tags = WaraObservationRequirement(
        path="tags", value_type="object", forbidden_keys=("aks-managed-poolName",)
    )
    assert _validate(tags, {})
    with pytest.raises(WaraObservationError, match="eligible"):
        _validate(tags, {"aks-managed-poolName": "example"})
    tier = WaraObservationRequirement(
        path="sku.tier", value_type="string", allowed_values=("Premium",)
    )
    with pytest.raises(WaraObservationError, match="eligible"):
        _validate(tier, "Free")


@pytest.mark.parametrize("value", (None, False, math.nan, math.inf, "2"))
def test_numeric_observation_cannot_be_null_boolean_nonfinite_or_text(value: object) -> None:
    requirement = WaraObservationRequirement(path="sku.capacity", value_type="number")
    with pytest.raises(WaraObservationError, match="required field"):
        _validate(requirement, value)


def test_explicit_null_failure_and_nested_identity_are_separate() -> None:
    requirement = WaraObservationRequirement(
        path="properties.storageProfile.osDisk.managedDisk",
        value_type="object",
        allow_null=True,
        required_keys=("id",),
    )
    assert _validate(requirement, None)
    assert _validate(requirement, {"id": RESOURCE_ID})
    for incomplete in ({}, {"id": None}, {"id": ""}):
        with pytest.raises(WaraObservationError, match="required field"):
            _validate(requirement, incomplete)


@pytest.mark.parametrize("value", (["1", "1"], ["1", "4"], [None, "2"], "1,2"))
def test_unknown_or_duplicated_zones_cannot_prove_redundancy(value: object) -> None:
    requirement = WaraObservationRequirement(
        path="zones",
        value_type="array",
        allowed_items=("1", "2", "3"),
        unique_items=True,
    )
    with pytest.raises(WaraObservationError, match="required field"):
        _validate(requirement, value)
    assert _validate(requirement, ["1", "2"])


def test_more_than_two_direct_links_cannot_be_silently_ignored() -> None:
    requirement = WaraObservationRequirement(
        path="properties.links",
        value_type="array",
        minimum_items=2,
        maximum_items=2,
    )
    with pytest.raises(WaraObservationError, match="required field"):
        _validate(requirement, [{}, {}, {}])


def test_guard_query_paths_cannot_inject_kql() -> None:
    with pytest.raises(ValidationError):
        WaraObservationRequirement(path="properties.x | union resources", value_type="string")
    requirement = WaraObservationRequirement(
        path="properties.links.1.properties.adminState", value_type="string"
    )
    assert "properties.links[1].properties.adminState" in _scope_coverage_query(
        (RESOURCE_ID,), requirements=(requirement,)
    )


def test_single_write_eligibility_and_nonempty_strings_are_enforced() -> None:
    requirement = WaraObservationRequirement(
        path="properties.enableMultipleWriteLocations",
        value_type="boolean",
        expected_boolean=False,
    )
    assert _validate(requirement, False)
    with pytest.raises(WaraObservationError, match="eligible"):
        _validate(requirement, True)
    nonempty = WaraObservationRequirement(
        path="properties.locations.*.locationName", value_type="string", minimum_length=1
    )
    with pytest.raises(WaraObservationError, match="required field"):
        _validate(nonempty, [{"locationName": ""}])
