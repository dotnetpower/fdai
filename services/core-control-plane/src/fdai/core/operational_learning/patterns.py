"""Compile fingerprint-scoped operational cases into inert pattern candidates."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from fdai.core.case_history import (
    OperationalCaseInput,
    OperationalCaseProjection,
    OperationalEvidenceSourceKind,
    OperationalOutcomeClass,
    OperationalReceiptType,
)

_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MAX_CASES = 100
_MAX_CASE_ID_CHARS = 256
_MAX_IDENTIFIER_CHARS = 128
_MAX_CASE_EVIDENCE_REFS = 64
_MAX_PATTERN_EVIDENCE_REFS = 256
_NEGATIVE_OUTCOMES = frozenset(
    {
        OperationalOutcomeClass.FAILURE,
        OperationalOutcomeClass.REFUSAL,
        OperationalOutcomeClass.NO_OP,
        OperationalOutcomeClass.ROLLBACK,
        OperationalOutcomeClass.RECURRENCE,
    }
)
_PATTERN_CASE_FIELDS = frozenset(
    {
        "case_id",
        "revision",
        "manifest_digest",
        "failure_fingerprint",
        "resource_type",
        "action_type",
        "outcome_class",
        "reusable",
        "negative",
        "digest_evidence",
        "fdai_revision",
        "scenario_set_version",
        "event_time_cutoff",
        "source_kind",
        "source_identity_digest",
        "source_synthetic",
        "evidence_complete",
        "conflict_digests",
    }
)
_GIT_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_DEFAULT_MAX_CASE_AGE = timedelta(days=90)


@dataclass(frozen=True, slots=True)
class PatternCase:
    case_id: str
    revision: int
    manifest_digest: str
    failure_fingerprint: str
    resource_type: str
    action_type: str
    outcome_class: OperationalOutcomeClass
    reusable: bool
    negative: bool
    digest_evidence: tuple[str, ...]
    fdai_revision: str
    scenario_set_version: str
    event_time_cutoff: datetime
    source_kind: OperationalEvidenceSourceKind
    source_identity_digest: str
    source_synthetic: bool
    evidence_complete: bool
    conflict_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.case_id or len(self.case_id) > _MAX_CASE_ID_CHARS or self.revision < 1:
            raise ValueError("pattern case MUST cite a case id and positive revision")
        for name, value in (
            ("manifest_digest", self.manifest_digest),
            ("failure_fingerprint", self.failure_fingerprint),
        ):
            if not _is_sha256(value):
                raise ValueError(f"pattern case {name} MUST be lowercase SHA-256")
        for name, value in (
            ("resource_type", self.resource_type),
            ("action_type", self.action_type),
        ):
            if len(value) > _MAX_IDENTIFIER_CHARS or _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"pattern case {name} MUST be a canonical identifier")
        expected_reusable = self.outcome_class is OperationalOutcomeClass.SUCCESS
        expected_negative = self.outcome_class in _NEGATIVE_OUTCOMES
        if self.reusable is not expected_reusable or self.negative is not expected_negative:
            raise ValueError("pattern case classification MUST match its outcome class")
        if self.reusable == self.negative:
            raise ValueError("pattern case MUST be reusable or negative")
        if _GIT_REVISION.fullmatch(self.fdai_revision) is None:
            raise ValueError("pattern case FDAI revision MUST be immutable")
        if _IDENTIFIER.fullmatch(self.scenario_set_version) is None:
            raise ValueError("pattern case scenario set MUST be canonical")
        if self.event_time_cutoff.tzinfo is None:
            raise ValueError("pattern case cutoff MUST be timezone-aware")
        if not _is_sha256(self.source_identity_digest):
            raise ValueError("pattern case source identity MUST be lowercase SHA-256")
        if not isinstance(self.source_synthetic, bool) or not isinstance(
            self.evidence_complete, bool
        ):
            raise ValueError("pattern case source flags MUST be boolean")
        conflicts = tuple(sorted(set(self.conflict_digests)))
        if any(not _is_sha256(item) for item in conflicts):
            raise ValueError("pattern case conflicts MUST contain SHA-256 values")
        object.__setattr__(self, "conflict_digests", conflicts)
        evidence = tuple(sorted(set(self.digest_evidence)))
        if not 1 <= len(evidence) <= _MAX_CASE_EVIDENCE_REFS or any(
            not _is_sha256(item) for item in evidence
        ):
            raise ValueError("pattern case digest evidence MUST contain SHA-256 values")
        object.__setattr__(self, "digest_evidence", evidence)

    @property
    def immutable_case_ref(self) -> str:
        return f"case-history:{self.case_id}:{self.revision}:{self.manifest_digest}"

    def to_mapping(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "revision": self.revision,
            "manifest_digest": self.manifest_digest,
            "failure_fingerprint": self.failure_fingerprint,
            "resource_type": self.resource_type,
            "action_type": self.action_type,
            "outcome_class": self.outcome_class.value,
            "reusable": self.reusable,
            "negative": self.negative,
            "digest_evidence": list(self.digest_evidence),
            "fdai_revision": self.fdai_revision,
            "scenario_set_version": self.scenario_set_version,
            "event_time_cutoff": self.event_time_cutoff.isoformat(),
            "source_kind": self.source_kind.value,
            "source_identity_digest": self.source_identity_digest,
            "source_synthetic": self.source_synthetic,
            "evidence_complete": self.evidence_complete,
            "conflict_digests": list(self.conflict_digests),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PatternCase:
        if set(value) != _PATTERN_CASE_FIELDS:
            raise ValueError("pattern case mapping does not match its standard schema")
        revision = value.get("revision")
        reusable = value.get("reusable")
        negative = value.get("negative")
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise ValueError("pattern case revision MUST be an integer")
        if not isinstance(reusable, bool) or not isinstance(negative, bool):
            raise ValueError("pattern case classifications MUST be boolean")
        source_synthetic = value.get("source_synthetic")
        evidence_complete = value.get("evidence_complete")
        if not isinstance(source_synthetic, bool) or not isinstance(evidence_complete, bool):
            raise ValueError("pattern case source flags MUST be boolean")
        try:
            outcome_class = OperationalOutcomeClass(_required(value, "outcome_class"))
            source_kind = OperationalEvidenceSourceKind(_required(value, "source_kind"))
        except ValueError as exc:
            raise ValueError("pattern case outcome class is unsupported") from exc
        evidence = value.get("digest_evidence")
        if not isinstance(evidence, Sequence) or isinstance(evidence, str | bytes):
            raise ValueError("pattern case digest_evidence MUST be an array")
        if not 1 <= len(evidence) <= _MAX_CASE_EVIDENCE_REFS:
            raise ValueError("pattern case digest_evidence MUST be bounded")
        if any(not isinstance(item, str) for item in evidence):
            raise ValueError("pattern case digest_evidence MUST contain strings")
        return cls(
            case_id=_required(value, "case_id"),
            revision=revision,
            manifest_digest=_required(value, "manifest_digest"),
            failure_fingerprint=_required(value, "failure_fingerprint"),
            resource_type=_required(value, "resource_type"),
            action_type=_required(value, "action_type"),
            outcome_class=outcome_class,
            reusable=reusable,
            negative=negative,
            digest_evidence=tuple(evidence),
            fdai_revision=_required(value, "fdai_revision"),
            scenario_set_version=_required(value, "scenario_set_version"),
            event_time_cutoff=_required_datetime(value, "event_time_cutoff"),
            source_kind=source_kind,
            source_identity_digest=_required(value, "source_identity_digest"),
            source_synthetic=source_synthetic,
            evidence_complete=evidence_complete,
            conflict_digests=_string_array(value, "conflict_digests"),
        )


@dataclass(frozen=True, slots=True)
class OperatingPatternCandidate:
    pattern_id: str
    failure_fingerprint: str
    resource_type: str
    action_type: str
    sample_size: int
    reusable_count: int
    negative_count: int
    outcome_counts: tuple[tuple[str, int], ...]
    immutable_case_refs: tuple[str, ...]
    digest_evidence: tuple[str, ...]
    fdai_revision: str
    scenario_set_version: str
    case_reviews: tuple[dict[str, object], ...]

    def to_rule_candidate_mapping(self) -> dict[str, object]:
        return {
            "source_signal": "operational_case_fingerprint_cohort",
            "evidence": {
                "sample_size": self.sample_size,
                "reusable_count": self.reusable_count,
                "negative_count": self.negative_count,
                "outcome_counts": dict(self.outcome_counts),
                "failure_fingerprint": self.failure_fingerprint,
                "resource_type": self.resource_type,
                "action_type": self.action_type,
                "immutable_case_refs": list(self.immutable_case_refs),
                "digest_evidence": list(self.digest_evidence),
                "fdai_revision": self.fdai_revision,
                "scenario_set_version": self.scenario_set_version,
                "case_reviews": [dict(review) for review in self.case_reviews],
            },
            "provenance": {"source": "case-history", "pattern_id": self.pattern_id},
            "proposed_by": "Norns",
            "proposal_kind": "new",
            "target_rule_id": self.action_type,
            "suggested_pattern": self.pattern_id,
        }


class OperatingPatternCompiler:
    """Require one mechanism/action pair with reusable and negative evidence."""

    def compile(
        self,
        cases: Sequence[PatternCase],
        *,
        reviewed_at: datetime | None = None,
        max_case_age: timedelta = _DEFAULT_MAX_CASE_AGE,
    ) -> OperatingPatternCandidate | None:
        if len(cases) < 2:
            return None
        if len(cases) > _MAX_CASES:
            raise ValueError("operational pattern cohort exceeds its case limit")
        fingerprints = {case.failure_fingerprint for case in cases}
        resource_types = {case.resource_type for case in cases}
        action_types = {case.action_type for case in cases}
        if len(fingerprints) != 1 or len(resource_types) != 1 or len(action_types) != 1:
            return None
        releases = {(case.fdai_revision, case.scenario_set_version) for case in cases}
        if len(releases) != 1:
            return None
        review_time = reviewed_at or max(case.event_time_cutoff for case in cases)
        if review_time.tzinfo is None or max_case_age <= timedelta(0):
            raise ValueError("operational pattern review bounds are invalid")
        if any(
            not case.evidence_complete
            or case.conflict_digests
            or (case.source_kind is OperationalEvidenceSourceKind.LIVE and case.source_synthetic)
            or case.event_time_cutoff > review_time
            or review_time - case.event_time_cutoff > max_case_age
            for case in cases
        ):
            return None
        reusable = sum(case.reusable for case in cases)
        negative = sum(case.negative for case in cases)
        if reusable < 1 or negative < 1:
            return None
        immutable_case_refs = tuple(sorted({case.immutable_case_ref for case in cases}))
        if len(immutable_case_refs) != len(cases):
            return None
        digest_evidence = tuple(
            sorted({digest for case in cases for digest in case.digest_evidence})
        )
        if len(digest_evidence) > _MAX_PATTERN_EVIDENCE_REFS:
            raise ValueError("operational pattern evidence exceeds its aggregate limit")
        outcome_counts = tuple(sorted(Counter(case.outcome_class.value for case in cases).items()))
        case_reviews: tuple[dict[str, object], ...] = tuple(
            {
                "case_ref": case.immutable_case_ref,
                "event_time_cutoff": case.event_time_cutoff.isoformat(),
                "source_kind": case.source_kind.value,
                "source_identity_digest": case.source_identity_digest,
                "source_synthetic": case.source_synthetic,
                "evidence_complete": case.evidence_complete,
                "conflict_digests": list(case.conflict_digests),
            }
            for case in sorted(cases, key=lambda item: item.immutable_case_ref)
        )
        fdai_revision, scenario_set_version = next(iter(releases))
        material = {
            "action_type": cases[0].action_type,
            "digest_evidence": digest_evidence,
            "failure_fingerprint": cases[0].failure_fingerprint,
            "immutable_case_refs": immutable_case_refs,
            "outcome_counts": outcome_counts,
            "resource_type": cases[0].resource_type,
            "fdai_revision": fdai_revision,
            "scenario_set_version": scenario_set_version,
            "case_reviews": case_reviews,
        }
        pattern_id = hashlib.sha256(
            json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        return OperatingPatternCandidate(
            pattern_id=pattern_id,
            failure_fingerprint=cases[0].failure_fingerprint,
            resource_type=cases[0].resource_type,
            action_type=cases[0].action_type,
            sample_size=len(cases),
            reusable_count=reusable,
            negative_count=negative,
            outcome_counts=outcome_counts,
            immutable_case_refs=immutable_case_refs,
            digest_evidence=digest_evidence,
            fdai_revision=fdai_revision,
            scenario_set_version=scenario_set_version,
            case_reviews=case_reviews,
        )


def pattern_case_from_operational_case(
    case_input: OperationalCaseInput,
    projection: OperationalCaseProjection,
) -> PatternCase | None:
    """Classify only sealed, verified operational cases for cohort learning."""
    if (
        projection.failure_fingerprint.digest != case_input.failure_fingerprint.digest
        or projection.action_type != case_input.action_type
        or projection.outcome_class is not case_input.outcome_class
    ):
        raise ValueError("operational case projection does not match its sealed input")
    if case_input.outcome_class is OperationalOutcomeClass.SUCCESS:
        receipt_facts = {
            receipt.receipt_type: dict(receipt.facts)
            for receipt in sorted(
                case_input.receipts,
                key=lambda item: (item.occurred_at, item.receipt_digest),
            )
        }
        audit = receipt_facts[OperationalReceiptType.AUDIT]
        response = receipt_facts[OperationalReceiptType.RESPONSE_OUTCOME]
        evaluation = receipt_facts.get(OperationalReceiptType.EVALUATION)
        reusable = (
            audit.get("mode") == "enforce"
            and response.get("label") == "verified"
            and response.get("verification_status") == "verified"
            and response.get("rollback_succeeded") is False
            and (
                evaluation is None
                or (
                    evaluation.get("validation_status") == "accepted"
                    and evaluation.get("operationalized") is True
                )
            )
        )
        if not reusable:
            return None
    elif case_input.outcome_class not in _NEGATIVE_OUTCOMES:
        return None
    return PatternCase(
        case_id=projection.case_id,
        revision=projection.case_revision,
        manifest_digest=projection.manifest_digest,
        failure_fingerprint=projection.failure_fingerprint.digest,
        resource_type=projection.failure_fingerprint.resource_type,
        action_type=projection.action_type,
        outcome_class=projection.outcome_class,
        reusable=projection.outcome_class is OperationalOutcomeClass.SUCCESS,
        negative=projection.outcome_class in _NEGATIVE_OUTCOMES,
        digest_evidence=case_input.evidence_refs,
        fdai_revision=projection.fdai_revision,
        scenario_set_version=projection.scenario_set_version,
        event_time_cutoff=projection.event_time_cutoff,
        source_kind=projection.source_kind,
        source_identity_digest=projection.source_identity_digest,
        source_synthetic=projection.source_synthetic,
        evidence_complete=projection.evidence_complete,
        conflict_digests=projection.conflict_digests,
    )


def _required(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"pattern case field {key!r} MUST be non-empty")
    return item


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _required_datetime(value: Mapping[str, object], key: str) -> datetime:
    raw = _required(value, key)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"pattern case field {key!r} MUST be timezone-aware")
    return parsed


def _string_array(value: Mapping[str, object], key: str) -> tuple[str, ...]:
    raw = value.get(key)
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise ValueError(f"pattern case field {key!r} MUST be an array")
    if any(not isinstance(item, str) for item in raw):
        raise ValueError(f"pattern case field {key!r} MUST contain strings")
    return tuple(raw)


__all__ = [
    "OperatingPatternCandidate",
    "OperatingPatternCompiler",
    "PatternCase",
    "pattern_case_from_operational_case",
]
