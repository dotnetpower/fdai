"""Verticals - Resilience (DR/Chaos), Change Safety, Cost Governance.

Each vertical composes existing P1/P2 primitives (`T0Engine`, `RiskGate`,
`ShadowExecutor`, `ContinuousRulePipeline`) with vertical-specific
scheduling / guardrails. This package is the P3 integration surface.

Each vertical is a sub-package (G-6, tracker #14):
:mod:`.resilience`, :mod:`.change_safety`, :mod:`.cost_governance`.
The subpackage lets a vertical grow past the 400-LOC per-file soft
limit without re-monolithing into one large file.

New operational domains onboard through the `VerticalRegistry` seam
(`registry.py`) - a fork registers a `VerticalDescriptor` at the
composition root rather than editing `core/`. The shared shape is the
:class:`Vertical` Protocol in :mod:`.base`.
"""

from fdai.core.verticals.base import Vertical
from fdai.core.verticals.registry import (
    VerticalDescriptor,
    VerticalRegistrationError,
    VerticalRegistry,
)

__all__ = [
    "Vertical",
    "VerticalDescriptor",
    "VerticalRegistrationError",
    "VerticalRegistry",
]
