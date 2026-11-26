"""Bounded GitHub review-source tests."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from fdai_code_assurance.github import (
    GitHubPullRequestSource,
    GitHubReviewLimitError,
    GitHubReviewSnapshotChangedError,
    GitHubReviewSourceConfig,
    GitHubReviewSourceError,
)

_BASE = "a" * 40
_HEAD = "b" * 40


async def _no_token() -> None:
    return None


def _metadata(*, head: str = _HEAD, changed_files: int = 1) -> dict[str, object]:
    return {"base": {"sha": _BASE}, "head": {"sha": head}, "changed_files": changed_files}


def _file(index: int) -> dict[str, object]:
    return {
        "filename": f"src/file_{index}.py",
        "status": "modified",
        "additions": 1,
        "deletions": 0,
        "patch": f"@@ -1 +1 @@\n+value_{index} = True",
    }


def _source(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_files: int = 200,
    max_response_bytes: int = 2 * 1024 * 1024,
) -> GitHubPullRequestSource:
    return GitHubPullRequestSource(
        config=GitHubReviewSourceConfig(
            max_files=max_files,
            max_response_bytes=max_response_bytes,
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        token_provider=_no_token,
    )


async def test_fetch_paginates_and_rechecks_immutable_metadata() -> None:
    metadata_calls = 0
    file_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal metadata_calls
        assert "authorization" not in request.headers
        if request.url.path.endswith("/files"):
            page = int(request.url.params["page"])
            file_pages.append(page)
            start = 0 if page == 1 else 100
            end = 100 if page == 1 else 101
            return httpx.Response(200, json=[_file(index) for index in range(start, end)])
        metadata_calls += 1
        return httpx.Response(200, json=_metadata(changed_files=101))

    snapshot = await _source(handler).fetch(repository="example/project", pull_number=7)

    assert snapshot.base_sha == _BASE
    assert snapshot.head_sha == _HEAD
    assert len(snapshot.files) == 101
    assert file_pages == [1, 2]
    assert metadata_calls == 2


async def test_file_cap_blocks_before_file_request() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=_metadata(changed_files=3))

    with pytest.raises(GitHubReviewLimitError, match="configured cap 2"):
        await _source(handler, max_files=2).fetch(
            repository="example/project",
            pull_number=7,
        )

    assert paths == ["/repos/example/project/pulls/7"]


async def test_changed_head_discards_collected_files() -> None:
    metadata_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal metadata_calls
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json=[_file(1)])
        metadata_calls += 1
        head = _HEAD if metadata_calls == 1 else "c" * 40
        return httpx.Response(200, json=_metadata(head=head))

    with pytest.raises(GitHubReviewSnapshotChangedError, match="changed while"):
        await _source(handler).fetch(repository="example/project", pull_number=7)


async def test_http_error_does_not_include_response_body() -> None:
    marker = "response-body-must-not-leak"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=marker)

    with pytest.raises(GitHubReviewSourceError) as caught:
        await _source(handler).fetch(repository="example/project", pull_number=7)

    assert marker not in str(caught.value)


async def test_token_provider_failure_is_sanitized_before_network() -> None:
    marker = "credential-provider-detail"

    async def broken_token() -> str:
        raise RuntimeError(marker)

    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("network MUST NOT be called when authentication fails")

    source = GitHubPullRequestSource(
        config=GitHubReviewSourceConfig(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        token_provider=broken_token,
    )
    with pytest.raises(GitHubReviewSourceError, match="authentication is unavailable") as caught:
        await source.fetch(repository="example/project", pull_number=7)

    assert marker not in str(caught.value)


async def test_response_cap_is_enforced_while_streaming() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2048)

    with pytest.raises(GitHubReviewLimitError, match="response exceeds"):
        await _source(handler, max_response_bytes=1024).fetch(
            repository="example/project",
            pull_number=7,
        )


@pytest.mark.parametrize(
    "unsafe_path",
    ("/absolute.py", "src/../secret.py", "src\\secret.py", "./src/example.py", "src//x.py"),
)
async def test_noncanonical_file_paths_are_rejected(unsafe_path: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files"):
            file = _file(1)
            file["filename"] = unsafe_path
            return httpx.Response(200, json=[file])
        return httpx.Response(200, json=_metadata())

    with pytest.raises(GitHubReviewSourceError, match="filename is invalid"):
        await _source(handler).fetch(repository="example/project", pull_number=7)


def test_config_rejects_unsafe_or_out_of_bounds_settings() -> None:
    with pytest.raises(ValueError, match="credential-free HTTPS URL"):
        GitHubReviewSourceConfig(api_base="http://api.github.com")
    with pytest.raises(ValueError, match="timeout MUST be positive"):
        GitHubReviewSourceConfig(timeout_seconds=0)
    with pytest.raises(ValueError, match="max_files MUST be in"):
        GitHubReviewSourceConfig(max_files=0)
    with pytest.raises(ValueError, match="byte and patch budgets MUST be at least 1024"):
        GitHubReviewSourceConfig(max_response_bytes=512)


async def test_fetch_with_token_and_zero_changed_files_or_null_patch() -> None:
    seen_auth: list[str] = []

    async def token_provider() -> str:
        return "token-example"

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization", ""))
        if request.url.path.endswith("/files"):
            item = _file(1)
            item["patch"] = None
            return httpx.Response(200, json=[item])
        return httpx.Response(200, json=_metadata(changed_files=1))

    source = GitHubPullRequestSource(
        config=GitHubReviewSourceConfig(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        token_provider=token_provider,
    )
    snapshot = await source.fetch(repository="example/project", pull_number=7)
    assert snapshot.files[0].patch is None
    assert all(value.startswith("Bearer ") for value in seen_auth)


@pytest.mark.parametrize(
    ("repository", "pull_number", "match"),
    [
        ("invalid-repo", 7, "owner/name syntax"),
        ("example/project", 0, "pull_number MUST be positive"),
    ],
)
async def test_fetch_validates_request_arguments(
    repository: str, pull_number: int, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        await _source(lambda _req: httpx.Response(200, json=_metadata())).fetch(
            repository=repository,
            pull_number=pull_number,
        )


@pytest.mark.parametrize(
    ("mode", "error_type", "match"),
    [
        ("non_object_metadata", GitHubReviewSourceError, "response MUST be an object"),
        ("bad_metadata_fields", GitHubReviewSourceError, "metadata is invalid"),
        ("non_array_files", GitHubReviewSourceError, "files response MUST be an array"),
        ("empty_files_page", GitHubReviewSourceError, "file count does not match"),
        ("patch_cap", GitHubReviewLimitError, "character cap"),
        ("files_overflow", GitHubReviewLimitError, "exceed configured file cap"),
        ("redirect", GitHubReviewSourceError, "redirects are not accepted"),
        ("http_transport_error", GitHubReviewSourceError, "request failed"),
        ("invalid_json", GitHubReviewSourceError, "response is not JSON"),
        ("non_object_file", GitHubReviewSourceError, "file entry MUST be an object"),
        ("invalid_status", GitHubReviewSourceError, "file status is invalid"),
        ("invalid_patch", GitHubReviewSourceError, "patch is invalid"),
        ("invalid_additions", GitHubReviewSourceError, "additions count is invalid"),
    ],
)
async def test_fetch_rejects_malformed_or_overflowing_github_responses(
    mode: str,
    error_type: type[Exception],
    match: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if mode == "redirect":
            return httpx.Response(302)
        if mode == "http_transport_error":
            raise httpx.ConnectError("network down")
        if mode == "invalid_json":
            return httpx.Response(200, content=b"{not-json")
        if not request.url.path.endswith("/files"):
            if mode == "non_object_metadata":
                return httpx.Response(200, json=["not-an-object"])
            if mode == "bad_metadata_fields":
                return httpx.Response(200, json={"base": {}, "head": {}, "changed_files": -1})
            return httpx.Response(200, json=_metadata(changed_files=1))
        if mode == "non_array_files":
            return httpx.Response(200, json={"items": []})
        if mode == "empty_files_page":
            return httpx.Response(200, json=[])
        if mode == "patch_cap":
            big = _file(1)
            big["patch"] = "+" + ("x" * 2048)
            return httpx.Response(200, json=[big])
        if mode == "files_overflow":
            return httpx.Response(200, json=[_file(1), _file(2)])
        if mode == "non_object_file":
            return httpx.Response(200, json=["bad"])
        if mode == "invalid_status":
            bad = _file(1)
            bad["status"] = ""
            return httpx.Response(200, json=[bad])
        if mode == "invalid_patch":
            bad = _file(1)
            bad["patch"] = 123
            return httpx.Response(200, json=[bad])
        bad = _file(1)
        bad["additions"] = True
        return httpx.Response(200, json=[bad])

    source = GitHubPullRequestSource(
        config=GitHubReviewSourceConfig(max_files=1, max_total_patch_chars=1024),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        token_provider=_no_token,
    )
    with pytest.raises(error_type, match=match):
        await source.fetch(repository="example/project", pull_number=7)
