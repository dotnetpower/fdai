"""GitHub-backed tools for self-debug, release, and security workflows."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import httpx

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import RemediationPr, RemediationPrPublisher
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
    ToolError,
    ToolPreconditionError,
    ToolPromotionError,
)

_PR_ACTIONS: Final[frozenset[str]] = frozenset({"tool.open-fix-pr", "tool.request-release"})
_SECURITY_ACTION: Final[str] = "tool.file-security-followup"
_IRP_ACTION: Final[str] = "tool.file-irp-followup"
_INCIDENT_ACTION: Final[str] = "tool.open-incident-ticket"
_ALL_ACTIONS: Final[frozenset[str]] = _PR_ACTIONS | {
    _SECURITY_ACTION,
    _IRP_ACTION,
    _INCIDENT_ACTION,
}


@dataclass(frozen=True, slots=True)
class GitHubWorkflowToolConfig:
    owner: str
    repo: str
    api_base: str = "https://api.github.com"
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not self.owner or not self.repo:
            raise ValueError("owner and repo MUST be non-empty")
        if not self.api_base.startswith("https://"):
            raise ValueError("api_base MUST use https://")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be positive")


class GitHubWorkflowToolExecutor:
    """Execute the three shipped SRE workflow tool ActionTypes."""

    def __init__(
        self,
        *,
        config: GitHubWorkflowToolConfig,
        publisher: RemediationPrPublisher,
        http_client: httpx.AsyncClient,
        token: str,
    ) -> None:
        if not token.strip():
            raise ValueError("token MUST NOT be empty")
        self._config = config
        self._publisher = publisher
        self._http = http_client
        self._token = token

    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt:
        if request.action_type_name not in _ALL_ACTIONS:
            raise ToolError("unknown_tool", f"unsupported GitHub tool {request.action_type_name!r}")
        if request.mode is Mode.SHADOW:
            return ToolCallReceipt(
                outcome=ToolCallOutcome.SUCCEEDED,
                receipt_ref=f"planned:{request.action_type_name}:{_fingerprint(request.idempotency_key)}",
                detail="shadow plan recorded; no GitHub artifact created",
            )
        if "enforce" not in request.labels:
            raise ToolPromotionError("GitHub workflow tool enforce requires the enforce label")
        if request.action_type_name in _PR_ACTIONS:
            return await self._publish_pr(request)
        return await self._file_followup_issue(request)

    async def _publish_pr(self, request: ToolCallRequest) -> ToolCallReceipt:
        values = _required_strings(request.arguments, _required_fields(request.action_type_name))
        fingerprint = _fingerprint(request.idempotency_key)
        artifact_kind = "fix" if request.action_type_name == "tool.open-fix-pr" else "release"
        title = (
            f"fix: review FDAI defect {values['target_ref']}"
            if artifact_kind == "fix"
            else f"chore(release): request {values['release_ref']} for {values['environment']}"
        )
        manifest = {
            "schema_version": "1.0.0",
            "action_type": request.action_type_name,
            "idempotency_key": request.idempotency_key,
            "requested_by_rules": list(request.rule_ids),
            "arguments": values,
            "mode": request.mode.value,
        }
        body = (
            "This draft pull request records a governed FDAI workflow request.\n\n"
            f"- ActionType: `{request.action_type_name}`\n"
            f"- Tool target: `{request.tool_ref}`\n"
            f"- Rollback: close this draft without merging\n"
        )
        receipt = await self._publisher.publish(
            RemediationPr(
                action_id=request.action_id,
                idempotency_key=request.idempotency_key,
                rule_ids=request.rule_ids,
                title=title,
                body=body,
                patch=json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                patch_path=f"delivery/{artifact_kind}-requests/{fingerprint}.json",
                labels=tuple(sorted(set(request.labels) | {"fdai-workflow"})),
                mode=request.mode,
            )
        )
        return ToolCallReceipt(
            outcome=(
                ToolCallOutcome.ALREADY_APPLIED
                if receipt.already_existed
                else ToolCallOutcome.SUCCEEDED
            ),
            receipt_ref=receipt.pr_ref,
            already_existed=receipt.already_existed,
            detail=receipt.url,
        )

    async def _file_followup_issue(self, request: ToolCallRequest) -> ToolCallReceipt:
        if request.action_type_name == _SECURITY_ACTION:
            values = _required_strings(request.arguments, ("finding_ref", "severity", "reason"))
            title = f"security: follow up {values['finding_ref']} ({values['severity']})"
            detail = (
                f"Finding: `{values['finding_ref']}`\n\n"
                f"Severity: `{values['severity']}`\n\n"
                f"Reason: {values['reason']}\n"
            )
            labels = ["security", "fdai-followup"]
        elif request.action_type_name == _IRP_ACTION:
            values = _required_strings(
                request.arguments,
                ("alert_id", "remediation_ref", "resource_ref", "priority", "detail"),
            )
            title = f"ops: IRP follow-up {values['alert_id']} ({values['priority']})"
            detail = (
                f"Alert: `{values['alert_id']}`\n\n"
                f"Resource: `{values['resource_ref']}`\n\n"
                f"Recommended remediation: `{values['remediation_ref']}`\n\n"
                f"Detail: {values['detail']}\n"
            )
            labels = ["incident", "fdai-irp", "fdai-followup"]
        else:
            values = _required_strings(
                request.arguments, ("incident_id", "ticket_provider", "summary")
            )
            if values["ticket_provider"] != "github":
                raise ToolPreconditionError("GitHub tool requires ticket_provider='github'")
            title = f"incident: {values['summary']}"
            description = request.arguments.get("description")
            detail = f"Incident: `{values['incident_id']}`\n\nSummary: {values['summary']}\n\n" + (
                f"Description: {description}\n" if isinstance(description, str) else ""
            )
            labels = ["incident", "fdai-followup"]
        marker = f"<!-- fdai-idempotency:{request.idempotency_key} -->"
        existing = await self._find_issue(marker)
        if existing is not None:
            return ToolCallReceipt(
                outcome=ToolCallOutcome.ALREADY_APPLIED,
                receipt_ref=existing[0],
                already_existed=True,
                detail=existing[1],
            )
        body = f"{marker}\n\n{detail}"
        payload = await self._post(
            f"/repos/{self._config.owner}/{self._config.repo}/issues",
            {"title": title, "body": body, "labels": labels},
        )
        number = payload.get("number")
        if not isinstance(number, int):
            raise ToolError("provider", "GitHub issue response omitted number")
        return ToolCallReceipt(
            outcome=ToolCallOutcome.SUCCEEDED,
            receipt_ref=f"{self._config.owner}/{self._config.repo}#{number}",
            detail=str(payload.get("html_url") or "") or None,
        )

    async def _find_issue(self, marker: str) -> tuple[str, str | None] | None:
        payload = await self._get(
            f"/repos/{self._config.owner}/{self._config.repo}/issues"
            "?state=all&labels=fdai-followup&per_page=100"
        )
        if not isinstance(payload, list):
            raise ToolError("provider", "GitHub issues response MUST be an array")
        for item in payload:
            if not isinstance(item, Mapping) or marker not in str(item.get("body") or ""):
                continue
            number = item.get("number")
            if isinstance(number, int):
                return (
                    f"{self._config.owner}/{self._config.repo}#{number}",
                    str(item.get("html_url")) if item.get("html_url") else None,
                )
        return None

    async def _get(self, path: str) -> Any:
        return await self._request("GET", path)

    async def _post(self, path: str, body: Mapping[str, object]) -> Mapping[str, Any]:
        payload = await self._request("POST", path, body=body)
        if not isinstance(payload, Mapping):
            raise ToolError("provider", "GitHub response MUST be an object")
        return payload

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, object] | None = None,
    ) -> Any:
        url = f"{self._config.api_base.rstrip('/')}{path}"
        try:
            response = await self._http.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                content=json.dumps(body) if body is not None else None,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ToolError("provider", f"GitHub request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise ToolError("provider", f"GitHub returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ToolError("provider", "GitHub returned non-JSON") from exc


def _required_fields(action_type: str) -> tuple[str, ...]:
    if action_type == "tool.open-fix-pr":
        return ("target_ref", "defect_kind", "reason")
    return ("release_ref", "environment", "reason")


def _required_strings(arguments: Mapping[str, object], fields: tuple[str, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in fields:
        value = arguments.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ToolPreconditionError(f"{field} MUST be a non-empty string")
        values[field] = value.strip()
    return values


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:20]


__all__ = ["GitHubWorkflowToolConfig", "GitHubWorkflowToolExecutor"]
