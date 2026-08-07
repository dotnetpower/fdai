"""Signed GitHub merge webhook and durable stewardship merge recording."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import psycopg
from fdai_service_contracts import (
    RepositoryHandoverDraft,
    RepositoryHandoverDraftRecorder,
    StewardshipMergeRecord,
    StewardshipMergeRecorder,
)

from fdai_ingestion_api_service.providers import StewardshipWebhookResult

_TARGET_FILE = "config/agent-stewardship.yaml"


@dataclass(frozen=True, slots=True)
class GitHubStewardshipWebhookConfig:
    repository: str
    webhook_secret: str
    token: str
    api_base: str = "https://api.github.com"
    timeout_seconds: float = 15.0
    max_file_pages: int = 30

    def __post_init__(self) -> None:
        parsed = urlparse(self.api_base)
        if self.repository.count("/") != 1:
            raise ValueError("GitHub repository MUST be 'owner/name'")
        if len(self.webhook_secret) < 32:
            raise ValueError("GitHub webhook secret MUST contain at least 32 characters")
        if not self.token.strip():
            raise ValueError("GitHub token MUST be non-empty")
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError("GitHub API base MUST be an HTTPS origin")
        if self.timeout_seconds <= 0 or self.max_file_pages < 1:
            raise ValueError("GitHub webhook bounds MUST be positive")


class PostgresStewardshipMergeRecorder:
    """Record verified merge evidence once without applying stewardship state."""

    def __init__(self, *, dsn: str, connect_timeout_s: int = 10) -> None:
        if not dsn:
            raise ValueError("stewardship merge PostgreSQL DSN MUST NOT be empty")
        if connect_timeout_s < 1:
            raise ValueError("stewardship merge connect timeout MUST be positive")
        self._dsn = dsn
        self._connect_timeout_s = connect_timeout_s

    async def record(self, merge: StewardshipMergeRecord) -> bool:
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            row = await (
                await connection.execute(
                    "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                    "ON CONFLICT (key) DO NOTHING RETURNING key",
                    (
                        f"stewardship_merge:{merge.delivery_id}",
                        merge.model_dump_json(),
                    ),
                )
            ).fetchone()
        return row is not None


class PostgresRepositoryHandoverDraftRecorder:
    """Store repository drafts as inert state without changing stewardship configuration."""

    def __init__(self, *, dsn: str, connect_timeout_s: int = 10) -> None:
        if not dsn:
            raise ValueError("repository handover PostgreSQL DSN MUST NOT be empty")
        if connect_timeout_s < 1:
            raise ValueError("repository handover connect timeout MUST be positive")
        self._dsn = dsn
        self._connect_timeout_s = connect_timeout_s

    async def record(self, draft: RepositoryHandoverDraft) -> bool:
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            connect_timeout=self._connect_timeout_s,
        ) as connection:
            row = await (
                await connection.execute(
                    "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                    "ON CONFLICT (key) DO NOTHING RETURNING key",
                    (
                        f"stewardship_repository_draft:{draft.delivery_id}",
                        draft.model_dump_json(),
                    ),
                )
            ).fetchone()
        return row is not None


@dataclass(frozen=True, slots=True)
class GitHubRepositoryHandoverIntakeConfig:
    """Authentication and content bounds for inert repository draft intake."""

    repository: str
    webhook_secret: str
    max_body_bytes: int = 1024 * 1024
    max_content_characters: int = 65_536

    def __post_init__(self) -> None:
        if self.repository.count("/") != 1:
            raise ValueError("GitHub repository MUST be 'owner/name'")
        if len(self.webhook_secret) < 32:
            raise ValueError("GitHub webhook secret MUST contain at least 32 characters")
        if self.max_body_bytes < 1 or not 1 <= self.max_content_characters <= 65_536:
            raise ValueError("repository handover intake bounds MUST be positive and supported")


class GitHubRepositoryHandoverIntake:
    """Authenticate one repository_dispatch event and persist an inert handover draft."""

    def __init__(
        self,
        *,
        config: GitHubRepositoryHandoverIntakeConfig,
        recorder: RepositoryHandoverDraftRecorder,
    ) -> None:
        self._config = config
        self._recorder = recorder

    async def handle(self, *, headers: Mapping[str, str], body: bytes) -> StewardshipWebhookResult:
        if len(body) > self._config.max_body_bytes:
            return StewardshipWebhookResult(False, "payload exceeds the configured limit")
        signature = headers.get("x-hub-signature-256", "")
        expected = (
            "sha256="
            + hmac.new(self._config.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(signature, expected):
            return StewardshipWebhookResult(False, "invalid signature")
        if headers.get("x-github-event", "") != "repository_dispatch":
            return StewardshipWebhookResult(True, "event ignored")
        delivery_id = headers.get("x-github-delivery", "").strip()
        if not delivery_id:
            return StewardshipWebhookResult(False, "delivery id missing")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return StewardshipWebhookResult(False, "invalid JSON")
        if not isinstance(payload, dict):
            return StewardshipWebhookResult(False, "payload is not an object")
        repository = payload.get("repository")
        sender = payload.get("sender")
        client_payload = payload.get("client_payload")
        if (
            not isinstance(repository, dict)
            or repository.get("full_name") != self._config.repository
        ):
            return StewardshipWebhookResult(False, "repository mismatch")
        if payload.get("action") != "handover_draft" or not isinstance(client_payload, dict):
            return StewardshipWebhookResult(True, "dispatch ignored")
        source_ref = client_payload.get("source_ref")
        content = client_payload.get("content")
        if (
            not isinstance(source_ref, str)
            or not source_ref.strip()
            or len(source_ref) > 512
            or not isinstance(content, str)
            or not content.strip()
            or len(content) > self._config.max_content_characters
        ):
            return StewardshipWebhookResult(False, "handover draft payload is invalid")
        login = sender.get("login") if isinstance(sender, dict) else None
        changed = await self._recorder.record(
            RepositoryHandoverDraft(
                delivery_id=delivery_id,
                repository=self._config.repository,
                actor_identity=(
                    f"github:{login}" if isinstance(login, str) and login else "github:unknown"
                ),
                source_ref=source_ref.strip(),
                content=content,
                content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            )
        )
        return StewardshipWebhookResult(True, "handover draft recorded", changed=changed)


class GitHubStewardshipWebhook:
    """Verify one GitHub pull-request merge before recording review evidence."""

    def __init__(
        self,
        *,
        config: GitHubStewardshipWebhookConfig,
        http_client: httpx.AsyncClient,
        recorder: StewardshipMergeRecorder,
    ) -> None:
        self._config = config
        self._http = http_client
        self._recorder = recorder

    async def handle(self, *, headers: Mapping[str, str], body: bytes) -> StewardshipWebhookResult:
        signature = headers.get("x-hub-signature-256", "")
        expected = (
            "sha256="
            + hmac.new(self._config.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(signature, expected):
            return StewardshipWebhookResult(False, "invalid signature")
        if headers.get("x-github-event", "") != "pull_request":
            return StewardshipWebhookResult(True, "event ignored")
        delivery_id = headers.get("x-github-delivery", "").strip()
        if not delivery_id:
            return StewardshipWebhookResult(False, "delivery id missing")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return StewardshipWebhookResult(False, "invalid JSON")
        if not isinstance(payload, dict):
            return StewardshipWebhookResult(False, "payload is not an object")
        repository = payload.get("repository")
        pull_request = payload.get("pull_request")
        if (
            not isinstance(repository, dict)
            or repository.get("full_name") != self._config.repository
            or not isinstance(pull_request, dict)
        ):
            return StewardshipWebhookResult(False, "repository mismatch")
        if payload.get("action") != "closed" or pull_request.get("merged") is not True:
            return StewardshipWebhookResult(True, "pull request not merged")
        number = payload.get("number")
        merge_sha = pull_request.get("merge_commit_sha")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            return StewardshipWebhookResult(False, "pull request number invalid")
        if not isinstance(merge_sha, str) or not merge_sha:
            return StewardshipWebhookResult(False, "merge commit missing")
        if not await self._target_file_changed(number):
            return StewardshipWebhookResult(True, "stewardship file unchanged")
        merged_yaml = await self._merged_content(merge_sha)
        merged_by = pull_request.get("merged_by")
        login = merged_by.get("login") if isinstance(merged_by, dict) else None
        changed = await self._recorder.record(
            StewardshipMergeRecord(
                delivery_id=delivery_id,
                pr_ref=f"{self._config.repository}#{number}",
                actor_identity=(
                    f"github:{login}" if isinstance(login, str) and login else "github:unknown"
                ),
                merge_commit_sha=merge_sha,
                merged_yaml=merged_yaml,
            )
        )
        return StewardshipWebhookResult(True, "merge recorded", changed=changed)

    async def _target_file_changed(self, number: int) -> bool:
        base = (
            f"{self._config.api_base.rstrip('/')}/repos/{self._config.repository}/"
            f"pulls/{number}/files"
        )
        for page in range(1, self._config.max_file_pages + 1):
            payload = await self._get_json(f"{base}?per_page=100&page={page}")
            if not isinstance(payload, list):
                raise RuntimeError("GitHub pull-request files response MUST be a list")
            if any(
                isinstance(item, dict) and item.get("filename") == _TARGET_FILE for item in payload
            ):
                return True
            if len(payload) < 100:
                return False
        raise RuntimeError("GitHub pull-request files exceeded the verification limit")

    async def _merged_content(self, merge_sha: str) -> str:
        payload = await self._get_json(
            f"{self._config.api_base.rstrip('/')}/repos/{self._config.repository}/"
            f"contents/{_TARGET_FILE}?ref={merge_sha}"
        )
        if not isinstance(payload, dict) or payload.get("encoding") != "base64":
            raise RuntimeError("GitHub stewardship content response is malformed")
        content = payload.get("content")
        if not isinstance(content, str):
            raise RuntimeError("GitHub stewardship content is missing")
        try:
            return base64.b64decode("".join(content.split()), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("GitHub stewardship content is not valid UTF-8 base64") from exc

    async def _get_json(self, url: str) -> object:
        response = await self._http.get(
            url,
            headers={
                "Authorization": f"Bearer {self._config.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=self._config.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
