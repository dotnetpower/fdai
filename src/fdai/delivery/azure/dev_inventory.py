"""AzureCliInventory - dev-mode Inventory backed by ``az`` CLI shell-outs.

Zero-dep alternative to :class:`~fdai.delivery.azure.inventory.AzureResourceGraphInventory`
for the operator console CLI. Instead of holding an :class:`httpx.AsyncClient`
+ :class:`WorkloadIdentity` and running Kusto queries against Azure
Resource Graph, this adapter shells out to well-known ``az`` commands
(``az group list``, ``az resource list``, ``az vm list --show-details``) and folds the JSON back
into :class:`ResourceRecord` shapes.

Why a dev adapter?
------------------

- The operator has already run ``az login``; the CLI should use that
  credential without a separate Managed-Identity provision.
- The full ARG factory in ``arg_query.py`` is async + requires an
  ``httpx.AsyncClient`` + subscription-scope config + a
  :class:`ResourceTypeRegistry`. The CLI REPL is sync per turn; a
  simpler surface keeps the composition root readable.
- The ``resource-graph`` az CLI extension is not installed by default -
  ``az group list`` + ``az resource list`` are core CLI commands and
  work on any freshly-installed ``az``.

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
import os
import subprocess
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from fdai.delivery.azure.arg_projection import (
    extract_attached_to_links_from_row,
    extract_depends_on_links_from_row,
    extract_rg_contains_links,
    truncate_props,
)
from fdai.shared.providers.inventory import (
    InventoryBatch,
    LinkRecord,
    ResourceRecord,
)

_AZ_TIMEOUT_SECONDS: Final[float] = 30.0
_MAX_PROPS_BYTES: Final[int] = 64 * 1024


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
        "resource",
        "list",
        "--resource-type",
        "Microsoft.DBforPostgreSQL/flexibleServers",
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
    resource_type: args[args.index("--resource-type") + 1]
    for resource_type, args in _NEUTRAL_TYPE_TO_AZ_ARGS.items()
    if "--resource-type" in args
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
    discover_all: bool = False
    subscription_id: str | None = None
    executable: str = "az"
    azure_config_dir: str | None = None
    """Optional isolated Azure CLI profile directory.

    ``None`` removes an inherited ``AZURE_CONFIG_DIR`` so local discovery uses
    the operator's default profile. A non-empty value selects that profile
    explicitly. The subscription id still scopes every list command.
    """

    def full_snapshot(self, since: str | None = None) -> AsyncIterator[InventoryBatch]:
        del since  # az CLI does not honour a since filter here.
        return self._emit()

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
        arm_type = self.azure_arm_types.get(resource_type)
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
        group_args = [self.executable, "group", "list", "--output", "json"]
        resource_args = [self.executable, "resource", "list", "--output", "json"]
        vm_args = [self.executable, "vm", "list", "--show-details", "--output", "json"]
        if self.subscription_id:
            for argv in (group_args, resource_args, vm_args):
                argv.extend(("--subscription", self.subscription_id))
        groups, resource_rows, vm_rows = await asyncio.gather(
            self._fetch_rows(group_args, "resource-group"),
            self._fetch_rows(resource_args, "registered resources"),
            self._fetch_rows(vm_args, "compute.vm"),
        )
        vm_by_id = {
            str(row.get("id") or "").casefold(): row
            for row in vm_rows
            if isinstance(row.get("id"), str)
        }
        by_arm_type = {
            arm_type.casefold(): resource_type
            for resource_type, arm_type in self.azure_arm_types.items()
            if resource_type in self.resource_types and resource_type != "subscription"
        }
        rows_by_type: dict[str, list[dict[str, Any]]] = {"resource-group": list(groups)}
        for row in resource_rows:
            arm_type = str(row.get("type") or "").casefold()
            resource_type = by_arm_type.get(arm_type)
            if resource_type is None or resource_type == "resource-group":
                continue
            if resource_type == "compute.vm":
                row = {**row, **vm_by_id.get(str(row.get("id") or "").casefold(), {})}
            rows_by_type.setdefault(resource_type, []).append(row)

        records: list[ResourceRecord] = []
        links: list[LinkRecord] = []
        for resource_type in self.resource_types:
            projected_records, projected_links = self._project_rows(
                rows_by_type.get(resource_type, ()), resource_type
            )
            records.extend(projected_records)
            links.extend(projected_links)
        return InventoryBatch(
            resources=tuple(records),
            links=_dedupe_links(links),
            cursor="az-cli:registered-resources",
        )

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

    def _project_rows(
        self,
        rows: Sequence[dict[str, Any]],
        resource_type: str,
    ) -> tuple[tuple[ResourceRecord, ...], tuple[LinkRecord, ...]]:
        now_iso = datetime.now(tz=UTC).isoformat()
        records = tuple(
            _record_from_az_row(row=row, resource_type=resource_type, now_iso=now_iso)
            for row in rows
        )
        arm_to_neutral = {
            arm_type.casefold(): neutral_type
            for neutral_type, arm_type in self.azure_arm_types.items()
        }
        links = list(extract_rg_contains_links(records))
        for row, record in zip(rows, records, strict=True):
            links.extend(
                extract_attached_to_links_from_row(
                    row,
                    child=record,
                    arm_to_neutral=arm_to_neutral,
                )
            )
            links.extend(
                extract_depends_on_links_from_row(
                    row,
                    child=record,
                    arm_to_neutral=arm_to_neutral,
                    acr_resolver=lambda _login_server: None,
                )
            )
        return records, _dedupe_links(links)


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
    for key in ("kind", "sku", "properties"):
        if row.get(key) is not None:
            props[key] = row[key]
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
        if provisioning_state := row.get("provisioningState"):
            props["provisioningState"] = provisioning_state
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
    """Strip ``/subscriptions/...`` and lowercase - matches arg_query."""
    if not arm_id:
        return ""
    lowered = arm_id.lower()
    marker = "/resourcegroups/"
    idx = lowered.find(marker)
    if idx < 0:
        return lowered.strip("/")
    return lowered[idx + 1 :].strip("/")


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
