"""Compile sealed O2 pattern candidates into inert catalog review packages."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Protocol, TypeGuard

from fdai.core.case_history import OperationalOutcomeClass
from fdai.shared.contracts.models import Autonomy, Mode, OntologyActionType

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MAX_CASES = 100
_MAX_DIGEST_EVIDENCE = 256
_MAX_CANDIDATE_BYTES = 256 * 1024
_MAX_VERSION_LENGTH = 128
_CANDIDATE_FIELDS = frozenset(
    {
        "source_signal",
        "evidence",
        "provenance",
        "proposed_by",
        "proposal_kind",
        "target_rule_id",
        "suggested_pattern",
    }
)
_TRANSPORT_FIELDS = frozenset(
    {
        "producer_principal",
        "correlation_id",
        "idempotency_key",
        "envelope_schema_version",
        "schema_version",
        "norns_consensus",
    }
)
_EVIDENCE_FIELDS = frozenset(
    {
        "sample_size",
        "reusable_count",
        "negative_count",
        "outcome_counts",
        "failure_fingerprint",
        "resource_type",
        "action_type",
        "immutable_case_refs",
        "digest_evidence",
    }
)
_PROVENANCE_FIELDS = frozenset({"source", "pattern_id"})
_CONSENSUS_FIELDS = frozenset({"decision", "unanimous", "perspective_count", "reason_codes"})
_CONSENSUS_REASONS = (
    "historical_evidence_grounded",
    "current_contract_valid",
    "future_safety_preserved",
)
_NEGATIVE_OUTCOMES = frozenset(
    {
        OperationalOutcomeClass.FAILURE.value,
        OperationalOutcomeClass.REFUSAL.value,
        OperationalOutcomeClass.NO_OP.value,
        OperationalOutcomeClass.ROLLBACK.value,
        OperationalOutcomeClass.RECURRENCE.value,
    }
)


class CatalogCompilationError(ValueError):
    """Bounded fail-closed reason for one rejected catalog candidate."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ImmutableCaseRef:
    case_id: str
    revision: int
    manifest_digest: str

    @classmethod
    def parse(cls, value: object) -> ImmutableCaseRef:
        if not isinstance(value, str) or len(value) > 320:
            raise CatalogCompilationError("immutable_case_refs_invalid")
        parts = value.split(":")
        if len(parts) != 4 or parts[0] != "case-history":
            raise CatalogCompilationError("immutable_case_refs_invalid")
        case_id, revision_text, manifest_digest = parts[1:]
        if (
            not case_id
            or len(case_id) > 128
            or _IDENTIFIER.fullmatch(case_id) is None
            or not revision_text.isascii()
            or not revision_text.isdecimal()
            or int(revision_text) < 1
            or _SHA256.fullmatch(manifest_digest) is None
        ):
            raise CatalogCompilationError("immutable_case_refs_invalid")
        return cls(
            case_id=case_id,
            revision=int(revision_text),
            manifest_digest=manifest_digest,
        )

    @property
    def value(self) -> str:
        return f"case-history:{self.case_id}:{self.revision}:{self.manifest_digest}"


