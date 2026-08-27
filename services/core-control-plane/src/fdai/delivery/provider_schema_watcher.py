"""Policy-aware periodic provider schema watcher with bounded source fallback."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol

from fdai.delivery.provider_schema import (
    ProviderSchemaCoverage,
    ProviderSchemaDrift,
    ProviderSchemaDriftKind,
    ProviderSchemaError,
    ProviderSchemaSnapshot,
    compare_provider_schema_snapshots,
    provider_schema_observation_time,
)
from fdai.delivery.provider_schema_ledger import ProviderSchemaLedger


class ProviderSchemaSourceKind(StrEnum):
    PRIMARY = "primary"
    MIRROR = "mirror"
    OFFLINE = "offline"


class ProviderSchemaRefreshDisposition(StrEnum):
    NOT_DUE = "not_due"
    UNCHANGED = "unchanged"
    COMPATIBLE = "compatible"
    BREAKING = "breaking"
    POLICY_BLOCKED = "policy_blocked"
    UNAVAILABLE = "unavailable"


class ProviderSchemaSnapshotSource(Protocol):
    """Return one complete normalized source snapshot or raise without partial output."""

    async def collect(self) -> ProviderSchemaSnapshot: ...


class ProviderSchemaReviewPublisher(Protocol):
    """Publish a strict durable package through Heimdall's existing Drift ownership."""

    async def publish_provider_schema_drift(self, package: Mapping[str, object]) -> bool: ...


@dataclass(frozen=True, slots=True)
class ProviderSchemaSourceBinding:
    name: str
    kind: ProviderSchemaSourceKind
    source: ProviderSchemaSnapshotSource
    allowed: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.name.isascii():
            raise ValueError("provider schema source name MUST be non-empty ASCII")


@dataclass(frozen=True, slots=True)
class ProviderSchemaWatchPolicy:
    """Cadence and freshness limits independent from network source configuration."""

    cadence_seconds: int = 86_400
    failure_retry_seconds: int = 3_600
    stale_after_seconds: int = 604_800
    review_compatible_drift: bool = False

    def __post_init__(self) -> None:
        if (
            min(
                self.cadence_seconds,
                self.failure_retry_seconds,
                self.stale_after_seconds,
            )
            < 1
        ):
            raise ValueError("provider schema watcher time bounds MUST be positive")
        if self.failure_retry_seconds > self.cadence_seconds:
            raise ValueError("provider schema failure retry MUST NOT exceed normal cadence")


@dataclass(frozen=True, slots=True)
class ProviderSchemaRefreshReceipt:
    """One no-authority terminal watcher outcome."""

    provider: str
    disposition: ProviderSchemaRefreshDisposition
    reason: str
    checked_at: str
    source_name: str | None
    source_kind: ProviderSchemaSourceKind | None
    fallback_used: bool
    baseline_digest: str | None
    observed_digest: str | None
    drift_digest: str | None
    type_count: int | None
    modeled_count: int | None
    stale: bool
    review_required: bool
    review_package_digest: str | None = None
    review_dispatched: bool = False
    review_handoff_reason: str | None = None
    grants_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.grants_authority is not False:
            raise ValueError("provider schema refresh receipt cannot grant authority")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "provider": self.provider,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "checked_at": self.checked_at,
            "source_name": self.source_name,
            "source_kind": None if self.source_kind is None else self.source_kind.value,
            "fallback_used": self.fallback_used,
            "baseline_digest": self.baseline_digest,
            "observed_digest": self.observed_digest,
            "drift_digest": self.drift_digest,
            "type_count": self.type_count,
            "modeled_count": self.modeled_count,
            "stale": self.stale,
            "review_required": self.review_required,
            "review_package_digest": self.review_package_digest,
            "review_dispatched": self.review_dispatched,
            "review_handoff_reason": self.review_handoff_reason,
            "grants_authority": False,
        }


