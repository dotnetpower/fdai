"""Installation binding: literal and binding values only, never in the pinned digest."""

from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from fdai_lifecycle_agent.cli import load_local_policy
from fdai_lifecycle_agent.state import write_json_atomically
from fdai_lifecycle_agent.workload import WorkloadError

_SPEC = importlib.util.spec_from_file_location(
    "runtime_bundle_fixtures", Path(__file__).with_name("test_runtime_bundle.py")
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURES)
bundle_document = _FIXTURES.bundle_document
parse = _FIXTURES.parse

IMAGES = {("application", "frontend"): "example.azurecr.io/frontend@sha256:" + "a" * 64}
BINDING = {"format": "fdai.installation-binding.v1", "values": {"event-bus.endpoint": "kafka:9093"}}


def with_environment(*variables: dict[str, Any]) -> dict[str, Any]:
    document = bundle_document()
    deployment = next(item for item in document["objects"] if item["kind"] == "Deployment")
    deployment["spec"]["template"]["spec"]["containers"][0]["env"].extend(variables)
    return document


def render_env(bundle: Any) -> dict[str, Any]:
    manifests = bundle.render("fdai-demo", frozenset({"application"}), IMAGES)
    deployment = next(item for item in manifests if item["kind"] == "Deployment")
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    return {item["name"]: item for item in env}


def test_configuration_key_renders_plain_value_without_changing_digest() -> None:
    document = with_environment(
        {"name": "KAFKA_BOOTSTRAP_SERVERS", "configuration": "event-bus.endpoint"}
    )
    bundle = parse(document)
    digest = bundle.digest

    manifests = bundle.render(
        "fdai-demo",
        frozenset({"application"}),
        IMAGES,
        configuration_values={"application": {"event-bus.endpoint": "kafka:9093"}},
    )
    deployment = next(item for item in manifests if item["kind"] == "Deployment")
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]

    assert {"name": "KAFKA_BOOTSTRAP_SERVERS", "value": "kafka:9093"} in env
    assert bundle.digest == digest


def test_configuration_key_missing_fails_without_value_disclosure() -> None:
    bundle = parse(
        with_environment({"name": "KAFKA_BOOTSTRAP_SERVERS", "configuration": "event-bus.endpoint"})
    )

    with pytest.raises(WorkloadError, match="configuration_key_missing") as caught:
        bundle.render(
            "fdai-demo",
            frozenset({"application"}),
            IMAGES,
            configuration_values={"application": {}},
        )

    assert "event-bus.endpoint" not in str(caught.value)


def test_configuration_key_is_resolved_only_from_its_entity() -> None:
    bundle = parse(
        with_environment({"name": "KAFKA_BOOTSTRAP_SERVERS", "configuration": "event-bus.endpoint"})
    )

    manifests = bundle.render(
        "fdai-demo",
        frozenset({"application"}),
        IMAGES,
        configuration_values={
            "application": {"event-bus.endpoint": "application.kafka:9093"},
            "other": {"event-bus.endpoint": "other.kafka:9093"},
        },
    )
    deployment = next(item for item in manifests if item["kind"] == "Deployment")
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]

    assert {
        "name": "KAFKA_BOOTSTRAP_SERVERS",
        "value": "application.kafka:9093",
    } in env
    assert all(item.get("value") != "other.kafka:9093" for item in env)


def test_configuration_value_changes_leave_bundle_digest_unchanged() -> None:
    bundle = parse(
        with_environment({"name": "KAFKA_BOOTSTRAP_SERVERS", "configuration": "event-bus.endpoint"})
    )
    digest = bundle.digest

    first = bundle.render(
        "fdai-demo",
        frozenset({"application"}),
        IMAGES,
        configuration_values={"application": {"event-bus.endpoint": "one:9093"}},
    )
    second = bundle.render(
        "fdai-demo",
        frozenset({"application"}),
        IMAGES,
        configuration_values={"application": {"event-bus.endpoint": "two:9093"}},
    )

    assert bundle.digest == digest
    assert first != second


def test_configuration_key_cannot_supply_a_credential_environment() -> None:
    with pytest.raises(ValueError, match="requires a Secret reference"):
        parse(with_environment({"name": "DATABASE_PASSWORD", "configuration": "database.password"}))


