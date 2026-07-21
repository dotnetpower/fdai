from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.types import Message, Scope

from fdai.delivery.read_api.app.authoritative_proxy import (
    AuthoritativeReadProxy,
    AuthoritativeReadProxyMiddleware,
)


def _app(proxy: AuthoritativeReadProxy) -> Starlette:
    async def local(_request):  # type: ignore[no-untyped-def]
        return JSONResponse({"source": "local"})

    return Starlette(
        routes=[Route("/kpi", local), Route("/local", local)],
        middleware=[Middleware(AuthoritativeReadProxyMiddleware, proxy=proxy)],
    )


class _FailingStream(httpx.AsyncByteStream):
    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield b"partial"
        raise httpx.ReadError("stream interrupted")


async def _proxy_messages(proxy: AuthoritativeReadProxy) -> list[Message]:
    messages: list[Message] = []
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/audit",
        "raw_path": b"/audit",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"authorization", b"Bearer token")],
        "client": None,
        "server": None,
    }

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        messages.append(message)

    await proxy(scope, receive, send)
    return messages


def test_proxy_forwards_only_allowlisted_gets_with_bearer_and_query() -> None:
    seen: list[httpx.Request] = []

    def remote(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"source": "remote", "query": request.url.query.decode()},
            headers={"cache-control": "public, max-age=3600"},
        )

    remote_client = httpx.AsyncClient(transport=httpx.MockTransport(remote))
    proxy = AuthoritativeReadProxy(base_url="https://read.example.test", client=remote_client)
    with TestClient(_app(proxy)) as client:
        response = client.get(
            "/kpi?window=7d",
            headers={"authorization": "Bearer signed-token"},
        )
        local = client.get("/local")
        post = client.post("/kpi")

    assert response.json() == {"source": "remote", "query": "window=7d"}
    assert response.headers.get_list("cache-control") == ["no-store"]
    assert seen[0].headers["authorization"] == "Bearer signed-token"
    assert local.json() == {"source": "local"}
    assert post.status_code == 405


async def test_proxy_returns_503_when_remote_fails_before_response_start() -> None:
    async def fail(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("remote unavailable")

    proxy = AuthoritativeReadProxy(
        base_url="https://read.example.test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(fail)),
    )

    messages = await _proxy_messages(proxy)

    starts = [message for message in messages if message["type"] == "http.response.start"]
    assert len(starts) == 1
    assert starts[0]["status"] == 503


async def test_proxy_closes_body_without_second_start_when_remote_stream_fails() -> None:
    proxy = AuthoritativeReadProxy(
        base_url="https://read.example.test",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=_FailingStream()))
        ),
    )

    messages = await _proxy_messages(proxy)

    starts = [message for message in messages if message["type"] == "http.response.start"]
    assert len(starts) == 1
    assert starts[0]["status"] == 200
    assert messages[-1] == {"type": "http.response.body", "body": b"", "more_body": False}


def test_proxy_handles_canonical_context_selection_comparisons_route() -> None:
    proxy = AuthoritativeReadProxy(
        base_url="https://read.example.test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
    )

    assert proxy.handles("/context-selection-comparisons") is True
    assert proxy.handles("/context-selection/comparisons") is False


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        ("/audit", True),
        ("/rca", True),
        ("/reports/monthly", True),
        ("/views/process/run-1", True),
        ("/reports/../local", False),
        ("/reports/./monthly", False),
        ("/reports//monthly", False),
        ("/reports/%2e%2e/local", False),
        ("/reports%2Fmonthly", False),
        ("/reports\\..\\local", False),
        ("/reports/monthly\n", False),
    ),
)
def test_proxy_requires_canonical_allowlisted_paths(path: str, expected: bool) -> None:
    proxy = AuthoritativeReadProxy(
        base_url="https://read.example.test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
    )

    assert proxy.handles(path) is expected


def test_proxy_requires_bearer_and_rejects_unsafe_origins() -> None:
    proxy = AuthoritativeReadProxy(
        base_url="https://read.example.test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
    )
    with TestClient(_app(proxy)) as client:
        response = client.get("/audit")
    assert response.status_code == 401

    for value in (
        "http://read.example.test",
        "https://user:secret@read.example.test",
        "https://read.example.test/api",
    ):
        with pytest.raises(ValueError):
            AuthoritativeReadProxy(base_url=value)


@pytest.mark.parametrize(
    "authorization",
    (None, "Bearer ", "Basic token", "Bearer token with-space"),
)
def test_proxy_rejects_malformed_bearer_without_remote_request(
    authorization: str | None,
) -> None:
    remote = httpx.MockTransport(
        lambda _: pytest.fail("malformed bearer MUST NOT reach the remote API")
    )
    proxy = AuthoritativeReadProxy(
        base_url="https://read.example.test",
        client=httpx.AsyncClient(transport=remote),
    )
    headers = {} if authorization is None else {"authorization": authorization}

    with TestClient(_app(proxy)) as client:
        response = client.get("/audit", headers=headers)

    assert response.status_code == 401


@pytest.mark.parametrize("scheme", ("Bearer", "bearer", "BEARER"))
def test_proxy_accepts_case_insensitive_bearer_scheme(scheme: str) -> None:
    proxy = AuthoritativeReadProxy(
        base_url="https://read.example.test",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True}))
        ),
    )

    with TestClient(_app(proxy)) as client:
        response = client.get("/audit", headers={"authorization": f"{scheme} token"})

    assert response.status_code == 200
