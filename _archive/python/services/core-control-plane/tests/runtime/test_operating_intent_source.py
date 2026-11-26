"""Deployment-owned six-type operating-intent source runtime binding."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog, load_ontology_catalog
from fdai.runtime.operating_intent_source import (
    OPERATING_INTENT_SOURCE_STATUS_KEY,
    project_operating_intent_source_from_env,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[4]
_EFFECTIVE_FROM = "2026-08-27T00:00:00+00:00"
_NOW = "2026-08-27T12:00:00+00:00"
_VALIDATION_NOW = datetime.fromisoformat(_NOW)
_REVISION = "operating-intent-revision-1"


def _catalog_and_store() -> tuple[OntologyCatalog, InMemoryOntologyInstanceStore]:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    return catalog, store


def _document(
    *,
    revision: str = _REVISION,
    resolved_ref: str | None = None,
    include_change_window: bool = True,
    extra_service_objectives: int = 0,
    service_objective_effective_from: str = _EFFECTIVE_FROM,
    change_window_effective_to: str = "2026-09-30T00:00:00+00:00",
    retrieved_at: str = _NOW,
) -> dict[str, object]:
    objects: list[dict[str, object]] = [
        {
            "id": "service-objective-1",
            "object_type": "ServiceObjective",
            "properties": {
                "id": "service-objective-1",
                "objective_kind": "availability",
                "metric": "availability",
                "unit": "ratio",
                "target": 0.999,
                "window_seconds": 2592000,
                "measurement_source_ref": "source:service-objectives",
                "freshness_seconds": 86400,
                "effective_from": service_objective_effective_from,
            },
        },
        {
            "id": "recovery-objective-1",
            "object_type": "RecoveryObjective",
            "properties": {
                "id": "recovery-objective-1",
                "rto_seconds": 3600,
                "rpo_seconds": 300,
                "measurement_source_ref": "source:recovery-objectives",
                "freshness_seconds": 86400,
                "effective_from": _EFFECTIVE_FROM,
            },
        },
        {
            "id": "cost-objective-1",
            "object_type": "CostObjective",
            "properties": {
                "id": "cost-objective-1",
                "objective_kind": "monthly_budget",
                "currency": "USD",
                "target": 1000,
                "period_seconds": 2592000,
                "measurement_source_ref": "source:cost-objectives",
                "freshness_seconds": 86400,
                "effective_from": _EFFECTIVE_FROM,
            },
        },
        {
            "id": "architecture-constraint-1",
            "object_type": "ArchitectureConstraint",
            "properties": {
                "id": "architecture-constraint-1",
                "constraint_kind": "network_isolation",
                "expression_ref": "policy:network-isolation",
                "severity": "high",
                "effective_from": _EFFECTIVE_FROM,
            },
        },
        {
            "id": "ownership-1",
            "object_type": "Ownership",
            "properties": {
                "id": "ownership-1",
                "owner_ref": "group:operations-owner",
                "escalation_ref": "route:on-call",
                "effective_from": _EFFECTIVE_FROM,
                "source_ref": "source:service-catalog",
            },
        },
    ]
    if include_change_window:
        objects.append(
            {
                "id": "change-window-1",
                "object_type": "ChangeWindow",
                "properties": {
                    "id": "change-window-1",
                    "window_kind": "maintenance",
                    "scope_ref": "scope:example",
                    "status": "approved",
                    "effective_from": _EFFECTIVE_FROM,
                    "effective_to": change_window_effective_to,
                    "policy_ref": "policy:change-window",
                },
            }
        )
    for index in range(extra_service_objectives):
        objects.append(
            {
                "id": f"service-objective-extra-{index}",
                "object_type": "ServiceObjective",
                "properties": {
                    "id": f"service-objective-extra-{index}",
                    "objective_kind": "availability",
                    "metric": "availability",
                    "unit": "ratio",
                    "target": 0.99,
                    "window_seconds": 2592000,
                    "measurement_source_ref": "source:service-objectives",
                    "freshness_seconds": 86400,
                    "effective_from": _EFFECTIVE_FROM,
                },
            }
        )
    return {
        "source_revision": revision,
        "provenance": {
            "source_url": "https://example.invalid/operating-intent-source",
            "resolved_ref": resolved_ref if resolved_ref is not None else revision,
            "retrieved_at": retrieved_at,
        },
        "objects": objects,
        "links": [],
    }


def _digest_of(document: Mapping[str, object]) -> str:
    """Pin the whole document, provenance included, exactly as an operator would."""

    from fdai.delivery.operating_model.json_file import (
        operating_intent_source_document_from_mapping,
    )
    from fdai.shared.providers.operating_model import (
        operating_intent_source_document_digest,
    )

    return operating_intent_source_document_digest(
        operating_intent_source_document_from_mapping(document)
    )


def _env(path: Path, document: Mapping[str, object], **overrides: str) -> dict[str, str]:
    env = {
        "FDAI_OPERATING_INTENT_SOURCE_PATH": str(path),
        "FDAI_OPERATING_INTENT_SOURCE_REVISION": str(document["source_revision"]),
        "FDAI_OPERATING_INTENT_SOURCE_SHA256": _digest_of(document),
    }
    env.update(overrides)
    return env


def _write(path: Path, document: Mapping[str, object]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


async def test_unconfigured_records_explicit_status() -> None:
    status_store = InMemoryStateStore()

    result = await project_operating_intent_source_from_env(
        store=None,
        object_types=(),
        link_types=(),
        status_store=status_store,
        env={},
    )

    assert result is None
    assert await status_store.read_state(OPERATING_INTENT_SOURCE_STATUS_KEY) == {
        "schema_version": "1.0.0",
        "status": "unconfigured",
    }


async def test_complete_pinned_source_projects_all_six_types(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-intent-source.json"
    document = _document()
    _write(path, document)

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=_env(path, document),
        now=_VALIDATION_NOW,
    )

    assert result is not None
    assert result.source_revision == _REVISION
    expected_types = {
        "ArchitectureConstraint",
        "ChangeWindow",
        "CostObjective",
        "Ownership",
        "RecoveryObjective",
        "ServiceObjective",
    }
    projected_types = {
        record.object_type
        for identifier in (
            "architecture-constraint-1",
            "change-window-1",
            "cost-objective-1",
            "ownership-1",
            "recovery-objective-1",
            "service-objective-1",
        )
        if (record := await store.get_object(identifier)) is not None
    }
    assert projected_types == expected_types
    status = await status_store.read_state(OPERATING_INTENT_SOURCE_STATUS_KEY)
    assert status is not None
    assert status["status"] == "projected"


async def test_missing_type_is_rejected_and_preserves_prior_graph(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-intent-source.json"
    good_document = _document()
    _write(path, good_document)
    await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=_env(path, good_document),
        now=_VALIDATION_NOW,
    )

    bad_document = _document(revision="operating-intent-revision-2", include_change_window=False)
    _write(path, bad_document)

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=_env(path, bad_document),
        now=_VALIDATION_NOW,
    )

    assert result is None
    status = await status_store.read_state(OPERATING_INTENT_SOURCE_STATUS_KEY)
    assert status is not None
    assert status["status"] == "rejected"
    assert status["reason"] == "source_validation_failed"
    # The prior, good, complete projection is untouched.
    assert await store.get_object("change-window-1") is not None


async def test_duplicate_instance_is_rejected(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-intent-source.json"
    document = _document(extra_service_objectives=1)
    _write(path, document)

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=_env(path, document),
        now=_VALIDATION_NOW,
    )

    assert result is None
    status = await status_store.read_state(OPERATING_INTENT_SOURCE_STATUS_KEY)
    assert status is not None
    assert status["status"] == "rejected"
    assert status["reason"] == "source_validation_failed"


async def test_stale_instance_is_rejected(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-intent-source.json"
    document = _document(change_window_effective_to="2026-08-27T06:00:00+00:00")
    _write(path, document)

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=_env(path, document),
        now=_VALIDATION_NOW,
    )

    assert result is None
    status = await status_store.read_state(OPERATING_INTENT_SOURCE_STATUS_KEY)
    assert status is not None
    assert status["status"] == "rejected"
    assert status["reason"] == "source_validation_failed"


async def test_long_lived_intent_from_a_current_retrieval_projects(tmp_path: Path) -> None:
    """A years-old but still effective objective is fresh when the source was just read."""

    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-intent-source.json"
    document = _document(service_objective_effective_from="2020-01-01T00:00:00+00:00")
    _write(path, document)

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=_env(path, document),
        now=_VALIDATION_NOW,
    )

    assert result is not None
    assert await store.get_object("service-objective-1") is not None


async def test_stale_retrieval_of_a_newly_effective_intent_is_rejected(tmp_path: Path) -> None:
    """Freshness is judged from the pinned retrieval time, not from effective_from."""

    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-intent-source.json"
    document = _document(
        service_objective_effective_from="2026-08-27T11:59:00+00:00",
        retrieved_at="2026-08-24T12:00:00+00:00",
    )
    _write(path, document)

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=_env(path, document),
        now=_VALIDATION_NOW,
    )

    assert result is None
    status = await status_store.read_state(OPERATING_INTENT_SOURCE_STATUS_KEY)
    assert status is not None
    assert status["status"] == "rejected"
    assert status["reason"] == "source_validation_failed"
    assert await store.get_object("service-objective-1") is None


async def test_below_pinned_instance_count_is_rejected(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-intent-source.json"
    document = _document()
    _write(path, document)
    env = _env(path, document)
    env["FDAI_OPERATING_INTENT_SOURCE_EXPECTED_COUNTS_JSON"] = json.dumps({"ServiceObjective": 2})

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=env,
        now=_VALIDATION_NOW,
    )

    assert result is None
    status = await status_store.read_state(OPERATING_INTENT_SOURCE_STATUS_KEY)
    assert status is not None
    assert status["status"] == "rejected"
    assert status["reason"] == "source_validation_failed"


async def test_rewritten_provenance_url_is_rejected(tmp_path: Path) -> None:
    """The pinned digest covers provenance, so rewriting attribution fails closed."""

    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-intent-source.json"
    original = _document()
    env = _env(path, original)
    rewritten = _document()
    provenance = rewritten["provenance"]
    assert isinstance(provenance, dict)
    provenance["source_url"] = "https://example.invalid/other-operating-intent-source"
    _write(path, rewritten)

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=env,
        now=_VALIDATION_NOW,
    )

    assert result is None
    status = await status_store.read_state(OPERATING_INTENT_SOURCE_STATUS_KEY)
    assert status is not None
    assert status["status"] == "rejected"
    assert status["reason"] == "source_validation_failed"


async def test_cross_release_revision_mismatch_is_rejected(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-intent-source.json"
    document = _document()
    _write(path, document)
    env = _env(path, document)
    env["FDAI_OPERATING_INTENT_SOURCE_REVISION"] = "operating-intent-revision-mismatch"

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=env,
    )

    assert result is None
    status = await status_store.read_state(OPERATING_INTENT_SOURCE_STATUS_KEY)
    assert status is not None
    assert status["status"] == "rejected"
    assert status["reason"] == "source_validation_failed"


async def test_cross_release_provenance_mismatch_is_rejected(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-intent-source.json"
    document = _document(resolved_ref="operating-intent-revision-mismatch")
    _write(path, document)

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=_env(path, document),
        now=_VALIDATION_NOW,
    )

    assert result is None
    status = await status_store.read_state(OPERATING_INTENT_SOURCE_STATUS_KEY)
    assert status is not None
    assert status["status"] == "rejected"
    assert status["reason"] == "source_validation_failed"


async def test_tampered_content_digest_is_rejected(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-intent-source.json"
    original = _document()
    env = _env(path, original)
    tampered = _document(extra_service_objectives=1)
    _write(path, tampered)

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=env,
    )

    assert result is None
    status = await status_store.read_state(OPERATING_INTENT_SOURCE_STATUS_KEY)
    assert status is not None
    assert status["status"] == "rejected"
    assert status["reason"] == "source_validation_failed"


async def test_configured_path_without_revision_raises(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    path = tmp_path / "operating-intent-source.json"
    document = _document()
    _write(path, document)

    with pytest.raises(RuntimeError, match="FDAI_OPERATING_INTENT_SOURCE_REVISION"):
        await project_operating_intent_source_from_env(
            store=store,
            object_types=catalog.object_types,
            link_types=catalog.link_types,
            env={
                "FDAI_OPERATING_INTENT_SOURCE_PATH": str(path),
                "FDAI_OPERATING_INTENT_SOURCE_SHA256": _digest_of(document),
            },
        )


async def test_configured_path_without_store_raises(tmp_path: Path) -> None:
    path = tmp_path / "operating-intent-source.json"
    document = _document()
    _write(path, document)

    with pytest.raises(RuntimeError, match="requires an ontology instance store"):
        await project_operating_intent_source_from_env(
            store=None,
            object_types=(),
            link_types=(),
            env=_env(path, document),
            now=_VALIDATION_NOW,
        )


async def test_malformed_expected_counts_json_raises(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    path = tmp_path / "operating-intent-source.json"
    document = _document()
    _write(path, document)
    env = _env(path, document)
    env["FDAI_OPERATING_INTENT_SOURCE_EXPECTED_COUNTS_JSON"] = "not-json"

    with pytest.raises(RuntimeError, match="EXPECTED_COUNTS_JSON"):
        await project_operating_intent_source_from_env(
            store=store,
            object_types=catalog.object_types,
            link_types=catalog.link_types,
            env=env,
            now=_VALIDATION_NOW,
        )


async def test_unconfigured_clears_previously_projected_instances(tmp_path: Path) -> None:
    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    path = tmp_path / "operating-intent-source.json"
    document = _document()
    _write(path, document)
    await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env=_env(path, document),
        now=_VALIDATION_NOW,
    )
    assert await store.get_object("service-objective-1") is not None

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env={},
    )

    assert result is None
    assert await store.get_object("service-objective-1") is None
    assert await status_store.read_state(OPERATING_INTENT_SOURCE_STATUS_KEY) == {
        "schema_version": "1.0.0",
        "status": "unconfigured",
    }


async def test_shipped_generic_source_projects_through_the_real_catalog(tmp_path: Path) -> None:
    """The artifact the Core image ships must actually project, not just parse.

    Instance validation happens at the store write boundary, so a property the ontology
    catalog does not declare - or a required one the artifact omits - would only surface
    here. Copying the tracked file keeps the check on the exact bytes the image carries.
    """

    from fdai.delivery.operating_model.json_file import (
        operating_intent_source_document_from_mapping,
    )
    from fdai.shared.providers.operating_model import (
        operating_intent_source_document_digest,
    )

    catalog, store = _catalog_and_store()
    status_store = InMemoryStateStore()
    source = REPO_ROOT / "config/operating-intent/generic-source.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    path = tmp_path / "generic-source.json"
    _write(path, document)
    parsed = operating_intent_source_document_from_mapping(document)

    result = await project_operating_intent_source_from_env(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        status_store=status_store,
        env={
            "FDAI_OPERATING_INTENT_SOURCE_PATH": str(path),
            "FDAI_OPERATING_INTENT_SOURCE_REVISION": parsed.snapshot.source_revision,
            "FDAI_OPERATING_INTENT_SOURCE_SHA256": operating_intent_source_document_digest(parsed),
        },
        now=datetime.now(UTC),
    )

    assert result is not None
    assert result.object_count == 6
    projected = {
        record.object_type
        for record in parsed.snapshot.objects
        if await store.get_object(record.id) is not None
    }
    assert projected == {
        "ArchitectureConstraint",
        "ChangeWindow",
        "CostObjective",
        "Ownership",
        "RecoveryObjective",
        "ServiceObjective",
    }
