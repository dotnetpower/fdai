"""Stable identity for one independently packaged FDAI service."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ServiceKind(StrEnum):
    """Supported independently deployed process shapes."""

    HTTP_API = "http-api"
    EVENT_CONSUMER = "event-consumer"
    CONTROL_PLANE = "control-plane"


@dataclass(frozen=True, slots=True)
class ServiceDescriptor:
    """Immutable package, image, entrypoint, and authority identity."""

    service_id: str
    distribution: str
    image: str
    entrypoint: str
    kind: ServiceKind
    executor_authority: bool = False

    def __post_init__(self) -> None:
        values = (self.service_id, self.distribution, self.image, self.entrypoint)
        if any(not value.strip() for value in values):
            raise ValueError("service descriptor values must be non-empty")
        if self.service_id == "isolated-executor" and not self.executor_authority:
            raise ValueError("isolated Executor descriptor must declare executor authority")
        if self.service_id != "isolated-executor" and self.executor_authority:
            raise ValueError("only isolated Executor may declare executor authority")
