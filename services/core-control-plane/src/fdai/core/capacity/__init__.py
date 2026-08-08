"""Capacity policy - warm-vs-cold executor provisioning.

Resolves the scale-to-zero (cost) vs cold-start (MTTR) tension: a pure,
deterministic policy the deployment layer reads at plan time and the
runtime reads to decide whether an action class needs a warm lane. See
[cost-model.md](../../../../docs/roadmap/interfaces/cost-model.md).
"""

from fdai.core.capacity.warm_pool import (
    CapacityDecision,
    WarmCapacityConfig,
    WarmCapacityPolicy,
)

__all__ = [
    "CapacityDecision",
    "WarmCapacityConfig",
    "WarmCapacityPolicy",
]
