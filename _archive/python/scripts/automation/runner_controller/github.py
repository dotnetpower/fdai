"""Repository-scoped GitHub Actions clients authenticated by an injected PAT."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import threading
from collections import OrderedDict
from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from urllib.parse import urlencode

from .transport import DEFAULT_ACCEPTED, HttpResponse, ProviderError, Transport

_BASE = "https://api.github.com"
_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_RUNNER_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_MAX_PAGES = 100
_MAX_WORKFLOW_BYTES = 1024 * 1024
_MAX_CACHED_GETS = 512
_CI_WORKFLOW_FILES = ("ci.yml", "container-supply-chain.yml")


def _id(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise ProviderError("invalid_response")
    return value


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderError("invalid_response")
    return value


def _etag(headers: Mapping[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() == "etag":
            if (
                isinstance(value, str)
                and 0 < len(value) <= 1024
                and all(32 <= ord(char) < 127 for char in value)
            ):
                return value
            return None
    return None


class GitHubAPI:
    def __init__(self, token: str, repository: str, transport: Transport | None = None) -> None:
        parts = repository.split("/")
        if (
            len(parts) != 2
            or not _LOGIN.fullmatch(parts[0])
            or not _REPOSITORY.fullmatch(parts[1])
            or parts[1] in {".", ".."}
            or not isinstance(token, str)
            or not token
            or any(ord(char) < 33 or ord(char) > 126 for char in token)
        ):
            raise ProviderError("invalid_request")
        self._token = token
        self._root = f"/repos/{repository}"
        self._transport = transport if transport is not None else Transport()
        self._get_cache: OrderedDict[str, tuple[str, HttpResponse]] = OrderedDict()
        self._cache_lock = threading.Lock()

    def __repr__(self) -> str:
        return "GitHubAPI()"

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        accepted: tuple[int, ...] = DEFAULT_ACCEPTED,
    ) -> HttpResponse:
        url = _BASE + self._root + path
        cacheable = method == "GET" and body is None and 200 in accepted
        with self._cache_lock:
            cached = self._get_cache.get(url) if cacheable else None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "fdai-runner-controller",
        }
        request_accepted = tuple(status for status in accepted if status != 304)
        if cached is not None:
            headers["If-None-Match"] = cached[0]
            request_accepted += (304,)
        response = self._transport.request(
            method,
            url,
            headers=headers,
            body=body,
            accepted=request_accepted,
        )
        if response.status == 304:
            if cached is None:
                raise ProviderError("invalid_response", 304)
            previous = cached[1]
            revalidated_etag = _etag(response.headers) or cached[0]
            updated_keys = {key.lower() for key in response.headers}
            response_headers = {
                key: value
                for key, value in previous.headers.items()
                if key.lower() not in updated_keys
            }
            response_headers.update(response.headers)
            response = HttpResponse(
                previous.status,
                deepcopy(previous.data),
                response_headers,
            )
            self._remember(url, revalidated_etag, response)
            return response
        if response.status not in request_accepted:
            raise ProviderError("http_status", response.status)
        if cacheable:
            with self._cache_lock:
                self._get_cache.pop(url, None)
            etag = _etag(response.headers)
            if response.status == 200 and isinstance(response.data, (dict, list)) and etag:
                self._remember(url, etag, response)
        return response

    def _remember(self, url: str, etag: str, response: HttpResponse) -> None:
        """Store isolated snapshots only; reuse always requires an authenticated 304."""
        with self._cache_lock:
            self._get_cache.pop(url, None)
            self._get_cache[url] = (
                etag,
                HttpResponse(response.status, deepcopy(response.data), dict(response.headers)),
            )
            while len(self._get_cache) > _MAX_CACHED_GETS:
                self._get_cache.popitem(last=False)

    def _pages(self, path: str, key: str) -> list[dict[str, Any]]:
        """Bound enumeration and reject inconsistent pages rather than truncate."""
        results: list[dict[str, Any]] = []
        seen: set[int] = set()
        total: int | None = None
        for page in range(1, _MAX_PAGES + 1):
            separator = "&" if "?" in path else "?"
            response = self._request("GET", f"{path}{separator}per_page=100&page={page}")
            data = _object(response.data)
            entries = data.get(key)
            if not isinstance(entries, list) or len(entries) > 100:
                raise ProviderError("invalid_response")
            if "total_count" in data:
                count = data["total_count"]
                if type(count) is not int or count < 0 or (total is not None and count != total):
                    raise ProviderError("invalid_response")
                total = count
            for entry in entries:
                item = _object(entry)
                item_id = _id(item.get("id"))
                if item_id in seen:
                    raise ProviderError("invalid_response")
                seen.add(item_id)
                results.append(item)
            if total is not None:
                if len(results) > total:
                    raise ProviderError("invalid_response")
                if len(results) == total:
                    return results
            if len(entries) < 100:
                if total is not None and len(results) != total:
                    raise ProviderError("pagination_limit")
                return results
        raise ProviderError("pagination_limit")

    def repository_id(self) -> int:
        return _id(_object(self._request("GET", "").data).get("id"))

    def runners(self) -> list[dict[str, Any]]:
        return self._pages("/actions/runners", "runners")

    def queued_jobs(self) -> list[dict[str, Any]]:
        """Observe only canonical CI queues; provider errors never become empty demand."""
        jobs: list[dict[str, Any]] = []
        seen_runs: dict[int, str] = {}
        seen_jobs: set[int] = set()
        for workflow in _CI_WORKFLOW_FILES:
            for status in ("queued", "in_progress"):
                runs = self._pages(
                    f"/actions/workflows/{workflow}/runs?status={status}", "workflow_runs"
                )
                for run in runs:
                    if run.get("status") not in ("queued", "in_progress"):
                        continue
                    if run.get("path") != f".github/workflows/{workflow}":
                        raise ProviderError("invalid_response")
                    run_id = _id(run.get("id"))
                    if run_id in seen_runs:
                        if seen_runs[run_id] != workflow:
                            raise ProviderError("invalid_response")
                        continue
                    seen_runs[run_id] = workflow
                    for job in self._pages(f"/actions/runs/{run_id}/jobs?filter=latest", "jobs"):
                        if job.get("status") not in ("queued", "in_progress"):
                            continue
                        job_id = _id(job.get("id"))
                        if job_id in seen_jobs:
                            raise ProviderError("invalid_response")
                        seen_jobs.add(job_id)
                        jobs.append({**job, "_run": dict(run)})
        return jobs

    def jit(self, name: str, labels: list[str]) -> tuple[int, str]:
        if (
            not _RUNNER_NAME.fullmatch(name)
            or not labels
            or len(labels) > 100
            or any(
                not isinstance(label, str)
                or not label
                or len(label) > 255
                or any(ord(char) < 32 or ord(char) == 127 for char in label)
                for label in labels
            )
        ):
            raise ProviderError("invalid_request")
        data = _object(
            self._request(
                "POST",
                "/actions/runners/generate-jitconfig",
                body={
                    "name": name,
                    "runner_group_id": 1,
                    "labels": labels,
                    "work_folder": "_work",
                },
                accepted=(201,),
            ).data
        )
        runner_id = _id(_object(data.get("runner")).get("id"))
        encoded = data.get("encoded_jit_config")
        if not isinstance(encoded, str) or not encoded or len(encoded) > 4 * 1024 * 1024:
            raise ProviderError("invalid_response")
        return runner_id, encoded

    def remove_idle(self, runner_id: int, name: str) -> bool:
        """Remove only a freshly observed idle registration, not its compute resource."""
        _id(runner_id)
        if not isinstance(name, str) or not name:
            raise ProviderError("invalid_request")
        try:
            response = self._request("GET", f"/actions/runners/{runner_id}", accepted=(200, 404))
            if response.status == 404:
                return True
            runner = _object(response.data)
            if (
                type(runner.get("id")) is not int
                or runner.get("id") != runner_id
                or runner.get("name") != name
                or runner.get("busy") is not False
            ):
                return False
            deleted = self._request(
                "DELETE", f"/actions/runners/{runner_id}", accepted=(204, 404, 409, 422)
            )
            return deleted.status in {204, 404}
        except ProviderError as error:
            if error.status in {404, 409, 422}:
                return error.status == 404
            raise

    def run(self, run_id: int) -> dict[str, Any]:
        return self._lookup(f"/actions/runs/{_id(run_id)}", run_id)

    def job(self, job_id: int) -> dict[str, Any]:
        return self._lookup(f"/actions/jobs/{_id(job_id)}", job_id)

    def _lookup(self, path: str, expected_id: int) -> dict[str, Any]:
        data = _object(self._request("GET", path).data)
        if _id(data.get("id")) != expected_id:
            raise ProviderError("invalid_response")
        return data

    def permission(self, login: str) -> str:
        if not _LOGIN.fullmatch(login):
            raise ProviderError("invalid_request")
        data = _object(self._request("GET", f"/collaborators/{login}/permission").data)
        permission = data.get("permission")
        if not isinstance(permission, str) or permission not in {
            "admin",
            "maintain",
            "write",
            "triage",
            "read",
            "none",
        }:
            raise ProviderError("invalid_response")
        return str(permission)

    def workflow_digest(self, ref: str) -> str:
        if (
            not isinstance(ref, str)
            or not ref
            or len(ref) > 1024
            or any(ord(char) < 32 or ord(char) == 127 for char in ref)
        ):
            raise ProviderError("invalid_request")
        query = urlencode({"ref": ref})
        data = _object(self._request("GET", f"/contents/.github/workflows/ci.yml?{query}").data)
        content, size = data.get("content"), data.get("size")
        if (
            data.get("type") != "file"
            or data.get("encoding") != "base64"
            or not isinstance(content, str)
            or len(content) > 2 * _MAX_WORKFLOW_BYTES
            or type(size) is not int
            or not 0 <= size <= _MAX_WORKFLOW_BYTES
        ):
            raise ProviderError("invalid_response")
        try:
            decoded = base64.b64decode(content.replace("\n", ""), validate=True)
        except (ValueError, binascii.Error):
            raise ProviderError("invalid_response") from None
        if len(decoded) != size or len(decoded) > _MAX_WORKFLOW_BYTES:
            raise ProviderError("invalid_response")
        return hashlib.sha256(decoded).hexdigest()
