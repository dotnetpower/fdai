"""Proof-carrying semantic candidates and verified plans.

Language models and embedding indexes may propose candidates. Only an exact
ontology release plus reviewed interpretation evidence can produce a verified
plan, and even a verified action interpretation remains proposal-only.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from fdai.shared.contracts.models import (
    ContractBase,
    OntologyDeclarationKind,
    OntologyRelease,
    OntologyTypeRef,
)

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_CONFIRMATION_REF = re.compile(r"^conversation-turn:[A-Za-z0-9._:-]{1,256}$")
_PROMOTION_REF = re.compile(r"^promotion:sha256:[a-f0-9]{64}$")


class InterpretationCandidateSource(StrEnum):
    """Non-authoritative mechanisms that may propose one interpretation."""

    LEXICAL = "lexical"
    EMBEDDING = "embedding"
    MODEL = "model"


class SemanticOperationClass(StrEnum):
    """Closed Data, Logic, and Action-facing semantic operations."""

    QUERY = "query"
    DERIVE = "derive"
    VALIDATE = "validate"
    ACTION_DRAFT = "action_draft"


class VerifiedInterpretationBasis(StrEnum):
    """Evidence classes allowed to promote a candidate into a verified plan."""

    EXACT_CATALOG = "exact_catalog"
    PROMOTED_SURFACE = "promoted_surface"
    OPERATOR_CONFIRMATION = "operator_confirmation"


class SemanticInterpretationCandidate(ContractBase):
    """One replayable interpretation proposal with no execution authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    source: InterpretationCandidateSource
    operation_class: SemanticOperationClass
    target_ref: OntologyTypeRef
    arguments_json: str
    semantic_catalog_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    input_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    unresolved_terms: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...] = ()
    authority: Literal["candidate_only"] = "candidate_only"
    candidate_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _candidate_is_canonical(self) -> SemanticInterpretationCandidate:
        if self.score is not None and not math.isfinite(self.score):
            raise ValueError("semantic candidate score MUST be finite")
        if len(self.unresolved_terms) != len(set(self.unresolved_terms)):
            raise ValueError("semantic candidate unresolved_terms MUST be unique")
        canonical_arguments = _parse_canonical_object(self.arguments_json)
        expected = _candidate_digest(
            source=self.source,
            operation_class=self.operation_class,
            target_ref=self.target_ref,
            arguments=canonical_arguments,
            semantic_catalog_digest=self.semantic_catalog_digest,
            input_digest=self.input_digest,
            score=self.score,
            unresolved_terms=self.unresolved_terms,
        )
        if self.candidate_digest != expected:
            raise ValueError("semantic candidate digest does not match its content")
        return self

    @property
    def arguments(self) -> dict[str, Any]:
        """Return a defensive JSON projection of immutable canonical arguments."""

        return _parse_canonical_object(self.arguments_json)


SemanticBasisValidator = Callable[
    [VerifiedInterpretationBasis, str, SemanticInterpretationCandidate],
    bool,
]


@runtime_checkable
class ActiveSemanticCatalog(Protocol):
    """Authoritative active catalog identity and exact-entry membership boundary."""

    @property
    def digest(self) -> str: ...

    def contains(self, candidate: SemanticInterpretationCandidate) -> bool: ...


