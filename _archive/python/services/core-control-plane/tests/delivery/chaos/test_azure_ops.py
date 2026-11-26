"""Unit tests for the extended Azure delivery-layer injectors in
``fdai.delivery.chaos.azure_ops``.

Subprocess is fully mocked (``fdai.delivery.chaos.live_injectors._run``
monkeypatched), so these never touch a real Azure resource - they lock
the ``az`` command shape and the rollback path each injector emits.
"""

from __future__ import annotations

import fdai.delivery.chaos.azure_ops as ao
import pytest


def _fake_run():  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    async def runner(cmd, *, timeout=60.0, drop_azure_config_dir=False):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return 0, "", ""

    return runner, calls


def _patch(monkeypatch: pytest.MonkeyPatch):
    """Monkeypatch the `_run` reference that `azure_ops` imported at module
    load. Patching `live_injectors._run` alone does not work: `azure_ops`
    rebound the symbol via `from fdai.delivery.chaos.live_injectors import
    _run`, so `azure_ops._run` is the shadowed local name every azure_ops
    call goes through.
    """
    runner, calls = _fake_run()
    monkeypatch.setattr(ao, "_run", runner)
    return runner, calls


# ---------------------------------------------------------------------------
# Guest-OS agent-based (az vm run-command)
# ---------------------------------------------------------------------------


async def test_vm_network_latency_injects_tc_netem_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzVmNetworkLatencyInjector(resource_group="rg", vm_name="vm", latency_ms=300)
    await inj.inject(target="vm-a", params={})
    # The last positional arg to `az vm run-command` is the script string.
    script = calls[0][calls[0].index("--scripts") + 1]
    assert "tc qdisc del" in script  # idempotent-ish: clear first
    assert "tc qdisc add" in script
    assert "netem delay 300ms" in script


