"""Regression tests for the any-source inbound SSH and RDP NSG Rules (version 1.1.0).

Each case runs the real OPA evaluator. Version 1.0.0 matched only one exact literal shape, so an
exposure written with a wildcard protocol, a port range or list, or an ``Internet`` source passed.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml
from fdai.core.tiers.t0_deterministic import OpaRegoEvaluator, PolicyResult
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[6]
POLICIES_ROOT = REPO_ROOT / "policies"

requires_opa = pytest.mark.skipif(
    shutil.which("opa") is None, reason="opa binary not found on PATH; skip subprocess tests"
)

SSH = "network.nsg.no-inbound-any-ssh"
RDP = "network.nsg.no-inbound-any-rdp"


def _rules() -> Mapping[str, Rule]:
    registry = PackageResourceSchemaRegistry()
    vocabulary = REPO_ROOT / "rule-catalog/vocabulary/resource-types.yaml"
    rules = load_rule_catalog(
        REPO_ROOT / "rule-catalog/catalog",
        schema_registry=registry,
        action_types=load_action_type_catalog(
            REPO_ROOT / "rule-catalog/action-types", schema_registry=registry
        ),
        resource_types=load_resource_type_registry_from_mapping(
            yaml.safe_load(vocabulary.read_text(encoding="utf-8"))
        ),
        policies_root=POLICIES_ROOT,
    )
    return {rule.id: rule for rule in rules if rule.id in {SSH, RDP}}


def _denied(rule_id: str, **rule: object) -> bool:
    merged = {
        "direction": "Inbound",
        "access": "Allow",
        "protocol": "Tcp",
        "source_address_prefix": "*",
        **rule,
    }
    security_rule = {key: value for key, value in merged.items() if value is not None}
    result = OpaRegoEvaluator(policies_root=POLICIES_ROOT).evaluate(
        _rules()[rule_id], {"security_rules": [security_rule]}
    )
    assert isinstance(result, PolicyResult)
    return result.denied


def test_rules_are_version_1_1_0() -> None:
    assert {rule.version for rule in _rules().values()} == {"1.1.0"}


@requires_opa
@pytest.mark.parametrize(("rule_id", "port"), [(SSH, "22"), (RDP, "3389")])
@pytest.mark.parametrize(
    "exposure",
    [
        {},
        {"protocol": "*"},
        {"protocol": "TCP"},
        {"destination_port_range": "*"},
        {"source_address_prefix": "Internet"},
        {"source_address_prefix": "0.0.0.0/0"},
        {"source_address_prefix": None, "source_address_prefixes": ["10.0.0.0/8", "Any"]},
    ],
)
def test_any_source_exposure_is_denied(
    rule_id: str, port: str, exposure: dict[str, object]
) -> None:
    rule = {"destination_port_range": port, **exposure}
    assert _denied(rule_id, **rule)


@requires_opa
@pytest.mark.parametrize(
    ("rule_id", "ports"),
    [(SSH, {"destination_port_range": "20-25"}), (RDP, {"destination_port_ranges": ["3380-3390"]})],
)
def test_ranges_and_lists_that_cover_the_port_are_denied(
    rule_id: str, ports: dict[str, object]
) -> None:
    assert _denied(rule_id, **ports)


@requires_opa
@pytest.mark.parametrize(("rule_id", "port"), [(SSH, "22"), (RDP, "3389")])
@pytest.mark.parametrize(
    "safe",
    [
        {"source_address_prefix": "10.0.0.0/8"},
        {"source_address_prefix": "VirtualNetwork"},
        {"source_address_prefix": None, "source_address_prefixes": ["10.0.0.0/8"]},
        {"access": "Deny"},
        {"direction": "Outbound"},
        {"protocol": "Udp"},
    ],
)
def test_scoped_or_non_matching_rules_are_allowed(
    rule_id: str, port: str, safe: dict[str, object]
) -> None:
    assert not _denied(rule_id, destination_port_range=port, **safe)


@requires_opa
def test_ranges_that_miss_the_port_are_allowed() -> None:
    assert not _denied(SSH, destination_port_range="80-443")
    assert not _denied(RDP, destination_port_ranges=["443", "8080-8090"])