class VerifiedSemanticPlan(ContractBase):
    """One ontology-pinned interpretation that still grants no execution authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    operation_class: SemanticOperationClass
    target_ref: OntologyTypeRef
    arguments_json: str
    ontology_release_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    semantic_catalog_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    input_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    candidate_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    basis: VerifiedInterpretationBasis
    basis_ref: Annotated[str, Field(min_length=1, max_length=512)]
    execution_authority: Literal[False] = False
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _plan_is_canonical(self) -> VerifiedSemanticPlan:
        canonical_arguments = _parse_canonical_object(self.arguments_json)
        expected = _plan_digest(
            operation_class=self.operation_class,
            target_ref=self.target_ref,
            arguments=canonical_arguments,
            ontology_release_digest=self.ontology_release_digest,
            semantic_catalog_digest=self.semantic_catalog_digest,
            input_digest=self.input_digest,
            candidate_digest=self.candidate_digest,
            basis=self.basis,
            basis_ref=self.basis_ref,
        )
        if self.plan_digest != expected:
            raise ValueError("verified semantic plan digest does not match its content")
        return self

    @property
    def arguments(self) -> dict[str, Any]:
        """Return a defensive JSON projection of immutable canonical arguments."""

        return _parse_canonical_object(self.arguments_json)


def build_semantic_candidate(
    *,
    source: InterpretationCandidateSource,
    operation_class: SemanticOperationClass,
    target_ref: OntologyTypeRef,
    arguments: dict[str, Any],
    semantic_catalog_digest: str,
    input_text: str,
    score: float | None,
    unresolved_terms: tuple[str, ...],
) -> SemanticInterpretationCandidate:
    """Build a canonical non-authoritative interpretation candidate."""

    if not input_text.strip():
        raise ValueError("semantic candidate input_text MUST be non-empty")
    canonical_arguments = _canonical_object(arguments)
    arguments_json = _canonical_json(canonical_arguments)
    input_digest = _digest(input_text)
    candidate_digest = _candidate_digest(
        source=source,
        operation_class=operation_class,
        target_ref=target_ref,
        arguments=canonical_arguments,
        semantic_catalog_digest=semantic_catalog_digest,
        input_digest=input_digest,
        score=score,
        unresolved_terms=unresolved_terms,
    )
    return SemanticInterpretationCandidate(
        source=source,
        operation_class=operation_class,
        target_ref=target_ref,
        arguments_json=arguments_json,
        semantic_catalog_digest=semantic_catalog_digest,
        input_digest=input_digest,
        score=score,
        unresolved_terms=unresolved_terms,
        candidate_digest=candidate_digest,
    )


def verify_semantic_candidate(
    candidate: SemanticInterpretationCandidate,
    *,
    release: OntologyRelease,
    active_semantic_catalog: ActiveSemanticCatalog,
    basis: VerifiedInterpretationBasis,
    basis_ref: str,
    basis_validator: SemanticBasisValidator | None = None,
) -> VerifiedSemanticPlan:
    """Verify exact type identity and interpretation evidence without granting execution."""

    if candidate.unresolved_terms:
        raise ValueError("semantic candidate has unresolved terms")
    if re.fullmatch(_DIGEST_PATTERN, active_semantic_catalog.digest) is None:
        raise ValueError("active semantic catalog digest is invalid")
    if candidate.semantic_catalog_digest != active_semantic_catalog.digest:
        raise ValueError("semantic candidate targets a stale semantic catalog")
    expected_candidate_digest = _candidate_digest(
        source=candidate.source,
        operation_class=candidate.operation_class,
        target_ref=candidate.target_ref,
        arguments=candidate.arguments,
        semantic_catalog_digest=candidate.semantic_catalog_digest,
        input_digest=candidate.input_digest,
        score=candidate.score,
        unresolved_terms=candidate.unresolved_terms,
    )
    if candidate.candidate_digest != expected_candidate_digest:
        raise ValueError("semantic candidate integrity check failed")
    expected_ref = release.type_ref(candidate.target_ref.kind, candidate.target_ref.name)
    if candidate.target_ref != expected_ref:
        raise ValueError("semantic candidate targets a stale ontology release")
    _validate_operation_target(candidate.operation_class, candidate.target_ref.kind)
    _validate_basis(
        candidate,
        basis,
        basis_ref,
        active_semantic_catalog=active_semantic_catalog,
        basis_validator=basis_validator,
    )
    plan_digest = _plan_digest(
        operation_class=candidate.operation_class,
        target_ref=candidate.target_ref,
        arguments=candidate.arguments,
        ontology_release_digest=release.digest,
        semantic_catalog_digest=candidate.semantic_catalog_digest,
        input_digest=candidate.input_digest,
        candidate_digest=candidate.candidate_digest,
        basis=basis,
        basis_ref=basis_ref,
    )
    return VerifiedSemanticPlan(
        operation_class=candidate.operation_class,
        target_ref=candidate.target_ref,
        arguments_json=candidate.arguments_json,
        ontology_release_digest=release.digest,
        semantic_catalog_digest=candidate.semantic_catalog_digest,
        input_digest=candidate.input_digest,
        candidate_digest=candidate.candidate_digest,
        basis=basis,
        basis_ref=basis_ref,
        plan_digest=plan_digest,
    )


def _validate_operation_target(
    operation_class: SemanticOperationClass,
    target_kind: OntologyDeclarationKind,
) -> None:
    if operation_class is SemanticOperationClass.ACTION_DRAFT:
        if target_kind is not OntologyDeclarationKind.ACTION:
            raise ValueError("action_draft semantic plan MUST target an action declaration")
        return
    if target_kind is not OntologyDeclarationKind.FUNCTION:
        raise ValueError(
            f"{operation_class.value} semantic plan MUST target a function declaration"
        )


def _validate_basis(
    candidate: SemanticInterpretationCandidate,
    basis: VerifiedInterpretationBasis,
    basis_ref: str,
    *,
    active_semantic_catalog: ActiveSemanticCatalog,
    basis_validator: SemanticBasisValidator | None,
) -> None:
    prefixes = {
        VerifiedInterpretationBasis.EXACT_CATALOG: "catalog:",
        VerifiedInterpretationBasis.PROMOTED_SURFACE: "promotion:",
        VerifiedInterpretationBasis.OPERATOR_CONFIRMATION: "conversation-turn:",
    }
    if not basis_ref.startswith(prefixes[basis]):
        raise ValueError("verified semantic plan basis_ref does not match basis")
    if basis is VerifiedInterpretationBasis.EXACT_CATALOG:
        if candidate.source is not InterpretationCandidateSource.LEXICAL:
            raise ValueError("exact catalog verification requires a lexical candidate")
        if basis_ref != f"catalog:{candidate.semantic_catalog_digest}":
            raise ValueError("exact catalog verification requires the candidate catalog digest")
        if not active_semantic_catalog.contains(candidate):
            raise ValueError("exact catalog candidate is absent from the active catalog")
        return
    pattern = (
        _PROMOTION_REF
        if basis is VerifiedInterpretationBasis.PROMOTED_SURFACE
        else _CONFIRMATION_REF
    )
    if pattern.fullmatch(basis_ref) is None:
        raise ValueError("verified semantic plan basis_ref is invalid")
    if basis_validator is None or not basis_validator(basis, basis_ref, candidate):
        raise ValueError("verified semantic plan basis evidence is unavailable")


def _candidate_digest(
    *,
    source: InterpretationCandidateSource,
    operation_class: SemanticOperationClass,
    target_ref: OntologyTypeRef,
    arguments: dict[str, Any],
    semantic_catalog_digest: str,
    input_digest: str,
    score: float | None,
    unresolved_terms: tuple[str, ...],
) -> str:
    return _digest(
        {
            "source": source.value,
            "operation_class": operation_class.value,
            "target_ref": target_ref.model_dump(mode="json"),
            "arguments": arguments,
            "semantic_catalog_digest": semantic_catalog_digest,
            "input_digest": input_digest,
            "score": score,
            "unresolved_terms": list(unresolved_terms),
        }
    )


def _plan_digest(
    *,
    operation_class: SemanticOperationClass,
    target_ref: OntologyTypeRef,
    arguments: dict[str, Any],
    ontology_release_digest: str,
    semantic_catalog_digest: str,
    input_digest: str,
    candidate_digest: str,
    basis: VerifiedInterpretationBasis,
    basis_ref: str,
) -> str:
    return _digest(
        {
            "operation_class": operation_class.value,
            "target_ref": target_ref.model_dump(mode="json"),
            "arguments": arguments,
            "ontology_release_digest": ontology_release_digest,
            "semantic_catalog_digest": semantic_catalog_digest,
            "input_digest": input_digest,
            "candidate_digest": candidate_digest,
            "basis": basis.value,
            "basis_ref": basis_ref,
            "execution_authority": False,
        }
    )


def _canonical_object(value: object) -> dict[str, Any]:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError("semantic plan arguments MUST be canonical JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("semantic plan arguments MUST be an object")
    return decoded


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("semantic plan arguments MUST be canonical JSON") from exc


def _parse_canonical_object(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("semantic plan arguments_json MUST be valid JSON") from exc
    canonical = _canonical_object(decoded)
    if value != _canonical_json(canonical):
        raise ValueError("semantic plan arguments_json MUST be canonical JSON")
    return canonical


def _digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("semantic plan value MUST be canonical JSON") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "InterpretationCandidateSource",
    "SemanticInterpretationCandidate",
    "SemanticBasisValidator",
    "SemanticOperationClass",
    "VerifiedInterpretationBasis",
    "VerifiedSemanticPlan",
    "build_semantic_candidate",
    "verify_semantic_candidate",
]
