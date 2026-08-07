"""Production composition boundary for the independent Operator service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fdai_service_contracts import OperatorReadModel, OperatorTokenVerifier, ReadDataSource

from fdai_operator_service.auth import EntraJwtVerifier, OperatorAuthenticator
from fdai_operator_service.environment import OperatorEnvironment
from fdai_operator_service.projections import UnavailableOperatorReadModel
from fdai_operator_service.runtime import OperatorRuntime


class OperatorComposition(Protocol):
    """Build the complete service-owned runtime from explicit provider seams."""

    def build_runtime(self, environ: Mapping[str, str] | None = None) -> OperatorRuntime: ...


class TokenVerifierFactory(Protocol):
    """Build the process-local token verifier from validated environment state."""

    def __call__(self, environment: OperatorEnvironment) -> OperatorTokenVerifier: ...


def _build_entra_verifier(environment: OperatorEnvironment) -> OperatorTokenVerifier:
    return EntraJwtVerifier.from_environment(environment)


@dataclass(frozen=True, slots=True)
class ProductionOperatorComposition:
    """Bind production identity and read providers without implementation imports."""

    verifier_factory: TokenVerifierFactory = _build_entra_verifier
    read_model: OperatorReadModel | None = None

    def build_runtime(self, environ: Mapping[str, str] | None = None) -> OperatorRuntime:
        """Bind a validated environment snapshot to service-owned HTTP dependencies."""
        environment = OperatorEnvironment.parse(os.environ if environ is None else environ)
        configured_read_model = self.read_model
        return OperatorRuntime(
            environment=environment,
            authenticator=OperatorAuthenticator(
                verifier=self.verifier_factory(environment),
                group_ids=environment.group_ids,
            ),
            read_model=configured_read_model or UnavailableOperatorReadModel(),
            data_sources=_build_data_sources(configured=configured_read_model is not None),
        )


def _build_data_sources(*, configured: bool) -> tuple[ReadDataSource, ...]:
    reason = None if configured else "Authoritative service-local projections are not configured."
    return (
        ReadDataSource(
            key="operational-state",
            source="service-local-projection" if configured else "not-configured",
            routes=(
                "/audit",
                "/audit/{correlation_id}/trace",
                "/hil-queue",
                "/incidents",
                "/incidents/stream",
                "/kpi",
                "/rca",
            ),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="notification-template",
            source="operator-service",
            routes=("/notification-templates/incident-opened",),
            availability="available",
            configured=True,
            reachable=True,
            authoritative=True,
            durable=False,
        ),
    )


__all__ = ["OperatorComposition", "ProductionOperatorComposition", "TokenVerifierFactory"]
