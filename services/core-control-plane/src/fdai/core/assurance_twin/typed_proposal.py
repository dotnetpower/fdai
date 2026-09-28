"""FDAI-owned typed ActionType proposal evidence for Assurance Twin reviews.

Forseti reviews FDAI's own typed change proposals. One review input binds an exact
ActionType id and version, exact target Resource refs, canonical parameters, and one
what-if or dry-run result bound to the same content-addressed proposal digest.

Terraform is a local deployment tool. A Terraform plan, rendered IaC template, or
pull-request diff is never a governance or review input (owner decision 2026-09-28).
None of these values carries approval, execution, or promotion authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.projection import ResourceRef

PROPOSAL_REF_PREFIX = "action-proposal:"
TYPED_PROPOSAL_EVIDENCE_KIND = "typed_action_proposal"
#: The authority class the T2 quality gate already requires for what-if evidence.
WHAT_IF_SOURCE_AUTHORITY = "simulation_engine"
MAX_PROPOSAL_TARGETS = 25
MAX_WHAT_IF_WINDOW = timedelta(minutes=30)
ACTION_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_\.\-]{0,79}$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_MAX_PARAMETER_BYTES = 16_384
_MAX_REFS = 64
_MAX_TEXT = 512


def canonical_digest(value: object) -> str:
    """Return the SHA-256 content address of one canonical JSON value."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def is_digest(value: object) -> bool:
    """Return whether ``value`` is one lowercase ``sha256:`` digest."""

    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def canonical_targets(targets: Iterable[ResourceRef]) -> tuple[ResourceRef, ...]:
    """Return unique targets in deterministic ``(resource_type, ref)`` order."""

    return tuple(sorted(set(targets), key=lambda item: (item.resource_type, item.ref)))


def target_material(targets: tuple[ResourceRef, ...]) -> list[list[str]]:
    """Return the JSON material that content-addresses an exact target set."""

    return [[target.resource_type, target.ref] for target in targets]


class WhatIfStatus(StrEnum):
    """Outcome reported by the independent what-if or dry-run producer."""

    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class TypedActionProposal:
    """One content-addressed ActionType proposal; never a verdict or approval."""

    action_type: str
    action_type_version: str
    targets: tuple[ResourceRef, ...]
    parameters_json: str
    parameters_digest: str
    proposal_digest: str

    @classmethod
    def create(
        cls,
        *,
        action_type: str,
        action_type_version: str,
        targets: Iterable[ResourceRef],
        parameters: Mapping[str, Any],
    ) -> TypedActionProposal:
        """Canonicalize exact inputs into their content-addressed proposal."""

        try:
            parameters_json = json.dumps(
                dict(parameters),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("typed proposal parameters MUST be canonical JSON") from exc
        ordered = tuple(targets)
        parameters_digest = canonical_digest(json.loads(parameters_json))
        return cls(
            action_type=action_type,
            action_type_version=action_type_version,
            targets=ordered,
            parameters_json=parameters_json,
            parameters_digest=parameters_digest,
            proposal_digest=_proposal_digest(
                action_type, action_type_version, ordered, parameters_digest
            ),
        )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.action_type, str)
            or ACTION_TYPE_PATTERN.fullmatch(self.action_type) is None
        ):
            raise ValueError("typed proposal action_type MUST be a canonical ActionType id")
        if (
            not isinstance(self.action_type_version, str)
            or SEMVER_PATTERN.fullmatch(self.action_type_version) is None
        ):
            raise ValueError("typed proposal action_type_version MUST use MAJOR.MINOR.PATCH")
        if (
            not self.targets
            or len(self.targets) > MAX_PROPOSAL_TARGETS
            or any(not isinstance(target, ResourceRef) for target in self.targets)
            or self.targets != canonical_targets(self.targets)
        ):
            raise ValueError("typed proposal targets MUST be bounded, unique, and ordered")
        if len(self.parameters_json.encode("utf-8")) > _MAX_PARAMETER_BYTES:
            raise ValueError("typed proposal parameters exceed their canonical byte bound")
        if self.parameters_digest != canonical_digest(_decode_parameters(self.parameters_json)):
            raise ValueError("typed proposal parameters digest does not match its content")
        if self.proposal_digest != _proposal_digest(
            self.action_type,
            self.action_type_version,
            self.targets,
            self.parameters_digest,
        ):
            raise ValueError("typed proposal digest does not match its content")

    @property
    def proposal_ref(self) -> str:
        """Opaque change handle rendered by read-only review surfaces."""

        return PROPOSAL_REF_PREFIX + self.proposal_digest.removeprefix("sha256:")

    def parameters(self) -> dict[str, Any]:
        """Return a fresh copy of the exact canonical parameters."""

        return _decode_parameters(self.parameters_json)


