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

- Ships six neutral resource types today, including resource groups, data
    services, AKS, storage, and VMs with live power state. Adding another type is one entry in
  :data:`_NEUTRAL_TYPE_TO_AZ_ARGS` plus (optionally) a props extractor.
- ``delta`` returns an empty final batch (Activity Log delta stream
  belongs to the production adapter).
- Never emits links - CLI users querying "list resource groups" do
  not need the container graph edges.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from fdai.shared.providers.inventory import (
    InventoryBatch,
    ResourceRecord,
)

_AZ_TIMEOUT_SECONDS: Final[float] = 30.0


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


@dataclass(slots=True)
class AzureCliInventory:
    """Dev :class:`Inventory` shelling to ``az`` for one subscription.

    A fork wanting parallel-shard ARG queries + link extraction uses
    :class:`~fdai.delivery.azure.inventory.AzureResourceGraphInventory`
    with :class:`~fdai.delivery.azure.arg_query.AzureArgQueryFactory`
    instead; this adapter is CLI-first.
    """

    resource_types: Sequence[str] = field(default_factory=lambda: tuple(_NEUTRAL_TYPE_TO_AZ_ARGS))
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
        for resource_type in self.resource_types:
            if resource_type not in _NEUTRAL_TYPE_TO_AZ_ARGS:
                continue
            records = await self._fetch(resource_type)
            yield InventoryBatch(
                resources=records,
                links=(),
                cursor=f"az-cli:{resource_type}",
                final=False,
            )
        # Fence: the caller MUST see final=True or discard the stream.
        yield InventoryBatch(resources=(), links=(), cursor="az-cli:end", final=True)

    async def _empty(self) -> AsyncIterator[InventoryBatch]:
        yield InventoryBatch(final=True)

    async def _fetch(self, resource_type: str) -> tuple[ResourceRecord, ...]:
        argv = [self.executable, *_NEUTRAL_TYPE_TO_AZ_ARGS[resource_type]]
        if self.subscription_id:
            argv.extend(("--subscription", self.subscription_id))
        proc = await asyncio.to_thread(_run_az, argv, self.azure_config_dir)
        try:
            payload = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise AzureCliInventoryError(f"az CLI returned non-JSON for {resource_type}") from exc
        if not isinstance(payload, list):
            raise AzureCliInventoryError(f"az CLI returned non-list JSON for {resource_type}")
        now_iso = datetime.now(tz=UTC).isoformat()
        return tuple(
            _record_from_az_row(row=row, resource_type=resource_type, now_iso=now_iso)
            for row in payload
            if isinstance(row, dict)
        )


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
        props=props,
        provider_ref=arm_id or None,
        last_seen=now_iso,
    )


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
