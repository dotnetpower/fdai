"""Read-only Azure OpenAI GPT catalog, quota, and deployment discovery."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{1,127}$")
_SKU_MARKERS = {
    ".GlobalStandard.": "GlobalStandard",
    ".DataZoneStandard.": "DataZoneStandard",
    ".Standard.": "Standard",
    ".ProvisionedManaged.": "ProvisionedManaged",
    ".GlobalProvisionedManaged.": "GlobalProvisionedManaged",
}
_UNSUITABLE_ROLE_MARKERS = ("audio", "chat", "codex", "image", "realtime")


class ModelCatalogUnavailableError(RuntimeError):
    """The live Azure model inventory could not be read safely."""


@dataclass(frozen=True, slots=True)
class ModelSkuAvailability:
    name: str
    available_tpm: int


@dataclass(frozen=True, slots=True)
class GptModelCatalogEntry:
    family: str
    version: str
    lifecycle: str
    skus: tuple[ModelSkuAvailability, ...]
    deployments: tuple[str, ...]
    selectable: bool

    @property
    def deployed(self) -> bool:
        return bool(self.deployments)

    @property
    def provisionable(self) -> bool:
        return self.selectable and any(sku.available_tpm > 0 for sku in self.skus)


@dataclass(frozen=True, slots=True)
class GptModelCatalogSnapshot:
    region: str
    models: tuple[GptModelCatalogEntry, ...]


class GptModelCatalogReader(Protocol):
    async def snapshot(self, *, force_refresh: bool = False) -> GptModelCatalogSnapshot: ...


Runner = Callable[[Sequence[str]], str]


class AzureCliGptModelCatalogReader:
    """Combine live Azure catalog, regional quota, and account deployments."""

    def __init__(
        self,
        *,
        region: str,
        account_name: str,
        executable: str = "az",
        timeout_seconds: float = 30.0,
        cache_ttl_seconds: float = 300.0,
        runner: Runner | None = None,
    ) -> None:
        if not _SAFE_NAME.fullmatch(region) or not _SAFE_NAME.fullmatch(account_name):
            raise ValueError("Azure model catalog region and account name MUST be safe names")
        if timeout_seconds <= 0 or cache_ttl_seconds < 0:
            raise ValueError("Azure model catalog timeouts MUST be valid")
        self._region = region
        self._account_name = account_name
        self._executable = executable
        self._timeout_seconds = timeout_seconds
        self._cache_ttl_seconds = cache_ttl_seconds
        self._runner = runner
        self._cached: GptModelCatalogSnapshot | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    async def snapshot(self, *, force_refresh: bool = False) -> GptModelCatalogSnapshot:
        now = time.monotonic()
        if (
            not force_refresh
            and self._cached is not None
            and now - self._cached_at < self._cache_ttl_seconds
        ):
            return self._cached
        async with self._lock:
            now = time.monotonic()
            if (
                not force_refresh
                and self._cached is not None
                and now - self._cached_at < self._cache_ttl_seconds
            ):
                return self._cached
            snapshot = await asyncio.to_thread(self._load_snapshot)
            self._cached = snapshot
            self._cached_at = time.monotonic()
            return snapshot

    def _load_snapshot(self) -> GptModelCatalogSnapshot:
        catalog = _json_array(
            self._run(("cognitiveservices", "model", "list", "-l", self._region)),
            "Azure model catalog",
        )
        usage = _json_array(
            self._run(("cognitiveservices", "usage", "list", "-l", self._region)),
            "Azure model quota",
        )
        accounts = _json_array(
            self._run(("cognitiveservices", "account", "list")),
            "Azure cognitive accounts",
        )
        resource_group = _account_resource_group(accounts, self._account_name)
        deployments = _json_array(
            self._run(
                (
                    "cognitiveservices",
                    "account",
                    "deployment",
                    "list",
                    "-g",
                    resource_group,
                    "-n",
                    self._account_name,
                )
            ),
            "Azure model deployments",
        )
        quota = _quota_index(usage)
        deployed = _deployment_index(deployments)
        models = tuple(
            sorted(
                _catalog_entries(catalog, quota=quota, deployed=deployed),
                key=lambda item: _model_sort_key(item.family, item.version),
                reverse=True,
            )
        )
        return GptModelCatalogSnapshot(region=self._region, models=models)

    def _run(self, arguments: Sequence[str]) -> str:
        argv = (self._executable, *arguments, "-o", "json")
        if self._runner is not None:
            return self._runner(argv)
        try:
            completed = subprocess.run(  # noqa: S603 - fixed Azure CLI arguments
                argv,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise ModelCatalogUnavailableError("Azure CLI model discovery failed") from exc
        if completed.returncode != 0:
            raise ModelCatalogUnavailableError(
                f"Azure CLI model discovery exited with code {completed.returncode}"
            )
        return completed.stdout


def _catalog_entries(
    catalog: list[object],
    *,
    quota: dict[tuple[str, str], int],
    deployed: dict[str, set[str]],
) -> list[GptModelCatalogEntry]:
    entries: list[GptModelCatalogEntry] = []
    seen: set[tuple[str, str]] = set()
    for raw in catalog:
        if not isinstance(raw, dict) or raw.get("kind") != "OpenAI":
            continue
        model = raw.get("model")
        if not isinstance(model, dict):
            continue
        family = model.get("name")
        version = model.get("version")
        lifecycle = model.get("lifecycleStatus")
        if (
            not isinstance(family, str)
            or not family
            or not isinstance(version, str)
            or not version
            or not isinstance(lifecycle, str)
            or not lifecycle
        ):
            continue
        if not family.startswith("gpt-") or (family, version) in seen:
            continue
        seen.add((family, version))
        sku_names = _sku_names(model.get("skus"))
        sku_availability = tuple(
            ModelSkuAvailability(
                name=sku,
                available_tpm=quota.get((_canonical(sku), _canonical(family)), 0),
            )
            for sku in sku_names
        )
        selectable = lifecycle == "GenerallyAvailable" and not any(
            marker in family.casefold() for marker in _UNSUITABLE_ROLE_MARKERS
        )
        entries.append(
            GptModelCatalogEntry(
                family=family,
                version=version,
                lifecycle=lifecycle,
                skus=sku_availability,
                deployments=tuple(sorted(deployed.get(_canonical(family), set()))),
                selectable=selectable,
            )
        )
    return entries


def _quota_index(usage: list[object]) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for raw in usage:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        metric = name.get("value") if isinstance(name, dict) else name
        if not isinstance(metric, str):
            continue
        for marker, sku in _SKU_MARKERS.items():
            if marker not in metric:
                continue
            family = metric.split(marker, 1)[1]
            limit = _number(raw.get("limit"))
            used = _number(raw.get("currentValue"))
            if limit is not None and used is not None:
                key = (_canonical(sku), _canonical(family))
                result[key] = max(result.get(key, 0), int(max(0.0, limit - used) * 1000))
            break
    return result


def _deployment_index(deployments: list[object]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for raw in deployments:
        if not isinstance(raw, dict):
            continue
        properties = raw.get("properties")
        model = properties.get("model") if isinstance(properties, dict) else None
        family = model.get("name") if isinstance(model, dict) else None
        name = raw.get("name")
        state = properties.get("provisioningState") if isinstance(properties, dict) else None
        if isinstance(family, str) and isinstance(name, str) and state in {None, "Succeeded"}:
            result.setdefault(_canonical(family), set()).add(name)
    return result


def _account_resource_group(accounts: list[object], account_name: str) -> str:
    matches = {
        raw.get("resourceGroup")
        for raw in accounts
        if isinstance(raw, dict) and raw.get("name") == account_name
    }
    valid = {value for value in matches if isinstance(value, str) and value}
    if len(valid) != 1:
        raise ModelCatalogUnavailableError("Azure OpenAI account lookup was not unique")
    return next(iter(valid))


def _sku_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names = {item.get("name") if isinstance(item, dict) else item for item in value}
    return tuple(sorted(name for name in names if isinstance(name, str) and name))


def _json_array(raw: str, label: str) -> list[object]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ModelCatalogUnavailableError(f"{label} returned invalid JSON") from exc
    if not isinstance(value, list):
        raise ModelCatalogUnavailableError(f"{label} MUST return an array")
    return value


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _canonical(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _model_sort_key(family: str, version: str) -> tuple[tuple[int, ...], str, str]:
    numbers = tuple(int(value) for value in re.findall(r"\d+", family))
    return numbers, family, version


__all__ = [
    "AzureCliGptModelCatalogReader",
    "GptModelCatalogEntry",
    "GptModelCatalogReader",
    "GptModelCatalogSnapshot",
    "ModelCatalogUnavailableError",
    "ModelSkuAvailability",
]