def test_configuration_keys_match_authenticated_entity_values() -> None:
    from types import SimpleNamespace

    from fdai_deployment_cli.lifecycle_release import APPLICATION_COMPONENT_RELEASE_SCHEMA

    from fdai_lifecycle_agent.configuration_rendering import validate_entity_configuration
    from fdai_lifecycle_agent.inputs import VerifiedConfiguration

    bundle = parse(
        with_environment({"name": "KAFKA_BOOTSTRAP_SERVERS", "configuration": "event-bus.endpoint"})
    )
    values = {
        "runtime_bundle_digest": bundle.digest,
        "event-bus.endpoint": "kafka:9093",
    }
    configuration = VerifiedConfiguration(
        digest="configuration-digest",
        values={},
        entity_values={"application": values},
        render_values={"application": values},
    )

    validate_entity_configuration(
        configuration,
        {"application": frozenset({"frontend"})},
        current_schema=0,
        release=SimpleNamespace(
            schema_version=APPLICATION_COMPONENT_RELEASE_SCHEMA,
            schema_target=0,
        ),
        plan=SimpleNamespace(entity_ids=frozenset({"application"})),
        runtime_bundle=bundle,
    )


@pytest.mark.parametrize(
    ("extra_values", "reason"),
    [
        ({}, "runtime_bundle_configuration_key_missing"),
        ({"event-bus.endpoint": "kafka:9093", "unused": "value"}, "unsupported"),
    ],
)
def test_configuration_key_validation_rejects_missing_or_unused_values(
    extra_values: dict[str, str],
    reason: str,
) -> None:
    from types import SimpleNamespace

    from fdai_deployment_cli.lifecycle_release import APPLICATION_COMPONENT_RELEASE_SCHEMA

    from fdai_lifecycle_agent.configuration_rendering import validate_entity_configuration
    from fdai_lifecycle_agent.inputs import VerifiedConfiguration

    bundle = parse(
        with_environment({"name": "KAFKA_BOOTSTRAP_SERVERS", "configuration": "event-bus.endpoint"})
    )
    values = {"runtime_bundle_digest": bundle.digest, **extra_values}
    configuration = VerifiedConfiguration(
        digest="configuration-digest",
        values={},
        entity_values={"application": values},
        render_values={"application": values},
    )

    with pytest.raises(WorkloadError, match=reason):
        validate_entity_configuration(
            configuration,
            {"application": frozenset({"frontend"})},
            current_schema=0,
            release=SimpleNamespace(
                schema_version=APPLICATION_COMPONENT_RELEASE_SCHEMA,
                schema_target=0,
            ),
            plan=SimpleNamespace(entity_ids=frozenset({"application"})),
            runtime_bundle=bundle,
        )


def test_literal_and_binding_values_render_as_plain_values() -> None:
    bundle = parse(
        with_environment(
            {"name": "FDAI_EXECUTION_VENUE", "value": "deployed"},
            {"name": "KAFKA_BOOTSTRAP_SERVERS", "binding": "event-bus.endpoint"},
        )
    ).with_installation_binding({"event-bus.endpoint": "kafka:9093"})

    env = render_env(bundle)

    assert env["FDAI_EXECUTION_VENUE"] == {"name": "FDAI_EXECUTION_VENUE", "value": "deployed"}
    assert env["KAFKA_BOOTSTRAP_SERVERS"] == {
        "name": "KAFKA_BOOTSTRAP_SERVERS",
        "value": "kafka:9093",
    }
    assert "valueFrom" in env["DATABASE_REFERENCE"]


def test_binding_values_never_enter_the_pinned_digest_but_the_reference_does() -> None:
    document = with_environment(
        {"name": "KAFKA_BOOTSTRAP_SERVERS", "binding": "event-bus.endpoint"}
    )
    bundle = parse(document)

    first = bundle.with_installation_binding({"event-bus.endpoint": "one:9093"})
    second = bundle.with_installation_binding({"event-bus.endpoint": "two:9093"})

    assert first.digest == second.digest == bundle.digest
    assert "one:9093" not in str(first.model_dump(mode="json"))
    renamed = with_environment({"name": "KAFKA_BOOTSTRAP_SERVERS", "binding": "event-bus.other"})
    assert parse(renamed).digest != bundle.digest


def test_an_unbound_reference_fails_at_render_and_at_binding() -> None:
    bundle = parse(
        with_environment({"name": "KAFKA_BOOTSTRAP_SERVERS", "binding": "event-bus.endpoint"})
    )

    with pytest.raises(WorkloadError, match="installation_binding_key_missing"):
        render_env(bundle)
    with pytest.raises(ValueError, match="lacks a key the bundle references"):
        bundle.with_installation_binding({})


def test_the_binding_cannot_carry_a_key_the_bundle_does_not_reference() -> None:
    bundle = parse(
        with_environment({"name": "KAFKA_BOOTSTRAP_SERVERS", "binding": "event-bus.endpoint"})
    )

    with pytest.raises(ValueError, match="does not reference"):
        bundle.with_installation_binding({"event-bus.endpoint": "x:1", "extra.key": "y"})


