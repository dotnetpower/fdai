"""Distinguish default forwarding routes from occupied Genesis address ranges."""

from __future__ import annotations

import ipaddress
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import genesis_prepare_inputs as inputs  # noqa: E402

SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"


def _layout(
    monkeypatch: pytest.MonkeyPatch,
    *,
    vnets: list[dict[str, object]] | None = None,
    azure_routes: list[dict[str, object]] | None = None,
    local_routes: list[dict[str, object]] | None = None,
    gateways: list[dict[str, object]] | None = None,
) -> tuple[ipaddress.IPv4Network, ...]:
    def capture(arguments: tuple[str, ...], *, cwd: Path) -> str:
        assert cwd == ROOT
        if arguments[:3] == ("/usr/bin/az", "network", "vnet"):
            assert arguments[4:6] == ("--subscription", SUBSCRIPTION)
            return json.dumps(vnets or [])
        if arguments[:4] == ("/usr/sbin/ip", "-j", "-4", "route"):
            return json.dumps(local_routes or [])
        pytest.fail("unexpected discovery command")

    def resources(**kwargs: object) -> list[dict[str, object]]:
        assert kwargs["subscription_id"] == SUBSCRIPTION
        if kwargs["resource_type"] == "Microsoft.Network/routeTables":
            return azure_routes or []
        assert kwargs["resource_type"] == "Microsoft.Network/localNetworkGateways"
        return gateways or []

    monkeypatch.setattr(inputs, "_capture", capture)
    monkeypatch.setattr(inputs, "_subscription_resource_values", resources)
    return inputs.network_layout(ROOT, subscription_id=SUBSCRIPTION)


@pytest.mark.parametrize(
    ("azure_routes", "local_routes"),
    [
        ([], [{"dst": "default"}]),
        ([], [{"dst": "0.0.0.0/0"}]),
        ([{"name": "default-egress", "prefix": "0.0.0.0/0"}], []),
        (
            [{"name": "default-egress", "prefix": "0.0.0.0/0"}],
            [{"dst": "default"}, {"dst": "0.0.0.0/0"}],
        ),
    ],
    ids=["local-default", "local-cidr-default", "azure-default", "combined-defaults"],
)
def test_default_routes_do_not_exhaust_candidate_networks(
    monkeypatch: pytest.MonkeyPatch,
    azure_routes: list[dict[str, object]],
    local_routes: list[dict[str, object]],
) -> None:
    layout = _layout(monkeypatch, azure_routes=azure_routes, local_routes=local_routes)

    assert str(layout[0]) == "172.29.0.0/16"
    assert str(layout[4]) == "172.30.0.0/16"
    assert not layout[0].overlaps(layout[4])
    assert all(subnet.subnet_of(layout[0]) for subnet in layout[1:4])
    assert all(subnet.subnet_of(layout[4]) for subnet in layout[5:])


def test_default_exclusion_preserves_all_specific_reservations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _layout(
        monkeypatch,
        vnets=[
            {
                "local": ["172.29.0.0/16"],
                "peers": [{"state": "Connected", "prefixes": ["172.30.0.0/16"]}],
            }
        ],
        gateways=[{"name": "example-gateway", "prefixes": ["172.27.0.0/16"]}],
        azure_routes=[
            {"name": "default-egress", "prefix": "0.0.0.0/0"},
            {"name": "reserved-network", "prefix": "172.28.0.0/16"},
        ],
        local_routes=[{"dst": "default"}, {"dst": "10.237.0.0/16"}],
    )

    assert str(layout[0]) == "10.238.0.0/16"
    assert str(layout[4]) == "192.168.240.0/20"


@pytest.mark.parametrize("source", ["vnet", "gateway"])
def test_default_prefix_is_not_ignored_in_declared_address_spaces(
    monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    vnets = [{"local": ["0.0.0.0/0"], "peers": []}] if source == "vnet" else []
    gateways = (
        [{"name": "example-gateway", "prefixes": ["0.0.0.0/0"]}] if source == "gateway" else []
    )

    with pytest.raises(ValueError, match="no non-overlapping reviewed"):
        _layout(monkeypatch, vnets=vnets, gateways=gateways)


@pytest.mark.parametrize("source", ["azure", "local"])
def test_specific_route_aggregates_still_exhaust_candidates(
    monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    prefixes = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
    azure_routes = [{"prefix": prefix} for prefix in prefixes] if source == "azure" else []
    local_routes = [{"dst": prefix} for prefix in prefixes] if source == "local" else []

    with pytest.raises(ValueError, match="no non-overlapping reviewed"):
        _layout(monkeypatch, azure_routes=azure_routes, local_routes=local_routes)


@pytest.mark.parametrize("remaining", [0, 1])
def test_real_exhaustion_reports_counts_without_network_values(
    monkeypatch: pytest.MonkeyPatch, remaining: int
) -> None:
    prefixes = ["10.0.0.0/8", "172.16.0.0/12"]
    if remaining == 0:
        prefixes.append("192.168.0.0/16")

    with pytest.raises(ValueError, match="no non-overlapping reviewed") as error:
        _layout(monkeypatch, vnets=[{"local": prefixes, "peers": []}])

    assert f"available={remaining}" in str(error.value)
    assert "required=2" in str(error.value)
    assert "review" in str(error.value)
    assert all(prefix not in str(error.value) for prefix in prefixes)
