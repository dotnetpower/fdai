"""Deployment-owned retention policy contracts for operational history."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class RetentionDeletionMethod(StrEnum):
    """Reviewed physical disposition for one fact family."""

    PARTITION_PURGE = "partition_purge"
    RETAIN = "retain"


@dataclass(frozen=True, slots=True)
class ObservationRetentionPolicy:
    """Deployment-owned retention and deletion policy for one fact family."""

    policy_id: str
    fact_family: str
    purpose: str
    hot_retention_seconds: int
    warm_retention_seconds: int
    archive_class: str
    deletion_method: RetentionDeletionMethod
    review_at: datetime
    digest: str

    def __post_init__(self) -> None:
        for name, value in (
            ("policy_id", self.policy_id),
            ("fact_family", self.fact_family),
            ("purpose", self.purpose),
            ("archive_class", self.archive_class),
        ):
            if not value or len(value) > 512:
                raise ValueError(f"{name} MUST be bounded non-empty text")
        if not 0 <= self.hot_retention_seconds <= self.warm_retention_seconds:
            raise ValueError("retention windows MUST be monotonic and non-negative")
        if self.review_at.tzinfo is None:
            raise ValueError("retention policy review_at MUST be timezone-aware")
        if self.digest != _sha256(_policy_body(self)):
            raise ValueError("retention policy digest does not match content")


def build_retention_policy(
    *,
    policy_id: str,
    fact_family: str,
    purpose: str,
    hot_retention_seconds: int,
    warm_retention_seconds: int,
    archive_class: str,
    deletion_method: RetentionDeletionMethod,
    review_at: datetime,
) -> ObservationRetentionPolicy:
    """Build one deployment-supplied policy without tenant values in source."""

    values = {
        "policy_id": policy_id,
        "fact_family": fact_family,
        "purpose": purpose,
        "hot_retention_seconds": hot_retention_seconds,
        "warm_retention_seconds": warm_retention_seconds,
        "archive_class": archive_class,
        "deletion_method": deletion_method,
        "review_at": review_at,
    }
    return ObservationRetentionPolicy(
        digest=_sha256(_policy_body_from_values(values)),
        **values,  # type: ignore[arg-type]
    )


def load_retention_policy_registry(
    values: Sequence[Mapping[str, object]],
) -> Mapping[str, ObservationRetentionPolicy]:
    """Validate a complete deployment-owned policy registry by fact family."""

    policies: dict[str, ObservationRetentionPolicy] = {}
    for value in values:
        policy = build_retention_policy(
            policy_id=_mapping_text(value, "policy_id"),
            fact_family=_mapping_text(value, "fact_family"),
            purpose=_mapping_text(value, "purpose"),
            hot_retention_seconds=_mapping_int(value, "hot_retention_seconds"),
            warm_retention_seconds=_mapping_int(value, "warm_retention_seconds"),
            archive_class=_mapping_text(value, "archive_class"),
            deletion_method=RetentionDeletionMethod(_mapping_text(value, "deletion_method")),
            review_at=_mapping_time(value, "review_at"),
        )
        if policy.fact_family in policies:
            raise ValueError("retention policy fact_family MUST be unique")
        policies[policy.fact_family] = policy
    if not policies:
        raise ValueError("retention policy registry MUST NOT be empty")
    return dict(sorted(policies.items()))


def _policy_body(value: ObservationRetentionPolicy) -> dict[str, object]:
    return _policy_body_from_values(
        {
            "policy_id": value.policy_id,
            "fact_family": value.fact_family,
            "purpose": value.purpose,
            "hot_retention_seconds": value.hot_retention_seconds,
            "warm_retention_seconds": value.warm_retention_seconds,
            "archive_class": value.archive_class,
            "deletion_method": value.deletion_method,
            "review_at": value.review_at,
        }
    )


def _policy_body_from_values(values: Mapping[str, object]) -> dict[str, object]:
    deletion = values["deletion_method"]
    review_at = values["review_at"]
    if not isinstance(deletion, RetentionDeletionMethod) or not isinstance(review_at, datetime):
        raise ValueError("retention policy values are invalid")
    return {
        **values,
        "deletion_method": deletion.value,
        "review_at": review_at.astimezone(UTC).isoformat(),
    }


def _mapping_text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"retention policy {key} MUST be a string")
    return item


def _mapping_int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"retention policy {key} MUST be an integer")
    return item


def _mapping_time(value: Mapping[str, object], key: str) -> datetime:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"retention policy {key} MUST be RFC 3339 text")
    parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"retention policy {key} MUST be timezone-aware")
    return parsed


def _sha256(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ObservationRetentionPolicy",
    "RetentionDeletionMethod",
    "build_retention_policy",
    "load_retention_policy_registry",
]
