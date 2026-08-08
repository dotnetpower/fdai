from __future__ import annotations

import pytest
from fdai.rule_catalog.schema.rego_semantics import RegoSemantics
from fdai.rule_catalog.schema.rule_semantic_manifest import (
    build_expression_semantic_manifest,
    build_rego_semantic_manifest,
    build_surface_candidate,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus, SurfaceOrigin
from fdai.shared.contracts.models import Rule

_RELEASE = "sha256:" + "a" * 64


def _rule(*, kind: str = "rego", redistribution: str = "embeddable") -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "2.0.0",
            "id": "object-storage.public-access.deny",
            "version": "1.0.0",
            "source": "custom",
            "severity": "high",
            "category": "security",
            "resource_type": "object-storage",
            "applies_to": ["object-storage"],
            "triggered_by": (["resource.configuration.observed"] if kind == "rego" else ["*"]),
            "evaluates": (["property.object-storage.public_access"] if kind == "rego" else ["*"]),
            "check_logic": {
                "kind": kind,
                "reference": (
                    "policies/object_storage/public_access.rego"
                    if kind == "rego"
                    else "azure-policy://public-access"
                ),
            },
            "remediation": {"template_ref": "remediation/public-access.tftpl"},
            "remediates": "remediate.disable-public-access",
            "provenance": {
                "source_url": "https://example.com/control",
                "resolved_ref": "source-revision",
                "content_hash": "sha256:" + "b" * 64,
                "license": "MIT",
                "redistribution": redistribution,
                "retrieved_at": "2026-08-06T00:00:00Z",
            },
        }
    )


def _semantics(*, property_paths: tuple[str, ...] = ("public_access",)) -> RegoSemantics:
    return RegoSemantics(
        package="fdai.object_storage.public_access",
        rule_id="object-storage.public-access.deny",
        title="Deny public access",
        description="Detect public object storage access.",
        severity="high",
        category="security",
        property_paths=property_paths,
        content_digest="c" * 64,
    )


def test_rego_manifest_pins_exact_ast_semantics() -> None:
    manifest = build_rego_semantic_manifest(
        _rule(),
        _semantics(),
        ontology_release_digest=_RELEASE,
    )

    assert manifest.corpus is RuleCorpus.ACTIVE
    assert manifest.property_refs == ("property.object-storage.public_access",)
    assert manifest.policy_digest == "sha256:" + "c" * 64
    assert manifest.digest == manifest.digest


def test_rego_manifest_rejects_property_drift() -> None:
    with pytest.raises(ValueError, match="drift"):
        build_rego_semantic_manifest(
            _rule(),
            _semantics(property_paths=("other",)),
            ontology_release_digest=_RELEASE,
        )


def test_expression_manifest_preserves_unknown_refs_in_discovery() -> None:
    manifest = build_expression_semantic_manifest(
        _rule(kind="expression"),
        ontology_release_digest=_RELEASE,
        parser_id="azure-policy-json",
        parser_version="1.0.0",
    )

    assert manifest.corpus is RuleCorpus.DISCOVERY
    assert manifest.signal_refs == ()
    assert manifest.property_refs == ()


def test_active_manifest_rejects_unknown_dispatch_refs() -> None:
    rule = _rule()
    rule.triggered_by.clear()

    with pytest.raises(ValueError, match="signal_refs"):
        build_rego_semantic_manifest(rule, _semantics(), ontology_release_digest=_RELEASE)


def test_reference_only_raw_text_cannot_feed_surface_generation() -> None:
    manifest = build_rego_semantic_manifest(
        _rule(redistribution="reference-only"),
        _semantics(),
        ontology_release_digest=_RELEASE,
    )

    with pytest.raises(ValueError, match="reference-only"):
        build_surface_candidate(
            manifest,
            surface_id="surface.public-access.en",
            locale="en",
            origin=SurfaceOrigin.GENERATED,
            intent_ids=("prevent-public-access",),
            concept_refs=("object-storage",),
            aliases=("block public access",),
            training_queries=("Which rule blocks public access?",),
            hard_negative_queries=("Which rule enables versioning?",),
            producer_ref="model:enricher@1",
            evidence_refs=("rule:public-access@1",),
            prompt_digest="sha256:" + "d" * 64,
            raw_source_text_used=True,
        )


def test_independently_authored_surface_remains_candidate_only() -> None:
    manifest = build_rego_semantic_manifest(
        _rule(redistribution="reference-only"),
        _semantics(),
        ontology_release_digest=_RELEASE,
    )
    surface = build_surface_candidate(
        manifest,
        surface_id="surface.public-access.en",
        locale="en",
        origin=SurfaceOrigin.AUTHORED,
        intent_ids=("prevent-public-access",),
        concept_refs=("object-storage",),
        aliases=("block public access",),
        training_queries=("Which rule blocks public access?",),
        hard_negative_queries=("Which rule enables versioning?",),
        producer_ref="catalog:maintainer-reviewed",
        evidence_refs=("rule:public-access@1",),
    )

    assert surface.execution_authority is False
    assert surface.state.value == "candidate"
