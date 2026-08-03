"""ARM URL policy blocks bearer-token SSRF and ambiguous resource paths."""

from __future__ import annotations

import httpx
import pytest

from fdai.delivery.azure.arm_url_policy import ArmUrlPolicy, ArmUrlPolicyError


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "http://management.example",
        "https://user:password@management.example",
        "https://management.example/arm",
        "https://management.example/?query=yes",
        "https://management.example/#fragment",
    ],
)
async def test_client_base_url_must_be_https_origin(base_url: str) -> None:
    async with httpx.AsyncClient(base_url=base_url) as client:
        with pytest.raises(ArmUrlPolicyError, match="base_url"):
            ArmUrlPolicy.from_client(client)


async def test_client_must_disable_automatic_redirects() -> None:
    async with httpx.AsyncClient(
        base_url="https://management.example",
        follow_redirects=True,
    ) as client:
        with pytest.raises(ArmUrlPolicyError, match="disable automatic redirects"):
            ArmUrlPolicy.from_client(client)


async def test_same_origin_and_root_relative_lro_urls_are_accepted() -> None:
    async with httpx.AsyncClient(base_url="https://management.example") as client:
        policy = ArmUrlPolicy.from_client(client)
    assert policy.validate_lro_url("/subscriptions/x/operations/1?api-version=1").startswith(
        "/subscriptions/"
    )
    assert policy.validate_lro_url(
        "https://management.example/subscriptions/x/operations/1?api-version=1"
    ).startswith("https://management.example/")


@pytest.mark.parametrize(
    "status_url",
    [
        "http://management.example/operations/1",
        "https://other.example/operations/1",
        "https://user:password@management.example/operations/1",
        "https://management.example/operations/1#fragment",
        "//other.example/operations/1",
        "operations/1",
        " https://management.example/operations/1",
        "https://management.example/operations/1\nX-Test: injected",
    ],
)
async def test_unsafe_lro_urls_are_rejected(status_url: str) -> None:
    async with httpx.AsyncClient(base_url="https://management.example") as client:
        policy = ArmUrlPolicy.from_client(client)
    with pytest.raises(ArmUrlPolicyError):
        policy.validate_lro_url(status_url)


@pytest.mark.parametrize(
    "provider_ref",
    [
        "https://other.example/subscriptions/x/resourceGroups/rg/providers/p/t/n",
        "//other.example/subscriptions/x/resourceGroups/rg/providers/p/t/n",
        "/tenants/x/providers/p/t/n",
        "/subscriptions/x/resourceGroups/rg/providers/p/t/n?api-version=1",
        "/subscriptions/x/resourceGroups/rg/providers/p/t/n#fragment",
    ],
)
def test_unsafe_provider_refs_are_rejected(provider_ref: str) -> None:
    with pytest.raises(ArmUrlPolicyError):
        ArmUrlPolicy.validate_resource_ref(provider_ref)


def test_root_relative_subscription_resource_ref_is_accepted() -> None:
    ref = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Example/widgets/one"
    assert ArmUrlPolicy.validate_resource_ref(ref) == ref
