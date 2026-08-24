"""One-shot global provider schema watcher composition entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import httpx
import yaml

from fdai.agents import EventBusBridge, load_pantheon
from fdai.agents.heimdall import Heimdall
from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.provider_schema import (
    AzureBicepProviderSchemaParser,
    GitAzureBicepProviderSchemaSource,
    LocalAzureBicepProviderSchemaSource,
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.provider_schema_ledger import ProviderSchemaLedger
from fdai.delivery.provider_schema_state_ledger import StateStoreProviderSchemaLedger
from fdai.delivery.provider_schema_watcher import (
    ProviderSchemaSourceBinding,
    ProviderSchemaSourceKind,
    ProviderSchemaWatcher,
    ProviderSchemaWatchPolicy,
)
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping


class ProviderSchemaNetworkPolicy(StrEnum):
    PUBLIC = "public"
    MIRROR_ONLY = "mirror-only"
    OFFLINE_ONLY = "offline-only"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ProviderSchemaWatcherConfig:
    """Validated source, policy, and output bindings for one watcher process."""

    ledger_root: Path
    state_store_dsn: str | None
    kafka_bootstrap_servers: str | None
    resource_types_path: Path
    network_policy: ProviderSchemaNetworkPolicy
    primary_repo: str | None
    primary_ref: str | None
    mirror_repo: str | None
    mirror_ref: str | None
    offline_root: Path | None
    offline_revision: str | None
    cadence_seconds: int
    failure_retry_seconds: int
    stale_after_seconds: int
    min_type_count: int
    max_type_count: int
    fetch_timeout_seconds: float
    review_compatible_drift: bool

    @classmethod
    def from_env(
        cls,
        source: Mapping[str, str] | None = None,
        *,
        repo_root: Path | None = None,
    ) -> ProviderSchemaWatcherConfig:
        values = os.environ if source is None else source
        root = Path.cwd() if repo_root is None else repo_root
        primary_repo, primary_ref = _optional_pair(
            values,
            "FDAI_PROVIDER_SCHEMA_PRIMARY_REPO",
            "FDAI_PROVIDER_SCHEMA_PRIMARY_REF",
        )
        mirror_repo, mirror_ref = _optional_pair(
            values,
            "FDAI_PROVIDER_SCHEMA_MIRROR_REPO",
            "FDAI_PROVIDER_SCHEMA_MIRROR_REF",
        )
        offline_root_raw, offline_revision = _optional_pair(
            values,
            "FDAI_PROVIDER_SCHEMA_OFFLINE_ROOT",
            "FDAI_PROVIDER_SCHEMA_OFFLINE_REVISION",
        )
        try:
            network_policy = ProviderSchemaNetworkPolicy(
                values.get("FDAI_PROVIDER_SCHEMA_NETWORK_POLICY", "blocked").strip()
            )
        except ValueError as exc:
            raise ValueError("FDAI_PROVIDER_SCHEMA_NETWORK_POLICY is invalid") from exc
        return cls(
            ledger_root=Path(
                values.get(
                    "FDAI_PROVIDER_SCHEMA_LEDGER_ROOT",
                    str(root / "provider-schema-catalog"),
                )
            ),
            state_store_dsn=_optional_value(values.get("FDAI_PROVIDER_SCHEMA_DSN")),
            kafka_bootstrap_servers=_optional_value(values.get("KAFKA_BOOTSTRAP_SERVERS")),
            resource_types_path=Path(
                values.get(
                    "FDAI_PROVIDER_SCHEMA_RESOURCE_TYPES_PATH",
                    str(root / "rule-catalog" / "vocabulary" / "resource-types.yaml"),
                )
            ),
            network_policy=network_policy,
            primary_repo=primary_repo,
            primary_ref=primary_ref,
            mirror_repo=mirror_repo,
            mirror_ref=mirror_ref,
            offline_root=None if offline_root_raw is None else Path(offline_root_raw),
            offline_revision=offline_revision,
            cadence_seconds=_positive_int(values, "FDAI_PROVIDER_SCHEMA_CADENCE_SECONDS", 86_400),
            failure_retry_seconds=_positive_int(
                values,
                "FDAI_PROVIDER_SCHEMA_FAILURE_RETRY_SECONDS",
                3_600,
            ),
            stale_after_seconds=_positive_int(
                values,
                "FDAI_PROVIDER_SCHEMA_STALE_AFTER_SECONDS",
                604_800,
            ),
            min_type_count=_positive_int(values, "FDAI_PROVIDER_SCHEMA_MIN_TYPES", 3_000),
            max_type_count=_positive_int(values, "FDAI_PROVIDER_SCHEMA_MAX_TYPES", 10_000),
            fetch_timeout_seconds=_positive_float(
                values,
                "FDAI_PROVIDER_SCHEMA_FETCH_TIMEOUT_SECONDS",
                120.0,
            ),
            review_compatible_drift=_bool_value(
                values.get("FDAI_PROVIDER_SCHEMA_REVIEW_COMPATIBLE", "0")
            ),
        )

    def __post_init__(self) -> None:
        if self.max_type_count < self.min_type_count:
            raise ValueError("provider schema maximum type count MUST cover minimum")
        ProviderSchemaWatchPolicy(
            cadence_seconds=self.cadence_seconds,
            failure_retry_seconds=self.failure_retry_seconds,
            stale_after_seconds=self.stale_after_seconds,
            review_compatible_drift=self.review_compatible_drift,
        )


async def run(
    config: ProviderSchemaWatcherConfig,
    *,
    now: datetime,
    force: bool,
) -> dict[str, object]:
    """Compose configured sources and return one serializable terminal receipt."""

    if config.state_store_dsn is not None:
        with tempfile.TemporaryDirectory(prefix="fdai-provider-schema-ledger-") as temporary:
            durable = StateStoreProviderSchemaLedger(
                PostgresStateStore(
                    config=PostgresStateStoreConfig(dsn=config.state_store_dsn),
                )
            )
            ledger_root = Path(temporary)
            await durable.hydrate(ledger_root)
            receipt = await _run_local(
                replace(config, ledger_root=ledger_root, state_store_dsn=None),
                now=now,
                force=force,
            )
            receipt["durable_generation_digest"] = await durable.persist(ledger_root)
            return receipt
    return await _run_local(config, now=now, force=force)


async def _run_local(
    config: ProviderSchemaWatcherConfig,
    *,
    now: datetime,
    force: bool,
) -> dict[str, object]:
    """Run against one local ledger root after any durable hydration."""

    parser = AzureBicepProviderSchemaParser(
        min_type_count=config.min_type_count,
        max_type_count=config.max_type_count,
    )
    sources = _build_sources(config, parser=parser)
    registry_raw = yaml.safe_load(config.resource_types_path.read_text(encoding="utf-8"))
    if not isinstance(registry_raw, Mapping):
        raise ValueError("provider schema ResourceType registry MUST be a mapping")
    registry = load_resource_type_registry_from_mapping(registry_raw)
    modeled = frozenset(
        entry.azure_arm_type.casefold()
        for entry in registry.types
        if entry.azure_arm_type is not None
    )
    watcher = ProviderSchemaWatcher(
        provider="azure",
        sources=sources,
        ledger=ProviderSchemaLedger(config.ledger_root),
        modeled_provider_types=modeled,
        policy=ProviderSchemaWatchPolicy(
            cadence_seconds=config.cadence_seconds,
            failure_retry_seconds=config.failure_retry_seconds,
            stale_after_seconds=config.stale_after_seconds,
            review_compatible_drift=config.review_compatible_drift,
        ),
        review_publisher=None,
    )
    if config.kafka_bootstrap_servers is None:
        return (await watcher.run(now=now, force=force)).to_mapping()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
    ) as http_client:
        identity = ManagedIdentityWorkloadIdentity.from_env(http_client=http_client)
        bus = EventHubsKafkaBus(
            identity=identity,
            config=EventHubsKafkaBusConfig(
                bootstrap_servers=config.kafka_bootstrap_servers,
                client_id="fdai-provider-schema-watcher",
            ),
        )
        bridge = EventBusBridge(provider=bus, registry=load_pantheon())
        try:
            watcher = ProviderSchemaWatcher(
                provider="azure",
                sources=sources,
                ledger=ProviderSchemaLedger(config.ledger_root),
                modeled_provider_types=modeled,
                policy=ProviderSchemaWatchPolicy(
                    cadence_seconds=config.cadence_seconds,
                    failure_retry_seconds=config.failure_retry_seconds,
                    stale_after_seconds=config.stale_after_seconds,
                    review_compatible_drift=config.review_compatible_drift,
                ),
                review_publisher=Heimdall(bus=bridge),
            )
            return (await watcher.run(now=now, force=force)).to_mapping()
        finally:
            await bus.close()


def _build_sources(
    config: ProviderSchemaWatcherConfig,
    *,
    parser: AzureBicepProviderSchemaParser,
) -> tuple[ProviderSchemaSourceBinding, ...]:
    public_allowed = config.network_policy is ProviderSchemaNetworkPolicy.PUBLIC
    mirror_allowed = config.network_policy in {
        ProviderSchemaNetworkPolicy.PUBLIC,
        ProviderSchemaNetworkPolicy.MIRROR_ONLY,
    }
    offline_allowed = config.network_policy is not ProviderSchemaNetworkPolicy.BLOCKED
    sources: list[ProviderSchemaSourceBinding] = []
    if config.primary_repo is not None and config.primary_ref is not None:
        sources.append(
            ProviderSchemaSourceBinding(
                name="azure-bicep-primary",
                kind=ProviderSchemaSourceKind.PRIMARY,
                source=GitAzureBicepProviderSchemaSource(
                    repo_url=config.primary_repo,
                    revision_ref=config.primary_ref,
                    parser=parser,
                    timeout_seconds=config.fetch_timeout_seconds,
                ),
                allowed=public_allowed,
            )
        )
    if config.mirror_repo is not None and config.mirror_ref is not None:
        sources.append(
            ProviderSchemaSourceBinding(
                name="azure-bicep-mirror",
                kind=ProviderSchemaSourceKind.MIRROR,
                source=GitAzureBicepProviderSchemaSource(
                    repo_url=config.mirror_repo,
                    revision_ref=config.mirror_ref,
                    parser=parser,
                    timeout_seconds=config.fetch_timeout_seconds,
                ),
                allowed=mirror_allowed,
            )
        )
    if config.offline_root is not None and config.offline_revision is not None:
        sources.append(
            ProviderSchemaSourceBinding(
                name="azure-bicep-offline",
                kind=ProviderSchemaSourceKind.OFFLINE,
                source=LocalAzureBicepProviderSchemaSource(
                    tree_root=config.offline_root,
                    source_revision=config.offline_revision,
                    parser=parser,
                ),
                allowed=offline_allowed,
            )
        )
    return tuple(sources)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdai-provider-schema-watcher")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--now", default=None)
    return parser


def _optional_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        now = datetime.now(UTC) if args.now is None else datetime.fromisoformat(args.now)
        receipt = asyncio.run(
            run(
                ProviderSchemaWatcherConfig.from_env(),
                now=now,
                force=bool(args.force),
            )
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


def _optional_pair(
    source: Mapping[str, str],
    first_key: str,
    second_key: str,
) -> tuple[str | None, str | None]:
    first = source.get(first_key, "").strip() or None
    second = source.get(second_key, "").strip() or None
    if (first is None) != (second is None):
        raise ValueError(f"{first_key} and {second_key} MUST be configured together")
    return first, second


def _positive_int(source: Mapping[str, str], key: str, default: int) -> int:
    try:
        value = int(source.get(key, str(default)))
    except ValueError as exc:
        raise ValueError(f"{key} MUST be an integer") from exc
    if value < 1:
        raise ValueError(f"{key} MUST be positive")
    return value


def _positive_float(source: Mapping[str, str], key: str, default: float) -> float:
    try:
        value = float(source.get(key, str(default)))
    except ValueError as exc:
        raise ValueError(f"{key} MUST be numeric") from exc
    if value <= 0:
        raise ValueError(f"{key} MUST be positive")
    return value


def _bool_value(raw: str) -> bool:
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("provider schema boolean setting is invalid")


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())


__all__ = ["ProviderSchemaNetworkPolicy", "ProviderSchemaWatcherConfig", "main", "run"]
