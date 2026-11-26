"""Stable identity for one independently packaged FDAI service."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from fdai_service_contracts.compatibility import SemVer


class ServiceKind(StrEnum):
    """Supported independently deployed process shapes."""

    HTTP_API = "http-api"
    EVENT_CONSUMER = "event-consumer"
    CONTROL_PLANE = "control-plane"


@dataclass(frozen=True, slots=True)
class ServiceDescriptor:
    """Immutable distribution, contract-set, entrypoint, and authority identity."""

    service_id: str
    distribution: str
    image: str
    entrypoint: str
    kind: ServiceKind
    distribution_version: str = "0.1.3"
    previous_distribution_version: str | None = "0.1.2"
    release_label: Literal["N-1", "N"] = "N"
    contract_set_version: str = "1.1.0"
    executor_authority: bool = False

    def __post_init__(self) -> None:
        values = (self.service_id, self.distribution, self.image, self.entrypoint)
        if any(not value.strip() for value in values):
            raise ValueError("service descriptor values must be non-empty")
        current = SemVer.parse(self.distribution_version)
        if self.previous_distribution_version is not None:
            previous = SemVer.parse(self.previous_distribution_version)
            if previous >= current:
                raise ValueError("previous distribution version must precede the current version")
        if SemVer.parse(self.contract_set_version).major != 1:
            raise ValueError("service contract set must use supported major 1")
        if self.service_id == "isolated-executor" and not self.executor_authority:
            raise ValueError("isolated Executor descriptor must declare executor authority")
        if self.service_id != "isolated-executor" and self.executor_authority:
            raise ValueError("only isolated Executor may declare executor authority")
