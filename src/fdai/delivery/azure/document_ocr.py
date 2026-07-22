"""Managed-identity Azure Document Intelligence OCR adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from math import isfinite
from urllib.parse import urlparse

import httpx

from fdai.shared.contracts import DocumentVersion, StructuralUnit
from fdai.shared.providers.workload_identity import WorkloadIdentity

_DEFAULT_AUDIENCE = "https://cognitiveservices.azure.com/.default"


class AzureDocumentOcrError(RuntimeError):
    """Raised when configured OCR cannot return trustworthy bounded text."""


@dataclass(frozen=True, slots=True)
class AzureDocumentOcrConfig:
    endpoint: str
    api_version: str = "2024-11-30"
    audience: str = _DEFAULT_AUDIENCE
    timeout_seconds: float = 30.0
    poll_interval_seconds: float = 0.5
    max_polls: int = 60
    max_lines: int = 5000
    max_characters: int = 1_000_000
    max_response_bytes: int = 4_000_000

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OCR endpoint MUST be an HTTPS origin without credentials or query")
        if not self.api_version or not self.audience:
            raise ValueError("OCR API version and audience MUST be non-empty")
        if (
            not isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
            or not isfinite(self.poll_interval_seconds)
            or self.poll_interval_seconds < 0
            or self.max_polls < 1
            or self.max_lines < 1
            or self.max_characters < 1
            or self.max_response_bytes < 1
        ):
            raise ValueError("OCR limits MUST be positive")


class AzureDocumentIntelligenceOcr:
    """Run the prebuilt-read model and preserve page/line locators."""

    def __init__(
        self,
        *,
        config: AzureDocumentOcrConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._identity = identity
        self._http = http_client

    async def extract(
        self,
        *,
        version: DocumentVersion,
        content: bytes,
    ) -> tuple[StructuralUnit, ...]:
        if not content:
            raise AzureDocumentOcrError("OCR source is empty")
        try:
            token = await self._identity.get_token(self._config.audience)
        except RuntimeError as exc:
            raise AzureDocumentOcrError("OCR identity token is unavailable") from exc
        analyze_url = (
            f"{self._config.endpoint.rstrip('/')}/documentintelligence/documentModels/"
            f"prebuilt-read:analyze?api-version={self._config.api_version}"
        )
        try:
            response = await self._http.post(
                analyze_url,
                content=content,
                headers={
                    "Authorization": f"Bearer {token.token}",
                    "Content-Type": version.media_type,
                },
                timeout=self._config.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise AzureDocumentOcrError("OCR analyze request failed") from exc
        if response.status_code != 202:
            raise AzureDocumentOcrError(f"OCR analyze request returned HTTP {response.status_code}")
        operation_url = response.headers.get("operation-location")
        if not operation_url:
            raise AzureDocumentOcrError("OCR analyze response has no operation location")
        self._validate_operation_url(operation_url)
        for poll in range(self._config.max_polls):
            try:
                result = await self._http.get(
                    operation_url,
                    headers={"Authorization": f"Bearer {token.token}"},
                    timeout=self._config.timeout_seconds,
                    follow_redirects=False,
                )
                if result.status_code != 200:
                    raise AzureDocumentOcrError(
                        f"OCR operation poll returned HTTP {result.status_code}"
                    )
                if len(result.content) > self._config.max_response_bytes:
                    raise AzureDocumentOcrError("OCR operation response exceeded configured bounds")
                payload = result.json()
            except AzureDocumentOcrError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                raise AzureDocumentOcrError("OCR operation poll failed") from exc
            status = payload.get("status") if isinstance(payload, dict) else None
            if status == "succeeded":
                return self._units(payload)
            if status in {"failed", "canceled"}:
                raise AzureDocumentOcrError(f"OCR operation ended with status {status}")
            if status not in {"notStarted", "running"}:
                raise AzureDocumentOcrError("OCR operation returned an unknown status")
            if poll + 1 < self._config.max_polls:
                await asyncio.sleep(self._config.poll_interval_seconds)
        raise AzureDocumentOcrError("OCR operation exceeded the polling limit")

    def _validate_operation_url(self, operation_url: str) -> None:
        endpoint = urlparse(self._config.endpoint)
        operation = urlparse(operation_url)
        try:
            endpoint_port = endpoint.port
            operation_port = operation.port
        except ValueError as exc:
            raise AzureDocumentOcrError(
                "OCR operation location is outside the configured origin"
            ) from exc
        if (
            operation.scheme != endpoint.scheme
            or operation.hostname != endpoint.hostname
            or operation_port != endpoint_port
            or operation.username is not None
            or operation.password is not None
            or operation.fragment
        ):
            raise AzureDocumentOcrError("OCR operation location is outside the configured origin")

    def _units(self, payload: dict[str, object]) -> tuple[StructuralUnit, ...]:
        analyze_result = payload.get("analyzeResult")
        pages = analyze_result.get("pages") if isinstance(analyze_result, dict) else None
        if not isinstance(pages, list):
            raise AzureDocumentOcrError("OCR result has no pages")
        units: list[StructuralUnit] = []
        total_characters = 0
        for page_index, page in enumerate(pages, start=1):
            if not isinstance(page, dict):
                raise AzureDocumentOcrError("OCR page is malformed")
            page_number = page.get("pageNumber")
            if isinstance(page_number, bool) or not isinstance(page_number, int):
                page_number = page_index
            lines = page.get("lines")
            if not isinstance(lines, list):
                raise AzureDocumentOcrError("OCR page has no lines")
            for line_index, line in enumerate(lines, start=1):
                if not isinstance(line, dict) or not isinstance(line.get("content"), str):
                    raise AzureDocumentOcrError("OCR line is malformed")
                text = line["content"].strip()
                if not text:
                    continue
                total_characters += len(text)
                if (
                    len(units) >= self._config.max_lines
                    or total_characters > self._config.max_characters
                ):
                    raise AzureDocumentOcrError("OCR output exceeded configured bounds")
                units.append(
                    StructuralUnit(
                        unit_id=f"page-{page_number}-line-{line_index}",
                        kind="page",
                        locator=f"page:{page_number}:line:{line_index}",
                        text=text,
                    )
                )
        return tuple(units)


__all__ = [
    "AzureDocumentIntelligenceOcr",
    "AzureDocumentOcrConfig",
    "AzureDocumentOcrError",
]