@dataclass(frozen=True, slots=True)
class OperationalPatternRuleCandidate:
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
    digest: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> OperationalPatternRuleCandidate:
        if len(_canonical_json(raw).encode()) > _MAX_CANDIDATE_BYTES:
            raise CatalogCompilationError("candidate_wire_too_large")
        if set(raw) - _TRANSPORT_FIELDS != _CANDIDATE_FIELDS:
            raise CatalogCompilationError("candidate_schema_invalid")
        if (
            raw.get("source_signal") != "operational_case_fingerprint_cohort"
            or raw.get("proposed_by") != "Norns"
            or raw.get("proposal_kind") != "new"
        ):
            raise CatalogCompilationError("candidate_schema_invalid")
        consensus = raw.get("norns_consensus")
        if (
            raw.get("producer_principal") != "Norns"
            or not isinstance(consensus, Mapping)
            or set(consensus) != _CONSENSUS_FIELDS
            or consensus.get("decision") != "propose"
            or consensus.get("unanimous") is not True
            or consensus.get("perspective_count") != 3
            or consensus.get("reason_codes") != list(_CONSENSUS_REASONS)
        ):
            raise CatalogCompilationError("candidate_consensus_invalid")
        evidence = raw.get("evidence")
        provenance = raw.get("provenance")
        if not isinstance(evidence, Mapping) or set(evidence) != _EVIDENCE_FIELDS:
            raise CatalogCompilationError("candidate_schema_invalid")
        if not isinstance(provenance, Mapping) or set(provenance) != _PROVENANCE_FIELDS:
            raise CatalogCompilationError("candidate_schema_invalid")
        if provenance.get("source") != "case-history":
            raise CatalogCompilationError("candidate_provenance_invalid")

        pattern_id = _required_sha256(provenance, "pattern_id", "candidate_provenance_invalid")
        if raw.get("suggested_pattern") != pattern_id:
            raise CatalogCompilationError("candidate_digest_conflict")
        failure_fingerprint = _required_sha256(
            evidence, "failure_fingerprint", "candidate_schema_invalid"
        )
        resource_type = _required_identifier(evidence, "resource_type")
        action_type = _required_identifier(evidence, "action_type")
        if raw.get("target_rule_id") != action_type:
            raise CatalogCompilationError("candidate_action_type_conflict")

        sample_size = _bounded_positive_int(evidence.get("sample_size"), maximum=_MAX_CASES)
        reusable_count = _bounded_positive_int(evidence.get("reusable_count"), maximum=sample_size)
        negative_count = _bounded_positive_int(evidence.get("negative_count"), maximum=sample_size)
        if reusable_count + negative_count != sample_size:
            raise CatalogCompilationError("candidate_count_conflict")

        outcome_counts = _parse_outcome_counts(evidence.get("outcome_counts"))
        counts = dict(outcome_counts)
        if (
            sum(counts.values()) != sample_size
            or counts.get(OperationalOutcomeClass.SUCCESS.value, 0) != reusable_count
            or sum(counts.get(name, 0) for name in _NEGATIVE_OUTCOMES) != negative_count
        ):
            raise CatalogCompilationError("candidate_count_conflict")

        case_refs = _parse_case_refs(evidence.get("immutable_case_refs"), sample_size)
        digest_evidence = _parse_digests(
            evidence.get("digest_evidence"),
            maximum=_MAX_DIGEST_EVIDENCE,
            code="digest_evidence_invalid",
        )
        expected_pattern_id = _pattern_id(
            action_type=action_type,
            digest_evidence=digest_evidence,
            failure_fingerprint=failure_fingerprint,
            immutable_case_refs=case_refs,
            outcome_counts=outcome_counts,
            resource_type=resource_type,
        )
        if pattern_id != expected_pattern_id:
            raise CatalogCompilationError("candidate_digest_conflict")

        material = {
            "action_type": action_type,
            "digest_evidence": digest_evidence,
            "failure_fingerprint": failure_fingerprint,
            "immutable_case_refs": case_refs,
            "negative_count": negative_count,
            "outcome_counts": outcome_counts,
            "pattern_id": pattern_id,
            "resource_type": resource_type,
            "reusable_count": reusable_count,
            "sample_size": sample_size,
        }
        return cls(
            pattern_id=pattern_id,
            failure_fingerprint=failure_fingerprint,
            resource_type=resource_type,
            action_type=action_type,
            sample_size=sample_size,
            reusable_count=reusable_count,
            negative_count=negative_count,
            outcome_counts=outcome_counts,
            immutable_case_refs=case_refs,
            digest_evidence=digest_evidence,
            digest=_digest(material),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "pattern_id": self.pattern_id,
            "failure_fingerprint": self.failure_fingerprint,
            "resource_type": self.resource_type,
            "action_type": self.action_type,
            "sample_size": self.sample_size,
            "reusable_count": self.reusable_count,
            "negative_count": self.negative_count,
            "outcome_counts": dict(self.outcome_counts),
            "immutable_case_refs": list(self.immutable_case_refs),
            "digest_evidence": list(self.digest_evidence),
        }


@dataclass(frozen=True, slots=True)
class DraftCatalogArtifact:
    kind: str
    canonical_json: str
    digest: str

    @classmethod
    def from_mapping(cls, *, kind: str, mapping: Mapping[str, object]) -> DraftCatalogArtifact:
        canonical_json = _canonical_json(mapping)
        return cls(kind=kind, canonical_json=canonical_json, digest=_sha256(canonical_json))

    @property
    def mapping(self) -> dict[str, object]:
        value = json.loads(self.canonical_json)
        if not isinstance(value, dict):
            raise AssertionError("canonical catalog artifact MUST decode to an object")
        return value


