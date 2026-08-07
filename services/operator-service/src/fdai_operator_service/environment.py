"""Validated environment contract for the independent Operator process."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

FACTORY_ENV = "FDAI_OPERATOR_SERVICE_FACTORY"
HOST_ENV = "FDAI_OPERATOR_SERVICE_HOST"
PORT_ENV = "FDAI_OPERATOR_SERVICE_PORT"
DEFAULT_FACTORY = "fdai_operator_service.legacy_adapter:create_app"
DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - Container ingress terminates external HTTPS.
DEFAULT_PORT = 8000


class OperatorServiceConfigurationError(ValueError):
    """Raised before dependency loading when service configuration is invalid."""


@dataclass(frozen=True, slots=True)
class OperatorEnvironment:
    """Hold the immutable service-owned subset of production configuration."""

    values: Mapping[str, str]
    factory_reference: str
    host: str
    port: int

    @classmethod
    def parse(cls, environ: Mapping[str, str]) -> OperatorEnvironment:
        """Validate the Operator factory reference and listener settings."""
        values = dict(environ)
        factory_reference = values.get(FACTORY_ENV, DEFAULT_FACTORY).strip()
        if not factory_reference:
            raise OperatorServiceConfigurationError(f"{FACTORY_ENV} MUST be non-empty")

        host = values.get(HOST_ENV, DEFAULT_HOST).strip()
        if not host:
            raise OperatorServiceConfigurationError(f"{HOST_ENV} MUST be non-empty")

        raw_port = values.get(PORT_ENV, str(DEFAULT_PORT)).strip()
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise OperatorServiceConfigurationError(f"{PORT_ENV} MUST be an integer") from exc
        if not 1 <= port <= 65535:
            raise OperatorServiceConfigurationError(f"{PORT_ENV} MUST be between 1 and 65535")

        return cls(
            values=values,
            factory_reference=factory_reference,
            host=host,
            port=port,
        )
