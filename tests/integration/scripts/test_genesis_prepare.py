"""One-command Genesis private preparation regressions."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_prepare  # noqa: E402
import genesis_prepare_inputs  # noqa: E402
import source_genesis  # noqa: E402

SOURCE = subprocess.run(
    ["/usr/bin/git", "rev-parse", "HEAD"],
    cwd=ROOT,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
TENANT = "00000000-0000-0000-0000-000000000001"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000002"


def test_source_preparation_retains_inputs_without_publisher_keys(tmp_path, monkeypatch) -> None:
    source = SimpleNamespace(root=ROOT, commit=SOURCE, digest="d" * 64, reverify=lambda: None)
    monkeypatch.setattr(source_genesis, "inspect_source", lambda *_, **__: source)
    monkeypatch.setattr(
        source_genesis,
        "active_azure_target",
        lambda: SimpleNamespace(tenant_id=TENANT, subscription_id=SUBSCRIPTION),
    )
    discoveries = []

    def discover(**kwargs):
        discoveries.append(kwargs)
        assert kwargs["execution_transport"] == "manual"
        return _values(**kwargs)

    monkeypatch.setattr(source_genesis, "foundation_values", discover)
    binding = source_genesis.compute_target_binding(tenant_id=TENANT, subscription_id=SUBSCRIPTION)
    args = SimpleNamespace(
        source_commit=SOURCE,
        target_binding=binding,
        work_dir=tmp_path / "source",
        region="koreacentral",
        monthly_cost_ceiling=1000,
    )
    result = source_genesis.prepare(args)
    assert source_genesis.prepare(args) == result
    assert len(discoveries) == 1
    assert result["mutation_performed"] is False
    assert result["deployment_ready"] is False
    assert {path.name for path in args.work_dir.iterdir()} == {
        "profile.json",
        "foundation-variables.json",
        "runner_ed25519",
        "runner_ed25519.pub",
        "source-genesis.json",
    }
    for path in args.work_dir.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
    args.target_binding = "f" * 64
    with pytest.raises(ValueError, match="target changed"):
        source_genesis.prepare(args)


def test_standalone_run_binding_matches_runner_image_mode() -> None:
    shared = f"{TENANT}:{SUBSCRIPTION}:koreacentral:dev:signed-kit"

    assert (
        genesis_prepare._standalone_run_binding(
            tenant_id=TENANT,
            subscription_id=SUBSCRIPTION,
            region="koreacentral",
            create_runner_image=False,
        )
        == hashlib.sha256(shared.encode()).hexdigest()
    )
    assert (
        genesis_prepare._standalone_run_binding(
            tenant_id=TENANT,
            subscription_id=SUBSCRIPTION,
            region="koreacentral",
            create_runner_image=True,
        )
        == hashlib.sha256(f"{shared}:runner-image=true".encode()).hexdigest()
    )


@pytest.mark.parametrize("provider_ready", [True, False])
@pytest.mark.parametrize("expired_approval", [False, True])
def test_source_advance_never_registers_or_applies_without_exact_approval(
    tmp_path, monkeypatch, provider_ready, expired_approval
):
    source = SimpleNamespace(
        root=ROOT,
        commit=SOURCE,
        digest="d" * 64,
        reverify=lambda: None,
        to_mapping=lambda: {"source_commit": SOURCE},
    )
    monkeypatch.setattr(source_genesis, "inspect_source", lambda *_, **__: source)
    monkeypatch.setattr(
        source_genesis, "verify_source_snapshot", lambda *_, **__: source.to_mapping()
    )
    monkeypatch.setattr(
        source_genesis,
        "active_azure_target",
        lambda: SimpleNamespace(tenant_id=TENANT, subscription_id=SUBSCRIPTION),
    )
    monkeypatch.setattr(source_genesis, "foundation_values", _values)
    args = SimpleNamespace(
        source_commit=SOURCE,
        target_binding=source_genesis.compute_target_binding(
            tenant_id=TENANT, subscription_id=SUBSCRIPTION
        ),
        work_dir=tmp_path / "source",
        region="koreacentral",
        monthly_cost_ceiling=1000,
        timeout_seconds=3600,
        source_snapshot=tmp_path / "snapshot",
        source_snapshot_digest="a" * 64,
        terraform=tmp_path / "terraform",
        approval_file=None,
    )
    source_genesis.prepare(args)
    if expired_approval:
        args.approval_file = args.work_dir / "expired-approval.json"

        def expired(*_, **__):
            raise source_genesis.GenesisApprovalExpiredError("expired")

        monkeypatch.setattr(source_genesis, "load_genesis_approval", expired)
    calls = []

    class Checks:
        def __init__(self, root):
            assert root == ROOT

        def verify_target(self, **kwargs):
            assert kwargs["subscription_id"] == SUBSCRIPTION

        def verify_toolchain(self, *, apply):
            assert apply is False

        def capture(self, command, reason, **kwargs):
            calls.append(command)
            if command[:2] == ("git", "remote"):
                return "https://github.com/example/fdai.git"
            assert command[:4] == ("az", "policy", "assignment", "list")
            return "[]"

    monkeypatch.setattr(source_genesis, "GenesisChecks", Checks)

    def providers(**kwargs):
        assert kwargs["apply"] is False
        assert kwargs["profile"] == "foundation"
        return SimpleNamespace(
            state="ready" if provider_ready else "review",
            to_mapping=lambda: {"mutation_performed": False},
        )

    monkeypatch.setattr(source_genesis, "reconcile_resource_providers", providers)
    coordinators = []

    class Coordinator:
        def __init__(self, *, config, store, checks):
            assert config.approval is None
            assert config.approval_path is None
            assert isinstance(config.foundation_inputs, source_genesis.SourceFoundationPlanInputs)
            coordinators.append(config)

        def run(self):
            raise source_genesis.PrivateExecutionWaitError(
                "runner-image-apply",
                "runner_image_exact_plan_approval_required",
                "review_runner_image_plan_and_supply_exact_approval",
            )

    monkeypatch.setattr(source_genesis, "PrivateExecutionCoordinator", Coordinator)
    result = source_genesis.advance(args)
    assert result["state"] == "review"
    assert result["deployment_ready"] is False
    assert result["mutation_performed"] is False
    assert len(coordinators) == int(provider_ready)
    assert result["stage"] == ("runner-image-apply" if provider_ready else "providers")
    assert len(calls) == (2 if provider_ready else 1)
    assert source_genesis.advance(args)["attempt"] == 2


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
        if arguments[:3] == ("/usr/bin/az", "network", "vnet"):
            assert arguments[4:6] == ("--subscription", SUBSCRIPTION)
            return (
                '[{"local":["172.29.0.0/16"],"peers":'
                '[{"state":"Connected","prefixes":["10.0.0.0/8"]}]}]'
            )
        if arguments[:4] == ("/usr/sbin/ip", "-j", "-4", "route"):
            return '[{"dst":"10.0.0.0/8"}]'
        raise AssertionError(arguments)

    monkeypatch.setattr(genesis_prepare_inputs, "_capture", capture)
    monkeypatch.setattr(
        genesis_prepare_inputs,
        "_subscription_resource_values",
        lambda **_kwargs: [],
    )

    ops, runner, endpoint, bastion, build, firewall, firewall_management = (
        genesis_prepare_inputs.network_layout(ROOT, subscription_id=SUBSCRIPTION)
    )

    assert str(ops) == "172.30.0.0/16"
    assert runner.subnet_of(ops)
    assert endpoint.subnet_of(ops)
    assert bastion.subnet_of(ops)
    assert not runner.overlaps(endpoint)
    assert not build.overlaps(ops)
    assert firewall.subnet_of(build)
    assert firewall_management.subnet_of(build)


def test_foundation_input_discovery_runs_independent_queries_concurrently(monkeypatch) -> None:
    barrier = threading.Barrier(3)
    monkeypatch.setattr(
        genesis_prepare_inputs,
        "discover_foundation_vm_size",
        lambda **_kwargs: "Standard_D4ds_v4",
    )

    def capture(arguments: tuple[str, ...], *, cwd: Path) -> str:
        del arguments, cwd
        barrier.wait(timeout=1)
        return "24.04.202608010"

    def account_name(**_kwargs: object) -> str:
        barrier.wait(timeout=1)
        return "stateexample"

    def network(_repository_root: Path, *, subscription_id: str):
        assert subscription_id == SUBSCRIPTION
        barrier.wait(timeout=1)
        ops = ipaddress.ip_network("172.29.0.0/16")
        subnets = list(ops.subnets(new_prefix=24))
        build = ipaddress.ip_network("172.30.0.0/16")
        build_subnets = list(build.subnets(new_prefix=26))
        return (
            ops,
            subnets[1],
            subnets[2],
            next(subnets[3].subnets(new_prefix=26)),
            build,
            build_subnets[1],
            build_subnets[2],
        )

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
    assert values["build_address_space"] == "172.30.0.0/16"
    assert values["runner_vm_size"] == "Standard_D4ds_v4"


def test_network_layout_rejects_incomplete_peer_evidence(monkeypatch) -> None:
    def capture(arguments: tuple[str, ...], *, cwd: Path) -> str:
        del cwd
        if arguments[:3] == ("/usr/bin/az", "network", "vnet"):
            return '[{"local":["172.29.0.0/16"],"peers":[{"state":"Connected","prefixes":null}]}]'
        if arguments[:4] == ("/usr/sbin/ip", "-j", "-4", "route"):
            return "[]"
        raise AssertionError(arguments)

    monkeypatch.setattr(genesis_prepare_inputs, "_capture", capture)
    monkeypatch.setattr(
        genesis_prepare_inputs,
        "_subscription_resource_values",
        lambda **_kwargs: [],
    )

    with pytest.raises(ValueError, match="peering evidence"):
        genesis_prepare_inputs.network_layout(ROOT, subscription_id=SUBSCRIPTION)


@pytest.mark.parametrize(
    ("vnets", "routes", "gateways"),
    [
        ([{"local": [], "peers": []}], [], []),
        ([{"local": [None], "peers": []}], [], []),
        ([{"local": ["10.0.0.1/16"], "peers": []}], [], []),
        ([{"local": ["10.0.0.0/16", None], "peers": []}], [], []),
        ([{"local": ["10.0.0.0/16"], "peers": []}], [{"prefix": "bad"}], []),
        (
            [{"local": ["10.0.0.0/16"], "peers": []}],
            [],
            [{"name": "gateway", "prefixes": [None]}],
        ),
    ],
)
def test_network_evidence_rejects_incomplete_or_malformed_prefixes(
    vnets: object, routes: object, gateways: object
) -> None:
    with pytest.raises(ValueError, match="evidence"):
        genesis_prepare_inputs._require_complete_network_evidence(
            vnets,
            routes,
            gateways,
            [{"dst": "default"}],
        )


def test_network_evidence_allows_explicit_route_service_tag() -> None:
    genesis_prepare_inputs._require_complete_network_evidence(
        [{"local": ["10.0.0.0/16"], "peers": []}],
        [{"prefix": "VirtualNetwork"}],
        [],
        [{"dst": "default"}],
    )


def test_network_evidence_allows_exact_ipv4_host_route() -> None:
    genesis_prepare_inputs._require_complete_network_evidence(
        [{"local": ["10.0.0.0/16"], "peers": []}],
        [],
        [],
        [{"dst": "192.0.2.1"}],
    )


def test_subscription_network_inventory_lists_ids_then_reads_exact_resources(
    monkeypatch,
) -> None:
    resource_ids = [
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/providers/"
        "Microsoft.Network/routeTables/route-b",
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/example/providers/"
        "Microsoft.Network/routeTables/route-a",
    ]
    calls: list[tuple[str, ...]] = []

    def capture(arguments: tuple[str, ...], *, cwd: Path) -> str:
        del cwd
        calls.append(arguments)
        if arguments[1:3] == ("resource", "list"):
            assert arguments[4] == SUBSCRIPTION
            assert arguments[6] == "Microsoft.Network/routeTables"
            return json.dumps(resource_ids)
        if arguments[1:3] == ("resource", "show"):
            resource_id = arguments[4]
            return json.dumps([{"name": resource_id.rsplit("/", 1)[-1], "prefix": "10.20.0.0/16"}])
        raise AssertionError(arguments)

    monkeypatch.setattr(genesis_prepare_inputs, "_capture", capture)

    values = genesis_prepare_inputs._subscription_resource_values(
        repository_root=ROOT,
        subscription_id=SUBSCRIPTION,
        resource_type="Microsoft.Network/routeTables",
        query="properties.routes[].{name:name,prefix:properties.addressPrefix}",
        list_result=True,
    )

    assert [value["name"] for value in values] == ["route-a", "route-b"]
    assert all(call[:3] != ("/usr/bin/az", "network", "route-table") for call in calls)


def test_subscription_network_inventory_rejects_unbounded_resource_count(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        genesis_prepare_inputs,
        "_capture",
        lambda *_args, **_kwargs: json.dumps([f"resource-{index}" for index in range(257)]),
    )

    with pytest.raises(ValueError, match="exceeds its bound"):
        genesis_prepare_inputs._subscription_resource_values(
            repository_root=ROOT,
            subscription_id=SUBSCRIPTION,
            resource_type="Microsoft.Network/routeTables",
            query="properties.routes",
            list_result=True,
        )
