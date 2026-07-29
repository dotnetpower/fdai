"""Canonical MCSB control IDs for Azure security posture observations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

MCSB_CONTROLS_BY_OBSERVATION: Final[Mapping[str, tuple[str, ...]]] = {
    "aks-rbac": ("MCSB-IM-1",),
    "aks-entra-integration": ("MCSB-IM-1",),
    "aks-policy-addon": ("MCSB-PV-2",),
    "aks-container-insights": ("MCSB-LT-1",),
    "aks-diagnostics": ("MCSB-LT-3",),
    "mysql-tls": ("MCSB-DP-3",),
    "mysql-public-access": ("MCSB-NS-2",),
    "mysql-audit-log": ("MCSB-LT-3",),
    "mysql-diagnostics": ("MCSB-LT-3",),
}


def mcsb_controls(observation_id: str) -> tuple[str, ...]:
    """Return the reviewed MCSB controls for one runtime observation."""

    try:
        return MCSB_CONTROLS_BY_OBSERVATION[observation_id]
    except KeyError as exc:
        raise ValueError(f"unknown MCSB observation id {observation_id!r}") from exc


__all__ = ["MCSB_CONTROLS_BY_OBSERVATION", "mcsb_controls"]
