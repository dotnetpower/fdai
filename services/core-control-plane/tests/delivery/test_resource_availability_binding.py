"""Use real versioned Settings reads/updates with the parent-owned catalog registration."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery import runtime_settings
from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.delivery.resource_availability_binding import (
    DEFAULT_RESOURCE_AVAILABILITY_SETTINGS,
    RESOURCE_AVAILABILITY_SETTING_KEY,
    build_resource_availability_analyzers,
    resource_availability_scope_ref,
    validate_resource_availability_setting,
)
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
REF = "scope-example/resource-group/example/compute/example"
OTHER = "scope-example/resource-group/example/compute/other"
ARM = (
    "/subscriptions/00000000-0000-0000-0000-000000000000"
    "/resourceGroups/example/providers/Microsoft.Compute/virtualMachines/example"
)
TARGET = AnalyzerTarget(REF, "virtual_machine", "compute.vm", ARM)
RECORD = ResourceRecord(
    REF,
    "compute.vm",
    {"status": "PowerState/stopped"},
    ARM,
    (NOW - timedelta(seconds=30)).isoformat(),
)


@pytest.fixture
def registered_catalog():
    assert RESOURCE_AVAILABILITY_SETTING_KEY in {
        spec.key for spec in runtime_settings.RUNTIME_SETTING_SPECS
    }


def test_delivery_exports_delegate_to_the_same_pure_schema() -> None:
    from fdai.core.readiness import resource_availability_settings as pure
    from fdai.delivery.azure.resource_availability import AZURE_AVAILABILITY_RESOURCE_TYPES

    assert validate_resource_availability_setting is pure.validate_resource_availability_setting
    assert DEFAULT_RESOURCE_AVAILABILITY_SETTINGS is pure.DEFAULT_RESOURCE_AVAILABILITY_SETTINGS
    assert AZURE_AVAILABILITY_RESOURCE_TYPES is pure.RESOURCE_AVAILABILITY_RESOURCE_TYPES


class Inventory:
    def __init__(self):
        self.generation = "example-generation"
        self.records = {REF: RECORD}
        self.requests = []
        self.on_read = None

    async def read_active_resources(self, *, resource_ids):
        self.requests.append(resource_ids)
        if self.on_read is not None:
            await self.on_read()
        return self.generation, {
            key: value for key, value in self.records.items() if key in resource_ids
        }


def _config(**changes):
    return {
        "enabled": True,
        "resource_types": ["compute.vm"],
        "max_age_seconds": 300.0,
        "resources": {},
        **changes,
    }


async def _settings(config=None, *, env=None):
    store = InMemoryStateStore()
    settings = RuntimeSettingsService(store=store, env=env or {}, durable=True)
    if config is not None:
        await settings.update(
            actor_id="example-owner",
            changes={RESOURCE_AVAILABILITY_SETTING_KEY: config},
            expected_revision=0,
        )
    return settings, store


async def _build(settings, store, inventory, **changes):
    return await build_resource_availability_analyzers(
        settings=settings,
        inventory=inventory,
        inventory_generation=changes.pop("inventory_generation", "example-generation"),
        targets=changes.pop("targets", (TARGET,)),
        state_store=store,
        wall_clock=lambda: NOW,
        **changes,
    )


async def test_missing_common_catalog_registration_is_explicitly_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_settings,
        "RUNTIME_SETTING_SPECS",
        tuple(
            spec
            for spec in runtime_settings.RUNTIME_SETTING_SPECS
            if spec.key != RESOURCE_AVAILABILITY_SETTING_KEY
        ),
    )
    monkeypatch.setattr(
        runtime_settings,
        "_SPECS_BY_KEY",
        {
            key: value
            for key, value in runtime_settings._SPECS_BY_KEY.items()
            if key != RESOURCE_AVAILABILITY_SETTING_KEY
        },
    )
    settings, store = await _settings()
    result = await _build(settings, store, Inventory())
    assert not result.available
    assert result.unavailable_reason == "setting_catalog_unregistered"
    assert not result.analyzers


async def test_default_and_environment_strings_do_not_enable_monitoring(registered_catalog) -> None:
    settings, store = await _settings(env={"FDAI_RESOURCE_AVAILABILITY_ENABLED": "1"})
    inventory = Inventory()
    result = await _build(settings, store, inventory)
    assert result.available
    assert not result.enabled
    assert result.settings_revision == 0
    assert not result.analyzers
    assert not inventory.requests


async def test_audited_settings_revision_builds_actual_scoped_analyzer(registered_catalog) -> None:
    settings, store = await _settings(_config())
    inventory = Inventory()
    result = await _build(settings, store, inventory)
    assert result.available and result.enabled
    assert result.monitored_resources == 1
    assert result.settings_revision == 1
    assert len(tuple(store.audit_entries)) == 1
    (analyzer,) = result.analyzers
    (finding,) = await analyzer.analyze(resource_ref=REF, window_seconds=300)
    assert finding.assessment.status == "stop_observed"
    assert finding.metadata["current_state"] == "stop_observed"
    assert finding.metadata["settings_revision"] == "1"
    replay = json.loads(finding.metadata["assessment_input"])
    assert replay["policy"]["expected_state"] is None
    assert replay["scope_ref"] == resource_availability_scope_ref(REF)
    assert ARM not in repr(finding)
    assert finding.remediation_ref is None


async def test_only_exact_per_resource_policy_supplies_an_expectation(registered_catalog) -> None:
    config = _config(
        resources={
            REF: {
                "resource_type": "compute.vm",
                "reference": "policy:running-example",
                "expected_state": "running",
            },
        }
    )
    settings, store = await _settings(config)
    inventory = Inventory()
    inventory.records[OTHER] = replace(RECORD, resource_id=OTHER, provider_ref=ARM + "-other")
    other_target = replace(TARGET, resource_ref=OTHER, provider_query_ref=ARM + "-other")
    result = await _build(settings, store, inventory, targets=(TARGET, other_target))
    (dispatcher,) = result.analyzers
    assert result.monitored_resources == 2
    reads = len(inventory.requests)
    assert not await dispatcher.analyze(resource_ref="unknown-resource", window_seconds=300)
    assert len(inventory.requests) == reads
    (declared,) = await dispatcher.analyze(resource_ref=REF, window_seconds=300)
    (undeclared,) = await dispatcher.analyze(resource_ref=OTHER, window_seconds=300)
    assert declared.assessment.status == "expected_running_not_observed"
    assert "policy:running-example" in declared.evidence_refs
    assert undeclared.assessment.status == "stop_observed"


async def test_declared_maintenance_is_not_a_new_fault(registered_catalog) -> None:
    config = _config(
        resources={
            REF: {
                "resource_type": "compute.vm",
                "reference": "policy:running-example",
                "expected_state": "running",
                "planned_stops": [
                    {
                        "since": (NOW - timedelta(minutes=5)).isoformat(),
                        "until": (NOW + timedelta(minutes=5)).isoformat(),
                        "reference": "maintenance:example",
                        "maintenance": True,
                    }
                ],
            },
        }
    )
    settings, store = await _settings(config)
    result = await _build(settings, store, Inventory())
    assert not await result.analyzers[0].analyze(resource_ref=REF, window_seconds=300)


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("generation", "inventory_generation_changed"),
        ("missing", "inventory_target_coverage_incomplete"),
        ("provider", "inventory_target_identity_mismatch"),
        ("type", "inventory_target_identity_mismatch"),
        ("logical", "inventory_target_identity_mismatch"),
        ("target_provider_missing", "target_identity_unavailable"),
    ],
)
async def test_identity_generation_and_coverage_are_fenced(
    registered_catalog, case, reason
) -> None:
    settings, store = await _settings(_config())
    inventory = Inventory()
    target = TARGET
    if case == "generation":
        inventory.generation = "another-generation"
    elif case == "missing":
        inventory.records.clear()
    elif case == "provider":
        inventory.records[REF] = replace(RECORD, provider_ref=ARM + "-wrong")
    elif case == "type":
        inventory.records[REF] = replace(RECORD, type="mysql-server")
    elif case == "logical":
        inventory.records[REF] = replace(RECORD, resource_id=OTHER)
    else:
        target = replace(TARGET, provider_query_ref=None)
    result = await _build(settings, store, inventory, targets=(target,))
    assert not result.available
    assert not result.analyzers
    assert result.unavailable_reason == reason


async def test_settings_change_while_reading_inventory_invalidates_binding(
    registered_catalog,
) -> None:
    settings, store = await _settings(_config())
    inventory = Inventory()

    async def disable():
        await settings.update(
            actor_id="example-owner",
            changes={RESOURCE_AVAILABILITY_SETTING_KEY: _config(enabled=False)},
            expected_revision=1,
        )

    inventory.on_read = disable
    result = await _build(settings, store, inventory)
    assert result.unavailable_reason == "runtime_settings_revision_changed"
    assert not result.analyzers


async def test_later_operator_enable_disable_revision_is_read_on_each_build(
    registered_catalog,
) -> None:
    settings, store = await _settings(_config())
    first = await _build(settings, store, Inventory())
    await settings.update(
        actor_id="example-owner",
        changes={RESOURCE_AVAILABILITY_SETTING_KEY: _config(enabled=False)},
        expected_revision=1,
    )
    second = await _build(settings, store, Inventory())
    assert first.enabled and first.settings_revision == 1
    assert not second.enabled and second.settings_revision == 2
    assert not second.analyzers


@pytest.mark.parametrize(
    "config",
    [
        _config(enabled="true"),
        _config(resource_types=[]),
        _config(resource_types=["unclassified-resource"]),
        _config(resource_types=["compute.vm", "compute.vm"]),
        _config(max_age_seconds=float("inf")),
        _config(max_age_seconds=True),
        _config(execution_authority=True),
        _config(resources={REF: {"resource_type": "compute.vm", "expected_state": "running"}}),
        _config(resources={REF: {"resource_type": "compute.vm", "reference": ARM}}),
        _config(resources={ARM: {"resource_type": "compute.vm", "reference": "policy:example"}}),
        _config(resources={REF: {"resource_type": "mysql-server", "reference": "policy:example"}}),
    ],
)
def test_structured_catalog_validator_rejects_ambiguous_or_authority_bearing_input(config) -> None:
    with pytest.raises(ValueError, match="setting is invalid"):
        validate_resource_availability_setting(config)


async def test_unknown_unselected_type_does_not_acquire_an_expectation(registered_catalog) -> None:
    settings, store = await _settings(_config())
    result = await _build(
        settings,
        store,
        Inventory(),
        targets=(replace(TARGET, resource_type="unclassified-resource"),),
    )
    assert result.available
    assert result.monitored_resources == 0
    assert not result.analyzers


async def test_one_exact_target_dispatcher_per_resource_kind(registered_catalog) -> None:
    settings, store = await _settings(_config(resource_types=["compute.vm", "mysql-server"]))
    inventory = Inventory()
    mysql_ref = "scope-example/resource-group/example/database/example"
    mysql_arm = ARM.replace(
        "Microsoft.Compute/virtualMachines",
        "Microsoft.DBforMySQL/flexibleServers",
    )
    inventory.records[mysql_ref] = ResourceRecord(
        mysql_ref,
        "mysql-server",
        {"properties": {"state": "Stopped"}},
        mysql_arm,
        RECORD.last_seen,
    )
    mysql_target = AnalyzerTarget(
        mysql_ref,
        "mysql_flexible_server",
        "mysql-server",
        mysql_arm,
    )
    result = await _build(settings, store, inventory, targets=(TARGET, mysql_target))
    by_kind = {analyzer.resource_kind: analyzer for analyzer in result.analyzers}
    assert set(by_kind) == {"virtual_machine", "mysql_flexible_server"}
    assert result.monitored_resources == 2
    reads = len(inventory.requests)
    assert not await by_kind["virtual_machine"].analyze(
        resource_ref=mysql_ref,
        window_seconds=300,
    )
    assert len(inventory.requests) == reads
    (finding,) = await by_kind["mysql_flexible_server"].analyze(
        resource_ref=mysql_ref,
        window_seconds=300,
    )
    assert finding.resource_ref == mysql_ref
    assert finding.assessment.status == "stop_observed"
