"""Deterministic Rule semantic manifests and licensing-aware surfaces."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable

from fdai.rule_catalog.schema.rego_semantics import RegoSemantics, property_ref
from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    RuleCorpus,
    RuleSemanticManifest,
    RuleSemanticSurface,
    SurfaceOrigin,
)
from fdai.shared.contracts.models import CheckLogicKind, Redistribution, Rule

_DIGEST = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$")


def build_rego_semantic_manifest(
    rule: Rule,
    semantics: RegoSemantics,
    *,
    ontology_release_digest: str,
    parser_version: str = "1.0.0",
) -> RuleSemanticManifest:
    """Build an active manifest only when OPA AST and Rule metadata agree."""

    if rule.check_logic.kind is not CheckLogicKind.REGO:
        raise ValueError("Rego semantic manifest requires check_logic.kind=rego")
    if semantics.rule_id != rule.id:
        raise ValueError("Rego semantic manifest Rule identity mismatch")
    ast_property_refs = tuple(
        sorted(property_ref(rule.resource_type, path) for path in semantics.property_paths)
    )
    declared_property_refs = _concrete_refs(rule.evaluates)
    if ast_property_refs != declared_property_refs:
        raise ValueError("Rego semantic manifest property references drift from OPA AST")
    return RuleSemanticManifest(
        rule_id=rule.id,
        rule_version=str(rule.version),
        corpus=RuleCorpus.ACTIVE,
        policy_ref=rule.check_logic.reference,
        policy_digest=_as_digest(semantics.content_digest),
        source_content_digest=_as_digest(rule.provenance.content_hash),
        parser_id="opa-ast",
        parser_version=parser_version,
        redistribution=rule.provenance.redistribution,
        resource_type=rule.resource_type,
        ontology_release_digest=ontology_release_digest,
        signal_refs=_concrete_refs(rule.triggered_by),
        property_refs=declared_property_refs,
        action_type_ref=rule.remediates,
    )


def build_expression_semantic_manifest(
    rule: Rule,
    *,
    ontology_release_digest: str,
    parser_id: str,
    parser_version: str,
) -> RuleSemanticManifest:
    """Build a discovery manifest without inventing missing expression semantics."""

    if rule.check_logic.kind is not CheckLogicKind.EXPRESSION:
        raise ValueError("expression semantic manifest requires check_logic.kind=expression")
    return RuleSemanticManifest(
        rule_id=rule.id,
        rule_version=str(rule.version),
        corpus=RuleCorpus.DISCOVERY,
        policy_ref=rule.check_logic.reference,
        policy_digest=_digest_text(rule.check_logic.reference),
        source_content_digest=_as_digest(rule.provenance.content_hash),
        parser_id=parser_id,
        parser_version=parser_version,
        redistribution=rule.provenance.redistribution,
        resource_type=rule.resource_type,
        ontology_release_digest=ontology_release_digest,
        signal_refs=_concrete_refs(rule.triggered_by),
        property_refs=_concrete_refs(rule.evaluates),
        action_type_ref=rule.remediates,
    )


def build_surface_candidate(
    manifest: RuleSemanticManifest,
    *,
    surface_id: str,
    locale: str,
    origin: SurfaceOrigin,
    intent_ids: Iterable[str],
    concept_refs: Iterable[str],
    aliases: Iterable[str],
    training_queries: Iterable[str],
    hard_negative_queries: Iterable[str],
    producer_ref: str,
    evidence_refs: Iterable[str],
    prompt_digest: str | None = None,
    raw_source_text_used: bool = False,
) -> RuleSemanticSurface:
    """Create an inert surface and reject unlicensed raw-source derivation."""

    if raw_source_text_used and manifest.redistribution is Redistribution.REFERENCE_ONLY:
        raise ValueError("reference-only raw source text MUST NOT feed semantic enrichment")
    return RuleSemanticSurface(
        surface_id=surface_id,
        manifest_digest=manifest.digest,
        locale=locale,
        origin=origin,
        intent_ids=_ordered(intent_ids),
        concept_refs=_ordered(concept_refs),
        aliases=_ordered(aliases),
        training_queries=_ordered(training_queries),
        hard_negative_queries=_ordered(hard_negative_queries),
        producer_ref=producer_ref,
        evidence_refs=_ordered(evidence_refs),
        prompt_digest=prompt_digest,
    )


def _concrete_refs(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value != "*"}))


def _ordered(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _as_digest(value: str) -> str:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError("semantic manifest source digest is invalid")
    return value if value.startswith("sha256:") else f"sha256:{value}"


def _digest_text(value: str) -> str:
    encoded = json.dumps(value, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "build_expression_semantic_manifest",
    "build_rego_semantic_manifest",
    "build_surface_candidate",
]
