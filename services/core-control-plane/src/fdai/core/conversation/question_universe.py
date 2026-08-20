"""Deterministic finite question universes derived from query manifests."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fdai.core.conversation.epistemic_coverage import QuestionUniverseReceipt
from fdai.core.conversation.question_perspectives import (
    QuestionAnchorKind,
    QuestionCapabilityFamily,
    QuestionCausalResult,
    QuestionEntityState,
    QuestionEvidencePosture,
    QuestionExpectedPosture,
    QuestionInvestigationPosture,
    QuestionPerspective,
    QuestionPerspectiveApplication,
    QuestionPresentationShape,
    QuestionRuleState,
    QuestionTemporalState,
    expected_question_posture,
    perspective_applications,
)
from fdai.core.ontology_platform.query_manifest import QueryManifest

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_LOCALE_PATTERN = re.compile(r"[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-[A-Z]{2}|-[0-9]{3})?")
_MAX_CASES = 10_000
_MAX_PATH_DEPTH = 16
_MAX_RESULT_BOUND = 100_000


class QuestionCaseClass(StrEnum):
    """Canonical behavioral classes generated for each readable descriptor."""

    POSITIVE = "positive"
    ZERO_MATCH = "zero_match"
    BOUNDARY = "boundary"
    ACCESS_FILTERED = "access_filtered"


class QuestionExclusionReason(StrEnum):
    """Reviewed reasons that keep unavailable declarations in the denominator."""

    RUNTIME_BINDING_UNAVAILABLE = "runtime_binding_unavailable"


@dataclass(frozen=True, slots=True)
class QuestionUniverseGrammar:
    """Bounded canonical axes used to expand each readable descriptor."""

    locales: tuple[str, ...]
    case_classes: tuple[QuestionCaseClass, ...]
    evidence_postures: tuple[QuestionEvidencePosture, ...]
    path_depths: tuple[int, ...]
    result_bounds: tuple[int, ...]
    entity_states: tuple[QuestionEntityState, ...]
    temporal_states: tuple[QuestionTemporalState, ...]
    causal_results: tuple[QuestionCausalResult, ...]
    presentation_shapes: tuple[QuestionPresentationShape, ...]
    max_cases: int
    digest: str

    def __post_init__(self) -> None:
        if not self.locales or self.locales != tuple(sorted(set(self.locales))):
            raise ValueError("question grammar locales MUST be non-empty, unique, and ordered")
        if any(_LOCALE_PATTERN.fullmatch(locale) is None for locale in self.locales):
            raise ValueError("question grammar locales MUST be canonical and bounded")
        if self.case_classes != tuple(sorted(set(self.case_classes), key=lambda item: item.value)):
            raise ValueError("question grammar case classes MUST be unique and ordered")
        if not self.case_classes:
            raise ValueError("question grammar case classes MUST be non-empty")
        if self.evidence_postures != tuple(
            sorted(set(self.evidence_postures), key=lambda item: item.value)
        ):
            raise ValueError("question grammar evidence postures MUST be unique and ordered")
        if not self.evidence_postures:
            raise ValueError("question grammar evidence postures MUST be non-empty")
        _require_bounded_axis("path depths", self.path_depths, maximum=_MAX_PATH_DEPTH)
        _require_bounded_axis("result bounds", self.result_bounds, maximum=_MAX_RESULT_BOUND)
        _require_enum_axis("entity states", self.entity_states)
        _require_enum_axis("temporal states", self.temporal_states)
        _require_enum_axis("causal results", self.causal_results)
        _require_enum_axis("presentation shapes", self.presentation_shapes)
        if not 1 <= self.max_cases <= _MAX_CASES:
            raise ValueError(f"question grammar max_cases MUST be in [1, {_MAX_CASES}]")
        _require_digest("question grammar digest", self.digest)
        if self.digest != _digest(self._body()):
            raise ValueError("question grammar digest does not match its content")

    @classmethod
    def build(
        cls,
        *,
        locales: Sequence[str],
        case_classes: Sequence[QuestionCaseClass] = tuple(QuestionCaseClass),
        evidence_postures: Sequence[QuestionEvidencePosture] = (QuestionEvidencePosture.FRESH,),
        path_depths: Sequence[int] = (1,),
        result_bounds: Sequence[int] = (100,),
        entity_states: Sequence[QuestionEntityState] = (QuestionEntityState.EXACT,),
        temporal_states: Sequence[QuestionTemporalState] = (QuestionTemporalState.ALIGNED,),
        causal_results: Sequence[QuestionCausalResult] = (QuestionCausalResult.COMPETING,),
        presentation_shapes: Sequence[QuestionPresentationShape] = (
            QuestionPresentationShape.TABLE,
        ),
        max_cases: int = _MAX_CASES,
    ) -> QuestionUniverseGrammar:
        """Build an order-independent, content-addressed grammar."""

        ordered_locales = tuple(sorted(set(locales)))
        ordered_case_classes = tuple(sorted(set(case_classes), key=lambda item: item.value))
        ordered_evidence_postures = tuple(
            sorted(set(evidence_postures), key=lambda item: item.value)
        )
        ordered_path_depths = tuple(sorted(set(path_depths)))
        ordered_result_bounds = tuple(sorted(set(result_bounds)))
        ordered_entity_states = tuple(sorted(set(entity_states), key=lambda item: item.value))
        ordered_temporal_states = tuple(sorted(set(temporal_states), key=lambda item: item.value))
        ordered_causal_results = tuple(sorted(set(causal_results), key=lambda item: item.value))
        ordered_presentation_shapes = tuple(
            sorted(set(presentation_shapes), key=lambda item: item.value)
        )
        body = {
            "schema_version": "1.0.0",
            "locales": ordered_locales,
            "case_classes": tuple(item.value for item in ordered_case_classes),
            "evidence_postures": tuple(item.value for item in ordered_evidence_postures),
            "path_depths": ordered_path_depths,
            "result_bounds": ordered_result_bounds,
            "entity_states": tuple(item.value for item in ordered_entity_states),
            "temporal_states": tuple(item.value for item in ordered_temporal_states),
            "causal_results": tuple(item.value for item in ordered_causal_results),
            "presentation_shapes": tuple(item.value for item in ordered_presentation_shapes),
            "max_cases": max_cases,
        }
        return cls(
            locales=ordered_locales,
            case_classes=ordered_case_classes,
            evidence_postures=ordered_evidence_postures,
            path_depths=ordered_path_depths,
            result_bounds=ordered_result_bounds,
            entity_states=ordered_entity_states,
            temporal_states=ordered_temporal_states,
            causal_results=ordered_causal_results,
            presentation_shapes=ordered_presentation_shapes,
            max_cases=max_cases,
            digest=_digest(body),
        )

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "locales": self.locales,
            "case_classes": tuple(item.value for item in self.case_classes),
            "evidence_postures": tuple(item.value for item in self.evidence_postures),
            "path_depths": self.path_depths,
            "result_bounds": self.result_bounds,
            "entity_states": tuple(item.value for item in self.entity_states),
            "temporal_states": tuple(item.value for item in self.temporal_states),
            "causal_results": tuple(item.value for item in self.causal_results),
            "presentation_shapes": tuple(item.value for item in self.presentation_shapes),
            "max_cases": self.max_cases,
        }

    def variants_for(self, perspective: QuestionPerspective) -> int:
        """Return the exact non-Cartesian multiplier for one perspective."""

        base = (
            len(self.locales)
            * len(self.case_classes)
            * len(self.evidence_postures)
            * len(self.path_depths)
            * len(self.result_bounds)
        )
        if perspective is not QuestionPerspective.CAUSAL:
            return base
        return (
            base
            * len(self.entity_states)
            * len(self.temporal_states)
            * len(self.causal_results)
            * len(self.presentation_shapes)
        )


@dataclass(frozen=True, slots=True)
class GeneratedQuestionCase:
    """One canonical executable case generated without mutation authority."""

    case_id: str
    principal_manifest_digest: str
    declaration_id: str
    declaration_digest: str
    locale: str
    case_class: QuestionCaseClass
    perspective: QuestionPerspective
    required_capability: QuestionCapabilityFamily
    evidence_posture: QuestionEvidencePosture
    anchor_kind: QuestionAnchorKind
    expected_posture: QuestionExpectedPosture
    action_posture: str
    path_depth: int
    result_bound: int
    rule_state: QuestionRuleState = QuestionRuleState.NOT_APPLICABLE
    entity_state: QuestionEntityState = QuestionEntityState.NOT_APPLICABLE
    temporal_state: QuestionTemporalState = QuestionTemporalState.NOT_APPLICABLE
    causal_result: QuestionCausalResult = QuestionCausalResult.NOT_APPLICABLE
    presentation_shape: QuestionPresentationShape = QuestionPresentationShape.DEFAULT


@dataclass(frozen=True, slots=True)
class QuestionCaseExclusion:
    """One canonical reason-bearing exclusion for an unavailable declaration."""

    case_id: str
    principal_manifest_digest: str
    declaration_id: str
    reason: QuestionExclusionReason


@dataclass(frozen=True, slots=True)
class GeneratedQuestionUniverse:
    """Generated records and the immutable release-gating denominator."""

    grammar: QuestionUniverseGrammar
    cases: tuple[GeneratedQuestionCase, ...]
    exclusions: tuple[QuestionCaseExclusion, ...]
    receipt: QuestionUniverseReceipt
    generation_digest: str


def generate_question_universe(
    *,
    manifests: Sequence[QueryManifest],
    grammar: QuestionUniverseGrammar,
) -> GeneratedQuestionUniverse:
    """Expand complete manifests into a bounded deterministic denominator."""

    ordered_manifests = tuple(sorted(manifests, key=lambda item: item.manifest_digest))
    if not ordered_manifests:
        raise ValueError("question universe requires at least one principal manifest")
    if len({item.manifest_digest for item in ordered_manifests}) != len(ordered_manifests):
        raise ValueError("question universe principal manifests MUST be unique")
    if len({item.release_digest for item in ordered_manifests}) != 1:
        raise ValueError("question universe manifests MUST bind one ontology release")

    normalized: list[
        tuple[QueryManifest, tuple[dict[str, Any], ...], tuple[dict[str, str], ...]]
    ] = []
    expected_case_count = 0
    for manifest in ordered_manifests:
        descriptors, unavailable = _validate_manifest(manifest)
        expected_case_count += sum(
            grammar.variants_for(application.perspective)
            for descriptor in descriptors
            for application in perspective_applications(descriptor)
        )
        expected_case_count += len(unavailable)
        normalized.append((manifest, descriptors, unavailable))
    if expected_case_count == 0:
        raise ValueError("question universe has no readable declaration accounting")
    if expected_case_count > grammar.max_cases:
        raise ValueError("question universe exceeds its preflight case bound")

    cases: list[GeneratedQuestionCase] = []
    exclusions: list[QuestionCaseExclusion] = []
    for manifest, descriptors, unavailable in normalized:
        for descriptor in descriptors:
            declaration_id = f"{descriptor['kind']}:{descriptor['name']}"
            applications = perspective_applications(descriptor)
            for locale in grammar.locales:
                for case_class in grammar.case_classes:
                    for evidence_posture in grammar.evidence_postures:
                        for application in applications:
                            for investigation in _investigation_variants(
                                application.perspective,
                                grammar=grammar,
                            ):
                                for path_depth in grammar.path_depths:
                                    for result_bound in grammar.result_bounds:
                                        expected_posture = _expected_case_posture(
                                            application.perspective,
                                            access_filtered=(
                                                case_class is QuestionCaseClass.ACCESS_FILTERED
                                            ),
                                            evidence_posture=evidence_posture,
                                            investigation=investigation,
                                        )
                                        body = _generated_case_body(
                                            manifest=manifest,
                                            descriptor=descriptor,
                                            declaration_id=declaration_id,
                                            locale=locale,
                                            case_class=case_class,
                                            application=application,
                                            evidence_posture=evidence_posture,
                                            expected_posture=expected_posture,
                                            investigation=investigation,
                                            path_depth=path_depth,
                                            result_bound=result_bound,
                                        )
                                        cases.append(
                                            GeneratedQuestionCase(
                                                case_id=_case_id("q", body),
                                                principal_manifest_digest=(
                                                    manifest.manifest_digest
                                                ),
                                                declaration_id=declaration_id,
                                                declaration_digest=(
                                                    descriptor["declaration_digest"]
                                                ),
                                                locale=locale,
                                                case_class=case_class,
                                                perspective=application.perspective,
                                                required_capability=(application.capability),
                                                evidence_posture=evidence_posture,
                                                anchor_kind=application.anchor_kind,
                                                expected_posture=expected_posture,
                                                action_posture=(application.action_posture),
                                                path_depth=path_depth,
                                                result_bound=result_bound,
                                                rule_state=application.rule_state,
                                                entity_state=investigation.entity_state,
                                                temporal_state=(investigation.temporal_state),
                                                causal_result=(investigation.causal_result),
                                                presentation_shape=(
                                                    investigation.presentation_shape
                                                ),
                                            )
                                        )
        for item in unavailable:
            try:
                reason = QuestionExclusionReason(item["reason"])
            except ValueError as error:
                raise ValueError(
                    f"unsupported question exclusion reason: {item['reason']}"
                ) from error
            body = {
                "principal_manifest_digest": manifest.manifest_digest,
                "declaration_id": item["declaration_id"],
                "reason": reason.value,
            }
            exclusions.append(
                QuestionCaseExclusion(
                    case_id=_case_id("x", body),
                    principal_manifest_digest=manifest.manifest_digest,
                    declaration_id=item["declaration_id"],
                    reason=reason,
                )
            )

    ordered_cases = tuple(sorted(cases, key=lambda item: item.case_id))
    ordered_exclusions = tuple(sorted(exclusions, key=lambda item: item.case_id))
    receipt = QuestionUniverseReceipt.build(
        ontology_release_digest=ordered_manifests[0].release_digest,
        principal_manifest_digests=tuple(item.manifest_digest for item in ordered_manifests),
        grammar_digest=grammar.digest,
        case_ids=tuple(item.case_id for item in ordered_cases),
        excluded_case_ids=tuple(item.case_id for item in ordered_exclusions),
    )
    generation_body = {
        "grammar_digest": grammar.digest,
        "question_universe_digest": receipt.receipt_digest,
        "cases": tuple(_case_body(item) for item in ordered_cases),
        "exclusions": tuple(_exclusion_body(item) for item in ordered_exclusions),
    }
    return GeneratedQuestionUniverse(
        grammar=grammar,
        cases=ordered_cases,
        exclusions=ordered_exclusions,
        receipt=receipt,
        generation_digest=_digest(generation_body),
    )


def _validate_manifest(
    manifest: QueryManifest,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, str], ...]]:
    receipt = manifest.coverage_receipt
    if not receipt.complete:
        raise ValueError("question universe requires complete principal manifests")
    if receipt.ontology_release_digest != manifest.release_digest:
        raise ValueError("question manifest coverage binds a different ontology release")
    if receipt.manifest_digest != manifest.manifest_digest:
        raise ValueError("question manifest coverage binds a different manifest")
    descriptors = tuple(
        sorted(
            manifest.descriptors,
            key=lambda item: (item.get("kind", ""), item.get("name", "")),
        )
    )
    unavailable = tuple(
        sorted(manifest.unavailable, key=lambda item: item.get("declaration_id", ""))
    )
    descriptor_ids: list[str] = []
    for descriptor in descriptors:
        kind = descriptor.get("kind")
        name = descriptor.get("name")
        declaration_digest = descriptor.get("declaration_digest")
        if not isinstance(kind, str) or not kind or not isinstance(name, str) or not name:
            raise ValueError("question manifest descriptors require kind and name")
        if not isinstance(declaration_digest, str):
            raise ValueError("question manifest descriptors require a declaration digest")
        _require_digest("declaration digest", declaration_digest)
        descriptor_ids.append(f"{kind}:{name}")
    unavailable_ids: list[str] = []
    for item in unavailable:
        declaration_id = item.get("declaration_id")
        reason = item.get("reason")
        if not isinstance(declaration_id, str) or not declaration_id:
            raise ValueError("question manifest exclusions require a declaration id")
        if not isinstance(reason, str) or not reason:
            raise ValueError("question manifest exclusions require a reason")
        unavailable_ids.append(declaration_id)
    all_ids = descriptor_ids + unavailable_ids
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("question manifest declaration accounting MUST be unique")
    if receipt.descriptor_count != len(descriptors):
        raise ValueError("question manifest descriptor count is incomplete")
    if set(receipt.unavailable_declaration_ids) != set(unavailable_ids):
        raise ValueError("question manifest unavailable accounting is incomplete")
    if receipt.readable_declaration_count != len(all_ids):
        raise ValueError("question manifest readable declaration accounting is incomplete")
    return descriptors, unavailable


def _require_bounded_axis(name: str, values: tuple[int, ...], *, maximum: int) -> None:
    if not values or values != tuple(sorted(set(values))):
        raise ValueError(f"question grammar {name} MUST be non-empty, unique, and ordered")
    if any(value < 1 or value > maximum for value in values):
        raise ValueError(f"question grammar {name} MUST be in [1, {maximum}]")


def _require_enum_axis(name: str, values: Sequence[StrEnum]) -> None:
    if not values or tuple(values) != tuple(sorted(set(values), key=lambda item: item.value)):
        raise ValueError(f"question grammar {name} MUST be non-empty, unique, and ordered")


def _investigation_variants(
    perspective: QuestionPerspective,
    *,
    grammar: QuestionUniverseGrammar,
) -> tuple[QuestionInvestigationPosture, ...]:
    if perspective is not QuestionPerspective.CAUSAL:
        return (QuestionInvestigationPosture(),)
    return tuple(
        QuestionInvestigationPosture(
            entity_state=entity_state,
            temporal_state=temporal_state,
            causal_result=causal_result,
            presentation_shape=presentation_shape,
        )
        for entity_state in grammar.entity_states
        for temporal_state in grammar.temporal_states
        for causal_result in grammar.causal_results
        for presentation_shape in grammar.presentation_shapes
    )


def _expected_case_posture(
    perspective: QuestionPerspective,
    *,
    access_filtered: bool,
    evidence_posture: QuestionEvidencePosture,
    investigation: QuestionInvestigationPosture,
) -> QuestionExpectedPosture:
    if investigation.entity_state in {
        QuestionEntityState.AMBIGUOUS,
        QuestionEntityState.MISSING,
    }:
        return QuestionExpectedPosture.CLARIFY
    if investigation.temporal_state in {
        QuestionTemporalState.PARTIAL_CURRENT,
        QuestionTemporalState.STALE_BASELINE,
    }:
        return QuestionExpectedPosture.HOLD
    return expected_question_posture(
        perspective,
        access_filtered=access_filtered,
        evidence_posture=evidence_posture,
    )


def _generated_case_body(
    *,
    manifest: QueryManifest,
    descriptor: dict[str, Any],
    declaration_id: str,
    locale: str,
    case_class: QuestionCaseClass,
    application: QuestionPerspectiveApplication,
    evidence_posture: QuestionEvidencePosture,
    expected_posture: QuestionExpectedPosture,
    investigation: QuestionInvestigationPosture,
    path_depth: int,
    result_bound: int,
) -> dict[str, object]:
    return {
        "principal_manifest_digest": manifest.manifest_digest,
        "declaration_id": declaration_id,
        "declaration_digest": descriptor["declaration_digest"],
        "locale": locale,
        "case_class": case_class.value,
        "perspective": application.perspective.value,
        "required_capability": application.capability.value,
        "evidence_posture": evidence_posture.value,
        "anchor_kind": application.anchor_kind.value,
        "expected_posture": expected_posture.value,
        "action_posture": application.action_posture,
        "rule_state": application.rule_state.value,
        "entity_state": investigation.entity_state.value,
        "temporal_state": investigation.temporal_state.value,
        "causal_result": investigation.causal_result.value,
        "presentation_shape": investigation.presentation_shape.value,
        "path_depth": path_depth,
        "result_bound": result_bound,
    }


def _case_body(item: GeneratedQuestionCase) -> dict[str, object]:
    return {
        "case_id": item.case_id,
        "principal_manifest_digest": item.principal_manifest_digest,
        "declaration_id": item.declaration_id,
        "declaration_digest": item.declaration_digest,
        "locale": item.locale,
        "case_class": item.case_class.value,
        "perspective": item.perspective.value,
        "required_capability": item.required_capability.value,
        "evidence_posture": item.evidence_posture.value,
        "anchor_kind": item.anchor_kind.value,
        "expected_posture": item.expected_posture.value,
        "action_posture": item.action_posture,
        "rule_state": item.rule_state.value,
        "entity_state": item.entity_state.value,
        "temporal_state": item.temporal_state.value,
        "causal_result": item.causal_result.value,
        "presentation_shape": item.presentation_shape.value,
        "path_depth": item.path_depth,
        "result_bound": item.result_bound,
    }


def _exclusion_body(item: QuestionCaseExclusion) -> dict[str, object]:
    return {
        "case_id": item.case_id,
        "principal_manifest_digest": item.principal_manifest_digest,
        "declaration_id": item.declaration_id,
        "reason": item.reason.value,
    }


def _case_id(prefix: str, value: object) -> str:
    return f"{prefix}:{_digest(value).removeprefix('sha256:')}"


def _require_digest(name: str, value: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a canonical SHA-256 value")


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "GeneratedQuestionCase",
    "GeneratedQuestionUniverse",
    "QuestionAnchorKind",
    "QuestionCapabilityFamily",
    "QuestionCaseClass",
    "QuestionCaseExclusion",
    "QuestionEvidencePosture",
    "QuestionExpectedPosture",
    "QuestionEntityState",
    "QuestionTemporalState",
    "QuestionCausalResult",
    "QuestionPresentationShape",
    "QuestionExclusionReason",
    "QuestionPerspective",
    "QuestionRuleState",
    "QuestionUniverseGrammar",
    "generate_question_universe",
]