@dataclass(frozen=True, slots=True)
class DraftActionTypeInput:
    """Explicit typed action semantics; none are inferred from case outcomes."""

    declaration: OntologyActionType

    def __post_init__(self) -> None:
        declaration = self.declaration
        ceilings = declaration.ceiling_by_tier
        if declaration.default_mode is not Mode.SHADOW:
            raise ValueError("draft ActionType MUST remain shadow-first")
        if declaration.promotion_gate.max_policy_escapes != 0:
            raise ValueError("draft ActionType MUST allow zero policy escapes")
        if (
            not declaration.preconditions
            or not declaration.stop_conditions
            or declaration.blast_radius is None
            or declaration.category is None
            or declaration.trigger_kind is None
            or declaration.execution_path is None
            or ceilings is None
            or ceilings.t0 is None
            or ceilings.t1 is None
            or ceilings.t2 is None
        ):
            raise ValueError("draft ActionType MUST declare its complete safety contract")
        if (
            ceilings.t0.max_autonomy is Autonomy.ENFORCE_AUTO
            or ceilings.t1.max_autonomy is not Autonomy.SHADOW_ONLY
            or ceilings.t2.max_autonomy is not Autonomy.SHADOW_ONLY
        ):
            raise ValueError("draft ActionType tier ceilings MUST remain shadow-first")

    def to_artifact(self) -> DraftCatalogArtifact:
        return DraftCatalogArtifact.from_mapping(
            kind="action_type",
            mapping=self.declaration.model_dump(mode="json", exclude_none=True),
        )


@dataclass(frozen=True, slots=True)
class CatalogValidationRequest:
    candidate: OperationalPatternRuleCandidate
    draft_rule: DraftCatalogArtifact
    draft_action_type: DraftCatalogArtifact | None
    catalog_version: str
    schema_version: str
    artifact_digest: str


@dataclass(frozen=True, slots=True)
class SchemaCheckReceipt:
    candidate_digest: str
    artifact_digest: str
    schema_version: str
    passed: bool


@dataclass(frozen=True, slots=True)
class ReplayCheckReceipt:
    candidate_digest: str
    artifact_digest: str
    replay_version: str
    first_result_digest: str
    second_result_digest: str
    passed: bool


@dataclass(frozen=True, slots=True)
class ShadowCheckReceipt:
    candidate_digest: str
    artifact_digest: str
    scenario_set_id: str
    baseline_result_digest: str
    challenger_result_digest: str
    regression_passed: bool
    policy_escapes: int
    passed: bool


@dataclass(frozen=True, slots=True)
class PolicyCheckReceipt:
    candidate_digest: str
    artifact_digest: str
    policy_version: str
    policy_escapes: int
    passed: bool


@dataclass(frozen=True, slots=True)
class CatalogCheckReceipts:
    schema: SchemaCheckReceipt
    replay: ReplayCheckReceipt
    shadow: ShadowCheckReceipt
    policy: PolicyCheckReceipt


class CatalogValidator(Protocol):
    def validate(self, request: CatalogValidationRequest) -> CatalogCheckReceipts: ...


@dataclass(frozen=True, slots=True)
class CatalogReviewPackage:
    candidate: OperationalPatternRuleCandidate
    draft_rule: DraftCatalogArtifact
    draft_action_type: DraftCatalogArtifact | None
    immutable_case_refs: tuple[str, ...]
    catalog_version: str
    schema_version: str
    schema: SchemaCheckReceipt
    replay: ReplayCheckReceipt
    shadow: ShadowCheckReceipt
    policy: PolicyCheckReceipt
    review_required: bool
    content_digest: str

    @classmethod
    def build(
        cls,
        *,
        request: CatalogValidationRequest,
        receipts: CatalogCheckReceipts,
    ) -> CatalogReviewPackage:
        _validate_receipts(request, receipts)
        material = {
            "candidate": request.candidate.to_mapping(),
            "candidate_digest": request.candidate.digest,
            "draft_action_type": (
                None if request.draft_action_type is None else request.draft_action_type.mapping
            ),
            "draft_rule": request.draft_rule.mapping,
            "immutable_case_refs": request.candidate.immutable_case_refs,
            "catalog_version": request.catalog_version,
            "schema_version": request.schema_version,
            "schema": asdict(receipts.schema),
            "replay": asdict(receipts.replay),
            "shadow": asdict(receipts.shadow),
            "policy": asdict(receipts.policy),
            "review_required": True,
        }
        return cls(
            candidate=request.candidate,
            draft_rule=request.draft_rule,
            draft_action_type=request.draft_action_type,
            immutable_case_refs=request.candidate.immutable_case_refs,
            catalog_version=request.catalog_version,
            schema_version=request.schema_version,
            schema=receipts.schema,
            replay=receipts.replay,
            shadow=receipts.shadow,
            policy=receipts.policy,
            review_required=True,
            content_digest=_digest(material),
        )


