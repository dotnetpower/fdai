from __future__ import annotations

from pathlib import Path

import yaml
from fdai.composition.readiness_catalog import load_runtime_best_practice_bindings
from fdai.core.ontology_platform.framework_projection import (
    build_framework_catalog_projection,
)
from fdai.rule_catalog.schema.control_objective import load_control_objective_catalog
from fdai.rule_catalog.schema.framework_catalog import load_framework_catalog

ROOT = Path(__file__).resolve().parents[5]
CATALOG = ROOT / "rule-catalog"
OBJECTIVE_REF = "reliability.node-pool.zone-failure-tolerance@1.0.0"


def test_framework_projection_is_advisory_and_complete() -> None:
    best_practices, _ = load_runtime_best_practice_bindings(CATALOG)
    objectives = load_control_objective_catalog(
        CATALOG / "control-objectives",
        operating_domains=frozenset({"reliability"}),
        object_type_names=frozenset({"Resource"}),
        resource_type_ids=frozenset({"kubernetes-node-pool"}),
        property_refs=frozenset({"property.kubernetes-node-pool.availability_zones"}),
    )
    frameworks = load_framework_catalog(
        CATALOG / "frameworks",
        best_practices=best_practices,
        objective_refs=frozenset({OBJECTIVE_REF}),
        additional_roots=(CATALOG / "collected/wara-aprl",),
    )

    projection = build_framework_catalog_projection(
        frameworks=frameworks,
        objectives=objectives,
    )

    assert sum(item.object_type == "Framework" for item in projection.objects) == 3
    assert sum(item.object_type == "FrameworkControl" for item in projection.objects) == 530
    assert sum(item.link_type == "framework_contains_control" for item in projection.links) == 530
    assert (
        sum(item.link_type == "framework_control_maps_objective" for item in projection.links) == 1
    )
    assert all(
        item.properties.get("advisory") is True
        for item in projection.objects
        if item.object_type == "Framework"
    )


def test_framework_types_do_not_connect_to_authorization_or_actions() -> None:
    forbidden = {"AccessGrant", "AuthorizationRequirement", "ActionType"}
    for path in (CATALOG / "vocabulary/link-types").glob("*.yaml"):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        endpoints = {raw["from_type"], raw["to_type"]}
        assert not (endpoints & {"Framework", "FrameworkControl"} and endpoints & forbidden), (
            path.name
        )