class ProviderSchemaWatcher:
    """Refresh raw schema evidence while keeping semantic catalogs inert."""

    def __init__(
        self,
        *,
        provider: str,
        sources: tuple[ProviderSchemaSourceBinding, ...],
        ledger: ProviderSchemaLedger,
        modeled_provider_types: frozenset[str],
        policy: ProviderSchemaWatchPolicy | None = None,
        review_publisher: ProviderSchemaReviewPublisher | None = None,
    ) -> None:
        source_names = [source.name for source in sources]
        if len(source_names) != len(set(source_names)):
            raise ValueError("provider schema watcher source names MUST be unique")
        self._provider = provider.casefold()
        self._sources = sources
        self._ledger = ledger
        self._modeled_provider_types = modeled_provider_types
        self._policy = policy or ProviderSchemaWatchPolicy()
        self._review_publisher = review_publisher

    async def run(
        self,
        *,
        now: datetime,
        force: bool = False,
    ) -> ProviderSchemaRefreshReceipt:
        checked_at = _aware_utc(now)
        baseline = self._ledger.read_baseline(self._provider)
        baseline_time = self._ledger.read_baseline_observed_at(self._provider)
        last_run = self._ledger.read_last_run(self._provider)
        if not force and not _is_due(last_run, now=checked_at, policy=self._policy):
            receipt = self._receipt(
                disposition=ProviderSchemaRefreshDisposition.NOT_DUE,
                reason="schedule_not_due",
                checked_at=checked_at,
                baseline=baseline,
                baseline_time=baseline_time,
            )
            self._ledger.record_run(self._provider, receipt.to_mapping(), update_last=False)
            return receipt

        if not self._sources:
            receipt = self._receipt(
                disposition=ProviderSchemaRefreshDisposition.UNAVAILABLE,
                reason="source_unconfigured",
                checked_at=checked_at,
                baseline=baseline,
                baseline_time=baseline_time,
            )
            self._ledger.record_run(self._provider, receipt.to_mapping())
            return receipt

        allowed_sources = tuple(source for source in self._sources if source.allowed)
        if not allowed_sources:
            receipt = self._receipt(
                disposition=ProviderSchemaRefreshDisposition.POLICY_BLOCKED,
                reason="network_policy_blocked",
                checked_at=checked_at,
                baseline=baseline,
                baseline_time=baseline_time,
            )
            self._ledger.record_run(self._provider, receipt.to_mapping())
            return receipt

        observed: ProviderSchemaSnapshot | None = None
        selected: ProviderSchemaSourceBinding | None = None
        for source in allowed_sources:
            try:
                candidate = await source.source.collect()
            except Exception:  # noqa: BLE001 - source details never enter durable receipts
                candidate = None
            if candidate is None or candidate.provider != self._provider:
                continue
            observed = candidate
            selected = source
            break
        if observed is None or selected is None:
            receipt = self._receipt(
                disposition=ProviderSchemaRefreshDisposition.UNAVAILABLE,
                reason="all_allowed_sources_unavailable",
                checked_at=checked_at,
                baseline=baseline,
                baseline_time=baseline_time,
            )
            self._ledger.record_run(self._provider, receipt.to_mapping())
            return receipt

        coverage = ProviderSchemaCoverage.build(
            snapshot=observed,
            modeled_provider_types=self._modeled_provider_types,
        )
        if baseline is None:
            drift = None
            disposition = ProviderSchemaRefreshDisposition.COMPATIBLE
            reason = "baseline_established"
            accept_baseline = True
            review_required = False
        else:
            drift = compare_provider_schema_snapshots(baseline, observed)
            disposition = ProviderSchemaRefreshDisposition(drift.kind.value)
            reason = f"schema_{drift.kind.value}"
            accept_baseline = drift.kind is not ProviderSchemaDriftKind.BREAKING
            review_required = drift.kind is ProviderSchemaDriftKind.BREAKING or (
                drift.kind is ProviderSchemaDriftKind.COMPATIBLE
                and self._policy.review_compatible_drift
            )
        self._ledger.record_snapshot(
            observed,
            observed_at=checked_at,
            accept_baseline=accept_baseline,
        )
        self._ledger.record_coverage(self._provider, coverage)
        receipt = self._receipt(
            disposition=disposition,
            reason=reason,
            checked_at=checked_at,
            baseline=baseline,
            baseline_time=baseline_time,
            observed=observed,
            selected=selected,
            fallback_used=selected is not allowed_sources[0],
            drift=drift,
            coverage=coverage,
            review_required=review_required,
        )
        if review_required and drift is not None:
            review_package = _review_package(observed, drift=drift, coverage=coverage)
            package_digest = self._ledger.record_review_package(
                self._provider,
                review_package,
            )
            review_dispatched = False
            handoff_reason: str | None = "heimdall_unconfigured"
            if self._review_publisher is not None:
                try:
                    review_dispatched = await self._review_publisher.publish_provider_schema_drift(
                        review_package
                    )
                except Exception:  # noqa: BLE001 - package remains durable for bounded retry
                    handoff_reason = "heimdall_unavailable"
                else:
                    handoff_reason = None if review_dispatched else "heimdall_transport_unavailable"
            receipt = replace(
                receipt,
                review_package_digest=package_digest,
                review_dispatched=review_dispatched,
                review_handoff_reason=handoff_reason,
            )
        self._ledger.record_run(self._provider, receipt.to_mapping())
        return receipt

    def _receipt(
        self,
        *,
        disposition: ProviderSchemaRefreshDisposition,
        reason: str,
        checked_at: datetime,
        baseline: ProviderSchemaSnapshot | None,
        baseline_time: datetime | None,
        observed: ProviderSchemaSnapshot | None = None,
        selected: ProviderSchemaSourceBinding | None = None,
        fallback_used: bool = False,
        drift: ProviderSchemaDrift | None = None,
        coverage: ProviderSchemaCoverage | None = None,
        review_required: bool = False,
    ) -> ProviderSchemaRefreshReceipt:
        return ProviderSchemaRefreshReceipt(
            provider=self._provider,
            disposition=disposition,
            reason=reason,
            checked_at=provider_schema_observation_time(checked_at),
            source_name=None if selected is None else selected.name,
            source_kind=None if selected is None else selected.kind,
            fallback_used=fallback_used,
            baseline_digest=None if baseline is None else baseline.schema_digest,
            observed_digest=None if observed is None else observed.schema_digest,
            drift_digest=None if drift is None else drift.drift_digest,
            type_count=None if coverage is None else len(coverage.entries),
            modeled_count=None if coverage is None else coverage.modeled_count,
            stale=_is_stale(baseline_time, now=checked_at, policy=self._policy),
            review_required=review_required,
        )


