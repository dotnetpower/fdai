"""Provider-neutral planning and completeness-preserving discovery routing."""

from fdai.core.discovery.router import (
    BackendEligibility,
    DiscoveryRoutingDecision,
    compile_discovery_routes,
    equivalent_fallback,
    merge_discovery_results,
)

__all__ = [
    "BackendEligibility",
    "DiscoveryRoutingDecision",
    "compile_discovery_routes",
    "equivalent_fallback",
    "merge_discovery_results",
]
