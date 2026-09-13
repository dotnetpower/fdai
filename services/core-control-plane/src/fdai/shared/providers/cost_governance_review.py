"""Authority-neutral independent reviews for Cost Governance W7 evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


class CostReviewTargetKind(StrEnum):
    """Kinds that require separate Cost Governance review decisions."""

    PACKAGE_ACTIVATION = "package-activation"
    ACTION_TYPE = "action-type"
    WORKFLOW = "workflow"


class CostReviewDecision(StrEnum):
    """Review-only decisions that grant no lifecycle or action authority."""

    RECOMMEND = "recommend"
    HOLD = "hold"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class CostPromotionReview:
    """One append-only human review of one exact campaign target."""

    schema_version: str
    request_id: str
    campaign_id: str
    campaign_evidence_digest: str
    revision_pin_digest: str
    campaign_report_digest: str
    target_kind: CostReviewTargetKind
    target_id: str
    reviewer_identity: str
    decision: CostReviewDecision
    rationale: str
    reviewed_at: datetime
    evidence_refs: tuple[str, ...]
    retention_until: datetime
    approval_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("Cost review schema_version MUST be 1.0.0")
        for name in ("request_id", "reviewer_identity", "rationale"):
            _bounded_ascii(name, getattr(self, name), maximum=2_000)
        for name in ("campaign_id", "target_id"):
            value = getattr(self, name)
            if len(value) > 512 or _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"{name} MUST be a canonical identifier")
        if (
            self.target_kind is CostReviewTargetKind.PACKAGE_ACTIVATION
            and self.target_id != "cost-governance"
        ):
            raise ValueError("package activation review MUST target cost-governance")
        _require_digest("campaign_evidence_digest", self.campaign_evidence_digest)
        _require_digest("revision_pin_digest", self.revision_pin_digest)
        _require_digest("campaign_report_digest", self.campaign_report_digest)
        _aware("reviewed_at", self.reviewed_at)
        _aware("retention_until", self.retention_until)
        if self.retention_until <= self.reviewed_at:
            raise ValueError("Cost review retention MUST follow review time")
        refs = tuple(dict.fromkeys(self.evidence_refs))
        if not 1 <= len(refs) <= 64:
            raise ValueError("Cost review evidence_refs MUST contain 1..64 unique values")
        for ref in refs:
            _bounded_ascii("evidence_ref", ref, maximum=512)
        object.__setattr__(self, "evidence_refs", refs)
        if (
            self.approval_authority is not False
            or self.execution_authority is not False
            or self.promotion_authority is not False
        ):
            raise ValueError("Cost review authority flags MUST be False")

    @property
    def review_id(self) -> str:
        """Return the content-addressed review identity."""

        return self.digest

    @property
    def digest(self) -> str:
        """Return the canonical immutable review digest."""

        encoded = json.dumps(
            self.to_mapping(),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical authority-neutral review payload."""

        return {
            "approval_authority": self.approval_authority,
            "campaign_id": self.campaign_id,
            "campaign_evidence_digest": self.campaign_evidence_digest,
            "campaign_report_digest": self.campaign_report_digest,
            "decision": self.decision.value,
            "evidence_refs": list(self.evidence_refs),
            "execution_authority": self.execution_authority,
            "promotion_authority": self.promotion_authority,
            "rationale": self.rationale,
            "request_id": self.request_id,
            "reviewed_at": self.reviewed_at.isoformat(),
            "reviewer_identity": self.reviewer_identity,
            "retention_until": self.retention_until.isoformat(),
            "revision_pin_digest": self.revision_pin_digest,
            "schema_version": self.schema_version,
            "target_id": self.target_id,
            "target_kind": self.target_kind.value,
        }


class CostPromotionReviewStore(Protocol):
    """Append and read review-only records without promotion authority."""

    async def append_cost_promotion_review(
        self,
        review: CostPromotionReview,
    ) -> tuple[CostPromotionReview, bool]: ...

    async def read_cost_promotion_reviews(
        self,
        *,
        campaign_id: str,
        revision_pin_digest: str,
        limit: int,
    ) -> tuple[CostPromotionReview, ...]: ...


def _bounded_ascii(name: str, value: str, *, maximum: int) -> None:
    if not value or not value.isascii() or len(value) > maximum:
        raise ValueError(f"{name} MUST be bounded non-empty ASCII")


def _require_digest(name: str, value: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} MUST use sha256:<digest>")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "CostPromotionReview",
    "CostPromotionReviewStore",
    "CostReviewDecision",
    "CostReviewTargetKind",
]
