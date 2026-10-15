"""Immutable reviewed evidence for Mimir governance maintenance."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from fdai.agents import (
    MimirCatalogPromotionOutcome,
    MimirDeprecationCandidate,
    MimirRegressionResult,
)

_MAX_FILE_BYTES = 1024 * 1024
_MAX_RECORDS = 1000
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_RULE_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


class ImmutableMimirMaintenanceEvidence:
    """Serve one content-addressed, deployment-reviewed maintenance snapshot."""

    def __init__(
        self,
        *,
        source_revision: str,
        review_ref: str,
        promotions: tuple[MimirCatalogPromotionOutcome, ...],
        regressions: Mapping[tuple[str, str, str], MimirRegressionResult],
        deprecations: tuple[MimirDeprecationCandidate, ...],
    ) -> None:
        self.source_revision = source_revision
        self.review_ref = review_ref
        self._promotions = promotions
        self._regressions = dict(regressions)
        self._deprecations = deprecations

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        expected_digest: str,
    ) -> ImmutableMimirMaintenanceEvidence:
        """Load one exact-digest closed manifest from a bounded regular file."""

        if _DIGEST.fullmatch(expected_digest) is None:
            raise ValueError("Mimir maintenance evidence digest MUST be lowercase SHA-256")
        content = _read_bounded_regular_file(path)
        if hashlib.sha256(content).hexdigest() != expected_digest:
            raise ValueError("Mimir maintenance evidence digest mismatch")
        raw = _object(_load_unique_json(content), "manifest")
        _exact_fields(
            raw,
            {
                "schema_version",
                "source_revision",
                "review_ref",
                "promotions",
                "regressions",
                "deprecations",
            },
            "manifest",
        )
        if raw["schema_version"] != "1.0.0":
            raise ValueError("unsupported Mimir maintenance evidence schema")
        source_revision = _text(raw, "source_revision")
        if _REVISION.fullmatch(source_revision) is None:
            raise ValueError("Mimir maintenance source revision is invalid")
        review_ref = _reference(raw, "review_ref")
        promotions = tuple(
            _promotion(item, review_ref=review_ref)
            for item in _object_list(raw["promotions"], "promotions")
        )
        regression_items = tuple(
            _regression(item) for item in _object_list(raw["regressions"], "regressions")
        )
        deprecations = tuple(
            _deprecation(item) for item in _object_list(raw["deprecations"], "deprecations")
        )
        if len(promotions) > _MAX_RECORDS:
            raise ValueError("Mimir maintenance promotions are outside the bounded range")
        if len(regression_items) > _MAX_RECORDS or len(deprecations) > _MAX_RECORDS:
            raise ValueError("Mimir maintenance evidence exceeds its record bound")
        promotion_keys = tuple(_promotion_key(item) for item in promotions)
        regression_keys = tuple(item[0] for item in regression_items)
        if len(set(promotion_keys)) != len(promotion_keys):
            raise ValueError("Mimir maintenance promotion identities MUST be unique")
        if len(set(regression_keys)) != len(regression_keys):
            raise ValueError("Mimir maintenance regression identities MUST be unique")
        if set(regression_keys) != set(promotion_keys):
            raise ValueError("Mimir maintenance regressions MUST match every promotion exactly")
        if len({item.rule_id for item in deprecations}) != len(deprecations):
            raise ValueError("Mimir maintenance deprecation Rule ids MUST be unique")
        return cls(
            source_revision=source_revision,
            review_ref=review_ref,
            promotions=promotions,
            regressions=dict(regression_items),
            deprecations=deprecations,
        )

    async def read_promotion_outcomes(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> Sequence[MimirCatalogPromotionOutcome]:
        _validate_read(limit=limit, now=now)
        return self._promotions[:limit]

    async def run_regression(
        self,
        outcome: MimirCatalogPromotionOutcome,
        *,
        now: datetime,
    ) -> MimirRegressionResult:
        _validate_read(limit=1, now=now)
        result = self._regressions.get(_promotion_key(outcome))
        if result is None:
            raise ValueError("Mimir maintenance regression evidence is unavailable")
        return result

    async def stale_or_retired_rules(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> Sequence[MimirDeprecationCandidate]:
        _validate_read(limit=limit, now=now)
        return self._deprecations[:limit]


def _promotion(value: object, *, review_ref: str) -> MimirCatalogPromotionOutcome:
    raw = _object(value, "promotion")
    _exact_fields(
        raw,
        {
            "problem_fingerprint",
            "promotion_pr",
            "correlation_id",
            "outcome",
            "rule_id",
            "promoted_at",
            "candidate_digest",
            "package_digest",
        },
        "promotion",
    )
    fingerprint = _digest_text(raw, "problem_fingerprint")
    promotion_pr = _reference(raw, "promotion_pr")
    if "/pull/" not in promotion_pr:
        raise ValueError("Mimir maintenance promotion PR reference is invalid")
    rule_id = _text(raw, "rule_id")
    if _RULE_ID.fullmatch(rule_id) is None:
        raise ValueError("Mimir maintenance Rule id is invalid")
    outcome = _text(raw, "outcome")
    if outcome not in {"promoted", "promotion_succeeded"}:
        raise ValueError("Mimir maintenance outcome is not a promotion")
    return MimirCatalogPromotionOutcome(
        problem_fingerprint=fingerprint,
        promotion_pr=promotion_pr,
        correlation_id=_reference(raw, "correlation_id"),
        outcome=outcome,
        rule_id=rule_id,
        promoted_at=_timestamp(raw, "promoted_at"),
        candidate_digest=_digest_text(raw, "candidate_digest"),
        package_digest=_digest_text(raw, "package_digest"),
        review_ref=review_ref,
    )


def _regression(value: object) -> tuple[tuple[str, str, str], MimirRegressionResult]:
    raw = _object(value, "regression")
    _exact_fields(
        raw,
        {
            "problem_fingerprint",
            "promotion_pr",
            "rule_id",
            "passed",
            "started_at",
            "completed_at",
            "evidence_ref",
        },
        "regression",
    )
    if type(raw["passed"]) is not bool:
        raise ValueError("Mimir maintenance regression passed MUST be boolean")
    key = (
        _digest_text(raw, "problem_fingerprint"),
        _reference(raw, "promotion_pr"),
        _text(raw, "rule_id"),
    )
    return key, MimirRegressionResult(
        passed=raw["passed"],
        started_at=_timestamp(raw, "started_at"),
        completed_at=_timestamp(raw, "completed_at"),
        evidence_ref=_reference(raw, "evidence_ref"),
    )


def _deprecation(value: object) -> MimirDeprecationCandidate:
    raw = _object(value, "deprecation")
    _exact_fields(raw, {"rule_id", "reason", "evidence_ref", "observed_at"}, "deprecation")
    rule_id = _text(raw, "rule_id")
    if _RULE_ID.fullmatch(rule_id) is None:
        raise ValueError("Mimir maintenance deprecation Rule id is invalid")
    return MimirDeprecationCandidate(
        rule_id=rule_id,
        reason=_reference(raw, "reason"),
        evidence_ref=_reference(raw, "evidence_ref"),
        observed_at=_timestamp(raw, "observed_at"),
    )


def _promotion_key(outcome: MimirCatalogPromotionOutcome) -> tuple[str, str, str]:
    return outcome.problem_fingerprint, outcome.promotion_pr, outcome.rule_id


def _validate_read(*, limit: int, now: datetime) -> None:
    if type(limit) is not int or not 1 <= limit <= _MAX_RECORDS:
        raise ValueError("Mimir maintenance read limit MUST be from 1 through 1000")
    if now.tzinfo is None:
        raise ValueError("Mimir maintenance observation time MUST be timezone-aware")


def _load_unique_json(content: bytes) -> object:
    def unique(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Mimir maintenance evidence contains duplicate keys")
            result[key] = value
        return result

    try:
        return json.loads(content, object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Mimir maintenance evidence is not valid UTF-8 JSON") from exc


def _read_bounded_regular_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("Mimir maintenance evidence MUST be a regular file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_FILE_BYTES:
            raise ValueError("Mimir maintenance evidence file is invalid or oversized")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read(_MAX_FILE_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(content) > _MAX_FILE_BYTES:
        raise ValueError("Mimir maintenance evidence file is invalid or oversized")
    return content


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"Mimir maintenance {label} MUST be an object")
    return value


def _object_list(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"Mimir maintenance {label} MUST be an array")
    return tuple(_object(item, label) for item in value)


def _exact_fields(raw: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(raw) != expected:
        raise ValueError(f"Mimir maintenance {label} fields are incomplete or unknown")


def _text(raw: Mapping[str, object], field: str) -> str:
    value = raw.get(field)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"Mimir maintenance {field} MUST be canonical text")
    return value


def _reference(raw: Mapping[str, object], field: str) -> str:
    return _text(raw, field)


def _digest_text(raw: Mapping[str, object], field: str) -> str:
    value = _text(raw, field)
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"Mimir maintenance {field} MUST be lowercase SHA-256")
    return value


def _timestamp(raw: Mapping[str, object], field: str) -> datetime:
    value = _text(raw, field)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Mimir maintenance {field} MUST be ISO 8601") from None
    if parsed.tzinfo is None:
        raise ValueError(f"Mimir maintenance {field} MUST be timezone-aware")
    return parsed


__all__ = ["ImmutableMimirMaintenanceEvidence"]
