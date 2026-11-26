"""Catalog identities for the reference chaos sweep.

The reference scenarios in :mod:`fdai.core.chaos.scenarios` declare which signal
each demo-parity fault MUST raise. They are a detection contract, not an
execution path: a live run may only use a reviewed entry from the chaos-scenario
catalog, because promotion, parameters, blast-radius caps, and rollback notes are
owned there.

This module is the reviewed bridge between the two. Each reference scenario maps
to exactly one catalog entry with the identical ``expected_signal`` and the
matching fault family, at ``mild`` intensity: the most conservative reviewed
variant that still raises the signal. The catalog entry governs the run; the
reference constant never overrides its parameters or caps.

Selection alone grants no authority. A mapped entry still has to be promoted,
approved, and executable before the governed adapter will run it, and an entry
whose ``target_type`` has no canonical substrate identity is refused.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from fdai.core.chaos.scenarios import default_scenarios

_CATALOG_IDS: Final[tuple[tuple[str, str], ...]] = (
    ("aks-pod-kill", "chaos.general.pod-stop-pod-restart-mild"),
    ("aks-pod-cpu-spike", "chaos.general.pod-saturate-node-cpu-mild"),
    ("network-rtt-delay", "chaos.general.pod-delay-gateway-latency-mild"),
    ("aks-http-abort", "chaos.general.pod-drop-request-failure-mild"),
    ("vm-cpu-stress", "chaos.general.vm-saturate-host-cpu-mild"),
    ("vm-mem-stress", "chaos.general.vm-saturate-host-memory-mild"),
    ("mysql-cpu-pressure", "chaos.general.db-saturate-db-cpu-mild"),
    ("aoai-tpm-throttle", "chaos.general.llm_endpoint-throttle-rate-limit-mild"),
    ("appgw-backend-failure", "chaos.general.lb-deny-backend-health-mild"),
    ("aks-bad-deploy", "chaos.general.pod-corrupt-rollout-stall-mild"),
)

REFERENCE_SWEEP_CATALOG_IDS: Final[MappingProxyType[str, str]] = MappingProxyType(
    dict(_CATALOG_IDS)
)
"""Reference scenario id -> the catalog entry a governed run executes for it."""


def reference_scenario_ids() -> tuple[str, ...]:
    """Return the reference scenario ids in the order the sweep runs them."""

    return tuple(reference_id for reference_id, _ in _CATALOG_IDS)


def reference_sweep_catalog_ids() -> tuple[str, ...]:
    """Return the mapped catalog ids in the order the sweep runs them."""

    return tuple(catalog_id for _, catalog_id in _CATALOG_IDS)


def reference_catalog_id(scenario_id: str) -> str | None:
    """Return the catalog id a reference scenario selects, or ``None``.

    ``None`` means the argument is not a reference scenario id. A caller that
    already holds a catalog id MUST keep using it rather than treating the
    absent mapping as a failure.
    """

    return REFERENCE_SWEEP_CATALOG_IDS.get(scenario_id)


def resolve_scenario_id(scenario_id: str) -> str:
    """Return the catalog id to execute for a reference or catalog scenario id."""

    return REFERENCE_SWEEP_CATALOG_IDS.get(scenario_id, scenario_id)


def unmapped_reference_scenarios() -> tuple[str, ...]:
    """Return reference scenarios this module does not map to a catalog entry.

    A non-empty result means the sweep would silently skip a declared demo-parity
    fault, so the owning regression fails instead of running a partial sweep.
    """

    mapped = REFERENCE_SWEEP_CATALOG_IDS
    return tuple(
        scenario.scenario_id
        for scenario in default_scenarios()
        if scenario.scenario_id not in mapped
    )


__all__ = [
    "REFERENCE_SWEEP_CATALOG_IDS",
    "reference_catalog_id",
    "reference_scenario_ids",
    "reference_sweep_catalog_ids",
    "resolve_scenario_id",
    "unmapped_reference_scenarios",
]
