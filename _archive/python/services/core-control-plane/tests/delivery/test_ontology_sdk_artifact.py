from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.core.ontology_platform.sdk_codegen import GeneratedOntologySdk
from fdai.delivery.ontology_sdk_artifact import (
    OntologySdkPublicationScope,
    publish_ontology_sdk,
)
from fdai.shared.contracts.models import CeilingRole


def _sdk(
    *,
    release: str = "sha256:" + "a" * 64,
    objects: tuple[str, ...] = ("Workload",),
) -> GeneratedOntologySdk:
    manifest = {
        "release_digest": release,
        "object_types": list(objects),
        "action_types": ["ops.restart-service"],
        "functions": ["query.workloads"],
        "interfaces": {"Operable": {"concrete_types": list(objects)}},
        "write_surface": "proposal_only",
    }
    return GeneratedOntologySdk(
        release_digest=release,
        python="class Workload: ...\n",
        typescript="export interface Workload {}\n",
        manifest_json=json.dumps(manifest, sort_keys=True, separators=(",", ":")),
    )


def _scope() -> OntologySdkPublicationScope:
    return OntologySdkPublicationScope(
        scope_id="operator-read",
        purposes=("operations-review",),
        max_role=CeilingRole.READER,
    )


def test_publish_sdk_is_content_addressed_scoped_and_idempotent(tmp_path: Path) -> None:
    first = publish_ontology_sdk(sdk=_sdk(), scope=_scope(), root=tmp_path)
    second = publish_ontology_sdk(sdk=_sdk(), scope=_scope(), root=tmp_path)

    assert first.created is True
    assert second.created is False
    assert first.path == second.path
    manifest = json.loads((first.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scope"] == {
        "id": "operator-read",
        "purposes": ["operations-review"],
        "max_role": "reader",
    }
    assert manifest["write_surface"] == "proposal_only"
    assert set(path.name for path in first.path.iterdir()) == {
        "manifest.json",
        "ontology_sdk.py",
        "ontology_sdk.ts",
    }


def test_publish_sdk_rejects_existing_artifact_drift(tmp_path: Path) -> None:
    published = publish_ontology_sdk(sdk=_sdk(), scope=_scope(), root=tmp_path)
    (published.path / "ontology_sdk.py").write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact differs"):
        publish_ontology_sdk(sdk=_sdk(), scope=_scope(), root=tmp_path)


def test_publish_sdk_requires_migration_for_removed_declaration(tmp_path: Path) -> None:
    previous = publish_ontology_sdk(
        sdk=_sdk(objects=("Resource", "Workload")),
        scope=_scope(),
        root=tmp_path,
    )
    previous_manifest = json.loads((previous.path / "manifest.json").read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="requires migration_ref"):
        publish_ontology_sdk(
            sdk=_sdk(release="sha256:" + "b" * 64),
            scope=_scope(),
            root=tmp_path,
            previous_manifest=previous_manifest,
        )

    published = publish_ontology_sdk(
        sdk=_sdk(release="sha256:" + "b" * 64),
        scope=_scope(),
        root=tmp_path,
        previous_manifest=previous_manifest,
        migration_ref="migration:remove-resource:v1",
    )
    assert published.created is True


def test_publish_sdk_rejects_non_proposal_write_surface(tmp_path: Path) -> None:
    raw = json.loads(_sdk().manifest_json)
    raw["write_surface"] = "direct_execution"
    unsafe = _sdk().__class__(
        release_digest=_sdk().release_digest,
        python=_sdk().python,
        typescript=_sdk().typescript,
        manifest_json=json.dumps(raw),
    )

    with pytest.raises(ValueError, match="proposal_only"):
        publish_ontology_sdk(sdk=unsafe, scope=_scope(), root=tmp_path)
