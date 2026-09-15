"""Incomplete or ambiguous public price evidence never approves a deployment."""

import copy
import io
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fdai_deployment_cli import azure_retail_prices as prices
from fdai_deployment_cli import deployment_cost as cost
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile

NOW = datetime(2026, 9, 15, tzinfo=UTC)
SKU = "Standard_D4as_v7"


def row(**values):
    return {
        "armSkuName": SKU,
        "armRegionName": "eastus",
        "serviceName": "Virtual Machines",
        "productName": "Virtual Machines Example Series",
        "skuName": "D4as v7",
        "meterName": "D4as v7",
        "type": "Consumption",
        "currencyCode": "USD",
        "unitOfMeasure": "1 Hour",
        "isPrimaryMeterRegion": True,
        "tierMinimumUnits": 0,
        "effectiveStartDate": "2025-01-01T00:00:00Z",
        "retailPrice": 0.2,
        **values,
    }


@pytest.mark.parametrize(
    "values",
    [
        {"productName": "Virtual Machines Example Series Windows"},
        {"skuName": "D4as v7 Spot"},
        {"meterName": "D4as v7 Low Priority"},
        {"serviceName": "Azure Database for PostgreSQL"},
        {"armRegionName": "westus2"},
        {"armSkuName": "Standard_D2ds_v5"},
        {"currencyCode": "EUR"},
        {"type": "Reservation"},
        {"unitOfMeasure": "1/Month"},
        {"isPrimaryMeterRegion": False},
        {"tierMinimumUnits": 100},
        {"effectiveStartDate": "2027-01-01T00:00:00Z"},
    ],
)
def test_price_selection_excludes_unrelated_or_discounted_meters(values):
    assert (
        prices.select_linux_vm_price([row(), row(**values)], sku=SKU, region="eastus", now=NOW)[
            "hourly_rate"
        ]
        == "0.2"
    )
    with pytest.raises(ValueError, match="missing or ambiguous"):
        prices.select_linux_vm_price([row(**values)], sku=SKU, region="eastus", now=NOW)


@pytest.mark.parametrize(
    "rate", [True, -1, 0, "0.2", float("nan"), Decimal("Infinity"), Decimal("1e-999999999")]
)
def test_price_selection_rejects_invalid_rates(rate):
    with pytest.raises(ValueError):
        prices.select_linux_vm_price([row(retailPrice=rate)], sku=SKU, region="eastus", now=NOW)


def test_duplicate_matching_rates_are_ambiguous():
    with pytest.raises(ValueError, match="ambiguous"):
        prices.select_linux_vm_price([row(), row()], sku=SKU, region="eastus", now=NOW)


@pytest.mark.parametrize(
    "continuation",
    [
        "https://example.com/prices",
        "http://prices.azure.com/api/retail/prices",
        "https://prices.azure.com/other",
        "https://user@prices.azure.com/api/retail/prices",
    ],
)
def test_foreign_continuations_never_contact_another_host(monkeypatch, continuation):
    calls = []

    class Opener:
        def open(self, url, timeout):
            calls.append(url)
            return io.BytesIO(
                json.dumps({"Items": [row()], "Count": 1, "NextPageLink": continuation}).encode()
            )

    monkeypatch.setattr(prices.urllib.request, "build_opener", lambda *_: Opener())
    with pytest.raises(ValueError, match="continuation"):
        prices.read_linux_vm_price(sku=SKU, region="eastus")
    assert len(calls) == 1


def test_complete_pages_and_decimal_rates(monkeypatch):
    responses = iter(
        [
            {
                "Items": [row(skuName="D4as v7 Spot")],
                "Count": 1,
                "NextPageLink": "https://prices.azure.com/api/retail/prices?$skip=1",
            },
            {"Items": [row()], "Count": 1, "NextPageLink": None},
        ]
    )

    class Opener:
        def open(self, url, timeout):
            assert 0 < timeout <= 30
            return io.BytesIO(json.dumps(next(responses)).encode())

    monkeypatch.setattr(prices.urllib.request, "build_opener", lambda *_: Opener())
    quote = prices.read_linux_vm_price(sku=SKU, region="eastus")
    assert quote["hourly_rate"] == "0.2"
    assert len(quote["catalog_digest"]) == 64


def test_missing_price_never_retries(monkeypatch):
    calls = []

    class Opener:
        def open(self, url, timeout):
            calls.append(url)
            raise OSError("private error")

    monkeypatch.setattr(prices.urllib.request, "build_opener", lambda *_: Opener())
    with pytest.raises(ValueError, match="no retry") as failure:
        prices.read_linux_vm_price(sku=SKU, region="eastus")
    assert "private error" not in str(failure.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure", ["missing-next", "wrong-count", "repeat", "too-many", "oversized"]
)
def test_incomplete_or_unbounded_catalog_is_rejected(monkeypatch, failure):
    calls = []

    class Opener:
        def open(self, url, timeout):
            calls.append(url)
            if failure == "oversized":
                return io.BytesIO(b" " * (prices._MAX_BYTES + 1))
            page = {"Items": [row()], "Count": 1, "NextPageLink": None}
            if failure == "missing-next":
                page.pop("NextPageLink")
            elif failure == "wrong-count":
                page["Count"] = 2
            elif failure == "repeat":
                page["NextPageLink"] = url
            elif failure == "too-many":
                page["NextPageLink"] = (
                    f"https://prices.azure.com/api/retail/prices?$skip={len(calls)}"
                )
            return io.BytesIO(json.dumps(page).encode())

    monkeypatch.setattr(prices.urllib.request, "build_opener", lambda *_: Opener())
    with pytest.raises(ValueError):
        prices.read_linux_vm_price(sku=SKU, region="eastus")
    assert len(calls) == (4 if failure == "too-many" else 1)


def test_price_redirects_are_never_followed():
    with pytest.raises(ValueError, match="redirects"):
        prices._NoRedirect().redirect_request(None, None, None, None, None, None)


@pytest.mark.parametrize("ceiling,state", [(1000, "blocked"), (1168, "partial"), (2000, "partial")])
def test_compute_partial_projection_cannot_approve_budget(monkeypatch, ceiling, state):
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks",
        database_placement="postgres-flex",
        system_node_sku=SKU,
        user_node_sku=SKU,
    )
    calls = []
    monkeypatch.setattr(
        cost, "read_linux_vm_price", lambda **kwargs: calls.append(kwargs) or {"hourly_rate": "0.2"}
    )
    before = copy.deepcopy(profile.to_mapping())
    result = cost.inspect_aks_compute_cost(
        profile=profile, region="eastus", monthly_cost_ceiling=ceiling
    )
    assert result["state"] == state
    assert result["monthly_compute_estimate_usd"] == "1168.00"
    assert len(calls) == 1
    assert result["whole_installation_cost_verified"] is False
    assert result["setup_cost_verified"] is False
    assert result["apply_authorized"] is False
    assert result["deployment_ready"] is False
    assert result["mutation_performed"] is False
    assert profile.to_mapping() == before
