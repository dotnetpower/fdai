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

import asyncio
import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote, urlencode

import httpx
from fdai_github_app_auth import TokenProvider, static_token_provider

from fdai.delivery.gitops_pr.catalog_review import CatalogReviewPrObservation
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

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_message = response_message


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
        token: str | None = None,
        token_provider: TokenProvider | None = None,
    ) -> None:
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if (token is None) == (token_provider is None):
            raise ValueError("exactly one token or token_provider MUST be configured")
        if not config.api_base.startswith("https://"):
            # The GitHub API and every Azure DevOps / GHE-Enterprise clone
            # of it MUST be reached over TLS - the caller's PAT / GitHub-
            # App JWT would leak on `http://`. Refuse construction so a
            # misconfigured tfvars can never ship a token in the clear.
            raise ValueError("api_base MUST use https:// scheme")
        self._config: Final[GitOpsPrConfig] = config
        self._http: Final[httpx.AsyncClient] = http_client
        self._token_provider: Final[TokenProvider] = (
            token_provider if token_provider is not None else static_token_provider(token or "")
        )
        self._publish_locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # RemediationPrPublisher
    # ------------------------------------------------------------------

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        if pr.mode is not Mode.SHADOW and "enforce" not in pr.labels:
            raise ValueError(
                "enforce-mode PR requires an explicit 'enforce' label (P1 promotion contract)"
            )

        lock = self._publish_locks.setdefault(pr.idempotency_key, asyncio.Lock())
        async with lock:
            branch = self._branch_for(pr.idempotency_key)
            # Recheck under the per-key lock so concurrent retries cannot
            # both pass the remote idempotency probe.
            existing = await self._find_open_pr(branch)
            if existing is not None:
                head_sha = await self._ensure_existing_review(
                    existing,
                    branch=branch,
                    pr=pr,
                )
                return PublishReceipt(
                    pr_ref=existing["ref"],
                    url=existing.get("url"),
                    already_existed=True,
                    state=existing["state"],
                    head_sha=head_sha,
                )

            base_sha = await self._resolve_base_sha()
            await self._create_branch(branch=branch, base_sha=base_sha)
            head_sha = await self._put_contents(
                branch=branch, path=pr.patch_path, content=pr.patch, title=pr.title
            )
            try:
                pr_ref, url = await self._open_draft_pr(branch=branch, title=pr.title, body=pr.body)
            except GitOpsPrError:
                # A transport timeout can occur after GitHub accepted the
                # create. Reconcile before surfacing failure so a retry cannot
                # create a second PR.
                existing = await self._find_open_pr(branch)
                if existing is None:
                    raise
                head_sha = await self._ensure_existing_review(
                    existing,
                    branch=branch,
                    pr=pr,
                )
                return PublishReceipt(
                    pr_ref=existing["ref"],
                    url=existing.get("url"),
                    already_existed=True,
                    state=existing["state"],
                    head_sha=head_sha,
                )
            await self._set_labels(pr_ref=pr_ref, labels=pr.labels)
            return PublishReceipt(
                pr_ref=pr_ref,
                url=url,
                already_existed=False,
                state="open",
                head_sha=head_sha,
            )

    async def publish_governance(
        self,
        document: Any,
        *,
        lifecycle_store: Any,
        correlation_id: str,
        source_event_id: str,
    ) -> Any:
        """Publish a pure governance document with lifecycle evidence.

        The governance wrapper uses this adapter's existing write-once,
        shadow-labeled PR flow and never invokes a merge operation.
        """
        from fdai.delivery.gitops_pr.governance import GovernedGovernancePrPublisher

        return await GovernedGovernancePrPublisher(
            publisher=self,
            lifecycle_store=lifecycle_store,
        ).publish(
            document,
            correlation_id=correlation_id,
            source_event_id=source_event_id,
        )

    async def reconcile(self, pr_ref: str) -> str:
        """Return the remote PR lifecycle state for replay reconciliation."""
        marker = f"{self._config.owner}/{self._config.repo}#"
        if not pr_ref.startswith(marker):
            raise GitOpsPrError("governance PR reference does not match this adapter")
        number = pr_ref[len(marker) :]
        if not number.isdigit():
            raise GitOpsPrError("governance PR reference number is invalid")
        payload = await self._get_json(self._repo_url(f"pulls/{quote(number, safe='')}"))
        if not isinstance(payload, dict):
            raise GitOpsPrError("governance PR lookup returned no pull request")
        if payload.get("merged_at") is not None:
            return "merged"
        if payload.get("state") == "closed":
            return "closed"
        if payload.get("state") == "open":
            return "open"
        raise GitOpsPrError("governance PR lookup returned an unknown state")

    async def read_existing(self, path: str) -> str | None:
        """Read one exact bounded UTF-8 file from this publisher's configured base branch.

        This is read-only and never follows provider download links. Writer exclusion
        and source digest checks still belong to the governed publication boundary.
        """
        from fdai.delivery.gitops_pr.existing_file import existing_file_path, read_existing_file

        path = existing_file_path(path)
        url = self._repo_url(f"contents/{self._content_path(path)}")
        url += "?" + urlencode({"ref": self._config.default_branch})
        return await read_existing_file(
            client=self._http,
            url=url,
            path=path,
            headers=self._headers,
            timeout_seconds=self._config.timeout_seconds,
        )

    async def observe_catalog_review(
        self,
        *,
        pr_ref: str,
        idempotency_key: str,
        required_labels: tuple[str, ...],
        expected_head_sha: str,
        expected_path: str,
        expected_document_digest: str,
    ) -> CatalogReviewPrObservation:
        """GET and bind one exact open draft without merge or auto-merge."""

        marker = f"{self._config.owner}/{self._config.repo}#"
        if not pr_ref.startswith(marker) or not pr_ref[len(marker) :].isdigit():
            raise GitOpsPrError("catalog review PR reference does not match this adapter")
        number = pr_ref[len(marker) :]
        payload = await self._get_json(self._repo_url(f"pulls/{quote(number, safe='')}"))
        if not isinstance(payload, dict):
            raise GitOpsPrError("catalog review PR readback returned no pull request")
        head = payload.get("head")
        base = payload.get("base")
        labels = payload.get("labels")
        if (
            not isinstance(head, dict)
            or not isinstance(base, dict)
            or not isinstance(labels, list)
            or any(
                not isinstance(item, dict) or not isinstance(item.get("name"), str)
                for item in labels
            )
        ):
            raise GitOpsPrError("catalog review PR readback is incomplete")
        observed_labels = tuple(sorted(str(item["name"]) for item in labels))
        await self._require_exact_pr_file(pr_ref=pr_ref, path=expected_path)
        material = {
            "pr_ref": pr_ref,
            "state": payload.get("state"),
            "draft": payload.get("draft"),
            "head": head.get("ref"),
            "head_sha": head.get("sha"),
            "base": base.get("ref"),
            "labels": observed_labels,
            "merged": payload.get("merged"),
            "merged_at": payload.get("merged_at"),
            "auto_merge": payload.get("auto_merge"),
            "review_document_digest": await self._read_content_digest(
                path=expected_path,
                ref=expected_head_sha,
            ),
            "changed_paths": [expected_path],
        }
        observation_digest = hashlib.sha256(
            json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        return CatalogReviewPrObservation(
            observation_digest=observation_digest,
            open=payload.get("state") == "open",
            draft=payload.get("draft") is True,
            head_matches=head.get("ref") == self._branch_for(idempotency_key),
            head_commit_matches=head.get("sha") == expected_head_sha,
            base_matches=base.get("ref") == self._config.default_branch,
            labels_match=observed_labels == tuple(sorted(required_labels)),
            content_matches=material["review_document_digest"] == expected_document_digest,
            files_match=True,
            observed_labels=observed_labels,
            merged=payload.get("merged") is True or payload.get("merged_at") is not None,
            auto_merge_enabled=payload.get("auto_merge") is not None,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _branch_for(self, idempotency_key: str) -> str:
        safe = "".join(
            character if character.isalnum() or character in "._-" else "-"
            for character in idempotency_key
        ).strip("-")[:80]
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return f"{self._config.branch_prefix}/{safe or 'request'}-{digest}"

    async def _headers(self) -> dict[str, str]:
        token = (await self._token_provider()).strip()
        if not token:
            raise GitOpsPrError("GitHub token provider returned an empty token")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo_url(self, suffix: str = "") -> str:
        owner = quote(self._config.owner, safe="")
        repo = quote(self._config.repo, safe="")
        return f"{self._config.api_base}/repos/{owner}/{repo}/{suffix}".rstrip("/")

    @staticmethod
    def _content_path(path: str) -> str:
        return "/".join(quote(segment, safe="") for segment in path.split("/"))

    async def _get_json(self, url: str) -> Any:
        try:
            response = await self._http.get(
                url,
                headers=await self._headers(),
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
                headers=await self._headers(),
                content=json.dumps(body),
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise GitOpsPrError(f"POST {url} failed: {exc}") from exc
        if response.status_code not in ok_statuses:
            response_message = None
            try:
                payload = response.json()
                if isinstance(payload, dict) and isinstance(payload.get("message"), str):
                    response_message = payload["message"]
            except ValueError:
                pass
            raise GitOpsPrError(
                f"POST {url} → HTTP {response.status_code}: {response.text[:200]!r}",
                status_code=response.status_code,
                response_message=response_message,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise GitOpsPrError(f"POST {url} returned non-JSON") from exc

    async def _put_json(self, url: str, body: dict[str, Any]) -> Any:
        try:
            response = await self._http.put(
                url,
                headers=await self._headers(),
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
        query = urlencode({"state": "all", "head": head})
        url = f"{self._repo_url('pulls')}?{query}"
        payload = await self._get_json(url)
        if not payload:
            return None
        first = payload[0]
        pr_number = first.get("number")
        if pr_number is None:
            return None
        state = "merged" if first.get("merged_at") is not None else first.get("state")
        if state not in {"open", "closed", "merged"}:
            raise GitOpsPrError("pull request lookup returned an unknown lifecycle state")
        return {
            "ref": f"{self._config.owner}/{self._config.repo}#{pr_number}",
            "url": first.get("html_url"),
            "state": state,
            "draft": first.get("draft"),
            "labels": tuple(
                item["name"]
                for item in first.get("labels", ())
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ),
        }

    async def _ensure_existing_review(
        self,
        existing: dict[str, Any],
        *,
        branch: str,
        pr: RemediationPr,
    ) -> str | None:
        if existing.get("state") != "open":
            return None
        payload = await self._read_pr_payload(str(existing["ref"]))
        head_sha, current_labels = await self._validate_existing_review(
            payload,
            pr_ref=str(existing["ref"]),
            branch=branch,
            path=pr.patch_path,
            expected_content_digest=hashlib.sha256(pr.patch.encode("utf-8")).hexdigest(),
        )
        expected_labels = tuple(sorted(pr.labels))
        if current_labels != expected_labels:
            await self._set_labels(pr_ref=str(existing["ref"]), labels=pr.labels)
            payload = await self._read_pr_payload(str(existing["ref"]))
            observed_head_sha, current_labels = await self._validate_existing_review(
                payload,
                pr_ref=str(existing["ref"]),
                branch=branch,
                path=pr.patch_path,
                expected_content_digest=hashlib.sha256(pr.patch.encode("utf-8")).hexdigest(),
            )
            if observed_head_sha != head_sha:
                raise GitOpsPrError("existing draft review head changed during label recovery")
            if current_labels != expected_labels:
                raise GitOpsPrError("existing draft review labels do not match exact intent")
        return head_sha

    async def _read_pr_payload(self, pr_ref: str) -> dict[str, Any]:
        number = pr_ref.rsplit("#", 1)[-1]
        if not number.isdigit():
            raise GitOpsPrError("pull request reference number is invalid")
        payload = await self._get_json(self._repo_url(f"pulls/{quote(number, safe='')}"))
        if not isinstance(payload, dict):
            raise GitOpsPrError("pull request readback returned no pull request")
        return payload

    async def _validate_existing_review(
        self,
        payload: dict[str, Any],
        *,
        pr_ref: str,
        branch: str,
        path: str,
        expected_content_digest: str,
    ) -> tuple[str, tuple[str, ...]]:
        head = payload.get("head")
        base = payload.get("base")
        labels = payload.get("labels")
        if (
            payload.get("state") != "open"
            or payload.get("draft") is not True
            or payload.get("merged") is True
            or payload.get("merged_at") is not None
            or payload.get("auto_merge") is not None
            or not isinstance(head, dict)
            or not isinstance(base, dict)
            or not isinstance(labels, list)
        ):
            raise GitOpsPrError("existing pull request is not an inert open draft review")
        head_sha = head.get("sha")
        if (
            head.get("ref") != branch
            or base.get("ref") != self._config.default_branch
            or not isinstance(head_sha, str)
            or not head_sha
        ):
            raise GitOpsPrError("existing draft review branch binding does not match")
        observed_labels = tuple(
            sorted(
                item["name"]
                for item in labels
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            )
        )
        if len(observed_labels) != len(labels):
            raise GitOpsPrError("existing draft review labels are unavailable")
        await self._require_exact_pr_file(pr_ref=pr_ref, path=path)
        observed_content_digest = await self._read_content_digest(path=path, ref=head_sha)
        if observed_content_digest != expected_content_digest:
            raise GitOpsPrError("existing draft review document does not match exact intent")
        return head_sha, observed_labels

    async def _read_content_digest(self, *, path: str, ref: str) -> str:
        url = self._repo_url(f"contents/{self._content_path(path)}")
        payload = await self._get_json(f"{url}?{urlencode({'ref': ref})}")
        if (
            not isinstance(payload, dict)
            or payload.get("encoding") != "base64"
            or not isinstance(payload.get("content"), str)
        ):
            raise GitOpsPrError("review document readback is incomplete")
        encoded = "".join(str(payload["content"]).split())
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise GitOpsPrError("review document readback is not valid base64") from exc
        return hashlib.sha256(content).hexdigest()

    async def _require_exact_pr_file(self, *, pr_ref: str, path: str) -> None:
        number = pr_ref.rsplit("#", 1)[-1]
        if not number.isdigit():
            raise GitOpsPrError("pull request reference number is invalid")
        url = self._repo_url(f"pulls/{quote(number, safe='')}/files")
        payload = await self._get_json(f"{url}?{urlencode({'per_page': 2})}")
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], dict)
            or payload[0].get("filename") != path
            or payload[0].get("status") != "added"
            or "previous_filename" in payload[0]
        ):
            raise GitOpsPrError(
                "catalog review pull request changed paths do not match exact intent"
            )

    async def _resolve_base_sha(self) -> str:
        url = self._repo_url(f"git/refs/heads/{quote(self._config.default_branch, safe='')}")
        payload = await self._get_json(url)
        if payload is None:
            raise GitOpsPrError(f"default branch {self._config.default_branch!r} not found")
        sha = payload.get("object", {}).get("sha")
        if not isinstance(sha, str) or not sha:
            raise GitOpsPrError("default branch ref is missing 'object.sha'")
        return sha

    async def _create_branch(self, *, branch: str, base_sha: str) -> None:
        url = self._repo_url("git/refs")
        body = {"ref": f"refs/heads/{branch}", "sha": base_sha}
        try:
            await self._post_json(url, body, ok_statuses=(201,))
        except GitOpsPrError as exc:
            if exc.status_code == 422 and exc.response_message == "Reference already exists":
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
        url = self._repo_url(f"contents/{self._content_path(path)}")
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
        existing = await self._get_json(f"{url}?{urlencode({'ref': branch})}")
        if isinstance(existing, dict) and isinstance(existing.get("sha"), str):
            body["sha"] = existing["sha"]

        payload = await self._put_json(url, body)
        commit_sha = payload.get("commit", {}).get("sha")
        if not isinstance(commit_sha, str) or not commit_sha:
            raise GitOpsPrError("contents PUT returned no commit sha")
        return commit_sha

    async def _open_draft_pr(self, *, branch: str, title: str, body: str) -> tuple[str, str | None]:
        url = self._repo_url("pulls")
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
        if pr_number is None or payload.get("draft") is not True or payload.get("state") != "open":
            raise GitOpsPrError("pulls POST did not return one open draft review")
        pr_ref = f"{self._config.owner}/{self._config.repo}#{pr_number}"
        return pr_ref, payload.get("html_url")

    async def _set_labels(self, *, pr_ref: str, labels: tuple[str, ...]) -> None:
        pr_number = pr_ref.rsplit("#", 1)[-1]
        url = self._repo_url(f"issues/{quote(pr_number, safe='')}/labels")
        await self._put_json(url, {"labels": list(labels)})


__all__ = [
    "GitOpsPrAdapter",
    "GitOpsPrConfig",
    "GitOpsPrError",
]