@pytest.mark.parametrize(
    "variable",
    [
        {"name": "FDAI_STATE_STORE_DSN", "value": "postgresql://host/db"},
        {"name": "AZURE_CLIENT_SECRET", "binding": "event-bus.endpoint"},
        {"name": "GITHUB_TOKEN", "value": "x"},
        {"name": "SIGNING_SEED", "value": "x"},
        {"name": "STORAGE_ACCESS_KEY", "value": "x"},
        {"name": "VALUE", "value": ""},
        {"name": "VALUE", "value": "x" * 1025},
        {"name": "VALUE", "value": "line\nbreak"},
        {"name": "VALUE", "value": 1},
        {"name": "VALUE", "value": "https://user:pw@host/path"},
        {"name": "VALUE", "value": "Server=x;Password=y"},
        {"name": "VALUE", "binding": "Upper.Case"},
        {"name": "VALUE", "binding": 3},
        {"name": "VALUE", "value": "a", "binding": "event-bus.endpoint"},
        {"name": "VALUE"},
        {"name": "VALUE", "value": "a", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}},
    ],
)
def test_other_value_sources_and_credential_shaped_values_are_rejected(
    variable: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        parse(with_environment(variable))


@pytest.mark.parametrize(
    "values",
    [
        {"Bad.Key": "x"},
        {"event-bus.endpoint": ""},
        {"event-bus.endpoint": "https://user:pw@host"},
        {"event-bus.endpoint": "ok\x00"},
        {"event-bus.endpoint": 5},
    ],
)
def test_binding_values_are_validated_without_echoing_them(values: dict[str, Any]) -> None:
    bundle = parse(
        with_environment({"name": "KAFKA_BOOTSTRAP_SERVERS", "binding": "event-bus.endpoint"})
    )

    with pytest.raises(ValueError, match="installation binding") as caught:
        bundle.with_installation_binding(values)

    assert "pw@host" not in str(caught.value)


def policy(tmp_path: Path, document: dict[str, Any], binding: Any = None) -> Path:
    value: dict[str, Any] = {
        "schema": "fdai.lifecycle-local-policy.v1",
        "entity_ids": ["application"],
        "regions": ["korea-central"],
        "capability_modes": {},
        "destructive_allowed": False,
        "max_duration_minutes": 60,
        "entity_components": {"application": ["frontend"]},
        "product": "example-web",
        "component_images": {"frontend": "registry.example.test/application/frontend"},
        "runtime_bundle": document,
    }
    if binding is not None:
        value["installation_binding"] = binding
    path = tmp_path / "local-policy.json"
    write_json_atomically(path, value)
    return path


def test_the_private_policy_resolves_the_binding_into_the_bundle(tmp_path: Path) -> None:
    document = with_environment(
        {"name": "KAFKA_BOOTSTRAP_SERVERS", "binding": "event-bus.endpoint"}
    )

    loaded = load_local_policy(policy(tmp_path, document, deepcopy(BINDING)))

    assert render_env(loaded["runtime_bundle"])["KAFKA_BOOTSTRAP_SERVERS"]["value"] == "kafka:9093"
    assert loaded["runtime_bundle"].digest == parse(document).digest


def test_the_private_policy_rejects_an_absent_malformed_or_orphan_binding(tmp_path: Path) -> None:
    referencing = with_environment(
        {"name": "KAFKA_BOOTSTRAP_SERVERS", "binding": "event-bus.endpoint"}
    )

    with pytest.raises(ValueError, match="references an installation binding that is absent"):
        load_local_policy(policy(tmp_path, referencing))
    with pytest.raises(ValueError, match="installation binding is invalid"):
        load_local_policy(policy(tmp_path, referencing, {"format": "other", "values": {}}))
    with pytest.raises(ValueError, match="does not reference"):
        load_local_policy(policy(tmp_path, bundle_document(), deepcopy(BINDING)))


def test_a_binding_without_a_private_bundle_is_rejected(tmp_path: Path) -> None:
    path = policy(tmp_path, bundle_document(), deepcopy(BINDING))
    document = json.loads(path.read_text())
    del document["runtime_bundle"]
    write_json_atomically(path, document)

    with pytest.raises(ValueError, match="requires a private runtime bundle"):
        load_local_policy(path)


def test_a_group_readable_policy_with_a_binding_is_rejected(tmp_path: Path) -> None:
    document = with_environment(
        {"name": "KAFKA_BOOTSTRAP_SERVERS", "binding": "event-bus.endpoint"}
    )
    path = policy(tmp_path, document, deepcopy(BINDING))
    path.chmod(0o644)

    with pytest.raises(ValueError):
        load_local_policy(path)
