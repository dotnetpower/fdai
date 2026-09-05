"""Pinned-revision certification for bounded operational history behavior."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal


class OperationalHistoryScenario(StrEnum):
    """Required OI-16 deterministic and failure-isolation scenarios."""

    BOUNDED_STORAGE = "bounded_storage"
    WARM_REPLAY = "warm_replay"
    ARCHIVE_RESTORE = "archive_restore"
    SAFE_PARTITION_PURGE = "safe_partition_purge"
    SCHEMA_REPLAY = "schema_replay"
    DATABASE_RECOVERY = "database_recovery"
    HOLD_ENFORCEMENT = "hold_enforcement"
    DUPLICATE_DELIVERY = "duplicate_delivery"
    LATE_OBSERVATION = "late_observation"
    DELETE_RECREATE = "delete_recreate"
    PROVIDER_FAILURE = "provider_failure"
    DATABASE_RESTART = "database_restart"
    ARCHIVE_OUTAGE = "archive_outage"


class OperationalHistoryScenarioStatus(StrEnum):
    """Outcome of one exact certification scenario."""

    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class OperationalHistoryScenarioResult:
    """One scenario outcome bound to immutable evidence."""

    scenario: OperationalHistoryScenario
    status: OperationalHistoryScenarioStatus
    evidence_digests: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.evidence_digests != tuple(sorted(set(self.evidence_digests))):
            raise ValueError("certification evidence digests MUST be sorted and unique")
        for digest in self.evidence_digests:
            _digest(digest, "certification evidence digest")
        if self.status is OperationalHistoryScenarioStatus.PASSED:
            if not self.evidence_digests or self.reason_codes:
                raise ValueError("passed certification scenario requires only evidence")
        elif not self.reason_codes:
            raise ValueError("non-passing certification scenario requires reason codes")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("certification reason codes MUST be sorted and unique")


@dataclass(frozen=True, slots=True)
class OperationalHistoryCertificationReceipt:
    """One local or deployed pinned-revision OI-16 certification receipt."""

    schema_version: Literal["1.0.0"]
    source_revision: str
    ontology_release_digest: str
    window_start: datetime
    window_end: datetime
    recorded_at: datetime
    scenario_results: tuple[OperationalHistoryScenarioResult, ...]
    deterministic_complete: bool
    deployment_receipt_digest: str | None
    operationally_validated: bool
    observation_authority: Literal[False]
    mutation_authority: Literal[False]
    execution_authority: Literal[False]
    digest: str

    def __post_init__(self) -> None:
        if not self.source_revision or len(self.source_revision) > 128:
            raise ValueError("certification source revision MUST be bounded non-empty text")
        _digest(self.ontology_release_digest, "certification ontology release digest")
        for value in (self.window_start, self.window_end, self.recorded_at):
            if value.tzinfo is None:
                raise ValueError("certification timestamps MUST be timezone-aware")
        if not self.window_start < self.window_end <= self.recorded_at:
            raise ValueError("certification time window is invalid")
        expected = tuple(sorted(OperationalHistoryScenario, key=lambda item: item.value))
        actual = tuple(item.scenario for item in self.scenario_results)
        if actual != expected:
            raise ValueError("certification receipt requires every ordered OI-16 scenario")
        all_passed = all(
            item.status is OperationalHistoryScenarioStatus.PASSED for item in self.scenario_results
        )
        if self.deterministic_complete is not all_passed:
            raise ValueError("deterministic certification completeness is inconsistent")
        if self.deployment_receipt_digest is not None:
            _digest(self.deployment_receipt_digest, "deployment receipt digest")
        if self.operationally_validated is not (
            all_passed and self.deployment_receipt_digest is not None
        ):
            raise ValueError("operational certification validation is inconsistent")
        if any(
            value is not False
            for value in (
                self.observation_authority,
                self.mutation_authority,
                self.execution_authority,
            )
        ):
            raise ValueError("operational history certification MUST NOT grant authority")
        if self.digest != _sha256(_receipt_body(self)):
            raise ValueError("operational history certification digest does not match content")


@dataclass(frozen=True, slots=True)
class OperationalHistoryRecoveryReceipt:
    """Database restore and archive-index rebuild equivalence evidence."""

    source_revision: str
    before_journal_watermark: int
    after_journal_watermark: int
    before_projection_watermark: int
    after_projection_watermark: int
    before_archive_index_digest: str
    after_archive_index_digest: str
    recovered_at: datetime
    complete: bool
    digest: str

    def __post_init__(self) -> None:
        if not self.source_revision or len(self.source_revision) > 128:
            raise ValueError("recovery source revision MUST be bounded non-empty text")
        watermarks = (
            self.before_journal_watermark,
            self.after_journal_watermark,
            self.before_projection_watermark,
            self.after_projection_watermark,
        )
        if any(value < 0 for value in watermarks):
            raise ValueError("recovery watermarks MUST be non-negative")
        _digest(self.before_archive_index_digest, "before archive index digest")
        _digest(self.after_archive_index_digest, "after archive index digest")
        if self.recovered_at.tzinfo is None:
            raise ValueError("recovery timestamp MUST be timezone-aware")
        equivalent = (
            self.before_journal_watermark == self.after_journal_watermark
            and self.before_projection_watermark == self.after_projection_watermark
            and self.before_archive_index_digest == self.after_archive_index_digest
        )
        if self.complete is not equivalent:
            raise ValueError("recovery completeness does not match restored evidence")
        if self.digest != _sha256(_recovery_body(self)):
            raise ValueError("recovery receipt digest does not match content")


def build_operational_history_recovery_receipt(
    *,
    source_revision: str,
    before_journal_watermark: int,
    after_journal_watermark: int,
    before_projection_watermark: int,
    after_projection_watermark: int,
    before_archive_index_digest: str,
    after_archive_index_digest: str,
    recovered_at: datetime,
) -> OperationalHistoryRecoveryReceipt:
    """Build a deterministic restore and index-rebuild comparison."""

    complete = (
        before_journal_watermark == after_journal_watermark
        and before_projection_watermark == after_projection_watermark
        and before_archive_index_digest == after_archive_index_digest
    )
    values = {
        "source_revision": source_revision,
        "before_journal_watermark": before_journal_watermark,
        "after_journal_watermark": after_journal_watermark,
        "before_projection_watermark": before_projection_watermark,
        "after_projection_watermark": after_projection_watermark,
        "before_archive_index_digest": before_archive_index_digest,
        "after_archive_index_digest": after_archive_index_digest,
        "recovered_at": recovered_at,
        "complete": complete,
    }
    return OperationalHistoryRecoveryReceipt(
        digest=_sha256(_recovery_body_from_values(values)),
        **values,  # type: ignore[arg-type]
    )


def build_operational_history_certification(
    results: Sequence[OperationalHistoryScenarioResult],
    *,
    source_revision: str,
    ontology_release_digest: str,
    window_start: datetime,
    window_end: datetime,
    recorded_at: datetime,
    deployment_receipt_digest: str | None = None,
) -> OperationalHistoryCertificationReceipt:
    """Build a replay-stable receipt without inventing deployment validation."""

    ordered = tuple(sorted(results, key=lambda item: item.scenario.value))
    all_passed = all(item.status is OperationalHistoryScenarioStatus.PASSED for item in ordered)
    values = {
        "schema_version": "1.0.0",
        "source_revision": source_revision,
        "ontology_release_digest": ontology_release_digest,
        "window_start": window_start,
        "window_end": window_end,
        "recorded_at": recorded_at,
        "scenario_results": ordered,
        "deterministic_complete": all_passed,
        "deployment_receipt_digest": deployment_receipt_digest,
        "operationally_validated": all_passed and deployment_receipt_digest is not None,
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }
    return OperationalHistoryCertificationReceipt(
        digest=_sha256(_receipt_body_from_values(values)),
        **values,  # type: ignore[arg-type]
    )


def certification_record(
    receipt: OperationalHistoryCertificationReceipt,
) -> dict[str, object]:
    """Return the canonical persisted certification record."""

    return {
        **_receipt_body(receipt),
        "digest": receipt.digest,
    }


def _receipt_body(
    receipt: OperationalHistoryCertificationReceipt,
) -> dict[str, object]:
    return _receipt_body_from_values(
        {
            name: getattr(receipt, name)
            for name in OperationalHistoryCertificationReceipt.__dataclass_fields__
            if name != "digest"
        }
    )


def _receipt_body_from_values(values: Mapping[str, object]) -> dict[str, object]:
    results = values["scenario_results"]
    if not isinstance(results, tuple):
        raise ValueError("certification scenario results MUST be an immutable tuple")
    return {
        "schema_version": values["schema_version"],
        "source_revision": values["source_revision"],
        "ontology_release_digest": values["ontology_release_digest"],
        "window_start": _timestamp(values["window_start"]),
        "window_end": _timestamp(values["window_end"]),
        "recorded_at": _timestamp(values["recorded_at"]),
        "scenario_results": [
            {
                "scenario": item.scenario.value,
                "status": item.status.value,
                "evidence_digests": list(item.evidence_digests),
                "reason_codes": list(item.reason_codes),
            }
            for item in results
            if isinstance(item, OperationalHistoryScenarioResult)
        ],
        "deterministic_complete": values["deterministic_complete"],
        "deployment_receipt_digest": values["deployment_receipt_digest"],
        "operationally_validated": values["operationally_validated"],
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }


def _recovery_body(receipt: OperationalHistoryRecoveryReceipt) -> dict[str, object]:
    return _recovery_body_from_values(
        {
            name: getattr(receipt, name)
            for name in OperationalHistoryRecoveryReceipt.__dataclass_fields__
            if name != "digest"
        }
    )


def _recovery_body_from_values(values: Mapping[str, object]) -> dict[str, object]:
    return {
        **values,
        "recovered_at": _timestamp(values["recovered_at"]),
    }


def _timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        raise ValueError("certification timestamp MUST be datetime")
    return value.astimezone(UTC).isoformat()


def _digest(value: str, name: str) -> None:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ValueError(f"{name} MUST be canonical SHA-256")


def _sha256(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "OperationalHistoryCertificationReceipt",
    "OperationalHistoryRecoveryReceipt",
    "OperationalHistoryScenario",
    "OperationalHistoryScenarioResult",
    "OperationalHistoryScenarioStatus",
    "build_operational_history_certification",
    "build_operational_history_recovery_receipt",
    "certification_record",
]
