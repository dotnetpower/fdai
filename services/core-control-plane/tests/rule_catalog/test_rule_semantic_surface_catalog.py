from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    CohortMetric,
    RuleCorpus,
    RuleSemanticManifest,
    RuleSemanticSurface,
    SurfaceOrigin,
    SurfaceValidationReceipt,
    ValidationDecision,
)
from fdai.rule_catalog.schema.rule_semantic_surface_catalog import (
    SemanticSurfaceCatalogError,
    load_promoted_semantic_surfaces,
)
from fdai.shared.contracts.models import Redistribution

_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64


def _manifest() -> RuleSemanticManifest:
    return RuleSemanticManifest(
        rule_id="rule.one",
        rule_version="1.0.0",
        corpus=RuleCorpus.ACTIVE,
        policy_ref="policies/rule.rego",
        policy_digest=_A,
        source_content_digest=_B,
        parser_id="opa-ast",
        parser_version="1.0.0",
        redistribution=Redistribution.EMBEDDABLE,
        resource_type="object-storage",
        ontology_release_digest=_A,
        signal_refs=("resource.configuration.observed",),
        property_refs=("property.object-storage.public_access",),
        action_type_ref="remediate.disable-public-access",
    )


def _surface(manifest: RuleSemanticManifest, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1.0.0",
        "surface_id": "surface.rule-one.en",
        "manifest_digest": manifest.digest,
        "locale": "en",
        "origin": "authored",
        "intent_ids": ["prevent-public-access"],
        "concept_refs": ["concept.public-access"],
        "aliases": ["block public access"],
        "training_queries": ["Which Rule blocks public storage?"],
        "hard_negative_queries": ["Which Rule enables versioning?"],
        "producer_ref": "catalog:reviewed",
        "evidence_refs": ["rule:rule.one@1.0.0"],
        "state": "promoted",
        "validation_receipt_digest": _B,
    }
    value.update(overrides)
    return value


def _write(root: Path, name: str, value: dict[str, object]) -> None:
    (root / name).write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _receipt(manifest: RuleSemanticManifest, **overrides: object) -> SurfaceValidationReceipt:
    candidate = RuleSemanticSurface(
        surface_id="surface.rule-one.en",
        manifest_digest=manifest.digest,
        locale="en",
        origin=SurfaceOrigin.AUTHORED,
        intent_ids=("prevent-public-access",),
        concept_refs=("concept.public-access",),
        aliases=("block public access",),
        training_queries=("Which Rule blocks public storage?",),
        hard_negative_queries=("Which Rule enables versioning?",),
        producer_ref="catalog:reviewed",
        evidence_refs=("rule:rule.one@1.0.0",),
    )
    values: dict[str, object] = {
        "surface_digest": candidate.validation_subject_digest,
        "generation_digest": _A,
        "catalog_digest": _B,
        "dataset_digest": _A,
        "evaluator_ref": "heimdall:test@1",
        "evaluation_policy_digest": _A,
        "training_query_digests": (_A,),
        "evaluation_query_digests": (_B,),
        "cohort_metrics": (
            CohortMetric(
                cohort="en-exact",
                metric="recall-at-5",
                value=1.0,
                sample_count=1,
            ),
        ),
        "failure_codes": (),
        "decision": ValidationDecision.PASS,
    }
    values.update(overrides)
    return SurfaceValidationReceipt(**values)  # type: ignore[arg-type]


def _load(
    root: Path,
    manifest: RuleSemanticManifest,
    receipt: SurfaceValidationReceipt,
    *,
    evaluation_policy_digest: str = _A,
) -> tuple[RuleSemanticSurface, ...]:
    return load_promoted_semantic_surfaces(
        root,
        manifests={manifest.rule_id: manifest},
        validation_receipts={receipt.digest: receipt},
        evaluation_policy_digest=evaluation_policy_digest,
    )


def test_promoted_surface_loads_against_exact_manifest(tmp_path: Path) -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    _write(
        tmp_path,
        "surface.yaml",
        _surface(manifest, validation_receipt_digest=receipt.digest),
    )

    loaded = _load(tmp_path, manifest, receipt)

    assert loaded[0].state.value == "promoted"
    assert loaded[0].execution_authority is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"state": "candidate"}, "promoted"),
        ({"manifest_digest": _B}, "unknown manifest"),
        ({"unexpected": True}, "Additional properties"),
    ),
)
def test_surface_catalog_rejects_unpromoted_unknown_or_extra_fields(
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    _write(
        tmp_path,
        "surface.yaml",
        _surface(manifest, validation_receipt_digest=receipt.digest, **overrides),
    )

    with pytest.raises(SemanticSurfaceCatalogError, match=message):
        _load(tmp_path, manifest, receipt)


def test_surface_catalog_rejects_duplicate_ids(tmp_path: Path) -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    value = _surface(manifest, validation_receipt_digest=receipt.digest)
    _write(tmp_path, "left.yaml", value)
    _write(tmp_path, "right.yaml", value)

    with pytest.raises(SemanticSurfaceCatalogError, match="duplicate surface_id"):
        _load(tmp_path, manifest, receipt)


def test_surface_catalog_rejects_missing_receipt(tmp_path: Path) -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    _write(
        tmp_path,
        "surface.yaml",
        _surface(manifest, validation_receipt_digest=receipt.digest),
    )

    with pytest.raises(SemanticSurfaceCatalogError, match="missing validation receipt"):
        load_promoted_semantic_surfaces(
            tmp_path,
            manifests={manifest.rule_id: manifest},
            validation_receipts={},
            evaluation_policy_digest=_A,
        )


@pytest.mark.parametrize(
    ("receipt", "policy_digest", "message"),
    (
        ("wrong-subject", _A, "subject mismatch"),
        ("current", _B, "policy is stale"),
    ),
)
def test_surface_catalog_rejects_wrong_subject_or_stale_policy(
    tmp_path: Path,
    receipt: str,
    policy_digest: str,
    message: str,
) -> None:
    manifest = _manifest()
    current = _receipt(manifest)
    bound = replace(current, surface_digest=_B) if receipt == "wrong-subject" else current
    _write(
        tmp_path,
        "surface.yaml",
        _surface(manifest, validation_receipt_digest=bound.digest),
    )

    with pytest.raises(SemanticSurfaceCatalogError, match=message):
        _load(tmp_path, manifest, bound, evaluation_policy_digest=policy_digest)
