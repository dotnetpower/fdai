"""Core stewardship governance follows the explicitly selected Console handover surfaces."""

from __future__ import annotations

import pytest
from fdai_deployment_cli.standalone_host_values import (
    aks_core_environment,
    stewardship_governance_selected,
)

_OPERATOR = "00000000-0000-0000-0000-0000000000aa"


def _values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "region": "westus3",
        "env": "dev",
        "product_profile_json": "{}",
        "enable_operator_api": True,
        "enable_document_ingestion": True,
        "stewardship_maintainers": _OPERATOR,
        "stewardship_agent_bindings": {"Odin": f"user:{_OPERATOR}", "Freyr": f"user:{_OPERATOR}"},
    }
    values.update(overrides)
    return values


def _environment(values: dict[str, object]) -> dict[str, object]:
    return aks_core_environment(
        context={"tenant_id": "tenant-1", "subscription_id": "subscription-1"},
        application_values=values,
        substrate_outputs={
            "kafka": "events",
            "postgres_fqdn": "postgres.example.invalid",
            "postgres_database": "fdai",
            "workspace": "workspace",
            "operating_model_topic": "operating-model",
            "operational_kafka": "operational-events",
            "installation_binding": "installation",
        },
        resource_group="rg-dev",
        core_identity={"client_id": "client"},
        topics=["events"],
        deployment_binding="deployment",
    )


def test_selected_handover_surfaces_enable_the_console_governed_worker_with_bindings() -> None:
    environment = _environment(_values())

    assert environment["FDAI_STEWARDSHIP_GOVERNANCE_ENABLED"] == "true"
    assert environment["FDAI_MAINTAINERS"] == _OPERATOR
    assert environment["FDAI_STEWARD_ODIN"] == f"user:{_OPERATOR}"
    assert environment["FDAI_STEWARD_FREYR"] == f"user:{_OPERATOR}"
    # No GitOps target, GitHub credential, or webhook secret is introduced.
    assert not [key for key in environment if "GITHUB" in key or "GITOPS" in key]


@pytest.mark.parametrize(
    "override",
    [
        {"enable_document_ingestion": False},
        {"enable_operator_api": False},
        {"stewardship_maintainers": ""},
        {"stewardship_maintainers": "   "},
    ],
)
def test_governance_stays_off_unless_every_surface_is_selected(override: dict[str, object]) -> None:
    values = _values(**override)
    assert stewardship_governance_selected(values) is False
    environment = _environment(values)
    assert "FDAI_STEWARDSHIP_GOVERNANCE_ENABLED" not in environment
    assert "FDAI_MAINTAINERS" not in environment


def test_an_installation_without_enterprise_identity_values_is_unchanged() -> None:
    values = {"region": "westus3", "env": "dev", "product_profile_json": "{}"}
    assert stewardship_governance_selected(values) is False
    assert "FDAI_STEWARDSHIP_GOVERNANCE_ENABLED" not in _environment(values)


def test_malformed_bindings_fail_closed_instead_of_enabling_governance() -> None:
    with pytest.raises(ValueError, match="stewardship bindings are invalid"):
        _environment(_values(stewardship_agent_bindings=["not", "a", "mapping"]))
