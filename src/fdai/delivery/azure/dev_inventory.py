"""AzureCliInventory - dev-mode Inventory backed by ``az`` CLI shell-outs.

Zero-dep alternative to :class:`~fdai.delivery.azure.inventory.AzureResourceGraphInventory`
for the operator console CLI. Instead of holding an :class:`httpx.AsyncClient`
+ :class:`WorkloadIdentity`, this adapter shells out through the operator's
authenticated ``az`` session. It prefers a bounded ``az graph query`` for
relationship-bearing properties and combines that with ``az group list`` and
``az vm list --show-details`` before folding rows into :class:`ResourceRecord` shapes.

Why a dev adapter?
------------------

- The operator has already run ``az login``; the CLI should use that
  credential without a separate Managed-Identity provision.
- The full ARG factory in ``arg_query.py`` is async + requires an
  ``httpx.AsyncClient`` + subscription-scope config + a
  :class:`ResourceTypeRegistry`. The CLI REPL is sync per turn; a
  simpler surface keeps the composition root readable.
- When the ``resource-graph`` az CLI extension or ARG is unavailable, the
    adapter falls back to core ``az resource list`` discovery. Resource coverage
    remains available while relationships without returned properties stay partial.

Scope
-----

- Interactive discovery maps every Azure ARM type declared in the canonical
    resource-type registry. It combines one resource-group scan, one complete
    resource scan, and one VM details scan so live power state does not require
    serial calls for every type.
- ``delta`` returns an empty final batch (Activity Log delta stream
  belongs to the production adapter).
- Emits bounded ``contains``, ``attached_to``, and ``depends_on`` links using
    the same ARM projection helpers as production Resource Graph discovery.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import subprocess
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Final

from fdai.delivery.azure.arg_projection import (
    build_arm_to_neutral_map,
    extract_attached_to_links_from_row,
    extract_depends_on_links_from_row,
    extract_rg_contains_links,
    materialize_nested_subnets,
    resource_operational_status,
    to_neutral_id,
    truncate_props,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    resolve_azure_resource_type,
)
from fdai.shared.providers.inventory import (
    InventoryBatch,
    LinkRecord,
    ResourceRecord,
)

_AZ_TIMEOUT_SECONDS: Final[float] = 30.0
_MAX_PROPS_BYTES: Final[int] = 64 * 1024
_ARG_PAGE_SIZE: Final[int] = 1000
_ARG_MAX_PAGES: Final[int] = 32
_ARG_MAX_ATTEMPTS: Final[int] = 3
_ARG_INITIAL_RETRY_DELAY_SECONDS: Final[float] = 0.5
_RECEIPT_PREVIEW_LIMIT: Final[int] = 10
_RECEIPT_VALUE_CHARS: Final[int] = 512
_ARG_RESOURCES_QUERY: Final[str] = (
    "Resources | order by id asc "
    "| project id, type, name, location, kind, sku, tags, properties, "
    "resourceGroup, subscriptionId"
)
_UNCLASSIFIED_RESOURCE_TYPE: Final[str] = "unclassified-resource"
_LOGGER = logging.getLogger(__name__)


class AzureCliInventoryError(RuntimeError):
    """Raised when ``az`` is missing or returns unusable output."""


# Neutral resource_type -> the argv tail passed to ``az`` (after the
# fixed prefix). Every entry MUST produce JSON on stdout on success.
_NEUTRAL_TYPE_TO_AZ_ARGS: Final[dict[str, tuple[str, ...]]] = {
    "resource-group": ("group", "list", "--output", "json"),
    "object-storage": (
        "resource",
        "list",
        "--resource-type",
        "Microsoft.Storage/storageAccounts",
        "--output",
        "json",
    ),
    "sql-database": (
        "resource",
        "list",
        "--resource-type",
        "Microsoft.Sql/servers/databases",
        "--output",
        "json",
    ),
    "postgresql-server": (
        "postgres",
        "flexible-server",
        "list",
        "--output",
        "json",
    ),
    "kubernetes-cluster": (
        "resource",
        "list",
        "--resource-type",
        "Microsoft.ContainerService/managedClusters",
        "--output",
        "json",
    ),
    "compute.vm": (
        "vm",
        "list",
        "--show-details",
        "--output",
        "json",
    ),
}
_DEFAULT_ARM_TYPES: Final[dict[str, str]] = {
    **{
        resource_type: args[args.index("--resource-type") + 1]
        for resource_type, args in _NEUTRAL_TYPE_TO_AZ_ARGS.items()
        if "--resource-type" in args
    },
    "postgresql-server": "Microsoft.DBforPostgreSQL/flexibleServers",
}


@dataclass(slots=True)
class AzureCliInventory:
    """Dev :class:`Inventory` shelling to ``az`` for one subscription.

    A fork wanting parallel-shard ARG queries + link extraction uses
    :class:`~fdai.delivery.azure.inventory.AzureResourceGraphInventory`
    with :class:`~fdai.delivery.azure.arg_query.AzureArgQueryFactory`
    instead; this adapter is CLI-first.
    """

    resource_types: Sequence[str] = field(default_factory=lambda: tuple(_NEUTRAL_TYPE_TO_AZ_ARGS))
    azure_arm_types: Mapping[str, str] = field(default_factory=lambda: dict(_DEFAULT_ARM_TYPES))
    resource_type_registry: ResourceTypeRegistry | None = None
    discover_all: bool = False
    subscription_id: str | None = None
    executable: str = "az"
    azure_config_dir: str | None = None
    _arm_to_neutral: Mapping[str, str] = field(init=False, repr=False)
    _last_discovery_backend: str | None = field(default=None, init=False, repr=False)
    _last_discovery_page_count: int = field(default=0, init=False, repr=False)
    _last_group_command: str | None = field(default=None, init=False, repr=False)
    _last_group_duration_ms: int | None = field(default=None, init=False, repr=False)
    _last_group_result: Mapping[str, Any] | None = field(default=None, init=False, repr=False)
    _last_resource_commands: tuple[str, ...] = field(default=(), init=False, repr=False)
    _last_resource_durations_ms: tuple[int, ...] = field(default=(), init=False, repr=False)
    _last_resource_results: tuple[Mapping[str, Any], ...] = field(
        default=(), init=False, repr=False
    )
    """Optional isolated Azure CLI profile directory.

    ``None`` removes an inherited ``AZURE_CONFIG_DIR`` so local discovery uses
    the operator's default profile. A non-empty value selects that profile
    explicitly. The subscription id still scopes every list command.
    """

    def __post_init__(self) -> None:
        arm_to_neutral = (
            build_arm_to_neutral_map(self.resource_type_registry)
            if self.resource_type_registry is not None
            else {
                arm_type.casefold(): neutral_type
                for neutral_type, arm_type in self.azure_arm_types.items()
            }
        )
        self._arm_to_neutral = MappingProxyType(dict(arm_to_neutral))

    def full_snapshot(self, since: str | None = None) -> AsyncIterator[InventoryBatch]:
        del since  # az CLI does not honour a since filter here.
        return self._emit()

    def query_receipt(self) -> Mapping[str, Any] | None:
        """Return bounded commands and results for the latest complete snapshot."""

        backend = self._last_discovery_backend
        if backend is None:
            return None
        if (
            self._last_group_command is None
            or self._last_group_duration_ms is None
            or self._last_group_result is None
            or not self._last_resource_commands
            or len(self._last_resource_commands) != len(self._last_resource_durations_ms)
            or len(self._last_resource_commands) != len(self._last_resource_results)
        ):
            return None
        return {
            "transport": "azure_cli",
            "backend": backend,
            "executed": True,
            "redacted": True,
            "page_count": self._last_discovery_page_count,
            **({"subscription_id": self.subscription_id} if self.subscription_id else {}),
            "commands": [
                {
                    "label": "resource_groups",
                    "language": "azure_cli",
                    "command": self._last_group_command,
                    "duration_ms": self._last_group_duration_ms,
                    "result": self._last_group_result,
                },
                *(
                    {
                        "label": "resources",
                        "language": "azure_cli",
                        "command": command,
                        "duration_ms": duration_ms,
                        "result": result,
                    }
                    for command, duration_ms, result in zip(
                        self._last_resource_commands,
                        self._last_resource_durations_ms,
                        self._last_resource_results,
                        strict=True,
                    )
                ),
            ],
        }

    def delta(self, cursor: str) -> AsyncIterator[InventoryBatch]:
        del cursor
        return self._empty()

    async def _emit(self) -> AsyncIterator[InventoryBatch]:
        if self.discover_all:
            yield await self._fetch_all_registered()
            yield InventoryBatch(resources=(), links=(), cursor="az-cli:end", final=True)
            return
        for resource_type in self.resource_types:
            args = self._args_for_type(resource_type)
            if args is None:
                continue
            records, links = await self._fetch(resource_type, args)
            yield InventoryBatch(
                resources=records,
                links=links,
                cursor=f"az-cli:{resource_type}",
                final=False,
            )
        # Fence: the caller MUST see final=True or discard the stream.
        yield InventoryBatch(resources=(), links=(), cursor="az-cli:end", final=True)

    async def _empty(self) -> AsyncIterator[InventoryBatch]:
        yield InventoryBatch(final=True)

    def _args_for_type(self, resource_type: str) -> tuple[str, ...] | None:
        special = _NEUTRAL_TYPE_TO_AZ_ARGS.get(resource_type)
        if special is not None:
            return special
        arm_type = self.azure_arm_types.get(
            "network.vnet" if resource_type == "network.subnet" else resource_type
        )
        if arm_type is None:
            return None
        return (
            "resource",
            "list",
            "--resource-type",
            arm_type,
            "--output",
            "json",
        )

    async def _fetch(
        self,
        resource_type: str,
        args: tuple[str, ...],
    ) -> tuple[tuple[ResourceRecord, ...], tuple[LinkRecord, ...]]:
        argv = [self.executable, *args]
        if self.subscription_id:
            argv.extend(("--subscription", self.subscription_id))
        rows = await self._fetch_rows(argv, resource_type)
        return self._project_rows(rows, resource_type)

    async def _fetch_all_registered(self) -> InventoryBatch:
        self._last_group_command = None
        self._last_group_duration_ms = None
        self._last_group_result = None
        self._last_resource_commands = ()
        self._last_resource_durations_ms = ()
        self._last_resource_results = ()
        group_args = [self.executable, "group", "list", "--output", "json"]
        resource_args = [self.executable, "resource", "list", "--output", "json"]
        if self.subscription_id:
            for argv in (group_args, resource_args):
                argv.extend(("--subscription", self.subscription_id))
        group_result, resource_rows = await asyncio.gather(
            self._fetch_rows_timed(group_args, "resource-group"),
            self._fetch_registered_rows(resource_args),
        )
        groups, group_duration_ms = group_result
        self._last_group_command = _receipt_argv(group_args)
        self._last_group_duration_ms = group_duration_ms
        self._last_group_result = _provider_result_preview(groups)
        rows_by_type: dict[str, list[dict[str, Any]]] = {"resource-group": list(groups)}
        for row in resource_rows:
            resource_type = self._resolve_registered_type(row)
            if resource_type is None:
                if self._registered_arm_candidates(row):
                    raise AzureCliInventoryError(
                        "registered ARM type is ambiguous without matching kind"
                    )
                rows_by_type.setdefault(_UNCLASSIFIED_RESOURCE_TYPE, []).append(row)
                continue
            if resource_type == "resource-group":
                continue
            rows_by_type.setdefault(resource_type, []).append(row)

        records: list[ResourceRecord] = []
        links: list[LinkRecord] = []
        for resource_type in (*self.resource_types, _UNCLASSIFIED_RESOURCE_TYPE):
            source_type = "network.vnet" if resource_type == "network.subnet" else resource_type
            projected_records, projected_links = self._project_rows(
                rows_by_type.get(source_type, ()), resource_type
            )
            records.extend(projected_records)
            links.extend(projected_links)
        return InventoryBatch(
            resources=tuple(records),
            links=_dedupe_links(links),
            cursor="az-cli:registered-resources",
        )

    async def _fetch_registered_rows(
        self,
        fallback_args: Sequence[str],
    ) -> list[dict[str, Any]]:
        self._last_discovery_backend = None
        self._last_discovery_page_count = 0
        self._last_resource_commands = ()
        self._last_resource_durations_ms = ()
        self._last_resource_results = ()
        try:
            return await self._fetch_arg_rows()
        except AzureCliInventoryError as exc:
            _LOGGER.warning(
                "azure_cli_inventory_arg_fallback",
                extra={"error_type": type(exc).__name__},
            )
            rows, duration_ms = await self._fetch_rows_timed(fallback_args, "registered resources")
            self._last_discovery_backend = "azure_resource_manager"
            self._last_discovery_page_count = 1
            self._last_resource_commands = (_receipt_argv(fallback_args),)
            self._last_resource_durations_ms = (duration_ms,)
            self._last_resource_results = (_provider_result_preview(rows),)
            return rows

    async def _fetch_arg_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        executed_commands: list[str] = []
        executed_durations_ms: list[int] = []
        executed_results: list[Mapping[str, Any]] = []
        skip_token: str | None = None
        seen_skip_tokens: set[str] = set()
        for _page in range(_ARG_MAX_PAGES):
            argv = [
                self.executable,
                "graph",
                "query",
                "--graph-query",
                _ARG_RESOURCES_QUERY,
                "--first",
                str(_ARG_PAGE_SIZE),
                "--output",
                "json",
            ]
            if self.subscription_id:
                argv.extend(("--subscriptions", self.subscription_id))
            if skip_token:
                argv.extend(("--skip-token", skip_token))
            started = time.monotonic()
            for attempt in range(_ARG_MAX_ATTEMPTS):
                try:
                    proc = await asyncio.to_thread(_run_az, argv, self.azure_config_dir)
                    break
                except AzureCliInventoryError as exc:
                    if not _is_arg_throttle_error(exc) or attempt + 1 >= _ARG_MAX_ATTEMPTS:
                        raise
                    await asyncio.sleep(_ARG_INITIAL_RETRY_DELAY_SECONDS * (2**attempt))
            executed_durations_ms.append(max(0, round((time.monotonic() - started) * 1_000)))
            try:
                payload = json.loads(proc.stdout or "{}")
            except json.JSONDecodeError as exc:
                raise AzureCliInventoryError("az graph returned non-JSON") from exc
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("data"), list)
                or not all(isinstance(row, dict) for row in payload["data"])
            ):
                raise AzureCliInventoryError("az graph returned an invalid page")
            executed_commands.append(_receipt_argv(argv, skip_token=skip_token))
            page_rows = payload["data"]
            executed_results.append(_provider_result_preview(page_rows))
            rows.extend(page_rows)
            raw_skip_token = payload.get("skip_token") or payload.get("$skipToken")
            next_token = raw_skip_token if isinstance(raw_skip_token, str) else None
            if not page_rows or not next_token:
                self._last_discovery_backend = "azure_resource_graph"
                self._last_discovery_page_count = _page + 1
                self._last_resource_commands = tuple(executed_commands)
                self._last_resource_durations_ms = tuple(executed_durations_ms)
                self._last_resource_results = tuple(executed_results)
                return rows
            if next_token in seen_skip_tokens:
                raise AzureCliInventoryError("az graph continuation token did not advance")
            seen_skip_tokens.add(next_token)
            skip_token = next_token
        raise AzureCliInventoryError("az graph pagination exceeded the page limit")

    async def _fetch_rows(
        self,
        argv: Sequence[str],
        resource_type: str,
    ) -> list[dict[str, Any]]:
        proc = await asyncio.to_thread(_run_az, argv, self.azure_config_dir)
        try:
            payload = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise AzureCliInventoryError(f"az CLI returned non-JSON for {resource_type}") from exc
        if not isinstance(payload, list):
            raise AzureCliInventoryError(f"az CLI returned non-list JSON for {resource_type}")
        return [row for row in payload if isinstance(row, dict)]

    async def _fetch_rows_timed(
        self,
        argv: Sequence[str],
        resource_type: str,
    ) -> tuple[list[dict[str, Any]], int]:
        started = time.monotonic()
        rows = await self._fetch_rows(argv, resource_type)
        return rows, max(0, round((time.monotonic() - started) * 1_000))

    def _project_rows(
        self,
        rows: Sequence[dict[str, Any]],
        resource_type: str,
    ) -> tuple[tuple[ResourceRecord, ...], tuple[LinkRecord, ...]]:
        now_iso = datetime.now(tz=UTC).isoformat()
        if resource_type == "network.subnet":
            subnet_records: list[ResourceRecord] = []
            subnet_links: list[LinkRecord] = []
            for row in rows:
                vnet = _record_from_az_row(
                    row=row,
                    resource_type="network.vnet",
                    now_iso=now_iso,
                )
                nested_records, nested_links = materialize_nested_subnets(vnet)
                subnet_records.extend(nested_records)
                subnet_links.extend(nested_links)
            return tuple(subnet_records), _dedupe_links(subnet_links)
        rows = tuple(row for row in rows if self._row_matches_type(row, resource_type))
        records = tuple(
            _record_from_az_row(row=row, resource_type=resource_type, now_iso=now_iso)
            for row in rows
        )
        links = list(extract_rg_contains_links(records))
        for row, record in zip(rows, records, strict=True):
            links.extend(
                extract_attached_to_links_from_row(
                    row,
                    child=record,
                    arm_to_neutral=self._arm_to_neutral,
                )
            )
            links.extend(
                extract_depends_on_links_from_row(
                    row,
                    child=record,
                    arm_to_neutral=self._arm_to_neutral,
                    acr_resolver=lambda _login_server: None,
                )
            )
        return records, _dedupe_links(links)

    def _resolve_registered_type(self, row: Mapping[str, Any]) -> str | None:
        arm_type = row.get("type")
        if not isinstance(arm_type, str) or not arm_type:
            return None
        if self.resource_type_registry is not None:
            resolved = resolve_azure_resource_type(
                self.resource_type_registry,
                arm_type=arm_type,
                kind=row.get("kind"),
            )
            return resolved if resolved in self.resource_types else None
        return next(
            (
                resource_type
                for resource_type, registered_arm_type in self.azure_arm_types.items()
                if resource_type in self.resource_types
                and registered_arm_type.casefold() == arm_type.casefold()
            ),
            None,
        )

    def _registered_arm_candidates(self, row: Mapping[str, Any]) -> tuple[str, ...]:
        arm_type = row.get("type")
        if not isinstance(arm_type, str) or not arm_type:
            return ()
        return tuple(
            sorted(
                resource_type
                for resource_type, registered_arm_type in self.azure_arm_types.items()
                if resource_type in self.resource_types
                and registered_arm_type.casefold() == arm_type.casefold()
            )
        )

    def _row_matches_type(self, row: Mapping[str, Any], resource_type: str) -> bool:
        if self.resource_type_registry is None or not isinstance(row.get("type"), str):
            return True
        if resource_type == _UNCLASSIFIED_RESOURCE_TYPE:
            return self._resolve_registered_type(row) is None
        return self._resolve_registered_type(row) == resource_type


def _run_az(
    argv: Sequence[str],
    azure_config_dir: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if azure_config_dir:
        environment["AZURE_CONFIG_DIR"] = azure_config_dir
    else:
        environment.pop("AZURE_CONFIG_DIR", None)
    try:
        proc = subprocess.run(  # noqa: S603 - CLI-mode dev adapter, timeout enforced
            list(argv),
            capture_output=True,
            text=True,
            timeout=_AZ_TIMEOUT_SECONDS,
            check=False,
            env=environment,
        )
    except FileNotFoundError as exc:
        raise AzureCliInventoryError(
            f"'{argv[0]}' not found on PATH; install the Azure CLI"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AzureCliInventoryError(
            f"'{' '.join(argv)}' timed out after {_AZ_TIMEOUT_SECONDS}s"
        ) from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise AzureCliInventoryError(
            f"az CLI exited with code {proc.returncode}: "
            f"{stderr[:400] if stderr else '(no stderr)'}"
        )
    return proc


def _is_arg_throttle_error(exc: AzureCliInventoryError) -> bool:
    message = str(exc).casefold()
    return any(
        marker in message
        for marker in ("429", "ratelimiting", "rate limit", "throttl", "too many requests")
    )


def _receipt_argv(
    argv: Sequence[str],
    *,
    skip_token: str | None = None,
) -> str:
    redacted = [
        ("<skip-token>" if skip_token is not None and argument == skip_token else argument)
        for argument in argv
    ]
    return shlex.join(redacted)


def _provider_result_preview(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    preview: list[dict[str, str]] = []
    for row in rows[:_RECEIPT_PREVIEW_LIMIT]:
        item: dict[str, str] = {}
        for output_key, source_key in (
            ("name", "name"),
            ("type", "type"),
            ("resource_group", "resourceGroup"),
            ("location", "location"),
        ):
            value = row.get(source_key)
            if isinstance(value, str) and value:
                item[output_key] = value[:_RECEIPT_VALUE_CHARS]
        status = resource_operational_status(row)
        if status:
            item["status"] = status[:_RECEIPT_VALUE_CHARS]
        preview.append(item)
    return {
        "count": len(rows),
        "preview": preview,
        "truncated": len(rows) > len(preview),
    }


def _record_from_az_row(*, row: dict[str, Any], resource_type: str, now_iso: str) -> ResourceRecord:
    """Fold one JSON row into a :class:`ResourceRecord`.

    Uses the ARM ``id`` as ``provider_ref`` and normalises a neutral
    ``resource_id`` from the ARM path (mirrors ``arg_query._to_neutral_id``:
    strip ``/subscriptions/...`` prefix, lowercase).
    """

    arm_id: str = str(row.get("id") or "")
    name: str = str(row.get("name") or "")
    resource_id = _neutral_id(arm_id) or f"resource:{resource_type}/{name.lower()}"
    props: dict[str, Any] = {
        "name": name,
        "location": row.get("location"),
        "tags": row.get("tags") or {},
    }
    if isinstance(row.get("type"), str) and row["type"]:
        props["providerType"] = row["type"]
    for key in ("kind", "sku", "properties"):
        if row.get(key) is not None:
            props[key] = row[key]
    nested_properties = row.get("properties")
    nested = nested_properties if isinstance(nested_properties, Mapping) else {}
    provisioning_state = row.get("provisioningState") or nested.get("provisioningState")
    if isinstance(provisioning_state, str) and provisioning_state:
        props["provisioningState"] = provisioning_state
    if status := resource_operational_status(row):
        props["status"] = status
        if resource_type in {"compute.vm", "postgresql-server"}:
            props["powerState"] = status
    # Carry the owning resource-group so a console read can scope by it
    # (parity with the production ARG adapter, which projects `resourceGroup`).
    # `az resource list` rows already include it; a resource-group row owns
    # itself; otherwise recover it from the ARM path.
    resource_group = row.get("resourceGroup")
    if not resource_group and resource_type == "resource-group":
        resource_group = name
    if not resource_group:
        resource_group = _resource_group_from_arm_id(arm_id)
    if resource_group:
        props["resourceGroup"] = resource_group
    # Resource-group-specific fields land at the top level of `row`.
    if resource_type == "resource-group":
        props["managed_by"] = row.get("managedBy")
    if resource_type == "compute.vm":
        if power_state := row.get("powerState"):
            props["powerState"] = power_state
    return ResourceRecord(
        resource_id=resource_id,
        type=resource_type,
        props=truncate_props(props, max_bytes=_MAX_PROPS_BYTES),
        provider_ref=arm_id or None,
        last_seen=now_iso,
    )


def _dedupe_links(links: Sequence[LinkRecord]) -> tuple[LinkRecord, ...]:
    unique: dict[tuple[str, str, str], LinkRecord] = {}
    for link in links:
        unique.setdefault((link.from_id, link.link_type, link.to_id), link)
    return tuple(unique.values())


def _neutral_id(arm_id: str) -> str:
    """Return the same subscription-scoped neutral id as production ARG."""
    if not arm_id:
        return ""
    return to_neutral_id(arm_id)


def _resource_group_from_arm_id(arm_id: str) -> str | None:
    """Recover the resource-group name from an ARM path, or ``None``.

    ARM ids look like ``/subscriptions/<sub>/resourceGroups/<rg>/providers/...``;
    the segment right after ``/resourceGroups/`` is the owning group. Returned
    with the group's original casing (ARM group names are case-insensitive).
    """
    if not arm_id:
        return None
    marker = "/resourcegroups/"
    lowered = arm_id.lower()
    idx = lowered.find(marker)
    if idx < 0:
        return None
    rest = arm_id[idx + len(marker) :]
    segment = rest.split("/", 1)[0].strip()
    return segment or None


__all__ = ["AzureCliInventory", "AzureCliInventoryError"]