class CatalogCandidateCompiler:
    """Build an inert package and delegate every authority check."""

    def __init__(
        self,
        *,
        validator: CatalogValidator,
        catalog_version: str,
        schema_version: str,
    ) -> None:
        if not catalog_version or not schema_version:
            raise ValueError("catalog and schema versions MUST be non-empty")
        self._validator = validator
        self._catalog_version = catalog_version
        self._schema_version = schema_version

    def compile(
        self,
        raw_candidate: Mapping[str, object],
        *,
        draft_action_type: DraftActionTypeInput | None = None,
    ) -> CatalogReviewPackage:
        candidate = OperationalPatternRuleCandidate.from_mapping(raw_candidate)
        action_artifact = None
        if draft_action_type is not None:
            if draft_action_type.declaration.name != candidate.action_type:
                raise CatalogCompilationError("candidate_action_type_conflict")
            action_artifact = draft_action_type.to_artifact()
        rule_artifact = _compile_rule(candidate)
        artifact_digest = _digest(
            {
                "draft_action_type_digest": (
                    None if action_artifact is None else action_artifact.digest
                ),
                "draft_rule_digest": rule_artifact.digest,
            }
        )
        request = CatalogValidationRequest(
            candidate=candidate,
            draft_rule=rule_artifact,
            draft_action_type=action_artifact,
            catalog_version=self._catalog_version,
            schema_version=self._schema_version,
            artifact_digest=artifact_digest,
        )
        receipts = self._validator.validate(request)
        return CatalogReviewPackage.build(request=request, receipts=receipts)


def _compile_rule(candidate: OperationalPatternRuleCandidate) -> DraftCatalogArtifact:
    rule_id = f"learned.operational.{candidate.pattern_id[:32]}"
    mapping: dict[str, object] = {
        "schema_version": "2.0.0",
        "id": rule_id,
        "version": "0.1.0",
        "source": "custom",
        "severity": "medium",
        "category": "reliability",
        "resource_type": candidate.resource_type,
        "check_logic": {
            "kind": "expression",
            "reference": f"review-required:{candidate.pattern_id}",
        },
        "remediation": {
            "template_ref": f"review-required:{candidate.action_type}",
            "cost_impact_monthly_usd": None,
        },
        "remediates": candidate.action_type,
        "alternatives": [],
        "parameters": {},
        "provenance": {
            "source_url": f"urn:fdai:operational-pattern:{candidate.pattern_id}",
            "resolved_ref": f"sha256:{candidate.digest}",
            "content_hash": f"sha256:{candidate.digest}",
            "license": "LicenseRef-reference-only",
            "redistribution": "reference-only",
            "retrieved_at": "1970-01-01T00:00:00Z",
            "mapped_by": "fdai.operational_learning.catalog",
        },
        "applies_to": [candidate.resource_type],
        "triggered_by": ["*"],
        "evaluates": ["*"],
        "required_interfaces": ["Evaluable", "Remediable"],
        "submission_criteria": [
            {"kind": "resource_type_registered", "value": candidate.resource_type}
        ],
        "scope_predicates": {},
    }
    return DraftCatalogArtifact.from_mapping(kind="rule", mapping=mapping)


