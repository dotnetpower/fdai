"""Policy-aware provider schema watcher state-machine tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai.delivery.provider_schema import ProviderSchemaSnapshot, ProviderSchemaType
from fdai.delivery.provider_schema_ledger import ProviderSchemaLedger
from fdai.delivery.provider_schema_watcher import (
    ProviderSchemaRefreshDisposition,
    ProviderSchemaSourceBinding,
    ProviderSchemaSourceKind,
    ProviderSchemaWatcher,
    ProviderSchemaWatchPolicy,
)

NOW = datetime(2026, 8, 24, tzinfo=UTC)


class _Source:
    def __init__(
        self,
        snapshot: ProviderSchemaSnapshot | None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.error = error
        self.calls = 0

    async def collect(self) -> ProviderSchemaSnapshot:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.snapshot is not None
        return self.snapshot


class _ReviewPublisher:
    def __init__(self, *, published: bool = True, error: Exception | None = None) -> None:
        self.published = published
        self.error = error
        self.packages: list[dict[str, object]] = []

    async def publish_provider_schema_drift(self, package: dict[str, object]) -> bool:
        self.packages.append(package)
        if self.error is not None:
            raise self.error
        return self.published


def _type(
    resource_type: str,
    *,
    versions: tuple[str, ...] = ("2025-01-01",),
) -> ProviderSchemaType:
    return ProviderSchemaType(
        resource_type=resource_type,
        stable_api_versions=versions,
        preview_api_versions=(),
        preferred_api_version=versions[-1],
        source_document="generated/example/types.md",
    )


def _snapshot(*types: ProviderSchemaType, revision: str = "a" * 40) -> ProviderSchemaSnapshot:
    return ProviderSchemaSnapshot.build(
        provider="azure",
        source_revision=revision,
        types=tuple(types),
    )


def _binding(
    name: str,
    kind: ProviderSchemaSourceKind,
    source: _Source,
    *,
    allowed: bool = True,
) -> ProviderSchemaSourceBinding:
    return ProviderSchemaSourceBinding(name=name, kind=kind, source=source, allowed=allowed)


def _watcher(
    tmp_path: Path,
    *sources: ProviderSchemaSourceBinding,
    review_compatible: bool = False,
    review_publisher: _ReviewPublisher | None = None,
) -> ProviderSchemaWatcher:
    return ProviderSchemaWatcher(
        provider="azure",
        sources=tuple(sources),
        ledger=ProviderSchemaLedger(tmp_path),
        modeled_provider_types=frozenset({"microsoft.example/widgets"}),
        policy=ProviderSchemaWatchPolicy(
            cadence_seconds=86_400,
            failure_retry_seconds=3_600,
            stale_after_seconds=172_800,
            review_compatible_drift=review_compatible,
        ),
        review_publisher=review_publisher,
    )


async def test_unconfigured_source_is_explicitly_unavailable(tmp_path: Path) -> None:
    receipt = await _watcher(tmp_path).run(now=NOW)

    assert receipt.disposition is ProviderSchemaRefreshDisposition.UNAVAILABLE
    assert receipt.reason == "source_unconfigured"


async def test_policy_blocked_makes_zero_calls_and_keeps_baseline(tmp_path: Path) -> None:
    snapshot = _snapshot(_type("Microsoft.Example/widgets"))
    ledger = ProviderSchemaLedger(tmp_path)
    ledger.record_snapshot(snapshot, observed_at=NOW, accept_baseline=True)
    source = _Source(snapshot)
    watcher = _watcher(
        tmp_path,
        _binding("public", ProviderSchemaSourceKind.PRIMARY, source, allowed=False),
    )

    receipt = await watcher.run(now=NOW + timedelta(days=1), force=True)

    assert receipt.disposition is ProviderSchemaRefreshDisposition.POLICY_BLOCKED
    assert receipt.reason == "network_policy_blocked"
    assert source.calls == 0
    assert ledger.read_baseline("azure") == snapshot


async def test_mirror_fallback_establishes_complete_baseline(tmp_path: Path) -> None:
    snapshot = _snapshot(_type("Microsoft.Example/widgets"))
    primary = _Source(None, error=OSError("offline"))
    mirror = _Source(snapshot)
    watcher = _watcher(
        tmp_path,
        _binding("public", ProviderSchemaSourceKind.PRIMARY, primary),
        _binding("mirror", ProviderSchemaSourceKind.MIRROR, mirror),
    )

    receipt = await watcher.run(now=NOW)

    assert receipt.disposition is ProviderSchemaRefreshDisposition.COMPATIBLE
    assert receipt.reason == "baseline_established"
    assert receipt.source_kind is ProviderSchemaSourceKind.MIRROR
    assert receipt.fallback_used is True
    assert receipt.type_count == 1
    assert receipt.modeled_count == 1
    assert primary.calls == mirror.calls == 1
    assert ProviderSchemaLedger(tmp_path).read_baseline("azure") == snapshot


async def test_unchanged_snapshot_creates_no_review_package(tmp_path: Path) -> None:
    snapshot = _snapshot(_type("Microsoft.Example/widgets"))
    ledger = ProviderSchemaLedger(tmp_path)
    ledger.record_snapshot(snapshot, observed_at=NOW, accept_baseline=True)
    source = _Source(snapshot)

    receipt = await _watcher(
        tmp_path,
        _binding("public", ProviderSchemaSourceKind.PRIMARY, source),
    ).run(now=NOW + timedelta(days=1), force=True)

    assert receipt.disposition is ProviderSchemaRefreshDisposition.UNCHANGED
    assert receipt.review_required is False
    assert receipt.review_package_digest is None
    assert not (tmp_path / "azure" / "review-packages").exists()


async def test_compatible_drift_advances_global_baseline_without_semantic_review(
    tmp_path: Path,
) -> None:
    baseline = _snapshot(_type("Microsoft.Example/widgets"))
    observed = _snapshot(
        _type("Microsoft.Example/widgets", versions=("2025-01-01", "2025-02-01")),
        _type("Microsoft.Example/reports"),
        revision="b" * 40,
    )
    ledger = ProviderSchemaLedger(tmp_path)
    ledger.record_snapshot(baseline, observed_at=NOW, accept_baseline=True)

    receipt = await _watcher(
        tmp_path,
        _binding("public", ProviderSchemaSourceKind.PRIMARY, _Source(observed)),
    ).run(now=NOW + timedelta(days=1), force=True)

    assert receipt.disposition is ProviderSchemaRefreshDisposition.COMPATIBLE
    assert receipt.review_required is False
    assert ledger.read_baseline("azure") == observed


async def test_breaking_drift_holds_baseline_and_writes_inert_review_package(
    tmp_path: Path,
) -> None:
    baseline = _snapshot(
        _type("Microsoft.Example/widgets", versions=("2025-01-01", "2025-02-01")),
        _type("Microsoft.Example/reports"),
    )
    observed = _snapshot(
        _type("Microsoft.Example/widgets", versions=("2025-02-01",)),
        revision="b" * 40,
    )
    ledger = ProviderSchemaLedger(tmp_path)
    ledger.record_snapshot(baseline, observed_at=NOW, accept_baseline=True)

    receipt = await _watcher(
        tmp_path,
        _binding("public", ProviderSchemaSourceKind.PRIMARY, _Source(observed)),
    ).run(now=NOW + timedelta(days=1), force=True)

    assert receipt.disposition is ProviderSchemaRefreshDisposition.BREAKING
    assert receipt.review_required is True
    assert receipt.review_package_digest is not None
    assert receipt.review_dispatched is False
    assert receipt.review_handoff_reason == "heimdall_unconfigured"
    assert ledger.read_baseline("azure") == baseline
    package_file = next((tmp_path / "azure" / "review-packages").glob("*.json"))
    package = json.loads(package_file.read_text(encoding="utf-8"))
    assert package["removed_types"] == ["microsoft.example/reports"]
    assert package["removed_stable_versions"] == ["microsoft.example/widgets@2025-01-01"]
    assert package["grants_authority"] is False


async def test_breaking_drift_dispatches_durable_package_to_heimdall_seam(
    tmp_path: Path,
) -> None:
    baseline = _snapshot(
        _type("Microsoft.Example/widgets"),
        _type("Microsoft.Example/reports"),
    )
    observed = _snapshot(_type("Microsoft.Example/widgets"), revision="b" * 40)
    ledger = ProviderSchemaLedger(tmp_path)
    ledger.record_snapshot(baseline, observed_at=NOW, accept_baseline=True)
    publisher = _ReviewPublisher()

    receipt = await _watcher(
        tmp_path,
        _binding("public", ProviderSchemaSourceKind.PRIMARY, _Source(observed)),
        review_publisher=publisher,
    ).run(now=NOW + timedelta(days=1), force=True)

    assert receipt.review_dispatched is True
    assert receipt.review_handoff_reason is None
    assert len(publisher.packages) == 1
    assert publisher.packages[0]["drift_kind"] == "breaking"
    assert next((tmp_path / "azure" / "review-packages").glob("*.json")).is_file()


async def test_heimdall_handoff_failure_keeps_durable_package_for_retry(tmp_path: Path) -> None:
    baseline = _snapshot(
        _type("Microsoft.Example/widgets"),
        _type("Microsoft.Example/reports"),
    )
    observed = _snapshot(_type("Microsoft.Example/widgets"), revision="b" * 40)
    ledger = ProviderSchemaLedger(tmp_path)
    ledger.record_snapshot(baseline, observed_at=NOW, accept_baseline=True)

    receipt = await _watcher(
        tmp_path,
        _binding("public", ProviderSchemaSourceKind.PRIMARY, _Source(observed)),
        review_publisher=_ReviewPublisher(error=RuntimeError("transport unavailable")),
    ).run(now=NOW + timedelta(days=1), force=True)

    assert receipt.review_dispatched is False
    assert receipt.review_handoff_reason == "heimdall_unavailable"
    assert receipt.review_package_digest is not None
    assert ledger.read_baseline("azure") == baseline


async def test_not_due_does_not_call_source_or_slide_schedule(tmp_path: Path) -> None:
    snapshot = _snapshot(_type("Microsoft.Example/widgets"))
    source = _Source(snapshot)
    watcher = _watcher(
        tmp_path,
        _binding("offline", ProviderSchemaSourceKind.OFFLINE, source),
    )
    await watcher.run(now=NOW)

    first = await watcher.run(now=NOW + timedelta(hours=1))
    second = await watcher.run(now=NOW + timedelta(days=1))

    assert first.disposition is ProviderSchemaRefreshDisposition.NOT_DUE
    assert second.disposition is ProviderSchemaRefreshDisposition.UNCHANGED
    assert source.calls == 2


async def test_all_source_failure_preserves_prior_snapshot_and_reports_staleness(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(_type("Microsoft.Example/widgets"))
    ledger = ProviderSchemaLedger(tmp_path)
    ledger.record_snapshot(snapshot, observed_at=NOW, accept_baseline=True)
    source = _Source(None, error=TimeoutError())

    receipt = await _watcher(
        tmp_path,
        _binding("public", ProviderSchemaSourceKind.PRIMARY, source),
    ).run(now=NOW + timedelta(days=3), force=True)

    assert receipt.disposition is ProviderSchemaRefreshDisposition.UNAVAILABLE
    assert receipt.reason == "all_allowed_sources_unavailable"
    assert receipt.stale is True
    assert ledger.read_baseline("azure") == snapshot
