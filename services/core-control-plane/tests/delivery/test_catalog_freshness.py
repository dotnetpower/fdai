"""Installation-side catalog freshness: signed metadata decides, and unknown means expired."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai.delivery.catalog_freshness import (
    CatalogFreshnessConfig,
    CatalogFreshnessMonitor,
    build_catalog_freshness_monitor,
)
from fdai_service_contracts.catalog_integrity import (
    CatalogRootRecord,
    CatalogSnapshotRecord,
    CatalogTimestampRecord,
    catalog_key_id,
    role_signing_message,
)
from fdai_service_contracts.catalog_metadata import MetadataBundle

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
URL = "https://releases.example.invalid/v1/catalog/metadata"


def _raw(key: Ed25519PrivateKey) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _sign(key: Ed25519PrivateKey, role: str, payload: bytes) -> bytes:
    return key.sign(role_signing_message(role, payload))


@dataclass
class Authority:
    root_keys: list[Ed25519PrivateKey] = field(
        default_factory=lambda: [Ed25519PrivateKey.generate() for _ in range(3)]
    )
    snapshot_key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)
    timestamp_key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)
    export_key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)

    @property
    def pin(self) -> frozenset[str]:
        return frozenset(catalog_key_id(_raw(key)) for key in self.root_keys)

    def root(self, now: datetime = NOW, *, valid_days: int = 365) -> CatalogRootRecord:
        every = [*self.root_keys, self.snapshot_key, self.timestamp_key, self.export_key]
        keys = {catalog_key_id(_raw(key)): _raw(key) for key in every}
        unsigned = CatalogRootRecord(
            version=1,
            threshold=2,
            root_key_ids=self.pin,
            snapshot_key_ids=frozenset({catalog_key_id(_raw(self.snapshot_key))}),
            timestamp_key_ids=frozenset({catalog_key_id(_raw(self.timestamp_key))}),
            export_key_ids=frozenset({catalog_key_id(_raw(self.export_key))}),
            public_keys=keys,
            signed_at=now,
            expires_at=now + timedelta(days=valid_days),
        )
        payload = unsigned.canonical_payload()
        signatures = {
            catalog_key_id(_raw(key)): _sign(key, "root", payload) for key in self.root_keys[:2]
        }
        return replace(unsigned, signatures=signatures)

    def metadata(
        self,
        *,
        now: datetime = NOW,
        version: int = 1,
        timestamp_ttl: timedelta = timedelta(hours=24),
        root: CatalogRootRecord | None = None,
        tamper: bool = False,
    ) -> bytes:
        snapshot_unsigned = CatalogSnapshotRecord(
            version=version,
            channel_versions={"DEV": 1},
            recall_sequences=(),
            key_id=catalog_key_id(_raw(self.snapshot_key)),
            signed_at=now,
            expires_at=now + timedelta(days=7),
            export_digest="0" * 64,
            export_revision=1,
        )
        snapshot = replace(
            snapshot_unsigned,
            signature=_sign(self.snapshot_key, "snapshot", snapshot_unsigned.canonical_payload()),
        )
        timestamp_unsigned = CatalogTimestampRecord(
            version=version,
            snapshot_version=snapshot.version,
            snapshot_digest=snapshot.digest,
            key_id=catalog_key_id(_raw(self.timestamp_key)),
            signed_at=now,
            expires_at=now + timestamp_ttl,
        )
        signer = Ed25519PrivateKey.generate() if tamper else self.timestamp_key
        timestamp = replace(
            timestamp_unsigned,
            signature=_sign(signer, "timestamp", timestamp_unsigned.canonical_payload()),
        )
        return MetadataBundle((root or self.root(now),), snapshot, timestamp).to_bytes()


class Registry:
    def __init__(self) -> None:
        self.expired: bool | None = None

    def set_catalog_timestamp_expired(self, expired: bool) -> None:
        self.expired = expired


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class Source:
    def __init__(self, *responses: bytes | Exception) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def __call__(self, url: str) -> bytes:
        assert url == URL
        self.calls += 1
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def _monitor(authority: Authority, source: Source, clock: Clock, **overrides):
    config = CatalogFreshnessConfig(
        metadata_url=URL, root_key_ids=authority.pin, root_threshold=2, **overrides
    )
    return CatalogFreshnessMonitor(config, fetch=source, clock=clock)


def _run(coro):
    return asyncio.run(coro)


def test_verified_fresh_metadata_clears_the_expiry_flag() -> None:
    authority, clock, registry = Authority(), Clock(), Registry()
    monitor = _monitor(authority, Source(authority.metadata()), clock)

    assert _run(monitor.apply(registry)) is False
    assert registry.expired is False
    assert monitor.status()["reason"] == "fresh"


def test_unreachable_source_with_no_verified_state_is_expired() -> None:
    authority, clock, registry = Authority(), Clock(), Registry()
    monitor = _monitor(authority, Source(TimeoutError()), clock)

    assert _run(monitor.apply(registry)) is True
    assert registry.expired is True
    assert monitor.status()["reason"] == "catalog_metadata_unavailable"


def test_the_local_clock_ends_freshness_even_when_the_source_stays_unreachable() -> None:
    authority, clock, registry = Authority(), Clock(), Registry()
    monitor = _monitor(
        authority, Source(authority.metadata(), TimeoutError()), clock, refresh_seconds=30
    )
    assert _run(monitor.apply(registry)) is False

    clock.now = NOW + timedelta(hours=23)
    assert _run(monitor.apply(registry)) is False

    clock.now = NOW + timedelta(hours=24, seconds=1)
    assert _run(monitor.apply(registry)) is True
    assert monitor.status()["reason"] == "catalog_metadata_unavailable"


def test_a_served_but_expired_timestamp_is_expired() -> None:
    authority, clock, registry = Authority(), Clock(), Registry()
    stale = authority.metadata(now=NOW - timedelta(days=2))
    monitor = _monitor(authority, Source(stale), clock)

    assert _run(monitor.apply(registry)) is True
    assert monitor.status()["reason"] == "catalog_timestamp_expired"


def test_a_different_root_pin_is_refused() -> None:
    authority, clock, registry = Authority(), Clock(), Registry()
    other = Authority()
    monitor = _monitor(other, Source(authority.metadata()), clock)

    assert _run(monitor.apply(registry)) is True
    assert monitor.status()["reason"] == "catalog_root_pin_mismatch"


def test_a_forged_timestamp_cannot_extend_verified_freshness() -> None:
    authority, clock, registry = Authority(), Clock(), Registry()
    source = Source(authority.metadata(), authority.metadata(version=2, tamper=True))
    monitor = _monitor(authority, source, clock, refresh_seconds=30)
    assert _run(monitor.apply(registry)) is False

    clock.now = NOW + timedelta(hours=24, seconds=1)
    assert _run(monitor.apply(registry)) is True
    assert monitor.status()["reason"] == "catalog_timestamp_signature_invalid"


def test_a_replayed_older_version_is_refused_and_keeps_the_verified_state() -> None:
    authority, clock, registry = Authority(), Clock(), Registry()
    source = Source(authority.metadata(version=5), authority.metadata(version=2))
    monitor = _monitor(authority, source, clock, refresh_seconds=30)
    _run(monitor.apply(registry))

    clock.now = NOW + timedelta(seconds=45)
    assert _run(monitor.apply(registry)) is False
    assert monitor.status()["timestamp_version"] == 5


def test_a_newer_signed_timestamp_renews_freshness() -> None:
    authority, clock, registry = Authority(), Clock(), Registry()
    renewed_at = NOW + timedelta(hours=20)
    source = Source(
        authority.metadata(version=1),
        authority.metadata(version=2, now=renewed_at, root=authority.root()),
    )
    monitor = _monitor(authority, source, clock, refresh_seconds=30)
    _run(monitor.apply(registry))

    clock.now = renewed_at
    assert _run(monitor.apply(registry)) is False
    clock.now = NOW + timedelta(hours=30)
    assert _run(monitor.apply(registry)) is False
    assert monitor.status()["timestamp_version"] == 2


def test_the_source_is_consulted_only_when_the_refresh_interval_has_passed() -> None:
    authority, clock, registry = Authority(), Clock(), Registry()
    source = Source(authority.metadata())
    monitor = _monitor(authority, source, clock, refresh_seconds=300)

    _run(monitor.apply(registry))
    clock.now = NOW + timedelta(seconds=299)
    _run(monitor.apply(registry))
    assert source.calls == 1
    clock.now = NOW + timedelta(seconds=301)
    _run(monitor.apply(registry))
    assert source.calls == 2


def test_oversized_and_malformed_bodies_are_refused() -> None:
    authority, clock, registry = Authority(), Clock(), Registry()
    monitor = _monitor(authority, Source(b"{not json"), clock)

    assert _run(monitor.apply(registry)) is True
    assert monitor.status()["reason"] == "Catalog metadata is malformed."


def test_the_feature_is_off_unless_selected() -> None:
    assert build_catalog_freshness_monitor({}) is None
    assert build_catalog_freshness_monitor({"FDAI_CATALOG_FRESHNESS_METADATA_URL": " "}) is None


def test_selected_configuration_is_validated() -> None:
    authority = Authority()
    pins = ",".join(sorted(authority.pin))
    base = {
        "FDAI_CATALOG_FRESHNESS_METADATA_URL": URL,
        "FDAI_CATALOG_FRESHNESS_ROOT_KEY_IDS": pins,
    }
    config = CatalogFreshnessConfig.from_environment(base)
    assert config is not None and config.root_threshold == 3 and config.refresh_seconds == 300.0

    with pytest.raises(ValueError):
        CatalogFreshnessConfig.from_environment(
            {**base, "FDAI_CATALOG_FRESHNESS_METADATA_URL": "http://releases.example.invalid/m"}
        )
    with pytest.raises(ValueError):
        CatalogFreshnessConfig.from_environment({"FDAI_CATALOG_FRESHNESS_METADATA_URL": URL})
    with pytest.raises(ValueError):
        CatalogFreshnessConfig.from_environment(
            {**base, "FDAI_CATALOG_FRESHNESS_ROOT_THRESHOLD": "4"}
        )
    with pytest.raises(ValueError):
        CatalogFreshnessConfig.from_environment(
            {**base, "FDAI_CATALOG_FRESHNESS_REFRESH_SECONDS": "5"}
        )
    with pytest.raises(ValueError):
        CatalogFreshnessConfig(
            metadata_url="https://user:secret@releases.example.invalid/m",
            root_key_ids=authority.pin,
            root_threshold=2,
        )
    assert CatalogFreshnessConfig(
        metadata_url="http://127.0.0.1:8080/m", root_key_ids=authority.pin, root_threshold=2
    )


class _Store:
    async def read_state(self, key: str) -> None:
        return None


def _profile_registry(monkeypatch, monitor):
    from types import SimpleNamespace

    from fdai.delivery import catalog_freshness
    from fdai.runtime.product_profile import RuntimeProductSelection, build_promotion_registry

    monkeypatch.setattr(catalog_freshness, "build_catalog_freshness_monitor", lambda env: monitor)
    return build_promotion_registry(
        RuntimeProductSelection(
            governed_execution=True,
            notifications=False,
            enterprise_identity=False,
            policy_administration=False,
        ),
        container=SimpleNamespace(
            operational_promotion_receipt_verifier=None,
            persisted_promotion_authority_verifier=None,
        ),
        audit_store=_Store(),
        durable=True,
        environment={},
    )


def test_every_promotion_refresh_applies_the_freshness_monitor(monkeypatch) -> None:
    authority, clock = Authority(), Clock()
    monitor = _monitor(authority, Source(TimeoutError()), clock)
    registry, refresh = _profile_registry(monkeypatch, monitor)

    _run(refresh("restart_workload"))
    assert registry._catalog_timestamp_expired is True

    fresh = _monitor(authority, Source(authority.metadata()), clock)
    registry, refresh = _profile_registry(monkeypatch, fresh)
    _run(refresh("restart_workload"))
    assert registry._catalog_timestamp_expired is False


def test_without_a_selected_monitor_the_registry_refresh_is_unchanged(monkeypatch) -> None:
    registry, refresh = _profile_registry(monkeypatch, None)

    assert refresh == registry.refresh
