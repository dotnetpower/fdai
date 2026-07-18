"""GitHub App implementation of :class:`RemediationPrPublisher`.

Talks to the GitHub REST API v2022-11-28 through :class:`httpx.AsyncClient`
under a bounded per-request timeout; ``core/`` never sees an ``httpx``
symbol thanks to the import-lint gate in
[`scripts/quality/architecture/check-core-imports.sh`](../../../../scripts/quality/architecture/check-core-imports.sh).

Wire-level flow per publish
---------------------------

1. Idempotency probe - search open PRs whose head branch equals
   ``<branch_prefix>/<idempotency_key>``. Match ⇒ return the existing PR
   as ``already_existed=True``, no writes.
2. Refresh the target branch base (fetch the default branch tip).
3. Commit the rendered patch on a shadow branch through the Contents API
   (``PUT /repos/{owner}/{repo}/contents/{path}``).
4. Open a **draft** PR (``POST /repos/{owner}/{repo}/pulls`` with
   ``draft=true``) targeting the default branch.
5. Apply labels including ``shadow`` + ``rule:<id>`` + ``action:<type>``.

Every step raises :class:`GitOpsPrError` on non-2xx and includes a
truncated response snippet - bodies are untrusted GitHub content and are
inert data on our side (never instructions).

P1 posture
----------

Shadow-only. The publisher rejects an ``enforce``-mode intent that does
not carry an explicit ``enforce`` label (the executor already guarantees
shadow labeling; this is defense-in-depth so a hand-crafted intent
cannot slip past). No merge call, no label removal - the publisher is a
write-once contract per
[`docs/roadmap/phases/phase-1-rule-catalog-t0.md § Remediation PR`].
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Final

import httpx

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import (
    PublishReceipt,
    RemediationPr,
    RemediationPrPublisher,
)

_DEFAULT_API_BASE: Final[str] = "https://api.github.com"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 15.0
_DEFAULT_BRANCH_PREFIX: Final[str] = "fdai/shadow"


class GitOpsPrError(RuntimeError):
    """Raised when a GitHub REST call fails or returns an unusable body."""


@dataclass(frozen=True, slots=True)
class GitOpsPrConfig:
    """Values a fork configures via ``AppConfig`` at composition time."""

    owner: str
    """GitHub owner (org or user) that hosts the IaC repo."""

    repo: str
    """Repository name; ``core/`` never sees the ``owner/repo`` pair
    directly - the adapter is the only place it lands."""

    default_branch: str = "main"
    """Base branch the shadow PR targets."""

    branch_prefix: str = _DEFAULT_BRANCH_PREFIX
    """Branch name = ``<prefix>/<idempotency_key>`` (kebab / slash safe)."""

    api_base: str = _DEFAULT_API_BASE
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    commit_author_name: str = "fdai-executor"
    commit_author_email: str = "fdai@example.com"


class GitOpsPrAdapter(RemediationPrPublisher):
    """GitHub REST implementation of :class:`RemediationPrPublisher`.

    The adapter is stateless w.r.t. PRs - every idempotency decision is
    delegated to a **remote query** so a process restart cannot cause a
    duplicate publish (matches the write-once contract in
    ``RemediationPrPublisher.publish``).
    """

    def __init__(
        self,
        *,
        config: GitOpsPrConfig,
        http_client: httpx.AsyncClient,
        token: str,
    ) -> None:
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if not token or not token.strip():
            raise ValueError("token MUST NOT be empty")
        if not config.api_base.startswith("https://"):
            # The GitHub API and every Azure DevOps / GHE-Enterprise clone
            # of it MUST be reached over TLS - the caller's PAT / GitHub-
            # App JWT would leak on `http://`. Refuse construction so a
            # misconfigured tfvars can never ship a token in the clear.
            raise ValueError("api_base MUST use https:// scheme")
        self._config: Final[GitOpsPrConfig] = config
        self._http: Final[httpx.AsyncClient] = http_client
        self._token: Final[str] = token

    # ------------------------------------------------------------------
    # RemediationPrPublisher
    # ------------------------------------------------------------------

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        if pr.mode is not Mode.SHADOW and "enforce" not in pr.labels:
            raise ValueError(
                "enforce-mode PR requires an explicit 'enforce' label (P1 promotion contract)"
            )

        branch = self._branch_for(pr.idempotency_key)

        # 1. Idempotency probe
        existing = await self._find_open_pr(branch)
        if existing is not None:
            return PublishReceipt(
                pr_ref=existing["ref"],
                url=existing.get("url"),
                already_existed=True,
            )

        # 2. Refresh base sha
        base_sha = await self._resolve_base_sha()

        # 3. Ensure branch + commit patch (idempotent - create-if-missing)
        await self._create_branch(branch=branch, base_sha=base_sha)
        await self._put_contents(
            branch=branch, path=pr.patch_path, content=pr.patch, title=pr.title
        )

        # 4. Open draft PR
        pr_ref, url = await self._open_draft_pr(branch=branch, title=pr.title, body=pr.body)

        # 5. Apply labels
        await self._apply_labels(pr_ref=pr_ref, labels=pr.labels)

        return PublishReceipt(
            pr_ref=pr_ref,
            url=url,
            already_existed=False,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _branch_for(self, idempotency_key: str) -> str:
        safe = idempotency_key.replace(" ", "-").replace("/", "-")
        return f"{self._config.branch_prefix}/{safe}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get_json(self, url: str) -> Any:
        try:
            response = await self._http.get(
                url,
                headers=self._headers(),
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise GitOpsPrError(f"GET {url} failed: {exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise GitOpsPrError(f"GET {url} → HTTP {response.status_code}: {response.text[:200]!r}")
        try:
            return response.json()
        except ValueError as exc:
            raise GitOpsPrError(f"GET {url} returned non-JSON") from exc

    async def _post_json(
        self, url: str, body: dict[str, Any], *, ok_statuses: tuple[int, ...] = (200, 201)
    ) -> Any:
        try:
            response = await self._http.post(
                url,
                headers=self._headers(),
                content=json.dumps(body),
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise GitOpsPrError(f"POST {url} failed: {exc}") from exc
        if response.status_code not in ok_statuses:
            raise GitOpsPrError(
                f"POST {url} → HTTP {response.status_code}: {response.text[:200]!r}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise GitOpsPrError(f"POST {url} returned non-JSON") from exc

    async def _put_json(self, url: str, body: dict[str, Any]) -> Any:
        try:
            response = await self._http.put(
                url,
                headers=self._headers(),
                content=json.dumps(body),
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise GitOpsPrError(f"PUT {url} failed: {exc}") from exc
        if response.status_code not in (200, 201):
            raise GitOpsPrError(f"PUT {url} → HTTP {response.status_code}: {response.text[:200]!r}")
        try:
            return response.json()
        except ValueError as exc:
            raise GitOpsPrError(f"PUT {url} returned non-JSON") from exc

    async def _find_open_pr(self, branch: str) -> dict[str, Any] | None:
        head = f"{self._config.owner}:{branch}"
        url = (
            f"{self._config.api_base}/repos/"
            f"{self._config.owner}/{self._config.repo}/pulls"
            f"?state=open&head={head}"
        )
        payload = await self._get_json(url)
        if not payload:
            return None
        first = payload[0]
        pr_number = first.get("number")
        if pr_number is None:
            return None
        return {
            "ref": f"{self._config.owner}/{self._config.repo}#{pr_number}",
            "url": first.get("html_url"),
        }

    async def _resolve_base_sha(self) -> str:
        url = (
            f"{self._config.api_base}/repos/"
            f"{self._config.owner}/{self._config.repo}"
            f"/git/refs/heads/{self._config.default_branch}"
        )
        payload = await self._get_json(url)
        if payload is None:
            raise GitOpsPrError(f"default branch {self._config.default_branch!r} not found")
        sha = payload.get("object", {}).get("sha")
        if not isinstance(sha, str) or not sha:
            raise GitOpsPrError("default branch ref is missing 'object.sha'")
        return sha

    async def _create_branch(self, *, branch: str, base_sha: str) -> None:
        url = f"{self._config.api_base}/repos/{self._config.owner}/{self._config.repo}/git/refs"
        body = {"ref": f"refs/heads/{branch}", "sha": base_sha}
        try:
            await self._post_json(url, body, ok_statuses=(201,))
        except GitOpsPrError as exc:
            if "422" in str(exc):
                # 422 means the branch already exists - idempotent path.
                return
            raise

    async def _put_contents(
        self,
        *,
        branch: str,
        path: str,
        content: str,
        title: str,
    ) -> str:
        url = (
            f"{self._config.api_base}/repos/"
            f"{self._config.owner}/{self._config.repo}/contents/{path}"
        )
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        body: dict[str, Any] = {
            "message": title,
            "content": encoded,
            "branch": branch,
            "committer": {
                "name": self._config.commit_author_name,
                "email": self._config.commit_author_email,
            },
        }
        # If the file already exists on the branch, GitHub requires the
        # target file's blob sha for an update.
        existing = await self._get_json(f"{url}?ref={branch}")
        if isinstance(existing, dict) and isinstance(existing.get("sha"), str):
            body["sha"] = existing["sha"]

        payload = await self._put_json(url, body)
        commit_sha = payload.get("commit", {}).get("sha")
        if not isinstance(commit_sha, str) or not commit_sha:
            raise GitOpsPrError("contents PUT returned no commit sha")
        return commit_sha

    async def _open_draft_pr(self, *, branch: str, title: str, body: str) -> tuple[str, str | None]:
        url = f"{self._config.api_base}/repos/{self._config.owner}/{self._config.repo}/pulls"
        payload = await self._post_json(
            url,
            {
                "title": title,
                "body": body,
                "head": branch,
                "base": self._config.default_branch,
                "draft": True,
            },
        )
        pr_number = payload.get("number")
        if pr_number is None:
            raise GitOpsPrError("pulls POST returned no PR number")
        pr_ref = f"{self._config.owner}/{self._config.repo}#{pr_number}"
        return pr_ref, payload.get("html_url")

    async def _apply_labels(self, *, pr_ref: str, labels: tuple[str, ...]) -> None:
        pr_number = pr_ref.rsplit("#", 1)[-1]
        url = (
            f"{self._config.api_base}/repos/"
            f"{self._config.owner}/{self._config.repo}"
            f"/issues/{pr_number}/labels"
        )
        await self._post_json(url, {"labels": list(labels)})


__all__ = [
    "GitOpsPrAdapter",
    "GitOpsPrConfig",
    "GitOpsPrError",
]
