"""Azure Container Apps Job adapter for server-owned execution templates."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from fdai.core.execution_backend import ExecutionBackendKind, ExecutionBackendProfile
from fdai.shared.providers.execution_backend import (
    ExecutionBackendCapabilities,
    ExecutionBackendError,
    ExecutionBackendHealth,
    ExecutionBackendPlan,
    ExecutionBackendReceipt,
    ExecutionBackendRequest,
    ExecutionCleanupResult,
    ExecutionCleanupState,
    ExecutionHealthState,
    ExecutionStatus,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity
from fdai.shared.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
)

_JOB_ID = re.compile(
    r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.App/jobs/[^/]+$",
    re.IGNORECASE,
)
_EXECUTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_INPUT_REF = re.compile(r"^input:sha256:[0-9a-f]{64}$")
_DEFAULT_AUDIENCE = "https://management.azure.com/.default"
_DEFAULT_ENDPOINT = "https://management.azure.com"
_DEFAULT_API_VERSION = "2024-03-01"


@dataclass(frozen=True, slots=True)
class ContainerAppsJobTrigger:
    """Reference to server-persisted input; never an image, command, or credential."""

    workload_id: str
    input_ref: str | None = None

    def __post_init__(self) -> None:
        if self.input_ref is not None and _INPUT_REF.fullmatch(self.input_ref) is None:
            raise ValueError("input_ref MUST be a content-addressed server input reference")


@dataclass(frozen=True, slots=True)
class AzureContainerAppsJobTemplate:
    """Server-owned pointer to a pre-provisioned Job and pinned image."""

    template_ref: str
    job_resource_id: str
    image_digest: str

    def __post_init__(self) -> None:
        if not self.template_ref or len(self.template_ref) > 128:
            raise ValueError("template_ref MUST be bounded")
        if _JOB_ID.fullmatch(self.job_resource_id) is None:
            raise ValueError("job_resource_id MUST be an Azure Container Apps Job ARM id")
        if re.fullmatch(r"[0-9a-f]{64}", self.image_digest) is None:
            raise ValueError("image_digest MUST be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class AzureContainerAppsJobBackendConfig:
    endpoint: str = _DEFAULT_ENDPOINT
    audience: str = _DEFAULT_AUDIENCE
    api_version: str = _DEFAULT_API_VERSION
    request_timeout_seconds: float = 30.0
    max_attempts: int = 3
    max_retry_delay_seconds: float = 10.0
    max_error_body_bytes: int = 512
    circuit_failure_threshold: int = 3
    circuit_reset_seconds: float = 30.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise ValueError("Container Apps Job endpoint MUST be an HTTPS origin")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds MUST be positive")
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts MUST be in [1, 5]")
        if not 0 < self.max_retry_delay_seconds <= 60:
            raise ValueError("max_retry_delay_seconds MUST be in (0, 60]")
        if self.max_error_body_bytes < 64:
            raise ValueError("max_error_body_bytes MUST be >= 64")


class AzureContainerAppsJobExecutionBackend:
    """Start only pre-provisioned Container Apps Jobs through ARM HTTPS."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        templates: Mapping[str, AzureContainerAppsJobTemplate],
        config: AzureContainerAppsJobBackendConfig | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._identity = identity
        self._http = http_client
        self._templates = dict(templates)
        if not self._templates:
            raise ValueError("Container Apps Job templates MUST NOT be empty")
        if any(key != value.template_ref for key, value in self._templates.items()):
            raise ValueError("Container Apps Job template map keys MUST match template_ref")
        self._config = config or AzureContainerAppsJobBackendConfig()
        self._sleep = sleep
        self._breaker = CircuitBreaker(
            name="azure-container-apps-job",
            config=CircuitBreakerConfig(
                failure_threshold=self._config.circuit_failure_threshold,
                reset_timeout_s=self._config.circuit_reset_seconds,
            ),
        )

    async def plan(
        self,
        request: ExecutionBackendRequest,
        *,
        profile: ExecutionBackendProfile,
    ) -> ExecutionBackendPlan:
        if profile.backend_kind is not ExecutionBackendKind.AZURE_CONTAINER_APPS_JOB:
            raise ExecutionBackendError("profile does not select Azure Container Apps Job")
        if not isinstance(request.payload, ContainerAppsJobTrigger):
            raise ExecutionBackendError("Container Apps Job requires a bounded trigger payload")
        if request.payload.workload_id != request.workload_id:
            raise ExecutionBackendError("trigger workload does not match execution request")
        template = self._template(profile)
        if request.artifact_digest != template.image_digest:
            raise ExecutionBackendError("request artifact digest does not match pinned image")
        digest = hashlib.sha256(
            f"{request.idempotency_key}:{template.template_ref}".encode()
        ).hexdigest()[:24]
        return ExecutionBackendPlan(
            plan_ref=f"aca-job-plan:{template.template_ref}:{digest}",
            backend_kind=ExecutionBackendKind.AZURE_CONTAINER_APPS_JOB.value,
            request=request,
            created_at=datetime.now(tz=UTC),
        )

    async def submit(self, plan: ExecutionBackendPlan) -> ExecutionBackendReceipt:
        profile_template = self._template_for_plan(plan)
        url = self._resource_url(profile_template.job_resource_id, suffix="/start")
        response = await self._request("POST", url, json_body={})
        payload = _json_object(response)
        execution_name = payload.get("name")
        if not isinstance(execution_name, str) or _EXECUTION_NAME.fullmatch(execution_name) is None:
            raise ExecutionBackendError("Container Apps Job start returned no execution name")
        submission_ref = self._resource_url(
            profile_template.job_resource_id,
            suffix=f"/executions/{execution_name}",
        )
        return ExecutionBackendReceipt(
            status=ExecutionStatus.SUBMITTED,
            submission_ref=submission_ref,
            receipt_ref=submission_ref,
            detail="Container Apps Job execution accepted",
        )

    async def status(self, submission_ref: str) -> ExecutionBackendReceipt:
        self._validate_submission_ref(submission_ref)
        response = await self._request("GET", submission_ref)
        return _receipt_from_execution(submission_ref, _json_object(response))

    async def cancel(self, submission_ref: str) -> ExecutionBackendReceipt:
        self._validate_submission_ref(submission_ref)
        await self._request("POST", f"{submission_ref}/stop", json_body={})
        try:
            return await self.status(submission_ref)
        except ExecutionBackendError as exc:
            raise ExecutionBackendError(
                "Container Apps Job stop was accepted but terminal status is ambiguous"
            ) from exc

    async def collect_receipt(self, submission_ref: str) -> ExecutionBackendReceipt:
        receipt = await self.status(submission_ref)
        if not receipt.status.terminal:
            raise ExecutionBackendError("Container Apps Job receipt is not terminal")
        return receipt

    async def cleanup(self, submission_ref: str) -> ExecutionCleanupResult:
        receipt = await self.status(submission_ref)
        if not receipt.status.terminal:
            await self.cancel(submission_ref)
        return ExecutionCleanupResult(
            state=ExecutionCleanupState.PROVIDER_RETENTION,
            detail="Container Apps Job execution metadata follows provider retention",
        )

    async def capabilities(self) -> ExecutionBackendCapabilities:
        return ExecutionBackendCapabilities(
            backend_kind=ExecutionBackendKind.AZURE_CONTAINER_APPS_JOB.value,
            supports_status=True,
            supports_cancel=True,
            supports_receipt=True,
            supports_cleanup=True,
            durable_provider_state=True,
        )

    async def health(self) -> ExecutionBackendHealth:
        try:
            for template in self._templates.values():
                response = await self._request("GET", self._resource_url(template.job_resource_id))
                if not _payload_has_image_digest(_json_object(response), template.image_digest):
                    return _health(
                        ExecutionHealthState.DEGRADED,
                        "configured Job image is not pinned to the expected digest",
                    )
        except Exception as exc:  # noqa: BLE001 - discovery returns state, not credentials
            return _health(
                ExecutionHealthState.UNAVAILABLE,
                f"Container Apps Job health check failed: {type(exc).__name__}",
            )
        return _health(ExecutionHealthState.HEALTHY, "all configured Jobs are reachable")

    def _template(self, profile: ExecutionBackendProfile) -> AzureContainerAppsJobTemplate:
        if profile.template_ref is None:
            raise ExecutionBackendError("Container Apps Job profile has no template reference")
        try:
            template = self._templates[profile.template_ref]
        except KeyError as exc:
            raise ExecutionBackendError("Container Apps Job template is not configured") from exc
        if profile.artifact_digest != template.image_digest:
            raise ExecutionBackendError("profile artifact digest does not match Job template")
        return template

    def _template_for_plan(self, plan: ExecutionBackendPlan) -> AzureContainerAppsJobTemplate:
        prefix = "aca-job-plan:"
        if not plan.plan_ref.startswith(prefix):
            raise ExecutionBackendError("plan does not reference a server-owned Job template")
        template_ref, separator, _digest = plan.plan_ref.removeprefix(prefix).rpartition(":")
        if not separator:
            raise ExecutionBackendError("plan does not reference a server-owned Job template")
        try:
            template = self._templates[template_ref]
        except KeyError as exc:
            raise ExecutionBackendError("plan Job template is not configured") from exc
        if template.image_digest != plan.request.artifact_digest:
            raise ExecutionBackendError("plan Job template digest changed")
        return template

    def _resource_url(self, resource_id: str, *, suffix: str = "") -> str:
        return f"{self._config.endpoint.rstrip('/')}{resource_id}{suffix}"

    def _validate_submission_ref(self, submission_ref: str) -> None:
        endpoint = urlparse(self._config.endpoint)
        parsed = urlparse(submission_ref)
        if parsed.scheme != endpoint.scheme or parsed.netloc != endpoint.netloc:
            raise ExecutionBackendError("submission_ref host does not match ARM endpoint")
        marker = "/executions/"
        if marker not in parsed.path:
            raise ExecutionBackendError("submission_ref is not a Job execution")
        job_id, execution_name = parsed.path.rsplit(marker, 1)
        if _JOB_ID.fullmatch(job_id) is None or _EXECUTION_NAME.fullmatch(execution_name) is None:
            raise ExecutionBackendError("submission_ref is not a valid Job execution")

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            return await self._breaker.call(
                self._request_with_retries,
                method,
                url,
                json_body=json_body,
            )
        except CircuitOpenError as exc:
            raise ExecutionBackendError("Container Apps Job circuit is open") from exc

    async def _request_with_retries(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, object] | None,
    ) -> httpx.Response:
        for attempt in range(1, self._config.max_attempts + 1):
            token = await self._identity.get_token(self._config.audience)
            try:
                response = await self._http.request(
                    method,
                    url,
                    params={"api-version": self._config.api_version},
                    headers={"Authorization": f"Bearer {token.token}"},
                    json=json_body,
                    timeout=self._config.request_timeout_seconds,
                )
            except httpx.HTTPError as exc:
                if attempt == self._config.max_attempts:
                    raise ExecutionBackendError(
                        f"Container Apps Job request failed: {type(exc).__name__}"
                    ) from exc
                await self._sleep(self._retry_delay(None, attempt))
                continue
            if response.status_code < 400:
                return response
            if response.status_code not in {408, 429, 500, 502, 503, 504} or (
                attempt == self._config.max_attempts
            ):
                raise ExecutionBackendError(
                    f"Container Apps Job returned HTTP {response.status_code}"
                )
            await self._sleep(self._retry_delay(response, attempt))
        raise AssertionError("bounded retry loop exhausted")

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            raw = response.headers.get("Retry-After")
            try:
                return max(
                    0.0,
                    min(float(raw or ""), self._config.max_retry_delay_seconds),
                )
            except ValueError:
                pass
        return min(float(2 ** (attempt - 1)), self._config.max_retry_delay_seconds)


