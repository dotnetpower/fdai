"""Read bounded public Linux VM retail prices without Azure identity or mutation."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fdai_deployment_cli.deployment_deadline import DeploymentDeadline

_ENDPOINT = "https://prices.azure.com/api/retail/prices"
_MAX_BYTES = 2 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError("Azure retail price redirects are not supported")


def read_linux_vm_price(*, sku: str, region: str, timeout_seconds: int = 90) -> dict[str, object]:
    """Fetch one complete exact-SKU catalog and select a unique primary USD hourly rate.

    At most four pages share one deadline. Redirects, foreign continuation URLs,
    repeated pages, malformed responses and ambiguous prices fail without retry.
    """
    if (
        re.fullmatch(r"Standard_[A-Za-z0-9_]{1,80}", sku) is None
        or re.fullmatch(r"[a-z][a-z0-9]{1,40}", region) is None
    ):
        raise ValueError("Azure retail price selection is invalid")
    deadline = DeploymentDeadline(timeout_seconds)
    query = urllib.parse.urlencode(
        {
            "$filter": f"armSkuName eq '{sku}' and armRegionName eq '{region}' and serviceName eq 'Virtual Machines' and priceType eq 'Consumption'",
            "currencyCode": "USD",
        }
    )
    url = f"{_ENDPOINT}?{query}"
    seen: set[str] = set()
    rows: list[object] = []
    evidence = hashlib.sha256()
    opener = urllib.request.build_opener(_NoRedirect())
    for _page in range(4):
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "prices.azure.com"
            or parsed.path != "/api/retail/prices"
            or parsed.fragment
            or url in seen
        ):
            raise ValueError("Azure retail price continuation is invalid")
        seen.add(url)
        try:
            with opener.open(url, timeout=deadline.remaining(30)) as response:
                chunks = bytearray()
                while len(chunks) <= _MAX_BYTES:
                    deadline.remaining()
                    chunk = response.read1(min(65536, _MAX_BYTES + 1 - len(chunks)))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                payload = bytes(chunks)
        except (OSError, urllib.error.URLError):
            raise ValueError(
                "Azure retail price observation unavailable; no retry performed"
            ) from None
        deadline.remaining()
        if len(payload) > _MAX_BYTES:
            raise ValueError("Azure retail price observation exceeds its bound")
        evidence.update(hashlib.sha256(payload).digest())
        page = json.loads(payload, parse_float=Decimal)
        if (
            not isinstance(page, dict)
            or not isinstance(page.get("Items"), list)
            or "NextPageLink" not in page
            or len(page["Items"]) > 1000
            or type(page.get("Count")) is not int
            or page["Count"] != len(page["Items"])
        ):
            raise ValueError("Azure retail price page is invalid")
        rows.extend(page["Items"])
        next_page = page.get("NextPageLink")
        if next_page in (None, ""):
            now = datetime.now(UTC)
            result = select_linux_vm_price(rows, sku=sku, region=region, now=now)
            deadline.remaining()
            return {
                **result,
                "observed_at": now.isoformat(),
                "catalog_digest": evidence.hexdigest(),
            }
        if not isinstance(next_page, str) or len(next_page) > 8192:
            raise ValueError("Azure retail price continuation is invalid")
        url = next_page
    raise ValueError("Azure retail price catalog exceeds the page limit")


def select_linux_vm_price(
    rows: list[object], *, sku: str, region: str, now: datetime
) -> dict[str, object]:
    """Select standard Linux consumption, never Windows, Spot, reservation or a foreign meter."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Azure retail price selection requires an aware time")
    matches = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Azure retail price row is invalid")
        product, meter, sku_name = row.get("productName"), row.get("meterName"), row.get("skuName")
        if (
            not isinstance(product, str)
            or not isinstance(meter, str)
            or not isinstance(sku_name, str)
        ):
            raise ValueError("Azure retail price labels are incomplete")
        if (
            row.get("armSkuName") != sku
            or row.get("armRegionName") != region
            or row.get("serviceName") != "Virtual Machines"
            or row.get("type") != "Consumption"
            or row.get("currencyCode") != "USD"
            or row.get("unitOfMeasure") != "1 Hour"
            or row.get("isPrimaryMeterRegion") is not True
            or row.get("tierMinimumUnits") != 0
            or type(row.get("tierMinimumUnits")) is bool
            or not product.startswith("Virtual Machines ")
            or any(
                token in f"{product} {meter} {sku_name}".casefold()
                for token in ("windows", "spot", "low priority")
            )
        ):
            continue
        try:
            effective = datetime.fromisoformat(
                str(row.get("effectiveStartDate")).replace("Z", "+00:00")
            )
            raw_rate = row.get("retailPrice")
            if isinstance(raw_rate, bool) or not isinstance(raw_rate, (int, float, Decimal)):
                raise ValueError("invalid price")
            rate = Decimal(str(raw_rate))
            if (
                not rate.is_finite()
                or not Decimal(0) < rate <= Decimal(1000000)
                or not -12 <= rate.adjusted() <= 6
                or len(rate.as_tuple().digits) > 18
            ):
                raise ValueError("invalid price")
        except (ValueError, InvalidOperation):
            raise ValueError("Azure retail price or effective time is invalid") from None
        if effective.tzinfo is None:
            raise ValueError("Azure retail price effective time is not timezone aware")
        if effective > now:
            continue
        matches.append((rate, effective))
    if len(matches) != 1:
        raise ValueError("Azure Linux VM retail price is missing or ambiguous")
    rate, effective = matches[0]
    return {
        "sku": sku,
        "region": region,
        "currency": "USD",
        "unit": "hour",
        "hourly_rate": format(rate, "f"),
        "effective_at": effective.isoformat(),
        "pricing_basis": "public-linux-consumption",
        "billing_cap_enforced": False,
    }
