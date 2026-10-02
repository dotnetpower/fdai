from __future__ import annotations

import json

import pytest

from fdai_deployment_cli.azure_naming import (
    azure_region_short_name,
    discover_existing_azure_region_short_name,
    reviewed_azure_region_short_names,
    selected_azure_region_short_name,
)
from fdai_deployment_cli.plan_input import write_plan_input

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        ("koreacentral", "krc"),
        ("westus", "wus"),
        ("westus2", "wus2"),
        ("westus3", "wus3"),
        ("eastus2", "eus2"),
        ("swedencentral", "swc"),
    ],
)
def test_returns_stable_region_short_name(region: str, expected: str) -> None:
    assert azure_region_short_name(region) == expected


def test_every_reviewed_public_region_has_a_unique_token() -> None:
    tokens = reviewed_azure_region_short_names()

    assert len(set(tokens.values())) == len(tokens)
    assert tokens["westus"] != tokens["westus3"]
    assert tokens["southcentralus"] != tokens["southeastasia"]


@pytest.mark.parametrize("region", ["", "West US 2", "-westus2", "a"])
def test_rejects_invalid_region_name(region: str) -> None:
    with pytest.raises(ValueError, match="region name"):
        azure_region_short_name(region)


def test_unreviewed_region_fails_instead_of_truncating() -> None:
    with pytest.raises(ValueError, match="no reviewed"):
        azure_region_short_name("futurepublicregion")


def test_retained_foundation_token_wins_without_discovery(tmp_path) -> None:
    variables = tmp_path / "foundation-variables.json"
    write_plan_input(variables, {"region_short": "westu"})

    selected = selected_azure_region_short_name(
        region="westus3",
        subscription_id=SUBSCRIPTION,
        environment="dev",
        workload="fdai",
        retained_variables=variables,
        azure_group_reader=lambda _subscription: pytest.fail("retained token must not discover"),
    )

    assert selected == "westu"


def test_existing_installation_discovery_reuses_legacy_token() -> None:
    selected = selected_azure_region_short_name(
        region="westus3",
        subscription_id=SUBSCRIPTION,
        environment="dev",
        workload="fdai",
        azure_group_reader=lambda _subscription: json.dumps(
            [
                {
                    "name": "rg-fdai-dev-westu",
                    "location": "westus3",
                    "tags": {
                        "fdai:managed": "true",
                        "fdai:env": "dev",
                        "fdai:workload": "fdai",
                    },
                },
                {
                    "name": "rg-fdai-ops-westu",
                    "location": "westus3",
                    "tags": {
                        "fdai:managed": "true",
                        "fdai:env": "dev",
                        "fdai:workload": "fdai",
                    },
                },
            ]
        ),
    )

    assert selected == "westu"


def test_existing_installation_discovery_prefers_explicit_future_tag() -> None:
    assert (
        discover_existing_azure_region_short_name(
            subscription_id=SUBSCRIPTION,
            region="westus3",
            environment="dev",
            workload="fdai",
            azure_group_reader=lambda _subscription: json.dumps(
                [
                    {
                        "name": "rg-fdai-dev-westu",
                        "location": "westus3",
                        "tags": {
                            "fdai:managed": "true",
                            "fdai:env": "dev",
                            "fdai:workload": "fdai",
                            "fdai:region-token": "westu",
                        },
                    }
                ]
            ),
        )
        == "westu"
    )


def test_existing_installation_discovery_fails_closed_on_ambiguity() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        selected_azure_region_short_name(
            region="westus3",
            subscription_id=SUBSCRIPTION,
            environment="dev",
            workload="fdai",
            azure_group_reader=lambda _subscription: json.dumps(
                [
                    {
                        "name": "rg-fdai-dev-westu",
                        "location": "westus3",
                        "tags": {
                            "fdai:managed": "true",
                            "fdai:env": "dev",
                            "fdai:workload": "fdai",
                        },
                    },
                    {
                        "name": "rg-fdai-dev-wus3",
                        "location": "westus3",
                        "tags": {
                            "fdai:managed": "true",
                            "fdai:env": "dev",
                            "fdai:workload": "fdai",
                        },
                    },
                ]
            ),
        )


def test_new_installation_uses_reviewed_token_when_no_existing_installation() -> None:
    selected = selected_azure_region_short_name(
        region="westus3",
        subscription_id=SUBSCRIPTION,
        environment="dev",
        workload="fdai",
        azure_group_reader=lambda _subscription: "[]",
    )

    assert selected == "wus3"