def _is_due(
    last_run: Mapping[str, object] | None,
    *,
    now: datetime,
    policy: ProviderSchemaWatchPolicy,
) -> bool:
    if last_run is None:
        return True
    raw_checked_at = last_run.get("checked_at")
    raw_disposition = last_run.get("disposition")
    if not isinstance(raw_checked_at, str) or not isinstance(raw_disposition, str):
        raise ProviderSchemaError("provider schema last-run receipt is invalid")
    try:
        checked_at = datetime.fromisoformat(raw_checked_at)
        disposition = ProviderSchemaRefreshDisposition(raw_disposition)
    except (ValueError, TypeError) as exc:
        raise ProviderSchemaError("provider schema last-run receipt is invalid") from exc
    interval = (
        policy.failure_retry_seconds
        if disposition
        in {
            ProviderSchemaRefreshDisposition.POLICY_BLOCKED,
            ProviderSchemaRefreshDisposition.UNAVAILABLE,
        }
        else policy.cadence_seconds
    )
    return now - _aware_utc(checked_at) >= timedelta(seconds=interval)


def _is_stale(
    baseline_time: datetime | None,
    *,
    now: datetime,
    policy: ProviderSchemaWatchPolicy,
) -> bool:
    return baseline_time is None or now - _aware_utc(baseline_time) > timedelta(
        seconds=policy.stale_after_seconds
    )


def _review_package(
    snapshot: ProviderSchemaSnapshot,
    *,
    drift: ProviderSchemaDrift,
    coverage: ProviderSchemaCoverage,
) -> dict[str, object]:
    status_counts: dict[str, int] = {}
    for entry in coverage.entries:
        status_counts[entry.status.value] = status_counts.get(entry.status.value, 0) + 1
    return {
        "schema_version": "1.0.0",
        "kind": "provider-schema-drift-review",
        "provider": snapshot.provider,
        "source_revision": snapshot.source_revision,
        "baseline_digest": drift.baseline_digest,
        "observed_digest": drift.observed_digest,
        "drift_digest": drift.drift_digest,
        "drift_kind": drift.kind.value,
        "added_types": list(drift.added_types),
        "removed_types": list(drift.removed_types),
        "added_stable_versions": list(drift.added_stable_versions),
        "removed_stable_versions": list(drift.removed_stable_versions),
        "added_preview_versions": list(drift.added_preview_versions),
        "removed_preview_versions": list(drift.removed_preview_versions),
        "type_count": len(coverage.entries),
        "modeled_count": coverage.modeled_count,
        "coverage_status_counts": dict(sorted(status_counts.items())),
        "review_required": True,
        "grants_authority": False,
    }


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ProviderSchemaError("provider schema watcher time MUST be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "ProviderSchemaRefreshDisposition",
    "ProviderSchemaRefreshReceipt",
    "ProviderSchemaReviewPublisher",
    "ProviderSchemaSnapshotSource",
    "ProviderSchemaSourceBinding",
    "ProviderSchemaSourceKind",
    "ProviderSchemaWatchPolicy",
    "ProviderSchemaWatcher",
]
