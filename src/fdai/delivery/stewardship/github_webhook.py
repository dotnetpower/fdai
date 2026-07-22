"""Signed GitHub merge webhook for stewardship governance changes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Final

import httpx

from fdai.delivery.stewardship.governance import (
    StewardshipGovernanceService,
    StewardshipMerge,
)

_TARGET_FILE: Final = "config/agent-stewardship.yaml"


@dataclass(frozen=True, slots=True)
class GitHubStewardshipWebhookConfig:
    repository: str
    webhook_secret: str
    token: str
    api_base: str = "https://api.github.com"
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.repository.count("/") != 1:
            raise ValueError("repository MUST be 'owner/name'")
        if len(self.webhook_secret) < 32:
            raise ValueError("webhook_secret MUST contain at least 32 characters")
        if not self.token.strip():
            raise ValueError("token MUST be non-empty")
        if not self.api_base.startswith("https://"):
            raise ValueError("api_base MUST use https://")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be positive")


@dataclass(frozen=True, slots=True)
class GitHubWebhookResult:
    accepted: bool
    reason: str
    changed: bool = False


class GitHubStewardshipWebhook:
    """Verify and consume one GitHub pull-request merge delivery."""

    def __init__(
        self,
        *,
        config: GitHubStewardshipWebhookConfig,
        http_client: httpx.AsyncClient,
        governance: StewardshipGovernanceService,
    ) -> None:
        self._config = config
        self._http = http_client
        self._governance = governance

    async def handle(
        self,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> GitHubWebhookResult:
        signature = headers.get("x-hub-signature-256", "")
        expected = (
            "sha256="
            + hmac.new(
                self._config.webhook_secret.encode("utf-8"),
                body,
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(signature, expected):
            return GitHubWebhookResult(False, "invalid signature")
        if headers.get("x-github-event", "") != "pull_request":
            return GitHubWebhookResult(True, "event ignored")
        delivery_id = headers.get("x-github-delivery", "").strip()
        if not delivery_id:
            return GitHubWebhookResult(False, "delivery id missing")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return GitHubWebhookResult(False, "invalid JSON")
        if not isinstance(payload, dict):
            return GitHubWebhookResult(False, "payload is not an object")
        repository = payload.get("repository")
        pull_request = payload.get("pull_request")
        if (
            not isinstance(repository, dict)
            or repository.get("full_name") != self._config.repository
            or not isinstance(pull_request, dict)
        ):
            return GitHubWebhookResult(False, "repository mismatch")
        if payload.get("action") != "closed" or pull_request.get("merged") is not True:
            return GitHubWebhookResult(True, "pull request not merged")
        number = payload.get("number")
        merge_sha = pull_request.get("merge_commit_sha")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            return GitHubWebhookResult(False, "pull request number invalid")
        if not isinstance(merge_sha, str) or not merge_sha:
            return GitHubWebhookResult(False, "merge commit missing")
        if not await self._target_file_changed(number):
            return GitHubWebhookResult(True, "stewardship file unchanged")
        merged_yaml = await self._merged_content(merge_sha)
        merged_by = pull_request.get("merged_by")
        login = merged_by.get("login") if isinstance(merged_by, dict) else None
        actor = f"github:{login}" if isinstance(login, str) and login else "github:unknown"
        changed = await self._governance.record_merge(
            StewardshipMerge(
                delivery_id=delivery_id,
                pr_ref=f"{self._config.repository}#{number}",
                actor_identity=actor,
                merged_yaml=merged_yaml,
            )
        )
        return GitHubWebhookResult(True, "merge recorded", changed=changed)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _target_file_changed(self, number: int) -> bool:
        base_url = (
            f"{self._config.api_base.rstrip('/')}/repos/"
            f"{self._config.repository}/pulls/{number}/files"
        )
        for page in range(1, 31):
            payload = await self._get_json(f"{base_url}?per_page=100&page={page}")
            if not isinstance(payload, list):
                raise RuntimeError("GitHub pull-request files response MUST be a list")
            if any(
                isinstance(item, dict) and item.get("filename") == _TARGET_FILE for item in payload
            ):
                return True
            if len(payload) < 100:
                return False
        raise RuntimeError("GitHub pull-request files exceeded the 3000-file verification limit")

    async def _merged_content(self, merge_sha: str) -> str:
        url = (
            f"{self._config.api_base.rstrip('/')}/repos/{self._config.repository}/contents/"
            f"{_TARGET_FILE}?ref={merge_sha}"
        )
        payload = await self._get_json(url)
        if not isinstance(payload, dict) or payload.get("encoding") != "base64":
            raise RuntimeError("GitHub stewardship content response is malformed")
        content = payload.get("content")
        if not isinstance(content, str):
            raise RuntimeError("GitHub stewardship content is missing")
        try:
            compact_content = "".join(content.split())
            return base64.b64decode(compact_content, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("GitHub stewardship content is not valid UTF-8 base64") from exc

    async def _get_json(self, url: str) -> object:
        response = await self._http.get(
            url,
            headers=self._headers(),
            timeout=self._config.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()


__all__ = [
    "GitHubStewardshipWebhook",
    "GitHubStewardshipWebhookConfig",
    "GitHubWebhookResult",
]