async def test_vm_network_latency_stop_clears_tc(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzVmNetworkLatencyInjector(resource_group="rg", vm_name="vm")
    await inj.stop(target="vm-a")
    script = calls[0][calls[0].index("--scripts") + 1]
    assert "tc qdisc del" in script
    assert "add" not in script


async def test_vm_network_latency_params_override_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzVmNetworkLatencyInjector(
        resource_group="rg", vm_name="vm", latency_ms=100, interface="eth0"
    )
    await inj.inject(target="vm-a", params={"latency_ms": "750", "interface": "eth1"})
    script = calls[0][calls[0].index("--scripts") + 1]
    assert "netem delay 750ms" in script
    assert "dev eth1" in script


async def test_vm_packet_loss_injects_and_reverses(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzVmPacketLossInjector(resource_group="rg", vm_name="vm", loss_percent=25)
    await inj.inject(target="vm-a", params={})
    inject_script = calls[0][calls[0].index("--scripts") + 1]
    assert "netem loss 25%" in inject_script
    await inj.stop(target="vm-a")
    stop_script = calls[1][calls[1].index("--scripts") + 1]
    assert "tc qdisc del" in stop_script


async def test_vm_network_disconnect_uses_iptables(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzVmNetworkDisconnectInjector(
        resource_group="rg", vm_name="vm", destination="10.0.0.5"
    )
    await inj.inject(target="vm-a", params={})
    inject_script = calls[0][calls[0].index("--scripts") + 1]
    assert "iptables -I OUTPUT -d 10.0.0.5 -j DROP" in inject_script
    await inj.stop(target="vm-a")
    stop_script = calls[1][calls[1].index("--scripts") + 1]
    assert "iptables -D OUTPUT -d 10.0.0.5 -j DROP" in stop_script


def test_vm_network_disconnect_rejects_empty_destination() -> None:
    with pytest.raises(ValueError, match="destination"):
        ao.AzVmNetworkDisconnectInjector(resource_group="rg", vm_name="vm", destination="")


async def test_vm_stop_service_toggles_systemctl(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzVmStopServiceInjector(resource_group="rg", vm_name="vm", service="nginx")
    await inj.inject(target="vm-a", params={})
    assert "systemctl stop nginx" in calls[0][calls[0].index("--scripts") + 1]
    await inj.stop(target="vm-a")
    assert "systemctl start nginx" in calls[1][calls[1].index("--scripts") + 1]


def test_vm_stop_service_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="service"):
        ao.AzVmStopServiceInjector(resource_group="rg", vm_name="vm", service="")


# ---------------------------------------------------------------------------
# ARM operations
# ---------------------------------------------------------------------------


async def test_vm_lifecycle_deallocates_and_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzVmLifecycleInjector(resource_group="rg", vm_name="vm")
    await inj.inject(target="vm-a", params={})
    assert calls[0] == ["az", "vm", "deallocate", "-g", "rg", "-n", "vm"]
    await inj.stop(target="vm-a")
    assert calls[1] == ["az", "vm", "start", "-g", "rg", "-n", "vm"]


async def test_vm_lifecycle_redeploy_action(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzVmLifecycleInjector(resource_group="rg", vm_name="vm", action="redeploy")
    await inj.inject(target="vm-a", params={})
    assert calls[0] == ["az", "vm", "redeploy", "-g", "rg", "-n", "vm"]
    await inj.stop(target="vm-a")
    # redeploy also uses `start` as the reverse (VM starts on the new host,
    # but calling start again is idempotent).
    assert calls[1][1:3] == ["vm", "start"]


async def test_vm_lifecycle_restart_no_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzVmLifecycleInjector(resource_group="rg", vm_name="vm", action="restart")
    await inj.stop(target="vm-a")
    assert calls == []


def test_vm_lifecycle_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="lifecycle action"):
        ao.AzVmLifecycleInjector(resource_group="rg", vm_name="vm", action="explode")


async def test_vmss_lifecycle_deallocate_and_start(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzVmssLifecycleInjector(resource_group="rg", vmss_name="vmss")
    await inj.inject(target="vmss-a", params={})
    assert calls[0] == ["az", "vmss", "deallocate", "-g", "rg", "-n", "vmss"]
    await inj.stop(target="vmss-a")
    assert calls[1] == ["az", "vmss", "start", "-g", "rg", "-n", "vmss"]


def test_vmss_lifecycle_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="lifecycle action"):
        ao.AzVmssLifecycleInjector(resource_group="rg", vmss_name="vmss", action="detonate")


async def test_redis_reboot_is_one_shot(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzRedisRebootInjector(resource_group="rg", cache_name="cache")
    await inj.inject(target="cache-a", params={})
    assert calls[0] == [
        "az",
        "redis",
        "force-reboot",
        "-g",
        "rg",
        "-n",
        "cache",
        "--reboot-type",
        "AllNodes",
    ]
    # stop() is a no-op - reboot is one-way.
    await inj.stop(target="cache-a")
    assert len(calls) == 1


async def test_cosmos_failover_reverses_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzCosmosFailoverInjector(
        resource_group="rg",
        account_name="cosmos",
        original_priorities="R1=0 R2=1",
        failover_priorities="R2=0 R1=1",
    )
    await inj.inject(target="cosmos-a", params={})
    assert calls[0][-1] == "R2=0 R1=1"
    await inj.stop(target="cosmos-a")
    assert calls[1][-1] == "R1=0 R2=1"


def test_cosmos_failover_rejects_empty_priorities() -> None:
    with pytest.raises(ValueError, match="MUST be non-empty"):
        ao.AzCosmosFailoverInjector(
            resource_group="rg",
            account_name="cosmos",
            original_priorities="",
            failover_priorities="R2=0",
        )


async def test_keyvault_deny_toggles_default_action(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzKeyVaultDenyAccessInjector(
        resource_group="rg", vault_name="kv", original_default_action="Allow"
    )
    await inj.inject(target="kv-a", params={})
    assert calls[0][:5] == ["az", "keyvault", "network-rule", "add", "--name"]
    assert calls[0][-1] == "Deny"
    await inj.stop(target="kv-a")
    # Rollback uses `keyvault update` to restore the recorded original action.
    assert calls[1][:4] == ["az", "keyvault", "update", "--name"]
    assert calls[1][-1] == "Allow"


async def test_nsg_rule_creates_and_deletes(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzNsgRuleInjector(
        resource_group="rg", nsg_name="my-nsg", rule_name="fdai-block", priority=200
    )
    await inj.inject(target="nsg-a", params={"destination": "1.2.3.4/32"})
    assert calls[0][:5] == ["az", "network", "nsg", "rule", "create"]
    assert "--priority" in calls[0]
    assert calls[0][calls[0].index("--destination-address-prefixes") + 1] == "1.2.3.4/32"
    await inj.stop(target="nsg-a")
    assert calls[1][:5] == ["az", "network", "nsg", "rule", "delete"]
    assert calls[1][calls[1].index("-n") + 1] == "fdai-block"


async def test_lb_backend_remove_and_readd(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzLbBackendRemoveInjector(
        resource_group="rg",
        lb_name="lb",
        pool_name="pool",
        address_name="addr",
        address_ip="10.0.0.5",
    )
    await inj.inject(target="lb-a", params={})
    assert calls[0][:6] == ["az", "network", "lb", "address-pool", "address", "remove"]
    await inj.stop(target="lb-a")
    assert calls[1][:6] == ["az", "network", "lb", "address-pool", "address", "add"]
    assert calls[1][calls[1].index("--ip-address") + 1] == "10.0.0.5"


async def test_lb_backend_remove_stop_is_noop_without_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rollback add requires knowing the original IP - if the composition
    root did not vouch for one, we do not fabricate one; the operator
    manually re-adds."""
    runner, calls = _patch(monkeypatch)
    inj = ao.AzLbBackendRemoveInjector(
        resource_group="rg", lb_name="lb", pool_name="pool", address_name="addr"
    )
    await inj.stop(target="lb-a")
    assert calls == []


async def test_servicebus_firewall_toggles(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _patch(monkeypatch)
    inj = ao.AzServiceBusFirewallInjector(
        resource_group="rg", namespace_name="sb", original_default_action="Allow"
    )
    await inj.inject(target="sb-a", params={})
    assert calls[0][-1] == "Deny"
    assert calls[0][:5] == ["az", "servicebus", "namespace", "network-rule-set", "update"]
    await inj.stop(target="sb-a")
    assert calls[1][-1] == "Allow"


async def test_az_cli_state_probe_matches_expected_and_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _patch(monkeypatch)

    async def state_runner(cmd, *, timeout=60.0, drop_azure_config_dir=False):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return 0, "PowerState/deallocated\n", ""

    monkeypatch.setattr(ao, "_run", state_runner)
    probe = ao.AzCliStateProbe(
        command=("az", "vm", "show"),
        expected_substrings=("deallocated",),
        absent_substrings=("running",),
    )
    assert await probe.observed(signal="pod_restart", targets=("vm",)) is True


async def test_az_cli_state_probe_fails_closed_on_command_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def state_runner(cmd, *, timeout=60.0, drop_azure_config_dir=False):  # type: ignore[no-untyped-def]
        return 1, "", "failed"

    monkeypatch.setattr(ao, "_run", state_runner)
    probe = ao.AzCliStateProbe(command=("az", "vm", "show"), expected_substrings=("ok",))
    assert await probe.observed(signal="pod_restart", targets=("vm",)) is False


def test_az_cli_state_probe_requires_a_predicate() -> None:
    with pytest.raises(ValueError, match="expected or absent"):
        ao.AzCliStateProbe(command=("az", "vm", "show"))


# ---------------------------------------------------------------------------
# fault_type identifiers on every class match the catalog vocabulary
# ---------------------------------------------------------------------------


def test_fault_types_are_stable() -> None:
    assert (
        ao.AzVmNetworkLatencyInjector(resource_group="rg", vm_name="vm").fault_type
        == "network_delay"
    )
    assert ao.AzVmPacketLossInjector(resource_group="rg", vm_name="vm").fault_type == "network_loss"
    assert (
        ao.AzVmNetworkDisconnectInjector(
            resource_group="rg", vm_name="vm", destination="x"
        ).fault_type
        == "network_disconnect"
    )
    assert (
        ao.AzVmStopServiceInjector(resource_group="rg", vm_name="vm", service="x").fault_type
        == "stop_service"
    )
    assert ao.AzVmLifecycleInjector(resource_group="rg", vm_name="vm").fault_type == "vm_lifecycle"
    assert (
        ao.AzVmssLifecycleInjector(resource_group="rg", vmss_name="v").fault_type
        == "vmss_lifecycle"
    )
    assert (
        ao.AzRedisRebootInjector(resource_group="rg", cache_name="c").fault_type == "redis_reboot"
    )
    assert (
        ao.AzCosmosFailoverInjector(
            resource_group="rg",
            account_name="c",
            original_priorities="a",
            failover_priorities="b",
        ).fault_type
        == "cosmosdb_failover"
    )
    assert (
        ao.AzKeyVaultDenyAccessInjector(resource_group="rg", vault_name="v").fault_type
        == "keyvault_deny_access"
    )
    assert ao.AzNsgRuleInjector(resource_group="rg", nsg_name="n").fault_type == "nsg_rule"
    assert (
        ao.AzLbBackendRemoveInjector(
            resource_group="rg", lb_name="l", pool_name="p", address_name="a"
        ).fault_type
        == "lb_backend_remove"
    )
    assert (
        ao.AzServiceBusFirewallInjector(resource_group="rg", namespace_name="s").fault_type
        == "servicebus_firewall"
    )
