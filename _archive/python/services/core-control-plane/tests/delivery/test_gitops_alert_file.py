"""Existing-file read conformance for the real publisher with a no-network HTTP transport."""

import base64

import httpx
import pytest
from fdai.delivery.gitops_pr.adapter import GitOpsPrAdapter, GitOpsPrConfig


@pytest.mark.parametrize(
    "problem", [None, "redirect", "directory", "path", "size", "utf8", "encoding", "symlink"]
)
async def test_read_existing_never_follows_download_or_changes_repo(problem: str | None) -> None:
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path == "/repos/example/example/contents/infra/alerts.tf.json"
        assert request.url.params["ref"] == "main"
        content = b"{}\n" if problem != "utf8" else b"\xff"
        row = {
            "path": "infra/alerts.tf.json",
            "type": "file",
            "encoding": "base64",
            "size": len(content),
            "content": base64.b64encode(content).decode(),
        }
        if problem == "redirect":
            return httpx.Response(302, headers={"location": "https://example.com/private"})
        if problem == "directory":
            row["type"] = "dir"
        if problem == "path":
            row["path"] = "other.tf.json"
        if problem == "size":
            row["size"] = 10_000_000
        if problem == "encoding":
            row["content"] = "not base64!"
        if problem == "symlink":
            row["target"] = "other.tf.json"
        return httpx.Response(200, json=row)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        adapter = GitOpsPrAdapter(
            config=GitOpsPrConfig(owner="example", repo="example"),
            http_client=http,
            token="synthetic-test-token",
        )
        if problem is None:
            assert await adapter.read_existing("infra/alerts.tf.json") == "{}\n"
        else:
            with pytest.raises(ValueError, match="unavailable"):
                await adapter.read_existing("infra/alerts.tf.json")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "path",
    ["../alerts.tf.json", "/alerts.tf.json", "a//alerts.tf.json", ".git/config", "a%2fb.tf.json"],
)
async def test_invalid_path_never_contacts_provider(path: str) -> None:
    def deny(_: httpx.Request) -> httpx.Response:
        pytest.fail("invalid path reached provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(deny)) as http:
        adapter = GitOpsPrAdapter(
            config=GitOpsPrConfig(owner="example", repo="example"),
            http_client=http,
            token="synthetic-test-token",
        )
        with pytest.raises(ValueError):
            await adapter.read_existing(path)
