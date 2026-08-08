"""Build authenticated model request targets without provider logic in core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import urlparse

from fdai.rule_catalog.schema.model_endpoint import ModelApiStyle, ModelRouteKind

COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"


@dataclass(frozen=True, slots=True)
class ModelRequest:
    url: str
    params: Mapping[str, str]
    model_body_field: str | None


@dataclass(frozen=True, slots=True)
class ModelRequestTarget:
    """Resolved data-plane URL shape and workload-identity audience."""

    endpoint: str
    deployment: str
    api_style: ModelApiStyle = ModelApiStyle.AZURE_OPENAI
    api_version: str | None = None
    auth_audience: str = COGNITIVE_SERVICES_SCOPE
    route_kind: ModelRouteKind = ModelRouteKind.DIRECT
    binding_id: str | None = None

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("model endpoint MUST be an https URL without credentials or query")
        if not self.deployment.strip():
            raise ValueError("model deployment MUST be non-empty")
        if not self.auth_audience.strip():
            raise ValueError("model auth audience MUST be non-empty")
        if self.api_style is ModelApiStyle.AZURE_OPENAI and not self.api_version:
            raise ValueError("Azure OpenAI API style requires api_version")
        if self.route_kind is ModelRouteKind.APIM_GATEWAY and not self.binding_id:
            raise ValueError("APIM model request target requires binding_id")

    def operation(self, operation: str) -> ModelRequest:
        if operation not in {"chat/completions", "embeddings"}:
            raise ValueError("model operation is unsupported")
        if self.api_style is ModelApiStyle.AZURE_OPENAI:
            return ModelRequest(
                url=(
                    self.endpoint.rstrip("/")
                    + "/openai/deployments/"
                    + self.deployment
                    + "/"
                    + operation
                ),
                params=MappingProxyType({"api-version": self.api_version or ""}),
                model_body_field=None,
            )
        return ModelRequest(
            url=self.endpoint.rstrip("/") + "/v1/" + operation,
            params=MappingProxyType({}),
            model_body_field=self.deployment,
        )


__all__ = [
    "COGNITIVE_SERVICES_SCOPE",
    "ModelRequest",
    "ModelRequestTarget",
]
