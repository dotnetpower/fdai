"""Offline contract tests for the PAT controller's provider boundaries."""

from __future__ import annotations

import base64
import hashlib
import io
from collections.abc import Mapping
from dataclasses import dataclass
from http.client import HTTPMessage
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request

import pytest
from scripts.automation.runner_controller import azure, github, transport
from scripts.automation.runner_controller.azure import AzureAPI, ManagedIdentityToken
from scripts.automation.runner_controller.github import GitHubAPI
from scripts.automation.runner_controller.transport import (
    DEFAULT_ACCEPTED,
    MAX_RESPONSE_BYTES,
    HttpResponse,
    ProviderError,
    Transport,
)

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
_ROOT = f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/example"
_JOB = _ROOT + "/providers/Microsoft.App/jobs/example"
_BASE = "https://management.azure.com"
_PAT = "example-pat"


@dataclass
class Call:
    method: str
    url: str
    headers: Mapping[str, str] | None
    body: Any
    accepted: tuple[int, ...]


class FakeTransport(Transport):
    def __init__(self, *responses: HttpResponse | ProviderError) -> None:
        self.responses = list(responses)
        self.calls: list[Call] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: Any = None,
        accepted: tuple[int, ...] = DEFAULT_ACCEPTED,
    ) -> HttpResponse:
        self.calls.append(Call(method, url, headers, body, accepted))
        assert self.responses, "Unexpected provider call"
        result = self.responses.pop(0)
        if isinstance(result, ProviderError):
            raise result
        return result


def reply(data: Any = None, status: int = 200) -> HttpResponse:
    return HttpResponse(status, data, {})


def client(fake: FakeTransport) -> AzureAPI:
    return AzureAPI(_SUBSCRIPTION, "example", lambda: "example-arm-token", fake)


class WireResponse(io.BytesIO):
    def __init__(self, data: bytes = b"{}", status: int = 200) -> None:
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Type": "application/json"}
        self.read_bounds: list[int | None] = []

    def read(self, size: int | None = -1) -> bytes:
        self.read_bounds.append(size)
        return super().read(size)


