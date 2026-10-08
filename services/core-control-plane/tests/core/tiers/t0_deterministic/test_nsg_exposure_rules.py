"""Tests for the Internet-reachable inbound SSH and RDP NSG Rules.

Each case runs the real OPA evaluator. The older ``network.nsg.no-inbound-any-*`` Rules match only
one exact literal shape and stay locked at 1.0.0, so these Rules ship under new ids and judge
wildcard protocols, port ranges and lists, any-source aliases, and higher-priority deny rules.
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

SSH = "network.nsg.no-internet-inbound-ssh"
RDP = "network.nsg.no-internet-inbound-rdp"


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


def _security_rule(**rule: object) -> dict[str, object]:
    merged = {
        "direction": "Inbound",
        "access": "Allow",
        "protocol": "Tcp",
        "source_address_prefix": "*",
        "source_port_range": "*",
        "destination_address_prefix": "*",
        "priority": 200,
        **rule,
    }
    return {key: value for key, value in merged.items() if value is not None}


def _evaluate(rule_id: str, *security_rules: dict[str, object]) -> bool:
    result = OpaRegoEvaluator(policies_root=POLICIES_ROOT).evaluate(
        _rules()[rule_id], {"inbound_security_rules": list(security_rules)}
    )
    assert isinstance(result, PolicyResult)
    return result.denied


def _denied(rule_id: str, **rule: object) -> bool:
    return _evaluate(rule_id, _security_rule(**rule))


def test_rules_are_new_ids_at_version_1_0_0() -> None:
    rules = _rules()
    assert set(rules) == {SSH, RDP}
    assert {rule.version for rule in rules.values()} == {"1.0.0"}
    assert {tuple(rule.evaluates) for rule in rules.values()} == {
        ("property.network.nsg.inbound_security_rules",)
    }


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


@requires_opa
@pytest.mark.parametrize(("rule_id", "port"), [(SSH, "22"), (RDP, "3389")])
def test_a_higher_priority_broad_deny_blocks_the_exposure(rule_id: str, port: str) -> None:
    allow = _security_rule(destination_port_range=port, priority=300)
    deny = _security_rule(
        access="Deny", protocol="*", destination_port_range="*", source_address_prefix="Internet"
    )

    assert not _evaluate(rule_id, deny | {"priority": 100}, allow)


@requires_opa
@pytest.mark.parametrize(
    "deny_change",
    [
        {"priority": 400},
        {"source_address_prefix": "203.0.113.0/24"},
        {"protocol": "Udp"},
        {"destination_port_range": "443"},
        {"priority": None},
        {"destination_address_prefix": "10.0.0.4"},
        {"destination_address_prefix": None},
        {"destination_address_prefix": None, "destination_address_prefixes": ["10.0.0.0/24"]},
        {"destination_application_security_groups": 1},
        {"source_port_range": "1-1023"},
        {"source_port_range": None, "source_port_ranges": ["1024-65535"]},
    ],
)
def test_a_deny_that_does_not_cover_every_source_first_does_not_block(
    deny_change: dict[str, object],
) -> None:
    allow = _security_rule(destination_port_range="3389", priority=300)
    deny = _security_rule(access="Deny", destination_port_range="3389", priority=100)

    assert _evaluate(RDP, _security_rule(**(deny | deny_change)), allow)


@requires_opa
def test_an_allow_without_a_priority_is_never_treated_as_blocked() -> None:
    allow = _security_rule(destination_port_range="22", priority=None)
    deny = _security_rule(access="Deny", destination_port_range="*", priority=100)

    assert _evaluate(SSH, deny, allow)


@requires_opa
def test_a_deny_written_with_wildcard_lists_blocks_the_exposure() -> None:
    allow = _security_rule(destination_port_range="22", priority=300)
    deny = _security_rule(
        access="Deny",
        destination_port_range="22",
        destination_address_prefix=None,
        destination_address_prefixes=["*"],
        source_port_range=None,
        source_port_ranges=["*"],
        priority=100,
    )

    assert not _evaluate(SSH, deny, allow)
