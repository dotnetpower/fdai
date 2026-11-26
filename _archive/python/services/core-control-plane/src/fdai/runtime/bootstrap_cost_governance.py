"""Cost Governance and Pantheon-enforcement bootstrap decisions."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fdai.agents import CostRuntimeBindings
from fdai.composition.cost_governance_activation import build_cost_runtime_bindings
from fdai.core.readiness import AuthorityCeiling
from fdai.runtime.readiness import RuntimeReadinessState


def boolean_env(environment: Mapping[str, str], key: str) -> bool:
    return environment.get(key, "").strip().lower() in {"1", "true", "yes", "on"}


async def build_logged_cost_runtime(
    environment: Mapping[str, str],
    *,
    logger: logging.Logger,
) -> CostRuntimeBindings:
    """Build package-neutral Njord bindings and record no-authority availability."""

    runtime = await build_cost_runtime_bindings(environment)
    logger.info(
        "cost_governance_runtime_binding",
        extra={
            "enabled": runtime.package_enabled,
            "advisory_bound": runtime.advisory_provider is not None,
            "activation_reader_bound": runtime.activation_reader is not None,
            "restored_samples": len(runtime.initial_samples),
        },
    )
    return runtime


def pantheon_enforce_enabled(
    environment: Mapping[str, str],
    startup_readiness: RuntimeReadinessState,
) -> bool:
    """Require both explicit selection and the deployment authority ceiling."""

    requested = environment.get("FDAI_PANTHEON_ENFORCE", "").lower() in ("1", "true")
    return requested and (
        startup_readiness.authority_ceiling("autonomous-action") is AuthorityCeiling.DEPLOYMENT
    )


__all__ = ["boolean_env", "build_logged_cost_runtime", "pantheon_enforce_enabled"]
