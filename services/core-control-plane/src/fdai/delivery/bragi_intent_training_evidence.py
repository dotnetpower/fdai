"""Immutable reviewed off-path intent-training batch for Bragi."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fdai.agents import (
    IntentTrainingEvaluationResult,
    IntentTrainingEvidence,
    ReviewedIntentTrainingPromotion,
)

_MAX_FILE_BYTES = 1024 * 1024
_MAX_RECORDS = 256
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class ImmutableBragiIntentTrainingBatch:
    """Serve reviewed corpus and evaluation results without routing authority."""

    def __init__(
        self,
        *,
        source_revision: str,
        batch_ref: str,
        evaluator_principal_digest: str,
        corpus: tuple[IntentTrainingEvidence, ...],
        results: Mapping[str, IntentTrainingEvaluationResult],
        reviewed_promotion: ReviewedIntentTrainingPromotion,
    ) -> None:
        self.source_revision = source_revision
        self.batch_ref = batch_ref
        self.evaluator_principal_digest = evaluator_principal_digest
        self.corpus = corpus
        self.reviewed_promotion = reviewed_promotion
        self._results = dict(results)

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        expected_digest: str,
    ) -> ImmutableBragiIntentTrainingBatch:
        """Load one exact-digest closed batch from a bounded regular file."""

        if _SHA256.fullmatch(expected_digest) is None:
            raise ValueError("Bragi intent-training digest MUST be lowercase SHA-256")
        content = _read_bounded_regular_file(path)
        if hashlib.sha256(content).hexdigest() != expected_digest:
            raise ValueError("Bragi intent-training digest mismatch")
        raw = _object(_load_unique_json(content), "manifest")
        _exact_fields(
            raw,
            {
                "schema_version",
                "source_revision",
                "batch_ref",
                "evaluator_principal_digest",
                "review",
                "corpus",
                "evaluation_results",
            },
            "manifest",
        )
        if raw["schema_version"] != "1.0.0":
            raise ValueError("unsupported Bragi intent-training schema")
        source_revision = _text(raw, "source_revision")
        if _REVISION.fullmatch(source_revision) is None:
            raise ValueError("Bragi intent-training source revision is invalid")
        evaluator_principal_digest = _digest_text(raw, "evaluator_principal_digest")
        review = _review(_object(raw["review"], "review"))
        if evaluator_principal_digest == review.reviewer_principal_digest:
            raise ValueError("Bragi evaluator and reviewer principals MUST be distinct")
        corpus = tuple(_evidence(item) for item in _object_list(raw["corpus"], "corpus"))
        result_items = tuple(
            _result(item) for item in _object_list(raw["evaluation_results"], "results")
        )
        if not corpus or len(corpus) > _MAX_RECORDS or len(result_items) > _MAX_RECORDS:
            raise ValueError("Bragi intent-training records are outside the bounded range")
        if len({item.evidence_id for item in corpus}) != len(corpus):
            raise ValueError("Bragi intent-training evidence ids MUST be unique")
        if len({item.evidence_id for item in result_items}) != len(result_items):
            raise ValueError("Bragi intent-training result ids MUST be unique")
        evidence_by_id = {item.evidence_id: item for item in corpus}
        results = {item.evidence_id: item for item in result_items}
        if set(results) != set(evidence_by_id):
            raise ValueError("Bragi evaluation results MUST match every corpus record exactly")
        if any(
            result.baseline_owner != evidence_by_id[evidence_id].baseline_owner
            or result.expected_owner != evidence_by_id[evidence_id].corrected_owner
            for evidence_id, result in results.items()
        ):
            raise ValueError("Bragi evaluation results changed frozen corpus identity")
        return cls(
            source_revision=source_revision,
            batch_ref=_text(raw, "batch_ref"),
            evaluator_principal_digest=evaluator_principal_digest,
            corpus=corpus,
            results=results,
            reviewed_promotion=review,
        )

    def evaluate(
        self,
        *,
        baseline_revision: Mapping[str, Any],
        candidate_revision: Mapping[str, Any],
        holdout_cases: Sequence[IntentTrainingEvidence],
    ) -> Sequence[IntentTrainingEvaluationResult]:
        """Return frozen external results only for this exact corpus-derived candidate."""

        selected = tuple(sorted(self.corpus, key=lambda item: item.evidence_id))
        expected_cases = (
            *(item for item in selected if not item.targeted),
            *(item for item in selected if item.targeted),
        )
        if tuple(holdout_cases) != expected_cases:
            raise ValueError("Bragi evaluator cases differ from the reviewed corpus")
        if (
            baseline_revision.get("revision") != "runtime-current"
            or baseline_revision.get("runtime_routing_authority_changed") is not False
            or candidate_revision.get("activation_authority") is not False
            or candidate_revision.get("runtime_routing_authority_changed") is not False
        ):
            raise ValueError("Bragi evaluator received an authority-bearing revision")
        return tuple(self._results[item.evidence_id] for item in holdout_cases)


def _review(raw: Mapping[str, object]) -> ReviewedIntentTrainingPromotion:
    _exact_fields(
        raw,
        {"review_id", "reviewer_principal_digest", "approval_ref"},
        "review",
    )
    return ReviewedIntentTrainingPromotion(
        review_id=_text(raw, "review_id"),
        reviewer_principal_digest=_digest_text(raw, "reviewer_principal_digest"),
        approval_ref=_text(raw, "approval_ref"),
    )


def _evidence(raw: Mapping[str, object]) -> IntentTrainingEvidence:
    _exact_fields(
        raw,
        {
            "evidence_id",
            "source_kind",
            "principal_scope_digest",
            "consent_ref",
            "input_digest",
            "baseline_owner",
            "corrected_owner",
            "baseline_intent",
            "corrected_intent",
            "corrected_object_type",
            "targeted",
            "evidence_refs",
        },
        "corpus record",
    )
    if type(raw["targeted"]) is not bool:
        raise ValueError("Bragi intent-training targeted MUST be boolean")
    evidence_refs = _references(raw["evidence_refs"], "evidence_refs")
    if not evidence_refs:
        raise ValueError("Bragi intent-training evidence_refs MUST be non-empty")
    return IntentTrainingEvidence(
        evidence_id=_text(raw, "evidence_id"),
        source_kind=_text(raw, "source_kind"),
        principal_scope_digest=_digest_text(raw, "principal_scope_digest"),
        consent_ref=_text(raw, "consent_ref"),
        input_digest=_digest_text(raw, "input_digest"),
        baseline_owner=_optional_text(raw, "baseline_owner"),
        corrected_owner=_text(raw, "corrected_owner"),
        baseline_intent=_optional_text(raw, "baseline_intent"),
        corrected_intent=_optional_text(raw, "corrected_intent"),
        corrected_object_type=_optional_text(raw, "corrected_object_type"),
        targeted=raw["targeted"],
        evidence_refs=evidence_refs,
    )


def _result(raw: Mapping[str, object]) -> IntentTrainingEvaluationResult:
    _exact_fields(
        raw,
        {"evidence_id", "baseline_owner", "candidate_owner", "expected_owner"},
        "evaluation result",
    )
    return IntentTrainingEvaluationResult(
        evidence_id=_text(raw, "evidence_id"),
        baseline_owner=_optional_text(raw, "baseline_owner"),
        candidate_owner=_optional_text(raw, "candidate_owner"),
        expected_owner=_text(raw, "expected_owner"),
    )


def _load_unique_json(content: bytes) -> object:
    def unique(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Bragi intent-training evidence contains duplicate keys")
            result[key] = value
        return result

    try:
        return json.loads(content, object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Bragi intent-training evidence is not valid UTF-8 JSON") from exc


def _read_bounded_regular_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("Bragi intent-training evidence MUST be a regular file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_FILE_BYTES:
            raise ValueError("Bragi intent-training evidence file is invalid or oversized")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read(_MAX_FILE_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(content) > _MAX_FILE_BYTES:
        raise ValueError("Bragi intent-training evidence file is invalid or oversized")
    return content


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"Bragi intent-training {label} MUST be an object")
    return value


def _object_list(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"Bragi intent-training {label} MUST be an array")
    return tuple(_object(item, label) for item in value)


def _exact_fields(raw: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(raw) != expected:
        raise ValueError(f"Bragi intent-training {label} fields are incomplete or unknown")


def _text(raw: Mapping[str, object], field: str) -> str:
    value = _optional_text(raw, field)
    if value is None:
        raise ValueError(f"Bragi intent-training {field} MUST be non-empty")
    return value


def _optional_text(raw: Mapping[str, object], field: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"Bragi intent-training {field} MUST be canonical text or null")
    return value


def _digest_text(raw: Mapping[str, object], field: str) -> str:
    value = _text(raw, field)
    if not value.startswith("sha256:") or _SHA256.fullmatch(value[7:]) is None:
        raise ValueError(f"Bragi intent-training {field} MUST be a SHA-256 digest")
    return value


def _references(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError(f"Bragi intent-training {label} MUST be a bounded array")
    references = tuple(_text({label: item}, label) for item in value)
    if len(set(references)) != len(references):
        raise ValueError(f"Bragi intent-training {label} MUST be unique")
    return references


__all__ = ["ImmutableBragiIntentTrainingBatch"]
