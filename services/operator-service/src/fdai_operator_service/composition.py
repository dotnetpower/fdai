"""Production composition boundary for the independent Operator service."""

from __future__ import annotations

import importlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from fdai_operator_service.contracts import ApplicationFactory, ApplicationFactoryResolver
from fdai_operator_service.environment import (
    FACTORY_ENV,
    OperatorEnvironment,
    OperatorServiceConfigurationError,
)
from fdai_operator_service.runtime import OperatorRuntime


class OperatorComposition(Protocol):
    """Build the complete service-owned runtime without loading live providers early."""

    def build_runtime(self, environ: Mapping[str, str] | None = None) -> OperatorRuntime: ...


def resolve_application_factory(reference: str) -> ApplicationFactory:
    """Resolve a ``module:attribute`` application factory reference."""
    module_name, separator, attribute_name = reference.strip().partition(":")
    if not separator or not module_name or not attribute_name:
        raise OperatorServiceConfigurationError(f"{FACTORY_ENV} MUST use module:attribute")
    try:
        candidate = getattr(importlib.import_module(module_name), attribute_name)
    except (AttributeError, ImportError) as exc:
        raise OperatorServiceConfigurationError(f"{FACTORY_ENV} could not be resolved") from exc
    if not callable(candidate):
        raise OperatorServiceConfigurationError(f"{FACTORY_ENV} MUST resolve to a callable")
    return cast(ApplicationFactory, candidate)


@dataclass(frozen=True, slots=True)
class ProductionOperatorComposition:
    """Validate service configuration before resolving the selected implementation adapter."""

    resolver: ApplicationFactoryResolver = resolve_application_factory

    def build_runtime(self, environ: Mapping[str, str] | None = None) -> OperatorRuntime:
        """Bind a validated environment snapshot to its application factory."""
        environment = OperatorEnvironment.parse(os.environ if environ is None else environ)
        return OperatorRuntime(
            environment=environment,
            application_factory=self.resolver(environment.factory_reference),
        )