@dataclass(frozen=True, slots=True)
class ProposalWhatIfResult:
    """One what-if or dry-run outcome bound to an exact proposal digest.

    Construction validates shape only. Status, completeness, freshness, and target
    agreement are review-admission decisions, so an incomplete or conflicting
    result stays representable and is rejected explicitly by the Twin review.
    """

    proposal_digest: str
    status: WhatIfStatus
    complete: bool
    synthetic: bool
    source_authority: str
    producer_id: str
    observed_at: datetime
    expires_at: datetime
    affected_targets: tuple[ResourceRef, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not is_digest(self.proposal_digest):
            raise ValueError("what-if proposal_digest MUST be a SHA-256 digest")
        if not isinstance(self.status, WhatIfStatus):
            raise ValueError("what-if status MUST be a WhatIfStatus")
        if not isinstance(self.complete, bool) or not isinstance(self.synthetic, bool):
            raise ValueError("what-if completeness flags MUST be booleans")
        if not _bounded_text(self.source_authority) or not _bounded_text(self.producer_id, 128):
            raise ValueError("what-if producer identity MUST be bounded text")
        if (
            self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
        ):
            raise ValueError("what-if timestamps MUST be timezone-aware")
        if self.expires_at < self.observed_at:
            raise ValueError("what-if expires_at MUST NOT precede observed_at")
        if (
            len(self.affected_targets) > MAX_PROPOSAL_TARGETS
            or any(not isinstance(target, ResourceRef) for target in self.affected_targets)
            or self.affected_targets != canonical_targets(self.affected_targets)
        ):
            raise ValueError("what-if affected_targets MUST be bounded, unique, and ordered")
        if (
            len(self.evidence_refs) > _MAX_REFS
            or len(set(self.evidence_refs)) != len(self.evidence_refs)
            or any(not _bounded_text(ref) for ref in self.evidence_refs)
        ):
            raise ValueError("what-if evidence refs MUST be bounded and unique")

    @property
    def what_if_digest(self) -> str:
        """Content address of every field the review relies on."""

        return canonical_digest(
            {
                "proposal_digest": self.proposal_digest,
                "status": self.status.value,
                "complete": self.complete,
                "synthetic": self.synthetic,
                "source_authority": self.source_authority,
                "producer_id": self.producer_id,
                "observed_at": self.observed_at.astimezone(UTC).isoformat(),
                "expires_at": self.expires_at.astimezone(UTC).isoformat(),
                "affected_targets": target_material(self.affected_targets),
                "evidence_refs": list(self.evidence_refs),
            }
        )


@dataclass(frozen=True, slots=True)
class TypedProposalAssessment:
    """Retained typed-proposal readback that Forseti re-validates before writing."""

    source_revision: str
    proposal_ref: str
    action_type: str
    action_type_version: str
    proposal_digest: str
    parameters_digest: str
    targets: tuple[ResourceRef, ...]
    what_if_digest: str
    effect_digest: str
    change_digest: str
    inventory_revision: str
    evidence_refs: tuple[str, ...]
    complete: bool


def typed_proposal_admissible(
    assessment: object,
    *,
    source_revision: str,
    inventory_revision: str,
    review: IacReview,
) -> bool:
    """Return whether review evidence is one complete exact typed-proposal readback.

    The review body, the retained readback, and the Rule assessment must name the same
    proposal, what-if result, reviewed effect model, predicted change, and Inventory
    revision. The proposal digest is recomputed so a substituted target set fails, and
    findings may cite only the proposal's own targets.
    """

    if not isinstance(assessment, TypedProposalAssessment):
        return False
    digests = (
        assessment.proposal_digest,
        assessment.parameters_digest,
        assessment.what_if_digest,
        assessment.effect_digest,
        assessment.change_digest,
        assessment.inventory_revision,
    )
    try:
        targets_bound = (
            0 < len(assessment.targets) <= MAX_PROPOSAL_TARGETS
            and all(isinstance(target, ResourceRef) for target in assessment.targets)
            and assessment.targets == canonical_targets(assessment.targets)
            and all(finding.resource in assessment.targets for finding in review.findings)
        )
        identity_bound = (
            ACTION_TYPE_PATTERN.fullmatch(assessment.action_type) is not None
            and SEMVER_PATTERN.fullmatch(assessment.action_type_version) is not None
            and assessment.proposal_digest
            == _proposal_digest(
                assessment.action_type,
                assessment.action_type_version,
                assessment.targets,
                assessment.parameters_digest,
            )
        )
    except (AttributeError, TypeError, ValueError):
        return False
    required_refs = {
        assessment.proposal_digest,
        assessment.what_if_digest,
        assessment.effect_digest,
        assessment.change_digest,
    }
    metadata = review.metadata
    return (
        assessment.complete is True
        and targets_bound
        and identity_bound
        and all(is_digest(value) for value in digests)
        and assessment.source_revision == source_revision
        and assessment.inventory_revision == inventory_revision
        and assessment.proposal_ref
        == PROPOSAL_REF_PREFIX + assessment.proposal_digest.removeprefix("sha256:")
        and review.pr_ref == assessment.proposal_ref
        and all(_bounded_text(ref) for ref in assessment.evidence_refs)
        and required_refs <= set(assessment.evidence_refs)
        and metadata.get("evidence_kind") == TYPED_PROPOSAL_EVIDENCE_KIND
        and metadata.get("action_type") == assessment.action_type
        and metadata.get("action_type_version") == assessment.action_type_version
        and metadata.get("proposal_digest") == assessment.proposal_digest
        and metadata.get("what_if_digest") == assessment.what_if_digest
        and metadata.get("effect_digest") == assessment.effect_digest
        and metadata.get("change_digest") == assessment.change_digest
        and metadata.get("inventory_revision") == assessment.inventory_revision
    )


def _proposal_digest(
    action_type: str,
    action_type_version: str,
    targets: tuple[ResourceRef, ...],
    parameters_digest: str,
) -> str:
    return canonical_digest(
        {
            "schema": "assurance-twin.typed-action-proposal/1.0.0",
            "action_type": action_type,
            "action_type_version": action_type_version,
            "targets": target_material(targets),
            "parameters_digest": parameters_digest,
        }
    )


def _decode_parameters(parameters_json: str) -> dict[str, Any]:
    try:
        decoded = json.loads(parameters_json)
        canonical = json.dumps(
            decoded,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("typed proposal parameters MUST be canonical JSON") from exc
    if not isinstance(decoded, dict) or canonical != parameters_json:
        raise ValueError("typed proposal parameters MUST be one canonical JSON object")
    return decoded


def _bounded_text(value: object, limit: int = _MAX_TEXT) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


__all__ = [
    "ACTION_TYPE_PATTERN",
    "MAX_PROPOSAL_TARGETS",
    "MAX_WHAT_IF_WINDOW",
    "PROPOSAL_REF_PREFIX",
    "SEMVER_PATTERN",
    "TYPED_PROPOSAL_EVIDENCE_KIND",
    "WHAT_IF_SOURCE_AUTHORITY",
    "ProposalWhatIfResult",
    "TypedActionProposal",
    "TypedProposalAssessment",
    "WhatIfStatus",
    "canonical_digest",
    "canonical_targets",
    "is_digest",
    "target_material",
    "typed_proposal_admissible",
]
