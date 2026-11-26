"""Disabled-by-default Azure Container Apps Job execution backend."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from fdai.core.execution_backend.profiles import (
    ExecutionAuthority,
    ExecutionBackendKind,
    ExecutionBackendProfile,
    intersect_execution_profile,
)
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
from fdai.shared.resilience.circuit_breaker import CircuitBreaker, CircuitOpenError

_JOB_ID = re.compile(
    r"^/subscriptions/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    r"/resourceGroups/[a-zA-Z0-9][a-zA-Z0-9._()-]{0,89}/providers/"
    r"Microsoft\.App/jobs/[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}$",
    re.IGNORECASE,
)
_EXECUTION_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
_API_VERSION = "2024-03-01"
_AUDIENCE = "https://management.azure.com/.default"
_IMAGE_DIGEST = re.compile(r"^[^@\s]+@sha256:([0-9a-f]{64})$")
_STATES = {
    "Processing": ExecutionStatus.SUBMITTED,
    "Running": ExecutionStatus.RUNNING,
    "Succeeded": ExecutionStatus.SUCCEEDED,
    "Failed": ExecutionStatus.FAILED,
    "Stopped": ExecutionStatus.CANCELLED,
    "Degraded": ExecutionStatus.AMBIGUOUS,
    "Unknown": ExecutionStatus.AMBIGUOUS,
}


class _RetryableArmError(Exception):
    def __init__(self, retry_after: str) -> None:
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class ContainerAppsJobTemplate:
    """Deployment-owned ARM job and independent sandbox authority."""

    resource_id: str
    authority: ExecutionAuthority
    image_digest: str

    def __post_init__(self) -> None:
        if _JOB_ID.fullmatch(self.resource_id) is None:
            raise ValueError("job template MUST contain an exact ARM Job resource ID")
        if self.authority.backend_kind is not ExecutionBackendKind.AZURE_CONTAINER_APPS_JOB:
            raise ValueError("job template MUST carry Job backend authority")
        if re.fullmatch(r"[0-9a-f]{64}", self.image_digest) is None:
            raise ValueError("job template MUST pin a lowercase image digest")


@dataclass(frozen=True, slots=True)
class ContainerAppsJobConfig:
    endpoint: str = "https://management.azure.com"
    request_timeout_seconds: float = 20.0
    read_attempts: int = 3
    max_retry_after_seconds: float = 5.0

    def __post_init__(self) -> None:
        url = urlsplit(self.endpoint)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or self.endpoint != f"https://{url.netloc}"
        ):
            raise ValueError("Job ARM endpoint MUST be an HTTPS origin")
        if self.request_timeout_seconds <= 0 or self.read_attempts not in range(1, 6):
            raise ValueError("Job request timeout and read attempts MUST be bounded")
        if not 0 <= self.max_retry_after_seconds <= 30:
            raise ValueError("Job Retry-After bound MUST be in [0, 30]")


class AzureContainerAppsJobExecutionBackend:
    """Start only a pre-provisioned, independently bounded, digest-pinned Job.

    The coordinator owns the durable claim. A lost start response is ambiguous;
    this adapter never retries a POST start or invents a provider execution ID.
    Status and stop validate the exact configured job after a process restart.
    """

    backend_kind = ExecutionBackendKind.AZURE_CONTAINER_APPS_JOB

    def __init__(
        self,
        *,
        templates: Mapping[str, ContainerAppsJobTemplate],
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: ContainerAppsJobConfig | None = None,
        circuit: CircuitBreaker | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not templates or len({v.resource_id.lower() for v in templates.values()}) != len(
            templates
        ):
            raise ValueError("Job templates MUST be non-empty and have distinct ARM targets")
        self._templates = dict(templates)
        self._identity = identity
        self._http = http_client
        self._config = config or ContainerAppsJobConfig()
        self._circuit = circuit or CircuitBreaker(name="container-apps-job")
        self._sleep = sleep
        self._plans: dict[str, ExecutionBackendPlan] = {}
        self._plan_templates: dict[str, str] = {}
        self._submitted: set[str] = set()

    def _url(self, resource_id: str) -> str:
        return f"{self._config.endpoint}{resource_id}"

    def _execution(self, ref: str) -> str:
        parsed = urlsplit(ref)
        if (
            parsed.scheme != "https"
            or parsed.netloc != urlsplit(self._config.endpoint).netloc
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
        ):
            raise ExecutionBackendError("Job execution reference has an invalid ARM origin")
        for template in self._templates.values():
            prefix = f"{self._url(template.resource_id)}/executions/"
            if ref.lower().startswith(prefix.lower()) and _EXECUTION_NAME.fullmatch(
                ref[len(prefix) :]
            ):
                return ref
        raise ExecutionBackendError("Job execution reference is outside configured targets")

    async def plan(
        self, request: ExecutionBackendRequest, *, profile: ExecutionBackendProfile
    ) -> ExecutionBackendPlan:
        if request.idempotency_key in self._submitted:
            raise ExecutionBackendError("Job start key was already submitted in this process")
        template = self._templates.get(profile.template_ref or "")
        if (
            template is None
            or profile.backend_kind is not self.backend_kind
            or request.payload is not None
            or request.profile_id != profile.profile_id
            or request.profile_version != profile.version
            or request.workload_id not in profile.workload_ids
            or request.scope_ref not in profile.scope_refs
            or request.region not in profile.regions
            or request.artifact_digest != profile.artifact_digest
            or request.artifact_digest != template.image_digest
        ):
            raise ExecutionBackendError("Job request does not match a server-owned template")
        intersect_execution_profile(template.authority, profile)
        await self._verify_template(template.resource_id, request.artifact_digest)
        plan = ExecutionBackendPlan(
            plan_ref=request.idempotency_key,
            backend_kind=self.backend_kind.value,
            request=request,
            created_at=datetime.now(UTC),
        )
        previous = self._plans.setdefault(plan.plan_ref, plan)
        if previous.request != plan.request:
            raise ExecutionBackendError("Job idempotency key belongs to a different request")
        self._plan_templates[plan.plan_ref] = profile.template_ref or ""
        return previous

    async def submit(self, plan: ExecutionBackendPlan) -> ExecutionBackendReceipt:
        if self._plans.get(plan.plan_ref) != plan:
            raise ExecutionBackendError("Job start requires an exact locally verified plan")
        template_ref = self._plan_templates.get(plan.plan_ref)
        if template_ref is None:
            raise ExecutionBackendError("Job plan lost its server-owned template")
        job_id = self._templates[template_ref].resource_id
        if plan.plan_ref in self._submitted:
            raise ExecutionBackendError("Job start key was already submitted in this process")
        await self._verify_template(job_id, plan.request.artifact_digest)
        self._submitted.add(plan.plan_ref)
        response = await self._request("POST", f"{self._url(job_id)}/start", body={})
        if response.status_code != 200:
            raise ExecutionBackendError("Job start acceptance has no execution reference")
        payload = _object(response)
        name = payload.get("name")
        if not isinstance(name, str) or not _EXECUTION_NAME.fullmatch(name):
            raise ExecutionBackendError("Job start returned no valid execution name")
        ref = self._execution(f"{self._url(job_id)}/executions/{name}")
        if "id" in payload and (
            not isinstance(payload["id"], str)
            or payload["id"].lower() != urlsplit(ref).path.lower()
        ):
            raise ExecutionBackendError("Job start returned a different execution target")
        self._plans.pop(plan.plan_ref, None)
        self._plan_templates.pop(plan.plan_ref, None)
        return ExecutionBackendReceipt(
            status=ExecutionStatus.SUBMITTED,
            submission_ref=ref,
            receipt_ref=ref,
            detail="Container Apps Job accepted; effect not yet verified",
        )

    async def status(self, submission_ref: str) -> ExecutionBackendReceipt:
        ref = self._execution(submission_ref)
        payload = _object(await self._request("GET", ref))
        if payload.get("name") != ref.rsplit("/", 1)[-1]:
            raise ExecutionBackendError("Job execution status identity does not match")
        if "id" in payload and (
            not isinstance(payload["id"], str)
            or payload["id"].lower() != urlsplit(ref).path.lower()
        ):
            raise ExecutionBackendError("Job execution status target does not match")
        properties = payload.get("properties")
        state = properties.get("status") if isinstance(properties, dict) else None
        if not isinstance(state, str) or state not in _STATES:
            raise ExecutionBackendError("Job execution status is missing or unrecognized")
        job_id = urlsplit(ref).path.rsplit("/executions/", 1)[0]
        template = next(
            item for item in self._templates.values() if item.resource_id.lower() == job_id.lower()
        )
        _check_images(
            properties.get("template") if isinstance(properties, dict) else None,
            template.image_digest,
        )
        return ExecutionBackendReceipt(
            status=_STATES[state],
            submission_ref=ref,
            receipt_ref=ref,
            detail=f"Container Apps Job state: {state}",
        )

    async def cancel(self, submission_ref: str) -> ExecutionBackendReceipt:
        ref = self._execution(submission_ref)
        before = await self.status(ref)
        if before.status.terminal:
            return before
        await self._request("POST", f"{ref}/stop", body={})
        return await self.status(ref)

    async def collect_receipt(self, submission_ref: str) -> ExecutionBackendReceipt:
        return await self.status(submission_ref)

    async def cleanup(self, submission_ref: str) -> ExecutionCleanupResult:
        if not (await self.status(submission_ref)).status.terminal:
            raise ExecutionBackendError("Job cleanup requires authoritative terminal state")
        return ExecutionCleanupResult(
            state=ExecutionCleanupState.PROVIDER_RETENTION,
            detail="Container Apps retains the execution record under provider policy",
        )

    async def capabilities(self) -> ExecutionBackendCapabilities:
        return ExecutionBackendCapabilities(self.backend_kind.value, True, True, True, True, True)

    async def health(self) -> ExecutionBackendHealth:
        try:
            for template in self._templates.values():
                await self._verify_template(template.resource_id, template.image_digest)
        except (ExecutionBackendError, CircuitOpenError):
            return ExecutionBackendHealth(
                state=ExecutionHealthState.UNAVAILABLE,
                checked_at=datetime.now(UTC),
                detail="Job ARM read is unavailable",
            )
        return ExecutionBackendHealth(
            state=ExecutionHealthState.HEALTHY,
            checked_at=datetime.now(UTC),
            detail="Job ARM read is reachable; no execution authority granted",
        )

    async def _verify_template(self, resource_id: str, digest: str) -> None:
        payload = _object(await self._request("GET", self._url(resource_id)))
        identity = payload.get("id")
        if not isinstance(identity, str) or identity.lower() != resource_id.lower():
            raise ExecutionBackendError("Job definition identity does not match the target")
        properties = payload.get("properties")
        definition = properties.get("template") if isinstance(properties, dict) else None
        _check_images(definition, digest)

    async def _request(
        self, method: str, url: str, *, body: dict[str, object] | None = None
    ) -> httpx.Response:
        attempts = self._config.read_attempts if method == "GET" else 1
        for attempt in range(attempts):
            try:
                response = await self._circuit.call(self._send, method, url, body)
            except _RetryableArmError as exc:
                if method != "GET" or attempt + 1 == attempts:
                    raise ExecutionBackendError(
                        "Job ARM request was throttled or unavailable"
                    ) from None
                delay = exc.retry_after
                seconds = (
                    min(int(delay), self._config.max_retry_after_seconds)
                    if delay.isascii() and delay.isdecimal() and len(delay) <= 3
                    else self._config.max_retry_after_seconds
                )
                await self._sleep(seconds)
                continue
            except CircuitOpenError as exc:
                raise ExecutionBackendError("Job ARM circuit is open") from exc
            except httpx.HTTPError as exc:
                raise ExecutionBackendError("Job ARM transport is unavailable") from exc
            if response.status_code not in ({200} if method == "GET" else {200, 202}):
                raise ExecutionBackendError(f"Job ARM request failed ({response.status_code})")
            return response
        raise ExecutionBackendError("Job ARM read retry budget exhausted")

    async def _send(self, method: str, url: str, body: dict[str, object] | None) -> httpx.Response:
        try:
            token = await self._identity.get_token(_AUDIENCE)
        except Exception as exc:  # noqa: BLE001 - identity boundary fails closed
            raise ExecutionBackendError("Job ARM workload identity is unavailable") from exc
        if (
            token.audience != _AUDIENCE
            or not token.token
            or token.expires_at.tzinfo is None
            or token.expires_at <= datetime.now(UTC)
        ):
            raise ExecutionBackendError("Job ARM workload identity token is invalid")
        response = await self._http.request(
            method,
            url,
            params={"api-version": _API_VERSION},
            headers={"Authorization": f"Bearer {token.token}"},
            json=body,
            timeout=self._config.request_timeout_seconds,
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableArmError(response.headers.get("Retry-After", ""))
        return response


def _check_images(definition: object, digest: str) -> None:
    containers = definition.get("containers") if isinstance(definition, dict) else None
    init = definition.get("initContainers", []) if isinstance(definition, dict) else []
    if not isinstance(containers, list) or not containers or not isinstance(init, list):
        raise ExecutionBackendError("Job definition has no valid container template")
    images: list[str] = []
    for container in (*containers, *init):
        image = container.get("image") if isinstance(container, dict) else None
        match = _IMAGE_DIGEST.fullmatch(image) if isinstance(image, str) else None
        if match is None:
            raise ExecutionBackendError("Job definition contains an unpinned container image")
        images.append(match.group(1))
    if any(image_digest != digest for image_digest in images):
        raise ExecutionBackendError("Job definition image does not match profile digest")


def _object(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ExecutionBackendError("Job ARM response is not JSON") from exc
    if not isinstance(payload, dict):
        raise ExecutionBackendError("Job ARM response is not an object")
    return payload


__all__ = [
    "AzureContainerAppsJobExecutionBackend",
    "ContainerAppsJobConfig",
    "ContainerAppsJobTemplate",
]
