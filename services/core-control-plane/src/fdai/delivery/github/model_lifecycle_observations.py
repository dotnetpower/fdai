"""Read trusted model-lifecycle proposal observations from GitHub."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import httpx
from fdai_github_app_auth import TokenProvider, static_token_provider

_PROPOSAL_PATH: Final[re.Pattern[str]] = re.compile(
    r"^config/model-lifecycle-proposals/([a-f0-9]{64})\.json$"
)
_SHADOW_REPLAY_PATH: Final[re.Pattern[str]] = re.compile(
    r"^config/model-lifecycle-shadow-replay/([a-f0-9]{64})\.json$"
)
_HEAD_REF_PREFIX: Final[str] = "automation/model-lifecycle-"


class ModelLifecycleObservationError(RuntimeError):
    """Report a bounded failure to read trusted lifecycle observations."""


@dataclass(frozen=True, slots=True)
class GitHubModelLifecycleObservationConfig:
    """Configure the single trusted repository and review window."""

    owner: str
    repo: str
    api_base: str = "https://api.github.com"
    base_ref: str = "main"
    review_ttl_hours: int = 168
    timeout_seconds: float = 15.0
    max_pages: int = 10

    def __post_init__(self) -> None:
        if not self.owner or not self.repo:
            raise ValueError("model lifecycle GitHub owner and repo MUST be non-empty")
        if not self.api_base.startswith("https://"):
            raise ValueError("model lifecycle GitHub API base MUST use HTTPS")
        if not self.base_ref:
            raise ValueError("model lifecycle GitHub base ref MUST be non-empty")
        if not 1 <= self.review_ttl_hours <= 720:
            raise ValueError("model lifecycle review TTL MUST be between 1 and 720 hours")
        if self.timeout_seconds <= 0:
            raise ValueError("model lifecycle GitHub timeout MUST be positive")
        if not 1 <= self.max_pages <= 10:
            raise ValueError("model lifecycle GitHub max_pages MUST be between 1 and 10")


class GitHubModelLifecycleObservationSource:
    """Read workflow-owned draft proposals at their exact immutable head SHA."""

    def __init__(
        self,
        *,
        config: GitHubModelLifecycleObservationConfig,
        http_client: httpx.AsyncClient,
        token: str | None = None,
        token_provider: TokenProvider | None = None,
    ) -> None:
        if (token is None) == (token_provider is None):
            raise ValueError("exactly one model lifecycle token source MUST be configured")
        self._config = config
        self._http = http_client
        self._token_provider = (
            token_provider if token_provider is not None else static_token_provider(token or "")
        )

    async def _headers(self) -> dict[str, str]:
        token = (await self._token_provider()).strip()
        if not token:
            raise ModelLifecycleObservationError(
                "model lifecycle GitHub token provider returned an empty token"
            )
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def load(self) -> tuple[Mapping[str, object], ...]:
        """Return bounded, verified observations without granting authority."""

        pulls = await self._get_paginated_array(
            f"/repos/{self._config.owner}/{self._config.repo}/pulls",
            params={"state": "all", "per_page": "100", "base": self._config.base_ref},
        )
        observations: list[Mapping[str, object]] = []
        for pull in pulls:
            if not isinstance(pull, Mapping):
                continue
            if not self._is_workflow_draft(pull):
                continue
            observations.append(await self._load_proposal(pull))
        return tuple(observations)

    def _is_workflow_draft(self, pull: object) -> bool:
        if not isinstance(pull, Mapping):
            return False
        user = pull.get("user")
        head = pull.get("head")
        base = pull.get("base")
        state = pull.get("state")
        review_state_is_visible = state == "closed" or (
            state == "open" and pull.get("draft") is True
        )
        return (
            review_state_is_visible
            and isinstance(user, Mapping)
            and user.get("login") == "github-actions[bot]"
            and isinstance(head, Mapping)
            and isinstance(head.get("ref"), str)
            and str(head["ref"]).startswith(_HEAD_REF_PREFIX)
            and isinstance(base, Mapping)
            and base.get("ref") == self._config.base_ref
        )

    async def _load_proposal(self, pull: Mapping[str, object]) -> Mapping[str, object]:
        number = pull.get("number")
        head = pull.get("head")
        created_at = _timestamp(pull.get("created_at"), "created_at")
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or not isinstance(head, Mapping)
            or not isinstance(head.get("sha"), str)
        ):
            raise ModelLifecycleObservationError("trusted lifecycle pull request is invalid")
        head_sha = str(head["sha"])
        files = await self._get_paginated_array(
            f"/repos/{self._config.owner}/{self._config.repo}/pulls/{number}/files",
            params={"per_page": "100"},
        )
        paths = [
            item.get("filename")
            for item in files
            if isinstance(item, Mapping)
            and isinstance(item.get("filename"), str)
            and _PROPOSAL_PATH.fullmatch(str(item["filename"])) is not None
        ]
        if len(paths) != 1:
            raise ModelLifecycleObservationError(
                "trusted lifecycle pull request MUST contain exactly one proposal"
            )
        replay_paths = [
            item.get("filename")
            for item in files
            if isinstance(item, Mapping)
            and isinstance(item.get("filename"), str)
            and _SHADOW_REPLAY_PATH.fullmatch(str(item["filename"])) is not None
        ]
        if len(replay_paths) > 1:
            raise ModelLifecycleObservationError(
                "trusted lifecycle pull request MUST contain at most one shadow replay receipt"
            )
        path = str(paths[0])
        proposal = await self._load_json_content(path, head_sha, "proposal")
        match = _PROPOSAL_PATH.fullmatch(path)
        if match is None or proposal.get("proposal_digest") != match.group(1):
            raise ModelLifecycleObservationError("lifecycle proposal path digest mismatch")
        merged_at = _optional_timestamp(pull.get("merged_at"), "merged_at")
        closed_at = None
        if pull.get("state") == "closed" and merged_at is None:
            closed_at = _timestamp(pull.get("closed_at"), "closed_at")
        observation: dict[str, object] = {
            "trusted": True,
            "pull_request": number,
            "head_sha": head_sha,
            "opened_at": created_at.isoformat(),
            "expires_at": (created_at + timedelta(hours=self._config.review_ttl_hours)).isoformat(),
            "merged_at": merged_at.isoformat() if merged_at is not None else None,
            "closed_at": closed_at.isoformat() if closed_at is not None else None,
            "proposal": proposal,
        }
        if replay_paths:
            replay_path = str(replay_paths[0])
            replay_match = _SHADOW_REPLAY_PATH.fullmatch(replay_path)
            if replay_match is None or replay_match.group(1) != match.group(1):
                raise ModelLifecycleObservationError("lifecycle shadow replay path digest mismatch")
            observation["shadow_replay"] = await self._load_json_content(
                replay_path,
                head_sha,
                "shadow replay",
            )
        return observation

    async def _load_json_content(
        self,
        path: str,
        head_sha: str,
        content_kind: str,
    ) -> dict[str, object]:
        encoded = await self._get_json(
            f"/repos/{self._config.owner}/{self._config.repo}/contents/{path}",
            params={"ref": head_sha},
        )
        if not isinstance(encoded, Mapping) or encoded.get("encoding") != "base64":
            raise ModelLifecycleObservationError(f"lifecycle {content_kind} content is invalid")
        raw_content = encoded.get("content")
        if not isinstance(raw_content, str):
            raise ModelLifecycleObservationError(f"lifecycle {content_kind} content is absent")
        try:
            loaded = json.loads(base64.b64decode("".join(raw_content.split()), validate=True))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ModelLifecycleObservationError(
                f"lifecycle {content_kind} JSON is invalid"
            ) from exc
        if not isinstance(loaded, dict):
            raise ModelLifecycleObservationError(f"lifecycle {content_kind} MUST be an object")
        return loaded

    async def _get_paginated_array(
        self,
        path: str,
        *,
        params: Mapping[str, str],
    ) -> list[object]:
        items: list[object] = []
        for page in range(1, self._config.max_pages + 1):
            payload = await self._get_json(
                path,
                params={**params, "page": str(page)},
            )
            if not isinstance(payload, list):
                raise ModelLifecycleObservationError("GitHub paginated response is invalid")
            items.extend(payload)
            if len(payload) < 100:
                return items
        raise ModelLifecycleObservationError("GitHub pagination exceeds the configured bound")

    async def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str],
    ) -> object:
        try:
            response = await self._http.get(
                f"{self._config.api_base.rstrip('/')}{path}",
                headers=await self._headers(),
                params=params,
                timeout=self._config.timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise ModelLifecycleObservationError(
                "trusted model lifecycle GitHub read failed"
            ) from exc


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ModelLifecycleObservationError(f"lifecycle pull request {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelLifecycleObservationError(f"lifecycle pull request {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ModelLifecycleObservationError(
            f"lifecycle pull request {field} MUST be timezone-aware"
        )
    return parsed


def _optional_timestamp(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    return _timestamp(value, field)


__all__ = [
    "GitHubModelLifecycleObservationConfig",
    "GitHubModelLifecycleObservationSource",
    "ModelLifecycleObservationError",
]
