"""Sanitized GitHub Checks delivery for an existing remediation pull request.

This is presentation only. It never creates a PR, approves a change, or treats
a Check as pre-publication evidence. A failed or ambiguous API call raises a
content-free error and must not be interpreted as a successful Check.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from fdai.core.deploy_preflight.report import ReadinessVerdict
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.preflight_check import (
    PreflightCheck,
    PreflightCheckPublishError,
    PreflightCheckReceipt,
)

_PR_NUMBER = re.compile(r"[1-9][0-9]*\Z")
_SHA = re.compile(r"[a-fA-F0-9]{40}\Z")


@dataclass(frozen=True, slots=True)
class GitHubPreflightChecksConfig:
    owner: str
    repo: str
    api_base: str = "https://api.github.com"
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if (
            not self.owner
            or not self.repo
            or len(self.owner) > 100
            or len(self.repo) > 100
            or not self.owner.isascii()
            or not self.repo.isascii()
        ):
            raise ValueError("Checks repository identity is invalid")
        endpoint = urlsplit(self.api_base)
        if (
            endpoint.scheme != "https"
            or not endpoint.hostname
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
            or not self.api_base.isascii()
            or len(self.api_base) > 2048
        ):
            raise ValueError("Checks API requires an HTTPS endpoint")
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("Checks timeout must be positive and bounded")


class GitHubPreflightCheckPublisher:
    """Implement the existing PreflightCheckPublisher seam with injected HTTP."""

    def __init__(
        self,
        *,
        config: GitHubPreflightChecksConfig,
        http_client: httpx.AsyncClient,
        token_provider: Callable[[], Awaitable[str]],
    ) -> None:
        self._config = config
        self._http = http_client
        self._token_provider = token_provider
        self._lock = asyncio.Lock()

    async def publish(self, check: PreflightCheck) -> PreflightCheckReceipt:
        """Resolve the exact PR head and post one idempotent, sanitized Check."""

        async with self._lock:
            return await self._publish(check)

    async def _publish(self, check: PreflightCheck) -> PreflightCheckReceipt:
        marker = f"{self._config.owner}/{self._config.repo}#"
        number = check.pr_ref.removeprefix(marker)
        if (
            not check.pr_ref.startswith(marker)
            or len(check.pr_ref) > 256
            or _PR_NUMBER.fullmatch(number) is None
        ):
            raise PreflightCheckPublishError("preflight Check PR reference is invalid")
        if not check.check_key or len(check.check_key) > 512:
            raise PreflightCheckPublishError("preflight Check key is invalid")
        report = check.report
        if (report.verdict is ReadinessVerdict.CLEAR) != (not report.findings):
            raise PreflightCheckPublishError("preflight Check report is inconsistent")
        if (report.verdict is ReadinessVerdict.BLOCKED) != bool(report.blocking_findings):
            raise PreflightCheckPublishError("preflight Check report is inconsistent")
        key_digest = hashlib.sha256(f"{check.pr_ref}\0{check.check_key}".encode()).hexdigest()
        name = f"fdai/preflight/{key_digest[:24]}"
        report_digest = hashlib.sha256(
            json.dumps(report.to_dict(), sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        digest = hashlib.sha256(f"{key_digest}\0{report_digest}".encode()).hexdigest()
        conclusion = (
            "neutral"
            if report.mode is Mode.SHADOW
            else "failure"
            if report.blocking_findings
            else "action_required"
            if report.verdict is ReadinessVerdict.NEEDS_REVIEW
            else "success"
        )
        base = (
            f"{self._config.api_base.rstrip('/')}/repos/"
            f"{quote(self._config.owner, safe='')}/{quote(self._config.repo, safe='')}"
        )
        pr = await self._request("GET", f"{base}/pulls/{number}")
        head = pr.get("head") if isinstance(pr, dict) else None
        sha = head.get("sha") if isinstance(head, dict) else None
        if not isinstance(sha, str) or _SHA.fullmatch(sha) is None:
            raise PreflightCheckPublishError("preflight Check head revision is unavailable")
        checks = await self._request(
            "GET",
            f"{base}/commits/{sha}/check-runs",
            params={"check_name": name, "per_page": "2"},
        )
        if not isinstance(checks, dict) or checks.get("total_count") != 0:
            if (
                isinstance(checks, dict)
                and checks.get("total_count") == 1
                and isinstance(checks.get("check_runs"), list)
                and len(checks["check_runs"]) == 1
            ):
                previous = checks["check_runs"][0]
                if (
                    isinstance(previous, dict)
                    and previous.get("external_id") == digest
                    and previous.get("head_sha") == sha
                    and previous.get("status") == "completed"
                    and previous.get("conclusion") == conclusion
                    and type(previous.get("id")) is int
                    and previous["id"] > 0
                ):
                    return PreflightCheckReceipt(
                        check_ref=f"github-check:{previous['id']}", already_existed=True
                    )
            raise PreflightCheckPublishError("preflight Check state is unavailable")
        if checks.get("check_runs") != []:
            raise PreflightCheckPublishError("preflight Check listing is incomplete")

        payload = {
            "name": name,
            "head_sha": sha,
            "external_id": digest,
            "status": "completed",
            "conclusion": conclusion,
            "output": {
                "title": "Deployment preflight",
                "summary": (
                    f"Decision: {report.verdict.value}. Mode: {report.mode.value}. "
                    f"Findings: {min(len(report.findings), 1000)}"
                    f"{'+' if len(report.findings) > 1000 else ''}. "
                    f"Checked categories: {len(set(report.checked_categories))}."
                ),
            },
        }
        result = await self._request("POST", f"{base}/check-runs", json=payload)
        if (
            not isinstance(result, dict)
            or type(result.get("id")) is not int
            or result["id"] <= 0
            or result.get("head_sha") != sha
            or result.get("external_id") != digest
        ):
            raise PreflightCheckPublishError("preflight Check receipt is unavailable")
        return PreflightCheckReceipt(check_ref=f"github-check:{result['id']}")

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            token = (await self._token_provider()).strip()
            if not token:
                raise ValueError("empty token")
            response = await self._http.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=self._config.timeout_seconds,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            raise PreflightCheckPublishError("preflight Checks adapter unavailable") from None


__all__ = ["GitHubPreflightCheckPublisher", "GitHubPreflightChecksConfig"]
