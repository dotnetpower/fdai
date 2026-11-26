"""Stable Azure naming tokens shared by Foundation and application deployment."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from fdai_deployment_cli.plan_input import read_plan_input

_REGION_SHORT_NAMES = {
    "australiacentral": "auc",
    "australiacentral2": "auc2",
    "australiaeast": "aue",
    "australiasoutheast": "ause",
    "austriaeast": "ate",
    "belgiumcentral": "bec",
    "brazilsouth": "brs",
    "brazilsoutheast": "brse",
    "canadacentral": "cac",
    "canadaeast": "cae",
    "centralus": "cus",
    "centraluseuap": "cuse",
    "centralindia": "cin",
    "chilecentral": "clc",
    "eastasia": "ea",
    "eastus": "eus",
    "eastus2": "eus2",
    "eastus2euap": "eus2e",
    "francecentral": "frc",
    "francesouth": "frs",
    "germanynorth": "gen",
    "germanywestcentral": "gwc",
    "indonesiacentral": "idc",
    "israelcentral": "ilc",
    "italynorth": "itn",
    "japaneast": "jpe",
    "japanwest": "jpw",
    "jioindiacentral": "jic",
    "jioindiawest": "jiw",
    "koreacentral": "krc",
    "koreasouth": "krs",
    "malaysiasouth": "mys",
    "mexicocentral": "mxc",
    "newzealandnorth": "nzn",
    "northcentralus": "ncus",
    "northeurope": "neu",
    "norwayeast": "noe",
    "norwaywest": "now",
    "polandcentral": "plc",
    "qatarcentral": "qac",
    "southafricanorth": "zan",
    "southafricawest": "zaw",
    "southcentralus": "scus",
    "southeastasia": "sea",
    "southindia": "sin",
    "spaincentral": "esc",
    "swedencentral": "swc",
    "swedensouth": "sws",
    "switzerlandnorth": "chn",
    "switzerlandwest": "chw",
    "taiwannorth": "twn",
    "taiwannorthwest": "twnw",
    "uaecentral": "uaec",
    "uaenorth": "uaen",
    "uksouth": "uks",
    "ukwest": "ukw",
    "westcentralus": "wcus",
    "westindia": "win",
    "westus": "wus",
    "westus2": "wus2",
    "westus3": "wus3",
    "westeurope": "weu",
}
_REGION = re.compile(r"[a-z][a-z0-9]{1,31}")
_TOKEN = re.compile(r"[a-z][a-z0-9]{1,7}")


def azure_region_short_name(region: str) -> str:
    """Return the stable FDAI token for one validated Azure region name."""

    if _REGION.fullmatch(region) is None:
        raise ValueError("Azure region name is invalid")
    token = _REGION_SHORT_NAMES.get(region)
    if token is None:
        raise ValueError("Azure region has no reviewed FDAI short token")
    _validate_region_short_name(token)
    return token


def reviewed_azure_region_short_names() -> dict[str, str]:
    """Return the reviewed public Azure region token table for tests and diagnostics."""

    return dict(_REGION_SHORT_NAMES)


def selected_azure_region_short_name(
    *,
    region: str,
    subscription_id: str,
    environment: str,
    workload: str,
    retained_variables: Path | None = None,
    azure_group_reader: Callable[[str], str] | None = None,
) -> str:
    """Select one region token, preserving retained or discovered installation names."""

    retained = retained_azure_region_short_name(retained_variables)
    if retained is not None:
        return retained
    discovered = discover_existing_azure_region_short_name(
        subscription_id=subscription_id,
        region=region,
        environment=environment,
        workload=workload,
        azure_group_reader=azure_group_reader,
    )
    if discovered is not None:
        return discovered
    return azure_region_short_name(region)


def retained_azure_region_short_name(path: Path | None) -> str | None:
    """Read the existing Foundation token without recomputing it from the region table."""

    if path is None or not path.exists():
        return None
    token = read_plan_input(path).get("region_short")
    if not isinstance(token, str):
        raise ValueError("retained Foundation region token is invalid")
    _validate_region_short_name(token)
    return token


def discover_existing_azure_region_short_name(
    *,
    subscription_id: str,
    region: str,
    environment: str,
    workload: str,
    azure_group_reader: Callable[[str], str] | None = None,
) -> str | None:
    """Find a pre-existing FDAI token from tagged resource groups before planning.

    Current installations did not tag the token explicitly. Until that tag exists,
    discovery parses only FDAI-owned resource group names whose location and ownership
    tags match the selected subscription, environment, workload, and region. Ambiguous
    tokens fail closed before any effect.
    """

    if _REGION.fullmatch(region) is None:
        raise ValueError("Azure region name is invalid")
    if environment not in {"dev", "staging", "prod"}:
        raise ValueError("Azure deployment environment is invalid")
    if re.fullmatch(r"[a-z][a-z0-9]{1,11}", workload) is None:
        raise ValueError("Azure deployment workload token is invalid")
    raw = (
        azure_group_reader(subscription_id)
        if azure_group_reader is not None
        else _read_resource_groups(subscription_id)
    )
    try:
        groups = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Azure resource group discovery returned invalid JSON") from exc
    if not isinstance(groups, list):
        raise ValueError("Azure resource group discovery returned invalid JSON")
    tokens: set[str] = set()
    for group in groups:
        token = _resource_group_region_token(
            group,
            region=region,
            environment=environment,
            workload=workload,
        )
        if token is not None:
            tokens.add(token)
    if len(tokens) > 1:
        raise ValueError("existing FDAI installation region token is ambiguous")
    return next(iter(tokens), None)


def _resource_group_region_token(
    group: object, *, region: str, environment: str, workload: str
) -> str | None:
    if not isinstance(group, dict):
        raise ValueError("Azure resource group discovery returned invalid JSON")
    name = group.get("name")
    location = group.get("location")
    tags = group.get("tags")
    if not isinstance(name, str) or not isinstance(location, str):
        raise ValueError("Azure resource group discovery returned invalid JSON")
    if location.casefold().replace(" ", "") != region:
        return None
    if not isinstance(tags, dict):
        return None
    normalized_tags = {str(key): str(value) for key, value in tags.items()}
    if (
        "fdai:managed" not in normalized_tags
        or normalized_tags.get("fdai:env") != environment
        or normalized_tags.get("fdai:workload") != workload
    ):
        return None
    tagged_token = normalized_tags.get("fdai:region-token")
    if tagged_token is not None:
        _validate_region_short_name(tagged_token)
        return tagged_token
    escaped_workload = re.escape(workload)
    escaped_environment = re.escape(environment)
    match = re.fullmatch(
        rf"rg-{escaped_workload}-(?:{escaped_environment}|ops)-(?P<token>[a-z][a-z0-9]{{1,7}})",
        name,
    )
    if match is None:
        return None
    token = match.group("token")
    _validate_region_short_name(token)
    return token


def _read_resource_groups(subscription_id: str) -> str:
    try:
        completed = subprocess.run(
            (
                "az",
                "group",
                "list",
                "--subscription",
                subscription_id,
                "--query",
                "[].{name:name,location:location,tags:tags}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Azure resource group discovery failed before planning") from None
    if completed.returncode != 0:
        raise ValueError("Azure resource group discovery failed before planning")
    return completed.stdout


def _validate_region_short_name(token: str) -> None:
    if _TOKEN.fullmatch(token) is None:
        raise ValueError("Azure region short name is invalid")
