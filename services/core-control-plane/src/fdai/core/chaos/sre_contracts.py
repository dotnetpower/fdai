"""Operational contracts for the S1-S14 SRE scenario pack."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.chaos.scenarios import default_scenarios
from fdai.core.detection.signals import (
    SIGNAL_ALERT_TRIGGER,
    SIGNAL_BACKEND_HEALTH,
    SIGNAL_CONFIG_DRIFT,
    SIGNAL_DB_CPU,
    SIGNAL_GATEWAY_LATENCY,
    SIGNAL_HOST_CPU,
    SIGNAL_HOST_MEMORY,
    SIGNAL_NODE_CPU,
    SIGNAL_POD_RESTART,
    SIGNAL_RATE_LIMIT,
    SIGNAL_REQUEST_FAILURE,
    SIGNAL_ROLLOUT_STALL,
    known_signals,
)
from fdai.core.recovery import RecoveryProbeKind

_ALL_RECOVERY_PROBES = tuple(RecoveryProbeKind)


@dataclass(frozen=True, slots=True)
class SreScenarioContract:
    scenario_id: str
    title: str
    fault: bool
    signals: tuple[str, ...]
    causal_mechanism: str
    chaos_scenario_id: str | None
    recovery_probes: tuple[RecoveryProbeKind, ...]
    recovery_action_types: tuple[str, ...]


def sre_scenario_contracts() -> tuple[SreScenarioContract, ...]:
    return (
        _fault(
            "S1",
            "AKS pod kill",
            SIGNAL_POD_RESTART,
            "pod_replacement",
            "aks-pod-kill",
            "ops.restart-service",
        ),
        _fault(
            "S2",
            "AKS pod CPU stress",
            SIGNAL_NODE_CPU,
            "cpu_saturation",
            "aks-pod-cpu-spike",
            "ops.scale-out",
        ),
        _fault(
            "S3",
            "AKS pod network latency",
            SIGNAL_GATEWAY_LATENCY,
            "dependency_latency",
            "network-rtt-delay",
            "ops.drain-connection",
        ),
        _fault(
            "S4",
            "AKS HTTP abort",
            SIGNAL_REQUEST_FAILURE,
            "request_abort",
            "aks-http-abort",
            "ops.restart-service",
        ),
        _fault(
            "S5",
            "VM CPU stress",
            SIGNAL_HOST_CPU,
            "host_cpu_saturation",
            "vm-cpu-stress",
            "ops.scale-out",
        ),
        _fault(
            "S6",
            "VM memory stress",
            SIGNAL_HOST_MEMORY,
            "host_memory_pressure",
            "vm-mem-stress",
            "ops.scale-out",
        ),
        _fault(
            "S7",
            "VM network latency",
            SIGNAL_GATEWAY_LATENCY,
            "egress_latency",
            "network-rtt-delay",
            "ops.drain-connection",
        ),
        _fault(
            "S8",
            "MySQL credit exhaustion",
            SIGNAL_DB_CPU,
            "database_credit_exhaustion",
            "mysql-cpu-pressure",
            "ops.scale-out",
        ),
        _fault(
            "S9",
            "Azure OpenAI 429",
            SIGNAL_RATE_LIMIT,
            "quota_pressure",
            "aoai-tpm-throttle",
            "ops.switch-t2-proposer-route",
        ),
        _fault(
            "S10",
            "Application Gateway first byte latency",
            SIGNAL_GATEWAY_LATENCY,
            "backend_latency",
            "network-rtt-delay",
            "ops.drain-connection",
        ),
        _fault(
            "S11",
            "Dependency outage cascade",
            SIGNAL_BACKEND_HEALTH,
            "backend_cascade",
            "appgw-backend-failure",
            "ops.scale-out",
        ),
        _fault(
            "S12",
            "Bad deployment",
            SIGNAL_ROLLOUT_STALL,
            "deployment_regression",
            "aks-bad-deploy",
            "ops.restart-service",
        ),
        SreScenarioContract(
            scenario_id="S13",
            title="Knowledge and configuration drift",
            fault=False,
            signals=(SIGNAL_CONFIG_DRIFT,),
            causal_mechanism="out_of_band_change",
            chaos_scenario_id=None,
            recovery_probes=(),
            recovery_action_types=(),
        ),
        SreScenarioContract(
            scenario_id="S14",
            title="Alert-triggered investigation",
            fault=False,
            signals=(SIGNAL_ALERT_TRIGGER,),
            causal_mechanism="alert_to_investigation",
            chaos_scenario_id=None,
            recovery_probes=(),
            recovery_action_types=(),
        ),
    )


def _fault(
    scenario_id: str,
    title: str,
    signal: str,
    mechanism: str,
    chaos_scenario_id: str,
    recovery_action_type: str,
) -> SreScenarioContract:
    return SreScenarioContract(
        scenario_id=scenario_id,
        title=title,
        fault=True,
        signals=(signal,),
        causal_mechanism=mechanism,
        chaos_scenario_id=chaos_scenario_id,
        recovery_probes=_ALL_RECOVERY_PROBES,
        recovery_action_types=(recovery_action_type,),
    )


def validate_sre_scenario_contracts() -> None:
    contracts = sre_scenario_contracts()
    expected_ids = {f"S{index}" for index in range(1, 15)}
    if {item.scenario_id for item in contracts} != expected_ids:
        raise ValueError("SRE contracts MUST cover exactly S1-S14")
    chaos_ids = {item.scenario_id for item in default_scenarios()}
    registered_signals = set(known_signals())
    for contract in contracts:
        if not set(contract.signals) <= registered_signals:
            raise ValueError(f"{contract.scenario_id} references an unknown signal")
        if contract.fault:
            if contract.chaos_scenario_id not in chaos_ids:
                raise ValueError(f"{contract.scenario_id} references an unknown chaos scenario")
            if set(contract.recovery_probes) != set(RecoveryProbeKind):
                raise ValueError(f"{contract.scenario_id} lacks complete recovery verification")
            if not contract.recovery_action_types:
                raise ValueError(f"{contract.scenario_id} lacks a recovery action")
        elif contract.chaos_scenario_id is not None:
            raise ValueError(f"{contract.scenario_id} is non-fault but references chaos")


__all__ = ["SreScenarioContract", "sre_scenario_contracts", "validate_sre_scenario_contracts"]
