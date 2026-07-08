"""The DI seam contract for :class:`SchemaRegistry`.

Both the shipped default (``PackageResourceSchemaRegistry``) and a test-only
in-memory implementation must satisfy the same Protocol. This suite runs the
same behavioural expectations against both so a future third implementation
(e.g. a remote schema registry adapter) has a fixed target to pass.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from fdai.shared.contracts.registry import (
    PackageResourceSchemaRegistry,
    SchemaNotFoundError,
    SchemaRegistry,
)

from ..conftest import InMemorySchemaRegistry


def _default_backed_fake() -> InMemorySchemaRegistry:
    """Build a fake seeded from the shipped schemas.

    The intent is that the fake and the default expose the same names, so a
    Protocol consumer cannot tell them apart.
    """
    default = PackageResourceSchemaRegistry()
    seed = {(name, "1.0.0"): default.get(name) for name in default.names()}
    return InMemorySchemaRegistry(seed)


REGISTRY_FACTORIES: list[Callable[[], SchemaRegistry]] = [
    lambda: cast(SchemaRegistry, PackageResourceSchemaRegistry()),
    lambda: cast(SchemaRegistry, _default_backed_fake()),
]


@pytest.mark.parametrize("factory", REGISTRY_FACTORIES)
def test_registry_returns_dict_for_known_schema(
    factory: Callable[[], SchemaRegistry],
) -> None:
    registry = factory()
    schema = registry.get("event")
    assert isinstance(schema, dict) or hasattr(schema, "keys")
    assert schema.get("title") == "Event"


@pytest.mark.parametrize("factory", REGISTRY_FACTORIES)
def test_registry_raises_on_unknown_schema(
    factory: Callable[[], SchemaRegistry],
) -> None:
    registry = factory()
    with pytest.raises(SchemaNotFoundError):
        registry.get("no-such-schema")


@pytest.mark.parametrize("factory", REGISTRY_FACTORIES)
def test_registry_names_covers_expected_set(
    factory: Callable[[], SchemaRegistry],
) -> None:
    registry = factory()
    expected = {
        "event",
        "action",
        "rule",
        "incident",
        "slo",
        "runbook",
        "profile",
        "ontology/object-type",
        "ontology/link-type",
        "ontology/action-type",
    }
    assert set(registry.names()) == expected


def test_package_registry_caches_parsed_schema() -> None:
    # The parsed schema is an immutable package resource; repeated get()
    # calls MUST return the cached object rather than re-reading + re-parsing
    # the file on a hot path (schema validation runs per rule / per event).
    registry = PackageResourceSchemaRegistry()
    first = registry.get("event")
    second = registry.get("event")
    assert first is second


def test_default_container_wires_the_upstream_seam(app_config: object) -> None:
    """The composition root MUST bind the upstream default when handed a valid config."""
    from fdai.composition import default_container
    from fdai.shared.config import AppConfig

    assert isinstance(app_config, AppConfig)
    container = default_container(app_config)
    assert isinstance(container.schema_registry, PackageResourceSchemaRegistry)
    assert container.config is app_config
    # And the validator holds a *reference* to whatever SchemaRegistry the
    # container decided to wire - not a hard-coded default.
    assert container.contract_validator is not None
    assert container.event_validator is not None
