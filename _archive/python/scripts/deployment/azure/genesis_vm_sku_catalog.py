"""Read one complete, bounded regional VM catalog without selecting or changing resources."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urlsplit

from genesis_checks import CheckError
from genesis_runner_image_skus import EVIDENCE_INVALID, load_sku_json

_API_VERSION = "2021-07-01"
_MAX_PAGES = 4
_MAX_BYTES = 8 * 1024 * 1024
_MAX_ROWS = 4096
_SECONDS = 90
_SUBSCRIPTION = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_REGION = re.compile(r"[A-Za-z][A-Za-z0-9]{0,63}")
_NAME = re.compile(r"[A-Za-z0-9_-]{1,100}")
_QUERY = (
    "{value:value[?resourceType == 'virtualMachines'].{name:name,resourceType:resourceType,"
    "locations:locations,locationInfo:locationInfo,restrictions:restrictions,"
    "capabilities:capabilities,family:family,tier:tier},nextLink:nextLink}"
)


def read_vm_catalog(
    *,
    subscription_id: str,
    region: str,
    azure_cli: Path,
    capture: Callable[..., str],
    cwd: Path,
    environment: Mapping[str, str],
) -> list[object]:
    """Return a complete catalog before hardware filtering; never infer absence from truncation.

    The caller supplies a trusted bounded capture. No retry, implicit region switch, availability
    cache, capacity reservation, or provider registration is performed here.
    """
    if _SUBSCRIPTION.fullmatch(subscription_id) is None or _REGION.fullmatch(region) is None:
        raise CheckError(EVIDENCE_INVALID, 3)
    base = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        "/providers/Microsoft.Compute/skus"
    )
    region_filter = f"location eq '{region.casefold()}'"
    url = base + "?" + urlencode({"api-version": _API_VERSION, "$filter": region_filter})
    deadline = monotonic() + _SECONDS
    seen: set[str] = set()
    names: set[str] = set()
    rows: list[object] = []
    total_bytes = 0
    for _ in range(_MAX_PAGES):
        _validate_page(url, base=base, region_filter=region_filter)
        if url in seen or monotonic() >= deadline:
            raise CheckError(EVIDENCE_INVALID, 3)
        seen.add(url)
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
                    _QUERY,
                    "--output",
                    "json",
                    "--only-show-errors",
                ],
                cwd=cwd,
                env=environment,
                timeout=min(30, max(1, int(deadline - monotonic()))),
                reason=EVIDENCE_INVALID,
            ).encode("utf-8")
            total_bytes += len(raw)
            page = load_sku_json(raw, max_bytes=_MAX_BYTES)
        except (OSError, ValueError, subprocess.SubprocessError):
            raise CheckError(EVIDENCE_INVALID, 3) from None
        values = page.get("value")
        if (
            monotonic() >= deadline
            or total_bytes > _MAX_BYTES
            or not isinstance(values, list)
            or len(rows) + len(values) > _MAX_ROWS
        ):
            raise CheckError(EVIDENCE_INVALID, 3)
        for value in values:
            if not isinstance(value, dict) or value.get("resourceType") != "virtualMachines":
                raise CheckError(EVIDENCE_INVALID, 3)
            name = value.get("name")
            if not isinstance(name, str) or _NAME.fullmatch(name) is None or name in names:
                raise CheckError(EVIDENCE_INVALID, 3)
            names.add(name)
        rows.extend(values)
        next_link = page.get("nextLink")
        if next_link is None:
            return rows
        if not isinstance(next_link, str) or not next_link:
            raise CheckError(EVIDENCE_INVALID, 3)
        url = next_link
    raise CheckError(EVIDENCE_INVALID, 3)


def _validate_page(url: str, *, base: str, region_filter: str) -> None:
    """Accept only continuation tokens on the same ARM resource, region and API version."""
    if len(url) > 8192 or any(ord(character) <= 32 or ord(character) >= 127 for character in url):
        raise CheckError(EVIDENCE_INVALID, 3)
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
        raise CheckError(EVIDENCE_INVALID, 3) from None
    if not valid:
        raise CheckError(EVIDENCE_INVALID, 3)