def _receipt_from_execution(
    submission_ref: str,
    payload: dict[str, object],
) -> ExecutionBackendReceipt:
    properties = payload.get("properties")
    values = properties if isinstance(properties, dict) else {}
    raw = str(values.get("status") or "unknown").lower()
    status = {
        "pending": ExecutionStatus.SUBMITTED,
        "running": ExecutionStatus.RUNNING,
        "succeeded": ExecutionStatus.SUCCEEDED,
        "failed": ExecutionStatus.FAILED,
        "stopped": ExecutionStatus.CANCELLED,
        "cancelled": ExecutionStatus.CANCELLED,
    }.get(raw, ExecutionStatus.AMBIGUOUS)
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ExecutionBackendReceipt(
        status=status,
        submission_ref=submission_ref,
        receipt_ref=submission_ref,
        detail=f"Container Apps Job execution state: {raw}",
        output_digest=digest,
    )


def _json_object(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ExecutionBackendError("Container Apps Job returned non-JSON content") from exc
    if not isinstance(payload, dict):
        raise ExecutionBackendError("Container Apps Job response MUST be a JSON object")
    return payload


def _payload_has_image_digest(payload: dict[str, object], digest: str) -> bool:
    properties = payload.get("properties")
    template = properties.get("template") if isinstance(properties, dict) else None
    containers = template.get("containers") if isinstance(template, dict) else None
    if not isinstance(containers, list):
        return False
    return any(
        isinstance(item, dict)
        and isinstance(item.get("image"), str)
        and item["image"].endswith(f"@sha256:{digest}")
        for item in containers
    )


def _health(state: ExecutionHealthState, detail: str) -> ExecutionBackendHealth:
    return ExecutionBackendHealth(state=state, checked_at=datetime.now(tz=UTC), detail=detail)


__all__ = [
    "AzureContainerAppsJobBackendConfig",
    "AzureContainerAppsJobExecutionBackend",
    "AzureContainerAppsJobTemplate",
    "ContainerAppsJobTrigger",
]
