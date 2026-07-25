"""GitHub Actions transport for plan-only FDAI deployment workflow dispatch."""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlparse

import httpx

from fdai.deployment_cli.remote import (
    DeploymentPlanContext,
    DeploymentPlanRecord,
    DeploymentSubmission,
    PlanStatus,
    RemoteDeploymentError,
    deployment_context_digest,
)

_API_VERSION: Final[str] = "2026-03-10"
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_REF = re.compile(r"^[A-Za-z0-9_./-]{1,200}$")
_PLAN_ID = re.compile(r"^plan-([1-9][0-9]*)-([1-9][0-9]*)$")
_MAX_ARCHIVE_BYTES: Final[int] = 1024 * 1024
_MAX_METADATA_BYTES: Final[int] = 64 * 1024

TokenProvider = Callable[[], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class GitHubDeploymentWorkflowConfig:
    repository: str
    workflow_id: str = "deploy-dev.yml"
    ref: str = "main"
    api_base: str = "https://api.github.com"
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        parts = self.repository.split("/")
        if len(parts) != 2 or any(_NAME.fullmatch(part) is None for part in parts):
            raise ValueError("repository MUST be a bounded owner/name")
        if _NAME.fullmatch(self.workflow_id) is None:
            raise ValueError("workflow_id MUST be a bounded workflow file name")
        if _REF.fullmatch(self.ref) is None or ".." in self.ref:
            raise ValueError("ref MUST be a bounded branch or tag name")
        parsed = urlparse(self.api_base)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("api_base MUST be an absolute HTTPS origin")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be positive")


class GitHubActionsDeploymentTransport:
    """Submit plan-only work; exact-plan retrieval and apply remain unavailable."""

    def __init__(
        self,
        *,
        config: GitHubDeploymentWorkflowConfig,
        http_client: httpx.AsyncClient,
        token_provider: TokenProvider,
    ) -> None:
        self._config = config
        self._http = http_client
        self._token_provider = token_provider

    async def submit_plan(self, context: DeploymentPlanContext) -> DeploymentSubmission:
        context_digest = deployment_context_digest(context)
        payload = await self._dispatch(
            {
                "ref": self._config.ref,
                "inputs": {
                    "environment": context.environment,
                    "apply": False,
                    "request_id": f"plan-{context_digest[:24]}",
                    "context_digest": context_digest,
                    "commit_sha": context.commit_sha,
                },
            }
        )
        return _submission(payload)

    async def get_plan(self, plan_id: str) -> DeploymentPlanRecord:
        match = _PLAN_ID.fullmatch(plan_id)
        if match is None:
            raise RemoteDeploymentError("plan_id is invalid")
        run_id = match.group(1)
        artifact_name = f"deployment-plan-{plan_id}"
        payload = await self._get_json(
            f"/repos/{self._config.repository}/actions/runs/{run_id}/artifacts",
            params={"name": artifact_name, "per_page": "2"},
        )
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            raise RemoteDeploymentError("GitHub plan artifact list is malformed")
        matching = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, dict) and artifact.get("name") == artifact_name
        ]
        if len(matching) != 1:
            raise RemoteDeploymentError("GitHub plan metadata artifact is missing or ambiguous")
        artifact = matching[0]
        if artifact.get("expired") is True:
            raise RemoteDeploymentError("GitHub plan metadata artifact has expired")
        artifact_id = artifact.get("id")
        if not isinstance(artifact_id, int):
            raise RemoteDeploymentError("GitHub plan metadata artifact id is invalid")
        metadata = await self._download_metadata(artifact_id)
        record = _plan_record(
            metadata,
            expected_plan_id=plan_id,
            repository=self._config.repository,
        )
        apply_status = await self._apply_status(plan_id)
        return replace(record, status=apply_status or record.status)

    async def submit_apply(
        self,
        *,
        plan_id: str,
        plan_digest: str,
        context: DeploymentPlanContext,
    ) -> DeploymentSubmission:
        context_digest = deployment_context_digest(context)
        payload = await self._dispatch(
            {
                "ref": self._config.ref,
                "inputs": {
                    "environment": context.environment,
                    "apply": True,
                    "request_id": f"apply-{context_digest[:24]}",
                    "context_digest": context_digest,
                    "commit_sha": context.commit_sha,
                    "plan_id": plan_id,
                    "plan_digest": plan_digest,
                },
            }
        )
        return _submission(payload)

    async def _dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        token = await self._token_provider()
        if not token.strip():
            raise RemoteDeploymentError("GitHub workflow token is unavailable")
        url = (
            f"{self._config.api_base.rstrip('/')}/repos/{self._config.repository}"
            f"/actions/workflows/{self._config.workflow_id}/dispatches"
        )
        try:
            response = await self._http.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": _API_VERSION,
                },
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise RemoteDeploymentError("GitHub workflow dispatch request failed") from exc
        if response.status_code != 200:
            raise RemoteDeploymentError(
                f"GitHub workflow dispatch returned HTTP {response.status_code}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise RemoteDeploymentError("GitHub workflow dispatch returned non-JSON") from exc
        if not isinstance(body, dict):
            raise RemoteDeploymentError("GitHub workflow dispatch payload is not an object")
        return body

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        token = await self._token_provider()
        if not token.strip():
            raise RemoteDeploymentError("GitHub workflow token is unavailable")
        try:
            response = await self._http.get(
                f"{self._config.api_base.rstrip('/')}{path}",
                params=params,
                headers=_headers(token),
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise RemoteDeploymentError("GitHub plan metadata request failed") from exc
        if response.status_code != 200:
            raise RemoteDeploymentError(
                f"GitHub plan metadata request returned HTTP {response.status_code}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise RemoteDeploymentError("GitHub plan metadata response is non-JSON") from exc
        if not isinstance(body, dict):
            raise RemoteDeploymentError("GitHub plan metadata response is not an object")
        return body

    async def _download_metadata(self, artifact_id: int) -> dict[str, Any]:
        token = await self._token_provider()
        url = (
            f"{self._config.api_base.rstrip('/')}/repos/{self._config.repository}"
            f"/actions/artifacts/{artifact_id}/zip"
        )
        try:
            response = await self._http.get(
                url,
                headers=_headers(token),
                timeout=self._config.timeout_seconds,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise RemoteDeploymentError("GitHub plan artifact download failed") from exc
        if response.status_code != 200:
            raise RemoteDeploymentError(
                f"GitHub plan artifact download returned HTTP {response.status_code}"
            )
        if len(response.content) > _MAX_ARCHIVE_BYTES:
            raise RemoteDeploymentError("GitHub plan metadata archive exceeds the size limit")
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = archive.namelist()
                if names != ["plan-metadata.json"]:
                    raise RemoteDeploymentError(
                        "GitHub plan metadata archive has an unexpected file set"
                    )
                info = archive.getinfo("plan-metadata.json")
                if info.file_size > _MAX_METADATA_BYTES:
                    raise RemoteDeploymentError("GitHub plan metadata exceeds the size limit")
                raw = archive.read(info)
        except zipfile.BadZipFile as exc:
            raise RemoteDeploymentError("GitHub plan metadata archive is invalid") from exc
        try:
            metadata = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteDeploymentError("GitHub plan metadata is invalid JSON") from exc
        if not isinstance(metadata, dict):
            raise RemoteDeploymentError("GitHub plan metadata is not an object")
        return metadata

    async def _apply_status(self, plan_id: str) -> PlanStatus | None:
        if await self._has_active_artifact(f"deployment-apply-receipt-{plan_id}"):
            return PlanStatus.APPLIED
        if await self._has_active_artifact(f"deployment-apply-claim-{plan_id}"):
            return PlanStatus.APPLYING
        return None

    async def _has_active_artifact(self, name: str) -> bool:
        payload = await self._get_json(
            f"/repos/{self._config.repository}/actions/artifacts",
            params={"name": name, "per_page": "2"},
        )
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            raise RemoteDeploymentError("GitHub apply status artifact list is malformed")
        active = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, dict)
            and artifact.get("name") == name
            and artifact.get("expired") is not True
        ]
        if len(active) > 1:
            raise RemoteDeploymentError("GitHub apply status artifact is ambiguous")
        return len(active) == 1


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _API_VERSION,
    }


def _submission(payload: dict[str, Any]) -> DeploymentSubmission:
    run_id = payload.get("workflow_run_id")
    workflow_url = payload.get("html_url")
    if not isinstance(run_id, int) or not isinstance(workflow_url, str) or not workflow_url:
        raise RemoteDeploymentError("GitHub workflow dispatch returned incomplete run details")
    return DeploymentSubmission(submission_id=str(run_id), workflow_url=workflow_url)


def _plan_record(
    metadata: dict[str, Any],
    *,
    expected_plan_id: str,
    repository: str,
) -> DeploymentPlanRecord:
    if metadata.get("schema_version") != "fdai.deployment-plan.v1":
        raise RemoteDeploymentError("GitHub plan metadata schema is unsupported")
    if metadata.get("plan_id") != expected_plan_id:
        raise RemoteDeploymentError("GitHub plan metadata id does not match the request")
    run_id = metadata.get("workflow_run_id")
    if not isinstance(run_id, str) or not run_id.isdigit():
        raise RemoteDeploymentError("GitHub plan metadata workflow run id is invalid")
    try:
        created_at = _timestamp(metadata.get("created_at"))
        expires_at = _timestamp(metadata.get("expires_at"))
        status = PlanStatus(str(metadata.get("status")))
        return DeploymentPlanRecord(
            plan_id=expected_plan_id,
            plan_digest=str(metadata.get("plan_digest")),
            context=None,
            context_digest=str(metadata.get("context_digest")),
            created_at=created_at,
            expires_at=expires_at,
            status=status,
            workflow_url=f"https://github.com/{repository}/actions/runs/{run_id}",
        )
    except (TypeError, ValueError) as exc:
        raise RemoteDeploymentError("GitHub plan metadata fields are invalid") from exc


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp MUST be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp MUST include a timezone")
    return parsed.astimezone(UTC)


__all__ = [
    "GitHubActionsDeploymentTransport",
    "GitHubDeploymentWorkflowConfig",
    "TokenProvider",
]
