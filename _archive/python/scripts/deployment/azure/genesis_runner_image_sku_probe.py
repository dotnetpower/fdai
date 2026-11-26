"""Read exact-subscription, region-filtered SKU evidence before an image effect.

Only the supplied trusted command capture performs I/O. There is no retry, fallback,
capacity reservation, persisted availability cache, or create authority in this module.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urlsplit

from genesis_checks import CheckError
from genesis_runner_image_skus import (
    EVIDENCE_INVALID,
    image_vm_selections,
    load_sku_json,
    require_sku_eligibility,
)

_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_API_VERSION = "2019-04-01"
_MAX_PAGES = 4
_MAX_BYTES = 256 * 1024
_MAX_ROWS = 64
_TOTAL_SECONDS = 90


def verify_image_vm_skus(
    projection: bytes,
    *,
    subscription_id: str,
    region: str,
    azure_cli: Path,
    capture: Callable[..., str],
    cwd: Path,
    environment: Mapping[str, str],
) -> None:
    """Require complete fresh eligibility metadata for both resolved VMs, without mutation."""

    selections = image_vm_selections(projection, region=region)
    rows = read_vm_skus(
        tuple(sorted({item.size for item in selections})),
        subscription_id=subscription_id,
        region=region,
        azure_cli=azure_cli,
        capture=capture,
        cwd=cwd,
        environment=environment,
    )
    require_sku_eligibility(selections, rows)


def read_vm_skus(
    sizes: tuple[str, ...],
    *,
    subscription_id: str,
    region: str,
    azure_cli: Path,
    capture: Callable[..., str],
    cwd: Path,
    environment: Mapping[str, str],
) -> list[object]:
    """Return a complete bounded exact-region candidate snapshot, including restrictions."""

    if (
        _UUID.fullmatch(subscription_id) is None
        or re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", region) is None
        or not 1 <= len(sizes) <= 16
        or any(re.fullmatch(r"Standard_[A-Za-z0-9_]{1,64}", size) is None for size in sizes)
    ):
        raise CheckError(EVIDENCE_INVALID)
    base = (
        "https://management.azure.com/subscriptions/"
        f"{subscription_id}/providers/Microsoft.Compute/skus"
    )
    region_filter = f"location eq '{region.casefold()}'"
    url = base + "?" + urlencode({"api-version": _API_VERSION, "$filter": region_filter})
    names = " || ".join(f"name == '{size}'" for size in sorted(set(sizes)))
    query = (
        "{value:value[?resourceType == 'virtualMachines' && ("
        + names
        + ")].{name:name,resourceType:resourceType,locations:locations,"
        "locationInfo:locationInfo,restrictions:restrictions,capabilities:capabilities,"
        "family:family},nextLink:nextLink}"
    )
    deadline = monotonic() + _TOTAL_SECONDS
    seen: set[str] = set()
    rows: list[object] = []
    byte_count = 0
    for _ in range(_MAX_PAGES):
        _validate_page_url(url, base=base, region_filter=region_filter)
        if url in seen:
            raise CheckError(EVIDENCE_INVALID)
        seen.add(url)
        remaining = int(deadline - monotonic())
        if remaining <= 0:
            raise CheckError(EVIDENCE_INVALID)
        try:
            raw = capture(
                [
                    str(azure_cli),
                    "rest",
                    "--method",
                    "get",
                    "--subscription",
                    subscription_id,
                    "--url",
                    url,
                    "--query",
                    query,
                    "--output",
                    "json",
                    "--only-show-errors",
                ],
                cwd=cwd,
                env=environment,
                timeout=min(30, remaining),
                reason=EVIDENCE_INVALID,
            )
            encoded = raw.encode("utf-8")
            byte_count += len(encoded)
            page = load_sku_json(encoded, max_bytes=_MAX_BYTES)
        except (OSError, ValueError, subprocess.SubprocessError):
            raise CheckError(EVIDENCE_INVALID) from None
        if monotonic() >= deadline or byte_count > _MAX_BYTES:
            raise CheckError(EVIDENCE_INVALID)
        values = page.get("value")
        if not isinstance(values, list) or len(rows) + len(values) > _MAX_ROWS:
            raise CheckError(EVIDENCE_INVALID)
        rows.extend(values)
        next_link = page.get("nextLink")
        if next_link is None:
            return rows
        if not isinstance(next_link, str) or not next_link or len(next_link) > 8192:
            raise CheckError(EVIDENCE_INVALID)
        url = next_link
    raise CheckError(EVIDENCE_INVALID)


def read_vm_usage(
    *,
    subscription_id: str,
    region: str,
    azure_cli: Path,
    capture: Callable[..., str],
    cwd: Path,
    environment: Mapping[str, str],
) -> list[object]:
    """Read regional/family headroom once; failed or incomplete reads cannot mean unused quota."""

    if (
        _UUID.fullmatch(subscription_id) is None
        or re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", region) is None
    ):
        raise CheckError(EVIDENCE_INVALID)
    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}/providers/Microsoft.Compute/"
        f"locations/{region.casefold()}/usages?api-version=2024-07-01"
    )
    try:
        raw = capture(
            [
                str(azure_cli),
                "rest",
                "--method",
                "get",
                "--subscription",
                subscription_id,
                "--url",
                url,
                "--query",
                "{value:value[].{name:name.value,current:currentValue,limit:limit},nextLink:nextLink}",
                "--output",
                "json",
                "--only-show-errors",
            ],
            cwd=cwd,
            env=environment,
            timeout=30,
            reason=EVIDENCE_INVALID,
        )
        page = load_sku_json(raw.encode("utf-8"), max_bytes=_MAX_BYTES)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise CheckError(EVIDENCE_INVALID) from None
    rows = page.get("value")
    if page.get("nextLink") is not None or not isinstance(rows, list) or not 1 <= len(rows) <= 512:
        raise CheckError(EVIDENCE_INVALID)
    return rows


def _validate_page_url(url: str, *, base: str, region_filter: str) -> None:
    """Keep every page on the same public ARM subscription, resource, API, and region filter."""

    if len(url) > 8192 or any(ord(character) <= 32 or ord(character) >= 127 for character in url):
        raise CheckError(EVIDENCE_INVALID)
    try:
        parsed = urlsplit(url)
        items = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        parameters = dict(items)
        valid = (
            parsed.scheme == "https"
            and parsed.netloc == "management.azure.com"
            and not parsed.fragment
            and parsed.path.casefold() == urlsplit(base).path.casefold()
            and len(parameters) == len(items)
            and set(parameters) <= {"api-version", "$filter", "$skiptoken"}
            and parameters.get("api-version") == _API_VERSION
            and parameters.get("$filter") == region_filter
            and ("$skiptoken" not in parameters or bool(parameters["$skiptoken"]))
        )
    except ValueError:
        raise CheckError(EVIDENCE_INVALID) from None
    if not valid:
        raise CheckError(EVIDENCE_INVALID)