def wire(monkeypatch: pytest.MonkeyPatch, result: WireResponse | Exception) -> list[Any]:
    requests: list[Any] = []

    class Opener:
        def open(self, request: Any, *, timeout: int) -> WireResponse:
            requests.append(request)
            assert timeout == 20
            if isinstance(result, Exception):
                raise result
            return result

    def build(*handlers: Any) -> Opener:
        redirect = next(handler for handler in handlers if isinstance(handler, HTTPRedirectHandler))
        assert (
            redirect.redirect_request(
                Request("https://example.com"),
                io.BytesIO(),
                302,
                "",
                HTTPMessage(),
                "https://example.com",
            )
            is None
        )
        assert any(getattr(handler, "proxies", None) == {} for handler in handlers)
        return Opener()

    monkeypatch.setattr(transport, "build_opener", build)
    return requests


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308, 401, 429, 503])
def test_transport_errors_are_redacted_and_never_retried(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    sensitive_url = "https://example.com/?token=example-secret"
    error = HTTPError(
        sensitive_url, status, "example-secret", HTTPMessage(), io.BytesIO(b"example-secret")
    )
    requests = wire(monkeypatch, error)
    with pytest.raises(ProviderError) as caught:
        Transport().request("GET", sensitive_url, headers={"Authorization": _PAT}, accepted=(302,))
    assert caught.value.status == status
    assert len(requests) == 1
    assert "example-secret" not in str(caught.value)
    assert "example.com" not in str(caught.value)
    assert "example-secret" not in repr(caught.value)
    assert caught.value.__suppress_context__
    assert "example-secret" not in str(ProviderError("example-secret"))


def test_transport_network_error_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = wire(monkeypatch, URLError("example-secret"))
    with pytest.raises(ProviderError) as caught:
        Transport().request("GET", "https://example.com")
    assert caught.value.status is None
    assert "example-secret" not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.parametrize("status", [404, 409, 412, 422, 429, 503])
def test_transport_honors_accepted_error_statuses_and_headers(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    headers = HTTPMessage()
    headers["x-ms-request-id"] = "example"
    requests = wire(
        monkeypatch,
        HTTPError("https://example.com", status, "example-secret", headers, io.BytesIO()),
    )
    response = Transport().request("GET", "https://example.com", accepted=(status,))
    assert response.status == status
    assert response.headers["x-ms-request-id"] == "example"
    assert response.data is None
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [b"", b"not-json", b"\xff", b'{"value":NaN}'])
def test_transport_validates_json(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    wire(monkeypatch, WireResponse(payload))
    with pytest.raises(ProviderError, match="response is invalid"):
        Transport().request("GET", "https://example.com")


def test_transport_is_bounded_and_accepts_empty_204(monkeypatch: pytest.MonkeyPatch) -> None:
    oversized = WireResponse(b" " * (MAX_RESPONSE_BYTES + 2))
    wire(monkeypatch, oversized)
    with pytest.raises(ProviderError, match="size limit"):
        Transport().request("GET", "https://example.com")
    assert oversized.read_bounds == [MAX_RESPONSE_BYTES + 1]
    wire(monkeypatch, WireResponse(b"", 204))
    assert Transport().request("DELETE", "https://example.com").data is None
    wire(monkeypatch, WireResponse(b"", 202))
    assert Transport().request("DELETE", "https://example.com").data is None
    requests = wire(monkeypatch, WireResponse(b'{"id":1}'))
    assert Transport().request("POST", "https://example.com", body={"value": 2}).data == {"id": 1}
    assert requests[0].data == b'{"value": 2}'


@pytest.mark.parametrize(
    "repository",
    ["owner", "a/b/c", "../repo", "owner/..", "owner/repo?x=y", "owner/repo#x", "owner/r%2fo"],
)
def test_github_repository_scope(repository: str) -> None:
    with pytest.raises(ProviderError):
        GitHubAPI(_PAT, repository, FakeTransport())


def test_github_pagination_is_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTransport(
        reply({"total_count": 101, "runners": [{"id": number} for number in range(1, 101)]}),
        reply({"total_count": 101, "runners": [{"id": 101}]}),
        reply({"id": 17}),
    )
    api = GitHubAPI(_PAT, "example/repo", fake)
    assert len(api.runners()) == 101
    assert api.repository_id() == 17
    assert all(
        call.url.startswith("https://api.github.com/repos/example/repo") for call in fake.calls
    )
    assert "per_page=100&page=2" in fake.calls[1].url
    assert _PAT not in repr(api)
    assert fake.calls[0].headers is not None
    assert fake.calls[0].headers["Authorization"] == f"Bearer {_PAT}"
    monkeypatch.setattr(github, "_MAX_PAGES", 1)
    incomplete = FakeTransport(reply({"runners": [{"id": i} for i in range(1, 101)]}))
    with pytest.raises(ProviderError, match="pagination"):
        GitHubAPI(_PAT, "example/repo", incomplete).runners()


@pytest.mark.parametrize(
    "payload",
    [
        {"total_count": 2, "runners": [{"id": 1}]},
        {"runners": [{"id": 1}, {"id": 1}]},
        {"runners": [{"id": True}]},
        {"runners": "example-secret"},
    ],
)
def test_github_rejects_incomplete_or_invalid_pages(payload: Any) -> None:
    with pytest.raises(ProviderError):
        GitHubAPI(_PAT, "example/repo", FakeTransport(reply(payload))).runners()


def test_queued_jobs_preserve_run_provenance_and_latest_attempt() -> None:
    run = {
        "id": 20,
        "status": "in_progress",
        "head_sha": "a" * 40,
        "event": "pull_request",
        "path": ".github/workflows/ci.yml",
        "head_repository": {"id": 17},
        "actor": {"login": "example-user"},
    }
    fake = FakeTransport(
        reply({"workflow_runs": [run, {"id": 21, "status": "waiting"}]}),
        reply(
            {
                "total_count": 101,
                "jobs": [
                    {"id": i, "status": "queued" if i == 1 else "completed"} for i in range(1, 101)
                ],
            }
        ),
        reply({"total_count": 101, "jobs": [{"id": 101, "status": "in_progress"}]}),
        reply({"workflow_runs": [run]}),
    )
    jobs = GitHubAPI(_PAT, "example/repo", fake).queued_jobs()
    assert [job["id"] for job in jobs] == [1, 101]
    assert all(job["_run"] == run for job in jobs)
    assert "filter=latest" in fake.calls[1].url
    assert "page=2" in fake.calls[2].url
    assert "status=in_progress" in fake.calls[-1].url
    assert not any("/runs/21/" in call.url for call in fake.calls)


def test_jit_is_memory_only_and_manual_configuration_is_exact(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeTransport(reply({"runner": {"id": 7}, "encoded_jit_config": "example-jit"}, 201))
    api = GitHubAPI(_PAT, "example/repo", fake)
    assert api.jit("example-runner", ["self-hosted", "example"]) == (7, "example-jit")
    assert fake.calls[0].body == {
        "name": "example-runner",
        "labels": ["self-hosted", "example"],
        "runner_group_id": 1,
        "work_folder": "_work",
    }
    captured = capsys.readouterr()
    assert not captured.out and not captured.err and not caplog.text
    assert "example-jit" not in repr(api)


@pytest.mark.parametrize("busy", [True, None, "false", 0])
def test_busy_or_unconfirmed_runner_is_never_deleted(busy: Any) -> None:
    fake = FakeTransport(reply({"id": 7, "name": "example", "busy": busy}))
    assert not GitHubAPI(_PAT, "example/repo", fake).remove_idle(7, "example")
    assert len(fake.calls) == 1


@pytest.mark.parametrize("status,expected", [(204, True), (404, True), (409, False), (422, False)])
@pytest.mark.parametrize("raised", [False, True])
def test_idle_delete_handles_races(status: int, expected: bool, raised: bool) -> None:
    result = (
        ProviderError("http_status", status) if raised and status != 204 else reply(None, status)
    )
    fake = FakeTransport(reply({"id": 7, "name": "example", "busy": False}), result)
    assert GitHubAPI(_PAT, "example/repo", fake).remove_idle(7, "example") is expected
    assert [call.method for call in fake.calls] == ["GET", "DELETE"]


def test_runner_removal_checks_exact_identity_and_absence() -> None:
    for data in (
        {"id": 8, "name": "example", "busy": False},
        {"id": 7, "name": "other", "busy": False},
    ):
        fake = FakeTransport(reply(data))
        assert not GitHubAPI(_PAT, "example/repo", fake).remove_idle(7, "example")
        assert len(fake.calls) == 1
    fake = FakeTransport(reply(None, 404))
    assert GitHubAPI(_PAT, "example/repo", fake).remove_idle(7, "example")
    assert len(fake.calls) == 1


@pytest.mark.parametrize("invalid", [True, 0, -1, "7/../../runners", 1.0, None])
def test_invalid_ids_never_reach_provider(invalid: Any) -> None:
    fake = FakeTransport()
    api = GitHubAPI(_PAT, "example/repo", fake)
    for method in (api.run, api.job):
        with pytest.raises(ProviderError):
            method(invalid)
    with pytest.raises(ProviderError):
        api.remove_idle(invalid, "example")
    assert not fake.calls


def test_lookup_permission_and_workflow_digest() -> None:
    content = b"name: CI\n"
    fake = FakeTransport(
        reply({"id": 7}),
        reply({"id": 8}),
        reply({"permission": "write"}),
        reply(
            {
                "type": "file",
                "encoding": "base64",
                "size": len(content),
                "content": base64.encodebytes(content).decode(),
            }
        ),
    )
    api = GitHubAPI(_PAT, "example/repo", fake)
    assert api.run(7)["id"] == 7
    assert api.job(8)["id"] == 8
    assert api.permission("example-user") == "write"
    ref = "refs/heads/example?x=y"
    assert api.workflow_digest(ref) == hashlib.sha256(content).hexdigest()
    assert parse_qs(urlsplit(fake.calls[-1].url).query) == {"ref": [ref]}
    with pytest.raises(ProviderError):
        api.permission("../example")


@pytest.mark.parametrize(
    "change",
    [
        {"size": 2**30},
        {"content": "not base64!"},
        {"encoding": "none"},
        {"type": "symlink"},
        {"size": 9},
        {"content": "a" * (2 * 1024 * 1024 + 1)},
    ],
)
def test_workflow_digest_rejects_malformed_or_oversized_content(change: dict[str, Any]) -> None:
    data = {"type": "file", "encoding": "base64", "size": 1, "content": "YQ==", **change}
    with pytest.raises(ProviderError):
        GitHubAPI(_PAT, "example/repo", FakeTransport(reply(data))).workflow_digest("a" * 40)


@pytest.mark.parametrize(
    "path",
    [
        _ROOT + "/../other",
        _ROOT + "/./providers",
        _ROOT + "/%2e%2e/other",
        _ROOT + "/%252e%252e/other",
        _ROOT + "/providers%2fother",
        _ROOT + "//providers",
        _ROOT + "/providers\\other",
        _ROOT + "/providers?api-version=other",
        _ROOT + "/providers#fragment",
        _ROOT + "/providers\n",
        _ROOT + "/providers\x00",
        _ROOT + "-other/providers",
        _ROOT.replace("/example", "/other") + "/providers",
        _ROOT.replace(_SUBSCRIPTION, "00000000-0000-0000-0000-000000000001"),
        "https://management.azure.com" + _ROOT,
        "//example.com" + _ROOT,
    ],
)
def test_azure_scope_escapes_fail_before_token_or_network(path: str) -> None:
    fake = FakeTransport()

    def forbidden_token() -> str:
        pytest.fail("Token requested for an out-of-scope resource")

    api = AzureAPI(_SUBSCRIPTION, "example", forbidden_token, fake)
    with pytest.raises(ProviderError, match="scope"):
        api.request("GET", path)
    assert not fake.calls


def test_azure_manual_start_and_resource_operations() -> None:
    fake = FakeTransport(
        reply({"name": "example-execution"}),
        reply({"name": "example-execution"}),
        reply(None, 204),
        reply({"id": "example"}),
        reply({"id": "example"}),
        reply(None, 202),
    )
    api = client(fake)
    template = {"containers": [{"name": "example", "env": [{"name": "JIT", "value": "example"}]}]}
    assert api.start_container("example", template) == "example-execution"
    assert fake.calls[0].body == {"template": template}
    assert fake.calls[0].method == "POST"
    assert urlsplit(fake.calls[0].url).path == _JOB + "/start"
    assert api.container_execution("example", "example-execution")["name"] == "example-execution"
    api.stop_container("example", "example-execution")
    path = _ROOT + "/providers/Microsoft.Compute/virtualMachines/example"
    assert api.put_resource(path, {"location": "example"}, "2024-07-01")["id"] == "example"
    assert api.get_resource(path, "2024-07-01")["id"] == "example"
    api.delete_resource(path, "2024-07-01")
    assert [call.method for call in fake.calls] == ["POST", "GET", "POST", "PUT", "GET", "DELETE"]
    assert all(call.url.startswith(_BASE + _ROOT) for call in fake.calls)


def test_azure_execution_pagination_is_complete() -> None:
    next_link = _BASE + _JOB + "/executions?api-version=2024-03-01&$skiptoken=example"
    fake = FakeTransport(
        reply({"value": [{"name": "first"}], "nextLink": next_link}),
        reply({"value": [{"name": "second"}]}),
    )
    assert client(fake).container_executions("example") == [{"name": "first"}, {"name": "second"}]
    assert parse_qs(urlsplit(fake.calls[-1].url).query)["$skiptoken"] == ["example"]


@pytest.mark.parametrize(
    "next_link",
    [
        "https://example.com" + _JOB + "/executions?api-version=2024-03-01",
        _BASE + _JOB.replace("/example/", "/other/") + "/executions?api-version=2024-03-01",
        _BASE + _JOB + "/executions/../other?api-version=2024-03-01",
        _BASE + _JOB + "/executions?api-version=2024-03-01#fragment",
        _BASE + _JOB + "/executions?api-version=2024-03-01&api-version=2024-03-01",
        _BASE + _JOB + "/executions?api-version=other",
        "http://management.azure.com" + _JOB + "/executions?api-version=2024-03-01",
        "https://management.azure.com@example.com" + _JOB + "/executions?api-version=2024-03-01",
    ],
)
def test_azure_off_scope_pagination_fails_closed(next_link: str) -> None:
    fake = FakeTransport(reply({"value": [], "nextLink": next_link}))
    with pytest.raises(ProviderError):
        client(fake).container_executions("example")
    assert len(fake.calls) == 1


def test_azure_pagination_limit_and_api_version_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(azure, "_MAX_PAGES", 1)
    next_link = _BASE + _JOB + "/executions?api-version=2024-03-01&$skiptoken=example"
    fake = FakeTransport(reply({"value": [], "nextLink": next_link}), reply({"value": []}))
    with pytest.raises(ProviderError, match="pagination"):
        client(fake).container_executions("example")
    assert len(fake.calls) == 1
    with pytest.raises(ProviderError):
        client(FakeTransport()).request("GET", _ROOT, api_version="2024-03-01&other=example")


@pytest.mark.parametrize("method", ["TRACE", "CONNECT", "GET\n", "get"])
def test_azure_method_allowlist_precedes_token_acquisition(method: str) -> None:
    fake = FakeTransport()

    def forbidden_token() -> str:
        pytest.fail("Token requested for an unsupported method")

    api = AzureAPI(_SUBSCRIPTION, "example", forbidden_token, fake)
    with pytest.raises(ProviderError):
        api.request(method, _ROOT)
    assert not fake.calls


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com/msi/token",
        "https://8.8.8.8/msi/token",
        "file:///msi/token",
        "http://127.0.0.1/msi/token?resource=other",
        "http://127.0.0.1/msi/token?",
        "http://127.0.0.1/msi/token#fragment",
        "http://127.0.0.1/msi/token#",
        "http://user@127.0.0.1/msi/token",
        "http://127.0.0.1/msi/../token",
        "http://127.0.0.1/msi/%74oken",
        "http://0.0.0.0/msi/token",
        "",
    ],
)
def test_managed_identity_rejects_nonlocal_or_ambiguous_endpoint(
    monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", endpoint)
    monkeypatch.setenv("IDENTITY_HEADER", "example-identity-header")
    fake = FakeTransport()
    with pytest.raises(ProviderError):
        ManagedIdentityToken(transport=fake)()
    assert not fake.calls


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "169.254.169.254", "10.0.0.1", "[::1]"])
@pytest.mark.parametrize(
    "resource", ["https://management.azure.com/", "https://storage.azure.com/"]
)
def test_managed_identity_uses_only_platform_endpoint(
    monkeypatch: pytest.MonkeyPatch, host: str, resource: str, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", f"http://{host}:42356/msi/token")
    monkeypatch.setenv("IDENTITY_HEADER", "example-identity-header")
    fake = FakeTransport(reply({"access_token": "example-arm-token"}))
    identity = ManagedIdentityToken(resource, fake)
    assert identity() == "example-arm-token"
    assert fake.calls[0].headers == {"X-IDENTITY-HEADER": "example-identity-header"}
    assert parse_qs(urlsplit(fake.calls[0].url).query) == {
        "api-version": ["2019-08-01"],
        "resource": [resource],
    }
    assert not caplog.text
    assert "example-arm-token" not in repr(identity)


def test_managed_identity_rejects_unapproved_audience_and_missing_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTransport()
    with pytest.raises(ProviderError):
        ManagedIdentityToken("https://example.com/", fake)
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://127.0.0.1/msi/token")
    monkeypatch.delenv("IDENTITY_HEADER", raising=False)
    with pytest.raises(ProviderError):
        ManagedIdentityToken(transport=fake)()
    assert not fake.calls


@pytest.mark.parametrize("as_error", [False, True])
def test_transport_304_requires_explicit_acceptance(
    monkeypatch: pytest.MonkeyPatch, as_error: bool
) -> None:
    headers = HTTPMessage()
    headers["ETag"] = '"example"'
    response: WireResponse | HTTPError = (
        HTTPError("https://example.com", 304, "", headers, io.BytesIO())
        if as_error
        else WireResponse(b"", 304)
    )
    wire(monkeypatch, response)
    with pytest.raises(ProviderError) as caught:
        Transport().request("GET", "https://example.com")
    assert caught.value.status == 304
    response = (
        HTTPError("https://example.com", 304, "", headers, io.BytesIO())
        if as_error
        else WireResponse(b"", 304)
    )
    requests = wire(monkeypatch, response)
    assert Transport().request("GET", "https://example.com", accepted=(200, 304)).status == 304
    assert len(requests) == 1


def test_authenticated_etag_304_reuses_isolated_body_and_refreshes_validator() -> None:
    original = {"id": 20, "status": "in_progress", "actor": {"login": "example-user"}}
    original_headers = {"etag": '"first"'}
    fake = FakeTransport(
        HttpResponse(200, original, original_headers),
        HttpResponse(304, None, {"ETag": 'W/"second"'}),
        reply(None, 304),
    )
    api = GitHubAPI(_PAT, "example/repo", fake)
    first = api.run(20)
    first["status"] = "completed"
    first["actor"]["login"] = "mutated"
    original_headers["etag"] = '"mutated"'
    second = api.run(20)
    assert second["status"] == "in_progress"
    assert second["actor"]["login"] == "example-user"
    second["actor"]["login"] = "mutated-again"
    assert api.run(20)["actor"]["login"] == "example-user"
    assert 304 not in fake.calls[0].accepted
    assert fake.calls[0].headers is not None
    assert "If-None-Match" not in fake.calls[0].headers
    for call, etag in zip(fake.calls[1:], ['"first"', 'W/"second"'], strict=True):
        assert 304 in call.accepted
        assert call.headers is not None
        assert call.headers["If-None-Match"] == etag
        assert call.headers["Authorization"] == f"Bearer {_PAT}"
        assert call.url == "https://api.github.com/repos/example/repo/actions/runs/20"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
@pytest.mark.parametrize("raised", [True, False])
def test_etag_cache_never_substitutes_for_provider_error(status: int, raised: bool) -> None:
    failure = ProviderError("http_status", status) if raised else reply(None, status)
    fake = FakeTransport(HttpResponse(200, {"id": 20}, {"ETag": '"example"'}), failure)
    api = GitHubAPI(_PAT, "example/repo", fake)
    assert api.run(20)["id"] == 20
    with pytest.raises(ProviderError) as caught:
        api.run(20)
    assert caught.value.status == status
    assert len(fake.calls) == 2


@pytest.mark.parametrize(
    "initial",
    [
        None,
        reply({"id": 20}),
        HttpResponse(200, None, {"ETag": '"example"'}),
        HttpResponse(200, {"id": 20}, {"ETag": ""}),
        HttpResponse(200, {"id": 20}, {"ETag": "example\ninjected"}),
    ],
)
def test_304_without_valid_cached_body_is_invalid(initial: HttpResponse | None) -> None:
    fake = FakeTransport(*([initial] if initial is not None else []), reply(None, 304))
    api = GitHubAPI(_PAT, "example/repo", fake)
    if initial is not None:
        api._request("GET", "/actions/runs/20")
    with pytest.raises(ProviderError) as caught:
        api._request("GET", "/actions/runs/20", accepted=(200, 304))
    assert caught.value.status == 304
    assert 304 not in fake.calls[-1].accepted


def test_etag_200_refreshes_dynamic_status_and_missing_etag_discards_cache() -> None:
    fake = FakeTransport(
        HttpResponse(200, {"id": 20, "status": "queued"}, {"ETag": '"queued"'}),
        HttpResponse(200, {"id": 20, "status": "in_progress"}, {"ETag": '"running"'}),
        reply({"id": 20, "status": "completed"}),
        reply({"id": 20, "status": "completed"}),
    )
    api = GitHubAPI(_PAT, "example/repo", fake)
    assert [api.run(20)["status"] for _ in range(4)] == [
        "queued",
        "in_progress",
        "completed",
        "completed",
    ]
    assert fake.calls[2].headers is not None
    assert fake.calls[2].headers["If-None-Match"] == '"running"'
    assert fake.calls[3].headers is not None
    assert "If-None-Match" not in fake.calls[3].headers


def test_etag_pagination_keys_keep_pages_and_filters_distinct() -> None:
    first = {"total_count": 101, "runners": [{"id": number} for number in range(1, 101)]}
    second = {"total_count": 101, "runners": [{"id": 101}]}
    fake = FakeTransport(
        HttpResponse(200, first, {"ETag": '"page1"'}),
        HttpResponse(200, second, {"ETag": '"page2"'}),
        reply(None, 304),
        reply(None, 304),
        reply({"workflow_runs": []}),
        reply({"workflow_runs": []}),
    )
    api = GitHubAPI(_PAT, "example/repo", fake)
    assert len(api.runners()) == len(api.runners()) == 101
    assert api.queued_jobs() == []
    assert fake.calls[2].headers is not None and fake.calls[3].headers is not None
    assert fake.calls[2].headers["If-None-Match"] == '"page1"'
    assert fake.calls[3].headers["If-None-Match"] == '"page2"'
    assert all(
        call.headers is not None and "If-None-Match" not in call.headers for call in fake.calls[4:]
    )


def test_non_get_requests_are_never_conditional_and_cache_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(github, "_MAX_CACHED_GETS", 1)
    fake = FakeTransport(
        HttpResponse(200, {"id": 20}, {"ETag": '"first"'}),
        HttpResponse(200, {"id": 21}, {"ETag": '"second"'}),
        reply({"id": 20}),
        reply(None, 204),
    )
    api = GitHubAPI(_PAT, "example/repo", fake)
    api.run(20)
    api.run(21)
    api.run(20)
    api._request("DELETE", "/actions/runs/21", accepted=(204, 304))
    for call in fake.calls[2:]:
        assert call.headers is not None
        assert "If-None-Match" not in call.headers
        assert 304 not in call.accepted


def test_303_remains_refused_even_when_conditional_get_accepts_304(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = GitHubAPI(
        _PAT,
        "example/repo",
        FakeTransport(HttpResponse(200, {"id": 20}, {"ETag": '"example"'})),
    )
    api.run(20)
    requests = wire(
        monkeypatch,
        HTTPError("https://api.github.com", 303, "", HTTPMessage(), io.BytesIO()),
    )
    api._transport = Transport()
    with pytest.raises(ProviderError) as caught:
        api.run(20)
    assert caught.value.status == 303
    assert len(requests) == 1
    assert requests[0].full_url == "https://api.github.com/repos/example/repo/actions/runs/20"
