"""Read exact reviewed GitHub artifact effects without trusting publisher dispatch receipts."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

from fdai.core.human_assignment.scoped_duties import utc_instant
from fdai.core.human_assignment.scoped_duty_ownership import ScopedDutyMergeObservation

_ROOT = "https://api.github.com"
_MAX_BYTES = 2_000_000


@dataclass(frozen=True, slots=True)
class GitHubScopedDutyMergeReader:
    """Bounded current readback of a protected review artifact, not merge or approval authority.

    Requires a human-reviewed exact PR head, human merge, configured repository/base,
    and equal artifact digests at the immutable merge and current default-branch refs.
    A bot dispatch, draft, closed PR, changed file, absent review, or outage proves nothing.
    """

    client: httpx.AsyncClient
    token_provider: Callable[[], Awaitable[str]]
    repository: str
    default_branch: str
    clock: Callable[[], datetime]
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository) is None
            or not self.default_branch
            or len(self.default_branch) > 256
            or not callable(self.clock)
            or isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or not 0 < self.timeout_seconds <= 30
        ):
            raise ValueError("scoped merge reader requires exact repository, branch and deadline")

    async def read(
        self,
        *,
        pr_ref: str,
        path: str,
        candidate_digest: str,
    ) -> ScopedDutyMergeObservation | None:
        """Return an expiring exact-merge observation; no retry, redirect, write or raw body log."""
        prefix = self.repository + "#"
        if (
            not pr_ref.startswith(prefix)
            or not pr_ref[len(prefix) :].isdigit()
            or not 1 <= int(pr_ref[len(prefix) :]) <= 2_147_483_647
            or re.fullmatch(r"config/scoped-duty-plans/[0-9a-f-]{36}\.json", path) is None
            or re.fullmatch(r"[0-9a-f]{64}", candidate_digest) is None
        ):
            raise ValueError("scoped merge reference does not match the configured artifact source")
        started = utc_instant(self.clock())
        async with asyncio.timeout(self.timeout_seconds):
            token = await self.token_provider()
            if not token:
                raise ValueError("scoped merge read credential is unavailable")
            headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
            pr = await self._get(
                f"/repos/{self.repository}/pulls/{int(pr_ref[len(prefix) :])}", headers
            )
            if (
                not isinstance(pr, dict)
                or pr.get("merged") is not True
                or pr.get("draft") is not False
            ):
                return None
            base, head = pr.get("base"), pr.get("head")
            author, merger = pr.get("user"), pr.get("merged_by")
            if (
                not isinstance(base, dict)
                or not isinstance(head, dict)
                or not isinstance(base.get("repo"), dict)
                or base["repo"].get("full_name") != self.repository
                or base.get("ref") != self.default_branch
                or not isinstance(author, dict)
                or not isinstance(author.get("login"), str)
                or not isinstance(merger, dict)
                or merger.get("type") != "User"
                or not isinstance(merger.get("login"), str)
                or author["login"].casefold() == merger["login"].casefold()
            ):
                return None
            merge_sha, head_sha = pr.get("merge_commit_sha"), head.get("sha")
            if any(
                not isinstance(sha, str) or re.fullmatch(r"[a-f0-9]{40}", sha) is None
                for sha in (merge_sha, head_sha)
            ):
                return None
            reviewers: dict[str, str] = {}
            complete = False
            for page in range(1, 6):
                reviews = await self._get(
                    f"/repos/{self.repository}/pulls/{int(pr_ref[len(prefix) :])}/reviews"
                    f"?per_page=100&page={page}",
                    headers,
                )
                if not isinstance(reviews, list) or len(reviews) > 100:
                    return None
                for review in reviews:
                    if not isinstance(review, dict):
                        return None
                    user = review.get("user")
                    if not isinstance(user, dict) or not isinstance(user.get("login"), str):
                        return None
                    login = user["login"].casefold()
                    state = review.get("state")
                    if state not in {
                        "APPROVED",
                        "CHANGES_REQUESTED",
                        "DISMISSED",
                        "COMMENTED",
                        "PENDING",
                    }:
                        return None
                    if state in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                        reviewers[login] = (
                            state
                            if (
                                user.get("type") == "User"
                                and review.get("commit_id") == head_sha
                                and login != author["login"].casefold()
                            )
                            else "unverified"
                        )
                if len(reviews) < 100:
                    complete = True
                    break
            if (
                not complete
                or "APPROVED" not in reviewers.values()
                or "CHANGES_REQUESTED" in reviewers.values()
            ):
                return None
            for revision in (merge_sha, self.default_branch):
                file = await self._get(
                    f"/repos/{self.repository}/contents/{path}?ref={quote(str(revision), safe='')}",
                    headers,
                )
                if (
                    not isinstance(file, dict)
                    or file.get("type") != "file"
                    or file.get("path") != path
                    or file.get("encoding") != "base64"
                    or not isinstance(file.get("content"), str)
                ):
                    return None
                try:
                    content = base64.b64decode("".join(file["content"].split()), validate=True)
                except ValueError:
                    return None
                if (
                    len(content) > 1_048_576
                    or hashlib.sha256(content).hexdigest() != candidate_digest
                ):
                    return None
            ended = utc_instant(self.clock())
            if not started <= ended < started + timedelta(seconds=60):
                return None
            return ScopedDutyMergeObservation(
                pr_ref,
                path,
                candidate_digest,
                str(merge_sha),
                started,
                started + timedelta(seconds=60),
            )

    async def _get(self, path: str, headers: dict[str, str]) -> object:
        try:
            async with self.client.stream(
                "GET",
                _ROOT + path,
                headers=headers,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code == 404:
                    return None
                if response.status_code != 200:
                    raise ValueError("scoped merge provider read is unavailable")
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > _MAX_BYTES:
                        raise ValueError("scoped merge provider response exceeds its bound")
            return json.loads(body, object_pairs_hook=_unique)
        except (httpx.HTTPError, ValueError, RecursionError):
            raise ValueError("scoped merge read failed closed") from None


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("scoped merge response has ambiguous JSON keys")
        result[key] = value
    return result


__all__ = ["GitHubScopedDutyMergeReader"]
