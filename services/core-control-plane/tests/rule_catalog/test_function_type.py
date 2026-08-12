"""Reviewed FunctionType catalog and exact-release integration tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
)
from fdai.core.ontology_platform.query_profiles import QueryProfile
from fdai.rule_catalog.schema.function_type import (
    FunctionTypeCatalogError,
    load_function_type_catalog,
    ontology_function_artifact_digest,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.ontology_provenance import ontology_content_hash
from fdai.shared.contracts.models import (
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release

REPO_ROOT = Path(__file__).resolve().parents[4]


def _function_mapping() -> dict[str, Any]:
    declaration = OntologyFunctionType(
        name="inventory.select_resources",
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest="sha256:" + "0" * 64,
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["object_set"],
            "properties": {"object_set": {"type": "object"}},
        },
        output_schema={"type": "object"},
        read_sets=["ontology.object-set"],
        purpose_bindings=["operations-review"],
    )
    declaration = declaration.model_copy(
        update={"artifact_digest": ontology_function_artifact_digest(declaration)}
    )
    raw = declaration.model_dump(mode="json", exclude_none=True)
    raw["provenance"] = {
        "source_url": "https://github.com/dotnetpower/fdai",
        "resolved_ref": "function-type:inventory.select_resources@1.0.0",
        "content_hash": "sha256:" + "0" * 64,
        "license": "MIT",
        "retrieved_at": "2026-08-12T00:00:00Z",
    }
    with_provenance = OntologyFunctionType.model_validate(raw)
    raw["provenance"]["content_hash"] = ontology_content_hash(with_provenance)
    return raw


def _write(root: Path, name: str, raw: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def test_shipped_function_type_enters_catalog_release_and_exact_consumers() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    function_type = next(
        item for item in catalog.function_types if item.name == "inventory.select_resources"
    )
    release = catalog.build_release()
    function_ref = release.type_ref(OntologyDeclarationKind.FUNCTION, function_type.name)
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=datetime(2026, 8, 12, tzinfo=UTC),
        purpose="operations-review",
        limit=10,
    )
    profile = QueryProfile.from_release(
        release=release,
        name="inventory.resources",
        version="1.0.0",
        function_type=function_type,
        object_set_template=definition,
        purpose=definition.purpose,
    )
    registry = OntologyFunctionRegistry(release=release)

    async def query(_arguments: Any) -> object:
        return {}

    registry.register(function_type, query)

    assert profile.function_ref == function_ref
    assert registry.release_ref == release.ref()
    assert registry.declaration(function_type.name) == profile.function_type
    assert function_type.execution_authority is False
    assert function_type.network_allowed is False
    assert function_type.credentials_allowed is False


def test_function_type_catalog_rejects_stale_artifact_digest(tmp_path: Path) -> None:
    raw = _function_mapping()
    raw["publisher"] = "changed-without-artifact-refresh"
    _write(tmp_path, "inventory.select_resources.yaml", raw)

    with pytest.raises(FunctionTypeCatalogError, match="artifact_digest mismatch"):
        load_function_type_catalog(
            tmp_path,
            schema_registry=PackageResourceSchemaRegistry(),
        )


def test_function_type_catalog_rejects_duplicate_name_version(tmp_path: Path) -> None:
    raw = _function_mapping()
    _write(tmp_path, "first.yaml", raw)
    _write(tmp_path, "second.yaml", raw)

    with pytest.raises(FunctionTypeCatalogError, match="duplicate FunctionType name/version"):
        load_function_type_catalog(
            tmp_path,
            schema_registry=PackageResourceSchemaRegistry(),
        )


def test_registry_rejects_undeclared_function() -> None:
    raw = _function_mapping()
    declaration = OntologyFunctionType.model_validate(raw)
    registry = OntologyFunctionRegistry(release=build_ontology_release())

    async def query(_arguments: Any) -> object:
        return {}

    with pytest.raises(ValueError, match="does not match release"):
        registry.register(declaration, query)


def test_query_profile_factory_rejects_changed_function_declaration() -> None:
    raw = _function_mapping()
    declaration = OntologyFunctionType.model_validate(raw)
    release = build_ontology_release(function_types=(declaration,))
    changed = declaration.model_copy(update={"publisher": "changed"})
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=datetime(2026, 8, 12, tzinfo=UTC),
        purpose="operations-review",
    )

    with pytest.raises(ValueError, match="does not match release"):
        QueryProfile.from_release(
            release=release,
            name="inventory.resources",
            version="1.0.0",
            function_type=changed,
            object_set_template=definition,
            purpose=definition.purpose,
        )


def test_function_invocation_context_exposes_no_execution_identity() -> None:
    fields = set(FunctionInvocationContext.model_fields)

    assert "executor_identity" not in fields
    assert "provider" not in fields
    assert "mutation" not in fields
