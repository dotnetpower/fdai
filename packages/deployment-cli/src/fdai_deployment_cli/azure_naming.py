"""Stable Azure naming tokens shared by Foundation and application deployment."""

from __future__ import annotations

import re

_REGION_SHORT_NAMES = {
    "centralus": "cus",
    "eastasia": "ea",
    "eastus": "eus",
    "eastus2": "eus2",
    "koreacentral": "krc",
    "northeurope": "neu",
    "westus2": "wus2",
    "westeurope": "weu",
}


def azure_region_short_name(region: str) -> str:
    """Return the stable FDAI token for one validated Azure region name."""

    if re.fullmatch(r"[a-z][a-z0-9]{1,31}", region) is None:
        raise ValueError("Azure region name is invalid")
    token = _REGION_SHORT_NAMES.get(region, region[:5])
    if re.fullmatch(r"[a-z][a-z0-9]{1,7}", token) is None:
        raise ValueError("Azure region short name is invalid")
    return token
