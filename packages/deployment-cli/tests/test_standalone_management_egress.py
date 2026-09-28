from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_host, standalone_management_egress

_IP_ID = "/subscriptions/s/resourceGroups/ops/providers/Microsoft.Network/publicIPAddresses/pip"


def _run(addresses: object, ip: str, calls: list[tuple[str, ...]]):
    def run(command, **_kwargs):
        calls.append(tuple(command))
        if command[1:4] == ("network", "nat", "gateway"):
            return SimpleNamespace(returncode=0, stdout=json.dumps(addresses), stderr="")
        if command[1:3] == ("network", "public-ip"):
            return SimpleNamespace(returncode=0, stdout=f"{ip}\n", stderr="")
        raise AssertionError(command)

    return run


def test_egress_is_the_single_nat_public_ip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        standalone_management_egress.subprocess, "run", _run([_IP_ID], "20.1.2.3", calls)
    )

    assert standalone_management_egress.management_egress_cidrs(
        {"state_resource_group": "ops", "subscription_id": "s"}, cwd=tmp_path
    ) == ["20.1.2.3/32"]
    assert calls[1][calls[1].index("--ids") + 1] == _IP_ID


@pytest.mark.parametrize(
    ("addresses", "ip", "message"),
    [
        ([], "20.1.2.3", "exactly one"),
        ([_IP_ID, _IP_ID], "20.1.2.3", "exactly one"),
        ([_IP_ID], "10.0.0.4", "not globally routable"),
        ([_IP_ID], "not-an-ip", "is invalid"),
    ],
)
def test_ambiguous_or_private_egress_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    addresses: object,
    ip: str,
    message: str,
) -> None:
    monkeypatch.setattr(standalone_management_egress.subprocess, "run", _run(addresses, ip, []))

    with pytest.raises(ValueError, match=message):
        standalone_management_egress.management_egress_cidrs(
            {"state_resource_group": "ops", "subscription_id": "s"}, cwd=tmp_path
        )


def test_runtime_values_bind_api_server_subnet_and_authorized_range() -> None:
    source = Path(standalone_host.__file__).read_text(encoding="utf-8")

    assert (
        '"aks_api_server_subnet_id": _terraform_output(substrate, "aks_api_server_subnet_id")'
        in (source)
    )
    assert '"api_server_authorized_ip_ranges": management_egress_cidrs(context' in source
