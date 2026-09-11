"""One-command Genesis private preparation regressions."""

from __future__ import annotations

import ipaddress
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_prepare  # noqa: E402
import genesis_prepare_inputs  # noqa: E402

SOURCE = "a" * 40
TENANT = "00000000-0000-0000-0000-000000000001"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000002"


def _values(**kwargs: object) -> dict[str, object]:
    return {
        "tenant_id": TENANT,
        "subscription_id": SUBSCRIPTION,
        "target_binding": kwargs["target_binding"],
        "workload": "fdai",
        "region": "koreacentral",
        "region_short": "kor",
        "state_storage_account_name": "stateexample",
        "state_retention_days": 30,
        "ops_address_space": "172.29.0.0/16",
        "runner_subnet_prefix": "172.29.1.0/24",
        "pe_subnet_prefix": "172.29.2.0/24",
        "enable_bastion": True,
        "bastion_subnet_prefix": "172.29.3.0/26",
        "enable_public_egress": True,
        "runner_ssh_public_key": "ssh-ed25519 " + "A" * 68,
        "runner_parallelism": 1,
        "runner_source_image_id": (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-example/"
            "providers/Microsoft.Compute/images/pending"
        ),
        "runner_image_toolchain_digest": "c" * 64,
        "runner_vm_size": "Standard_D4ds_v5",
        "source_commit": kwargs["source_commit"],
        "run_digest": kwargs["run_binding"],
        "foundation_context_digest": "e" * 64,
    }


def test_prepare_creates_private_keys_profile_and_inputs(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "private"
    monkeypatch.setattr(
        genesis_prepare,
        "_ensure_kit",
        lambda **_: SimpleNamespace(manifest_digest="f" * 64),
    )
    monkeypatch.setattr(genesis_prepare, "foundation_values", _values)

    prepared = genesis_prepare.prepare_genesis(
        repository_root=ROOT,
        repository="example/fdai",
        source_commit=SOURCE,
        tenant_id=TENANT,
        subscription_id=SUBSCRIPTION,
        region="koreacentral",
        monthly_cost_ceiling=1000,
        root=root,
    )

    assert prepared.kit_manifest_digest == "f" * 64
    assert root.stat().st_mode & 0o777 == 0o700
    for name in (
        "release-signing-key.pem",
        "bundle-signing-key.pem",
        "runner_ed25519",
        "runner_ed25519.pub",
        "profile.json",
        "foundation-variables.json",
    ):
        assert (root / name).stat().st_mode & 0o777 == 0o600


def test_prepare_overlaps_kit_staging_with_foundation_input_discovery(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "private"
    kit_started = threading.Event()
    discovery_started = threading.Event()

    def ensure_kit(**_kwargs: object) -> SimpleNamespace:
        kit_started.set()
        assert discovery_started.wait(timeout=1)
        return SimpleNamespace(manifest_digest="f" * 64)

    def values(**kwargs: object) -> dict[str, object]:
        discovery_started.set()
        assert kit_started.wait(timeout=1)
        return _values(**kwargs)

    monkeypatch.setattr(genesis_prepare, "_ensure_kit", ensure_kit)
    monkeypatch.setattr(genesis_prepare, "foundation_values", values)

    prepared = genesis_prepare.prepare_genesis(
        repository_root=ROOT,
        repository="example/fdai",
        source_commit=SOURCE,
        tenant_id=TENANT,
        subscription_id=SUBSCRIPTION,
        region="koreacentral",
        monthly_cost_ceiling=1000,
        root=root,
    )

    assert prepared.kit_manifest_digest == "f" * 64


def test_network_layout_avoids_existing_azure_and_local_ranges(monkeypatch) -> None:
    def capture(arguments: tuple[str, ...], *, cwd: Path) -> str:
        del cwd
        if arguments[:3] == ("az", "network", "vnet"):
            return '[["172.29.0.0/16"]]'
        if arguments[:4] == ("ip", "-j", "-4", "route"):
            return '[{"dst":"10.0.0.0/8"}]'
        raise AssertionError(arguments)

    monkeypatch.setattr(genesis_prepare_inputs, "_capture", capture)

    ops, runner, endpoint, bastion = genesis_prepare_inputs.network_layout(ROOT)

    assert str(ops) == "172.30.0.0/16"
    assert runner.subnet_of(ops)
    assert endpoint.subnet_of(ops)
    assert bastion.subnet_of(ops)
    assert not runner.overlaps(endpoint)


def test_foundation_input_discovery_runs_independent_queries_concurrently(monkeypatch) -> None:
    barrier = threading.Barrier(3)

    def capture(arguments: tuple[str, ...], *, cwd: Path) -> str:
        del arguments, cwd
        barrier.wait(timeout=1)
        return "24.04.202608010"

    def account_name(**_kwargs: object) -> str:
        barrier.wait(timeout=1)
        return "stateexample"

    def network(_repository_root: Path):
        barrier.wait(timeout=1)
        ops = ipaddress.ip_network("172.29.0.0/16")
        subnets = list(ops.subnets(new_prefix=24))
        return ops, subnets[1], subnets[2], next(subnets[3].subnets(new_prefix=26))

    monkeypatch.setattr(genesis_prepare_inputs, "_capture", capture)
    monkeypatch.setattr(genesis_prepare_inputs, "state_account_name", account_name)
    monkeypatch.setattr(genesis_prepare_inputs, "network_layout", network)

    values = genesis_prepare_inputs.foundation_values(
        repository_root=ROOT,
        source_commit=SOURCE,
        tenant_id=TENANT,
        subscription_id=SUBSCRIPTION,
        region="koreacentral",
        target_binding="b" * 64,
        run_binding="c" * 64,
        ssh_public_key="ssh-ed25519 " + "A" * 68,
    )

    assert values["state_storage_account_name"] == "stateexample"
    assert values["ops_address_space"] == "172.29.0.0/16"
