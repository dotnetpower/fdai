"""Validate the environment contract for inventory reconciliation jobs."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from fdai.delivery.azure.arg_transport import DEFAULT_ARG_REQUESTS_PER_SECOND
from fdai.delivery.inventory_source_policy import (
    InventoryCollectionPolicy,
    SourceCollectionPolicy,
    load_inventory_collection_policy,
)
from fdai.delivery.inventory_sync import (
    DEFAULT_ATTEMPT_DEADLINE_SECONDS,
    DEFAULT_PROGRESS_DEADLINE_SECONDS,
    MAX_ATTEMPT_DEADLINE_SECONDS,
)
from fdai.delivery.repo_assets import repo_asset_root

_DEFAULT_LOOP_SECONDS = 60
_DEFAULT_CHANGE_MIN_INTERVAL_SECONDS = 120
_DEFAULT_COLLECTION_POLICY_PATH = repo_asset_root() / "config" / "inventory-collection-policy.json"
_MANAGEMENT_AUDIENCE_BY_ORIGIN = {
    "https://management.azure.com": "https://management.azure.com/.default",
    "https://management.chinacloudapi.cn": "https://management.chinacloudapi.cn/.default",
    "https://management.microsoftazure.de": "https://management.microsoftazure.de/.default",
    "https://management.usgovcloudapi.net": "https://management.usgovcloudapi.net/.default",
}


@dataclass(frozen=True, slots=True)
class InventoryJobConfig:
    """Hold one validated inventory collection and scheduling profile."""

    dsn: str
    scopes: tuple[str, ...]
    source_order: tuple[str, ...]
    resource_types: tuple[str, ...]
    management_endpoint: str
    management_audience: str
    freshness_budget_seconds: int
    reconciliation_interval_seconds: int
    loop_seconds: int = _DEFAULT_LOOP_SECONDS
    change_min_interval_seconds: int = _DEFAULT_CHANGE_MIN_INTERVAL_SECONDS
    progress_deadline_seconds: int = int(DEFAULT_PROGRESS_DEADLINE_SECONDS)
    attempt_deadline_seconds: int = int(DEFAULT_ATTEMPT_DEADLINE_SECONDS)
    arg_requests_per_second: float = DEFAULT_ARG_REQUESTS_PER_SECOND
    recovery_delta_enabled: bool = True
    resource_change_feed_enabled: bool = True
    declarative_path: Path | None = None
    declarative_sha256: str | None = None
    kubernetes_api_server: str | None = None
    kubernetes_cluster_ref: str | None = None
    kubernetes_token_path: Path | None = None
    kubernetes_ca_path: Path | None = None
    kubernetes_ca_pem: str | None = None
    kubernetes_auth_mode: str | None = None
    kubernetes_audience: str | None = None
    collection_policy: InventoryCollectionPolicy | None = None

    def snapshot_policy(self, source_name: str) -> SourceCollectionPolicy:
        """Return the validated snapshot policy for one configured fallback source."""

        if self.collection_policy is None:
            raise RuntimeError("inventory collection policy is unavailable")
        return self.collection_policy.source(f"{source_name}-snapshot")

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        runtime_values: Mapping[str, object] | None = None,
    ) -> InventoryJobConfig:
        """Parse bounded settings and reject incomplete source configuration."""

        source = env if env is not None else os.environ
        dsn = source.get("FDAI_INVENTORY_DSN", "").strip()
        default_scope = source.get("AZURE_SUBSCRIPTION_ID", "").strip()
        scopes = _csv(source.get("FDAI_INVENTORY_SCOPES", default_scope))
        source_order = _csv(source.get("FDAI_INVENTORY_SOURCES", "arg,arm"))
        resource_types = _csv(source.get("FDAI_INVENTORY_RESOURCE_TYPES", ""))
        management_endpoint = source.get(
            "FDAI_INVENTORY_MANAGEMENT_ENDPOINT", "https://management.azure.com"
        ).strip()
        management_audience = source.get(
            "FDAI_INVENTORY_MANAGEMENT_AUDIENCE",
            "https://management.azure.com/.default",
        ).strip()
        freshness = _freshness_seconds(source=source, runtime_values=runtime_values)
        reconciliation_interval = _integer_env(
            source,
            "FDAI_INVENTORY_RECONCILIATION_INTERVAL_SECONDS",
            21_600,
        )
        loop_seconds = _integer_env(source, "FDAI_INVENTORY_LOOP_SECONDS", _DEFAULT_LOOP_SECONDS)
        change_min_interval = _integer_env(
            source,
            "FDAI_INVENTORY_CHANGE_MIN_INTERVAL_SECONDS",
            _DEFAULT_CHANGE_MIN_INTERVAL_SECONDS,
        )
        progress_deadline = _integer_env(
            source,
            "FDAI_INVENTORY_PROGRESS_DEADLINE_SECONDS",
            int(DEFAULT_PROGRESS_DEADLINE_SECONDS),
        )
        attempt_deadline = _integer_env(
            source,
            "FDAI_INVENTORY_ATTEMPT_DEADLINE_SECONDS",
            int(DEFAULT_ATTEMPT_DEADLINE_SECONDS),
        )
        arg_requests_per_second = _float_env(
            source,
            "FDAI_INVENTORY_ARG_REQUESTS_PER_SECOND",
            DEFAULT_ARG_REQUESTS_PER_SECOND,
        )
        recovery_delta_enabled = read_bool_env(
            source,
            "FDAI_INVENTORY_RECOVERY_DELTA",
            True,
        )
        resource_change_feed_enabled = read_bool_env(
            source,
            "FDAI_INVENTORY_RESOURCE_CHANGE_FEED",
            True,
        )
        declarative_value = source.get("FDAI_INVENTORY_DECLARATIVE_PATH", "").strip()
        declarative_sha256 = source.get("FDAI_INVENTORY_DECLARATIVE_SHA256", "").strip() or None
        kubernetes_api_server = source.get("FDAI_KUBERNETES_API_SERVER", "").strip() or None
        kubernetes_cluster_ref = source.get("FDAI_KUBERNETES_CLUSTER_REF", "").strip() or None
        kubernetes_token_value = source.get("FDAI_KUBERNETES_TOKEN_PATH", "").strip()
        kubernetes_ca_value = source.get("FDAI_KUBERNETES_CA_PATH", "").strip()
        kubernetes_ca_pem = source.get("FDAI_KUBERNETES_CA_PEM", "").strip() or None
        kubernetes_auth_mode = source.get("FDAI_KUBERNETES_AUTH_MODE", "").strip() or (
            "service-account" if kubernetes_token_value else None
        )
        kubernetes_audience = source.get(
            "FDAI_KUBERNETES_AUDIENCE",
            "",
        ).strip()
        collection_policy_path = Path(
            source.get(
                "FDAI_INVENTORY_COLLECTION_POLICY_PATH",
                str(_DEFAULT_COLLECTION_POLICY_PATH),
            ).strip()
        )

        if not dsn:
            raise ValueError("FDAI_INVENTORY_DSN MUST NOT be empty")
        if not scopes:
            raise ValueError("FDAI_INVENTORY_SCOPES MUST NOT be empty")
        if not source_order or set(source_order) - {"arg", "arm", "declarative"}:
            raise ValueError("FDAI_INVENTORY_SOURCES supports arg, arm, declarative")
        _validate_management_origin(management_endpoint, management_audience)
        if freshness < 1:
            raise ValueError("FDAI_INVENTORY_FRESHNESS_SECONDS MUST be >= 1")
        if reconciliation_interval < 60:
            raise ValueError("FDAI_INVENTORY_RECONCILIATION_INTERVAL_SECONDS MUST be >= 60")
        if not 5 <= loop_seconds <= 3_600:
            raise ValueError("FDAI_INVENTORY_LOOP_SECONDS MUST be in [5, 3600]")
        if not 1 <= change_min_interval <= reconciliation_interval:
            raise ValueError(
                "FDAI_INVENTORY_CHANGE_MIN_INTERVAL_SECONDS MUST be in "
                "[1, FDAI_INVENTORY_RECONCILIATION_INTERVAL_SECONDS]"
            )
        if progress_deadline < 60:
            raise ValueError("FDAI_INVENTORY_PROGRESS_DEADLINE_SECONDS MUST be >= 60")
        if not progress_deadline <= attempt_deadline <= MAX_ATTEMPT_DEADLINE_SECONDS:
            raise ValueError(
                "FDAI_INVENTORY_ATTEMPT_DEADLINE_SECONDS MUST be in "
                "[FDAI_INVENTORY_PROGRESS_DEADLINE_SECONDS, "
                f"{int(MAX_ATTEMPT_DEADLINE_SECONDS)}]"
            )
        if not 0 < arg_requests_per_second <= 100:
            raise ValueError("FDAI_INVENTORY_ARG_REQUESTS_PER_SECOND MUST be in (0, 100]")
        if "declarative" in source_order and (not declarative_value or declarative_sha256 is None):
            raise ValueError(
                "declarative fallback requires FDAI_INVENTORY_DECLARATIVE_PATH and SHA256"
            )
        kubernetes_values = (
            kubernetes_api_server,
            kubernetes_cluster_ref,
            kubernetes_auth_mode,
            kubernetes_ca_value or kubernetes_ca_pem,
        )
        if any(kubernetes_values) and not all(kubernetes_values):
            raise ValueError(
                "Kubernetes inventory requires API server, cluster ref, auth mode, and CA"
            )
        if kubernetes_ca_value and kubernetes_ca_pem is not None:
            raise ValueError("Kubernetes inventory accepts exactly one CA binding")
        if kubernetes_auth_mode not in {None, "service-account", "workload-identity"}:
            raise ValueError("FDAI_KUBERNETES_AUTH_MODE is invalid")
        if kubernetes_auth_mode == "service-account" and not kubernetes_token_value:
            raise ValueError("service-account Kubernetes auth requires token path")
        if kubernetes_auth_mode == "workload-identity" and kubernetes_token_value:
            raise ValueError("workload-identity Kubernetes auth MUST NOT bind a token path")
        if kubernetes_auth_mode == "workload-identity" and not kubernetes_audience:
            raise ValueError("workload-identity Kubernetes auth requires an audience")
        if kubernetes_api_server is not None:
            parsed_kubernetes = urlparse(kubernetes_api_server)
            if (
                parsed_kubernetes.scheme != "https"
                or not parsed_kubernetes.netloc
                or parsed_kubernetes.username is not None
                or parsed_kubernetes.password is not None
                or parsed_kubernetes.query
                or parsed_kubernetes.fragment
            ):
                raise ValueError("FDAI_KUBERNETES_API_SERVER MUST be credential-free HTTPS")
        collection_policy = load_inventory_collection_policy(collection_policy_path)
        _validate_collection_policy_bindings(
            collection_policy,
            source_order=source_order,
            freshness_seconds=freshness,
            reconciliation_interval_seconds=reconciliation_interval,
            change_min_interval_seconds=change_min_interval,
            progress_deadline_seconds=progress_deadline,
            attempt_deadline_seconds=attempt_deadline,
            arg_requests_per_second=arg_requests_per_second,
            recovery_delta_enabled=recovery_delta_enabled,
            resource_change_feed_enabled=resource_change_feed_enabled,
        )
        return cls(
            dsn=dsn,
            scopes=scopes,
            source_order=source_order,
            resource_types=resource_types,
            management_endpoint=management_endpoint,
            management_audience=management_audience,
            freshness_budget_seconds=freshness,
            reconciliation_interval_seconds=reconciliation_interval,
            loop_seconds=loop_seconds,
            change_min_interval_seconds=change_min_interval,
            progress_deadline_seconds=progress_deadline,
            attempt_deadline_seconds=attempt_deadline,
            arg_requests_per_second=arg_requests_per_second,
            recovery_delta_enabled=recovery_delta_enabled,
            resource_change_feed_enabled=resource_change_feed_enabled,
            declarative_path=Path(declarative_value) if declarative_value else None,
            declarative_sha256=declarative_sha256,
            kubernetes_api_server=kubernetes_api_server,
            kubernetes_cluster_ref=kubernetes_cluster_ref,
            kubernetes_token_path=(
                Path(kubernetes_token_value) if kubernetes_token_value else None
            ),
            kubernetes_ca_path=Path(kubernetes_ca_value) if kubernetes_ca_value else None,
            kubernetes_ca_pem=kubernetes_ca_pem,
            kubernetes_auth_mode=kubernetes_auth_mode,
            kubernetes_audience=(
                kubernetes_audience if kubernetes_auth_mode == "workload-identity" else None
            ),
            collection_policy=collection_policy,
        )


def _validate_management_origin(endpoint: str, audience: str) -> None:
    parsed = urlparse(endpoint)
    normalized = endpoint.rstrip("/")
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or normalized not in _MANAGEMENT_AUDIENCE_BY_ORIGIN
    ):
        raise ValueError("FDAI_INVENTORY_MANAGEMENT_ENDPOINT MUST be an approved HTTPS ARM origin")
    if audience != _MANAGEMENT_AUDIENCE_BY_ORIGIN[normalized]:
        raise ValueError("FDAI_INVENTORY_MANAGEMENT_AUDIENCE MUST match the ARM origin")


def _validate_collection_policy_bindings(
    policy: InventoryCollectionPolicy,
    *,
    source_order: tuple[str, ...],
    freshness_seconds: int,
    reconciliation_interval_seconds: int,
    change_min_interval_seconds: int,
    progress_deadline_seconds: int,
    attempt_deadline_seconds: int,
    arg_requests_per_second: float,
    recovery_delta_enabled: bool,
    resource_change_feed_enabled: bool,
) -> None:
    for source_name in source_order:
        try:
            source_policy = policy.source(f"{source_name}-snapshot")
        except KeyError as exc:
            raise ValueError(
                f"inventory collection policy is missing {source_name}-snapshot"
            ) from exc
        if freshness_seconds > source_policy.max_staleness_seconds:
            raise ValueError("inventory freshness exceeds the source maximum staleness")
        if not (
            source_policy.min_poll_interval_seconds
            <= reconciliation_interval_seconds
            <= source_policy.max_poll_interval_seconds
        ):
            raise ValueError("inventory reconciliation interval is outside the source policy")
        if change_min_interval_seconds < source_policy.min_poll_interval_seconds:
            raise ValueError("inventory change interval is below the source policy minimum")
        if progress_deadline_seconds > source_policy.no_progress_timeout_seconds:
            raise ValueError("inventory progress deadline exceeds the source no-progress bound")
        if attempt_deadline_seconds > source_policy.max_run_seconds:
            raise ValueError("inventory attempt deadline exceeds the source run bound")
        if source_name == "arg" and (
            arg_requests_per_second * source_policy.budget_window_seconds
            > source_policy.max_requests_per_window
        ):
            raise ValueError("inventory ARG request rate exceeds the source request budget")
    if recovery_delta_enabled:
        try:
            policy.source("activity-log-delta")
        except KeyError as exc:
            raise ValueError("inventory collection policy is missing activity-log-delta") from exc
    if resource_change_feed_enabled:
        try:
            policy.source("resourcechanges-delta")
        except KeyError as exc:
            raise ValueError(
                "inventory collection policy is missing resourcechanges-delta"
            ) from exc


def _freshness_seconds(
    *,
    source: Mapping[str, str],
    runtime_values: Mapping[str, object] | None,
) -> int:
    if runtime_values is None:
        return _integer_env(source, "FDAI_INVENTORY_FRESHNESS_SECONDS", 86_400)
    value = runtime_values.get("inventory.freshness_seconds")
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("effective inventory freshness setting MUST be an integer")
    return value


def _integer_env(source: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(source.get(key, str(default)))
    except ValueError as exc:
        raise ValueError(f"{key} MUST be an integer") from exc


def _float_env(source: Mapping[str, str], key: str, default: float) -> float:
    try:
        return float(source.get(key, str(default)))
    except ValueError as exc:
        raise ValueError(f"{key} MUST be a decimal number") from exc


def verify_declarative_sha256(path: Path, expected: str) -> None:
    """Verify one declarative fallback without exposing its content."""

    if len(expected) != 64 or any(char not in "0123456789abcdefABCDEF" for char in expected):
        raise ValueError("declarative SHA256 MUST be 64 hexadecimal characters")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual.lower() != expected.lower():
        raise ValueError("declarative inventory SHA256 does not match")


def _csv(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))


def read_bool_env(source: Mapping[str, str], key: str, default: bool) -> bool:
    raw = source.get(key)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true"}:
        return True
    if normalized in {"0", "false"}:
        return False
    raise ValueError(f"{key} MUST be one of 1, 0, true, false")


__all__ = ["InventoryJobConfig", "read_bool_env", "verify_declarative_sha256"]