def _validate_receipts(
    request: CatalogValidationRequest,
    receipts: CatalogCheckReceipts,
) -> None:
    for name in ("schema", "replay", "shadow", "policy"):
        receipt = getattr(receipts, name, None)
        if receipt is None:
            raise CatalogCompilationError(f"{name}_check_absent")
        if (
            receipt.candidate_digest != request.candidate.digest
            or receipt.artifact_digest != request.artifact_digest
        ):
            raise CatalogCompilationError("check_receipt_conflict")
        if receipt.passed is not True:
            raise CatalogCompilationError(f"{name}_check_failed")
    if receipts.schema.schema_version != request.schema_version:
        raise CatalogCompilationError("check_receipt_conflict")
    for digest_value in (
        receipts.replay.first_result_digest,
        receipts.replay.second_result_digest,
        receipts.shadow.baseline_result_digest,
        receipts.shadow.challenger_result_digest,
    ):
        if not isinstance(digest_value, str) or _SHA256.fullmatch(digest_value) is None:
            raise CatalogCompilationError("check_receipt_invalid")
    for version_value in (
        receipts.replay.replay_version,
        receipts.shadow.scenario_set_id,
        receipts.policy.policy_version,
    ):
        if (
            not isinstance(version_value, str)
            or not version_value
            or len(version_value) > _MAX_VERSION_LENGTH
        ):
            raise CatalogCompilationError("check_receipt_invalid")
    if receipts.shadow.regression_passed is not True:
        raise CatalogCompilationError("shadow_regression")
    for escape_count in (receipts.shadow.policy_escapes, receipts.policy.policy_escapes):
        if isinstance(escape_count, bool) or not isinstance(escape_count, int) or escape_count < 0:
            raise CatalogCompilationError("check_receipt_invalid")
    if receipts.replay.first_result_digest != receipts.replay.second_result_digest:
        raise CatalogCompilationError("replay_non_deterministic")
    if receipts.shadow.policy_escapes != 0 or receipts.policy.policy_escapes != 0:
        raise CatalogCompilationError("policy_escape")


def _parse_case_refs(value: object, sample_size: int) -> tuple[str, ...]:
    if not _is_sequence(value) or len(value) != sample_size:
        raise CatalogCompilationError("immutable_case_refs_invalid")
    parsed = tuple(ImmutableCaseRef.parse(item) for item in value)
    identities: dict[str, tuple[int, str]] = {}
    for item in parsed:
        identity = (item.revision, item.manifest_digest)
        prior = identities.setdefault(item.case_id, identity)
        if prior != identity:
            raise CatalogCompilationError("immutable_case_refs_conflict")
    refs = tuple(sorted({item.value for item in parsed}))
    if len(refs) != sample_size or len(identities) != sample_size:
        raise CatalogCompilationError("immutable_case_refs_conflict")
    return refs


def _parse_digests(value: object, *, maximum: int, code: str) -> tuple[str, ...]:
    if not _is_sequence(value) or not 1 <= len(value) <= maximum:
        raise CatalogCompilationError(code)
    digests: list[str] = []
    for item in value:
        if not isinstance(item, str) or _SHA256.fullmatch(item) is None:
            raise CatalogCompilationError(code)
        digests.append(item)
    return tuple(sorted(set(digests)))


def _parse_outcome_counts(value: object) -> tuple[tuple[str, int], ...]:
    allowed = {item.value for item in OperationalOutcomeClass}
    if not isinstance(value, Mapping) or not value or set(value) - allowed:
        raise CatalogCompilationError("candidate_count_conflict")
    counts: list[tuple[str, int]] = []
    for name, count in value.items():
        counts.append((str(name), _bounded_positive_int(count, maximum=_MAX_CASES)))
    return tuple(sorted(counts))


def _pattern_id(
    *,
    action_type: str,
    digest_evidence: tuple[str, ...],
    failure_fingerprint: str,
    immutable_case_refs: tuple[str, ...],
    outcome_counts: tuple[tuple[str, int], ...],
    resource_type: str,
) -> str:
    return _digest(
        {
            "action_type": action_type,
            "digest_evidence": digest_evidence,
            "failure_fingerprint": failure_fingerprint,
            "immutable_case_refs": immutable_case_refs,
            "outcome_counts": outcome_counts,
            "resource_type": resource_type,
        }
    )


def _required_sha256(value: Mapping[str, object], key: str, code: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or _SHA256.fullmatch(item) is None:
        raise CatalogCompilationError(code)
    return item


def _required_identifier(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or len(item) > 128 or _IDENTIFIER.fullmatch(item) is None:
        raise CatalogCompilationError("candidate_schema_invalid")
    return item


def _bounded_positive_int(value: object, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise CatalogCompilationError("candidate_count_conflict")
    return value


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes)


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CatalogCompilationError("candidate_schema_invalid") from exc


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _digest(value: object) -> str:
    return _sha256(_canonical_json(value))


__all__ = [
    "CatalogCandidateCompiler",
    "CatalogCheckReceipts",
    "CatalogCompilationError",
    "CatalogReviewPackage",
    "CatalogValidationRequest",
    "CatalogValidator",
    "DraftActionTypeInput",
    "DraftCatalogArtifact",
    "ImmutableCaseRef",
    "OperationalPatternRuleCandidate",
    "PolicyCheckReceipt",
    "ReplayCheckReceipt",
    "SchemaCheckReceipt",
    "ShadowCheckReceipt",
]
