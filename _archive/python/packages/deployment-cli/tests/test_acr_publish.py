from __future__ import annotations

import importlib
import json
import socket
import ssl
import sys
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fdai_deployment_cli import acr_publish
from fdai_deployment_cli.acr_publish import (
    AcrPublishError,
    HttpsRegistryTransport,
    RegistryResponse,
    publish_oci_archive,
)
from fdai_deployment_cli.oci_archive import OciArchiveError

_TESTS = str(Path(__file__).parent)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
test_oci_archive = importlib.import_module("test_oci_archive")
ArchiveFixture = test_oci_archive.ArchiveFixture
make_archive = test_oci_archive.make_archive
write_archive = test_oci_archive.write_archive

REGISTRY = "example.azurecr.io"
REPOSITORY = "fdai/operator-service"
REFRESH = "synthetic-refresh"
ACCESS = "synthetic-access"
UPLOAD = f"/v2/{REPOSITORY}/blobs/uploads/synthetic-upload"


@dataclass
class Request:
    host: str
    method: str
    target: str
    headers: Mapping[str, str] = field(repr=False)
    body: bytes = field(repr=False)
    deadline: float


class RecordingTransport:
    def __init__(self, responses: list[RegistryResponse | Exception]) -> None:
        self.responses = responses
        self.requests: list[Request] = []

    def request(
        self,
        host: str,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: Iterable[bytes],
        *,
        content_length: int,
        deadline: float,
    ) -> RegistryResponse:
        payload = b"".join(body)
        assert len(payload) == content_length
        self.requests.append(Request(host, method, target, dict(headers), payload, deadline))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def responses_for(
    fixture: ArchiveFixture,
    *,
    existing: bool = False,
    location: str = UPLOAD,
) -> list[RegistryResponse | Exception]:
    responses = [RegistryResponse(200, body=json.dumps({"access_token": ACCESS}).encode())]
    manifest = json.loads(fixture.manifest_bytes)
    for blob in [manifest["config"], *manifest["layers"]]:
        digest_header = {"Docker-Content-Digest": blob["digest"]}
        if existing:
            responses.append(RegistryResponse(200, digest_header))
        else:
            responses.extend(
                [
                    RegistryResponse(404),
                    RegistryResponse(202, {"Location": location}),
                    RegistryResponse(201, digest_header),
                ]
            )
    responses.extend(
        [
            RegistryResponse(201),
            RegistryResponse(
                200, {"Docker-Content-Digest": fixture.manifest_digest}, fixture.manifest_bytes
            ),
        ]
    )
    return list(responses)


def publish(fixture: ArchiveFixture, transport: RecordingTransport, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        **fixture.expectations(),
        "registry": REGISTRY,
        "repository": REPOSITORY,
        "credential_provider": lambda: REFRESH,
        "transport": transport,
        **overrides,
    }
    return publish_oci_archive(fixture.path, **arguments)


def test_uploads_exact_bytes_in_distribution_order_and_reads_back(tmp_path: Path) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport(responses_for(fixture, location=UPLOAD + "?_state=synthetic"))
    receipt = publish(fixture, transport)
    assert receipt.manifest_digest == fixture.manifest_digest
    assert receipt.requests == 9
    assert [request.method for request in transport.requests] == [
        "POST",
        "HEAD",
        "POST",
        "PUT",
        "HEAD",
        "POST",
        "PUT",
        "PUT",
        "GET",
    ]
    token, *authenticated = transport.requests
    assert token.target == "/oauth2/token"
    assert "Authorization" not in token.headers
    assert parse_qs(token.body.decode()) == {
        "service": [REGISTRY],
        "scope": [f"repository:{REPOSITORY}:pull,push"],
        "grant_type": ["refresh_token"],
        "refresh_token": [REFRESH],
    }
    assert all(request.host == REGISTRY for request in transport.requests)
    assert all(request.headers["Authorization"] == "Bearer " + ACCESS for request in authenticated)
    manifest = json.loads(fixture.manifest_bytes)
    for index, blob in zip((3, 6), [manifest["config"], *manifest["layers"]], strict=True):
        request = transport.requests[index]
        assert request.body == fixture.entries["blobs/sha256/" + blob["digest"][7:]]
        assert parse_qs(urlsplit(request.target).query) == {
            "_state": ["synthetic"],
            "digest": [blob["digest"]],
        }
    assert transport.requests[-2].body == fixture.manifest_bytes
    assert transport.requests[-1].target == transport.requests[-2].target
    assert not transport.requests[-1].body
    assert not transport.responses


def test_existing_blobs_are_not_reuploaded(tmp_path: Path) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport(responses_for(fixture, existing=True))
    receipt = publish(fixture, transport)
    assert receipt.requests == 5
    assert [request.method for request in transport.requests] == [
        "POST",
        "HEAD",
        "HEAD",
        "PUT",
        "GET",
    ]


def test_absolute_same_registry_upload_location_is_supported(tmp_path: Path) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport(responses_for(fixture, location=f"https://{REGISTRY}{UPLOAD}"))
    assert publish(fixture, transport).manifest_digest == fixture.manifest_digest
    assert all(request.target.startswith("/") for request in transport.requests)


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_manifest_digest": "sha256:" + "b" * 64},
        {"expected_archive_sha256": "b" * 64},
        {"expected_source_commit": "b" * 40},
        {"expected_platform_tag": "linux-aarch64"},
    ],
)
def test_no_credentials_or_http_until_all_archive_checks_pass(
    tmp_path: Path,
    overrides: dict[str, str],
) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport([])
    credentials: list[bool] = []
    with pytest.raises(OciArchiveError):
        publish(
            fixture, transport, credential_provider=lambda: credentials.append(True), **overrides
        )
    assert not transport.requests
    assert not credentials


def test_malformed_archive_prevents_even_token_exchange(tmp_path: Path) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    fixture.entries["../escaped"] = b"untrusted"
    write_archive(fixture.path, fixture.entries)
    transport = RecordingTransport([])
    with pytest.raises(OciArchiveError):
        publish(fixture, transport)
    assert not transport.requests


@pytest.mark.parametrize(
    "location",
    [
        f"https://foreign.azurecr.io{UPLOAD}",
        f"https://example.eastus.data.azurecr.io{UPLOAD}",
        f"http://{REGISTRY}{UPLOAD}",
        f"//{REGISTRY}{UPLOAD}",
        f"https://user@{REGISTRY}{UPLOAD}",
        f"https://{REGISTRY}:443{UPLOAD}",
        UPLOAD.replace(REPOSITORY, "another/repository"),
        UPLOAD + "/../other",
        UPLOAD + "%2Fother",
        UPLOAD + "?digest=sha256:foreign",
        UPLOAD + "?scope=foreign",
        UPLOAD + "?_state=one&_state=two",
        UPLOAD + "#fragment",
        UPLOAD + "\n",
        "/v2/fdai/operator-service/blobs/uploads/..",
    ],
)
def test_foreign_or_injected_upload_location_is_refused_before_forwarding(
    tmp_path: Path,
    location: str,
) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport(responses_for(fixture, location=location))
    with pytest.raises(AcrPublishError) as failure:
        publish(fixture, transport)
    assert (failure.value.stage, failure.value.status) == ("blob-start", "invalid-location")
    assert len(transport.requests) == 3
    assert all(request.host == REGISTRY for request in transport.requests)
    assert not any(request.method == "PUT" for request in transport.requests)
    assert location not in str(failure.value)


@pytest.mark.parametrize("index", [0, 3, 8])
@pytest.mark.parametrize("status", [429, 503, "timeout"])
def test_timeouts_and_rate_or_service_errors_never_retry(
    tmp_path: Path,
    index: int,
    status: int | str,
) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    responses = responses_for(fixture)
    responses[index] = (
        TimeoutError(REFRESH)
        if status == "timeout"
        else RegistryResponse(int(status), body=REFRESH.encode())
    )
    transport = RecordingTransport(responses)
    with pytest.raises(AcrPublishError) as failure:
        publish(fixture, transport)
    assert failure.value.status == ("timeout" if status == "timeout" else "http-error")
    assert failure.value.http_status == (None if status == "timeout" else status)
    assert len(transport.requests) == index + 1
    assert REFRESH not in str(failure.value)


@pytest.mark.parametrize("corruption", ["body", "header", "missing"])
def test_manifest_dispatch_is_not_success_without_independent_readback(
    tmp_path: Path,
    corruption: str,
) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    responses = responses_for(fixture)
    responses[-1] = {
        "body": RegistryResponse(200, {"Docker-Content-Digest": fixture.manifest_digest}, b"wrong"),
        "header": RegistryResponse(
            200, {"Docker-Content-Digest": "sha256:" + "b" * 64}, fixture.manifest_bytes
        ),
        "missing": RegistryResponse(404),
    }[corruption]
    transport = RecordingTransport(responses)
    with pytest.raises(AcrPublishError) as failure:
        publish(fixture, transport)
    assert failure.value.stage == "manifest-readback"
    assert len(transport.requests) == 9


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("registry", "https://example.azurecr.io"),
        ("registry", "user@example.azurecr.io"),
        ("registry", "example.azurecr.io?scope=other"),
        ("registry", "example.azurecr.io:443"),
        ("registry", "example.azurecr.io.example.com"),
        ("registry", "example.privatelink.azurecr.io"),
        ("registry", "fdai.azurecr.io"),
        ("registry", "fdai-registry.azurecr.io"),
        ("registry", "a" * 51 + ".azurecr.io"),
        ("repository", "../foreign"),
        ("repository", "fdai/image?scope=foreign"),
        ("repository", "fdai/image#tag"),
        ("repository", "fdai//image"),
    ],
)
def test_targets_are_explicit_and_not_urls(
    tmp_path: Path,
    field_name: str,
    value: str,
) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport([])
    with pytest.raises(AcrPublishError, match="invalid-target"):
        publish(fixture, transport, **{field_name: value})
    assert not transport.requests


@pytest.mark.parametrize("registry", ["fdai1.azurecr.io", "a" * 50 + ".azurecr.io"])
def test_registry_names_accept_azure_length_boundaries(tmp_path: Path, registry: str) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport(responses_for(fixture, existing=True))
    assert publish(fixture, transport, registry=registry).manifest_digest == fixture.manifest_digest
    assert all(request.host == registry for request in transport.requests)


def test_snapshot_cannot_change_during_credential_acquisition(tmp_path: Path) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport(responses_for(fixture))

    def credentials() -> str:
        fixture.path.write_bytes(b"untrusted replacement")
        return REFRESH

    publish(fixture, transport, credential_provider=credentials)
    assert transport.requests[-2].body == fixture.manifest_bytes


def test_request_budget_stops_new_calls(tmp_path: Path) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport(responses_for(fixture))
    with pytest.raises(AcrPublishError, match="request-limit"):
        publish(fixture, transport, max_requests=2)
    assert len(transport.requests) == 2


def test_late_transport_result_cannot_escape_per_call_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    clock = [100.0]
    monkeypatch.setattr(acr_publish.time, "monotonic", lambda: clock[0])

    class LateTransport(RecordingTransport):
        def request(self, *args: Any, **kwargs: Any) -> RegistryResponse:
            result = super().request(*args, **kwargs)
            clock[0] += 61
            return result

    transport = LateTransport(responses_for(fixture))
    with pytest.raises(AcrPublishError, match="token: timeout"):
        publish(fixture, transport)
    assert len(transport.requests) == 1


def test_expired_total_deadline_after_credentials_sends_no_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    clock = [100.0]
    monkeypatch.setattr(acr_publish.time, "monotonic", lambda: clock[0])

    def credentials() -> str:
        clock[0] += 301
        return REFRESH

    transport = RecordingTransport([])
    with pytest.raises(AcrPublishError, match="timeout"):
        publish(fixture, transport, credential_provider=credentials)
    assert not transport.requests


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b"{}",
        b"[]",
        b'{"access_token":"first","access_token":"second"}',
        b'{"access_token":"unsafe\\r\\nheader"}',
    ],
)
def test_invalid_token_response_stops_before_registry_mutation(
    tmp_path: Path, payload: bytes
) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport([RegistryResponse(200, body=payload)])
    with pytest.raises(AcrPublishError, match="token: invalid-response"):
        publish(fixture, transport)
    assert len(transport.requests) == 1


def test_http_redirect_never_follows_location(tmp_path: Path) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport(
        [
            RegistryResponse(307, {"Location": "https://example.com/credentials"}),
        ]
    )
    with pytest.raises(AcrPublishError) as failure:
        publish(fixture, transport)
    assert failure.value.http_status == 307
    assert len(transport.requests) == 1


def test_credential_and_transport_errors_are_sanitized(tmp_path: Path, capsys: Any) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport([])

    def credentials() -> str:
        raise RuntimeError(REFRESH)

    with pytest.raises(AcrPublishError) as failure:
        publish(fixture, transport, credential_provider=credentials)
    assert failure.value.stage == "credentials"
    assert REFRESH not in str(failure.value)
    assert not transport.requests
    assert not capsys.readouterr().out
    assert ACCESS not in repr(RegistryResponse(200, {"Authorization": ACCESS}, ACCESS.encode()))


def test_unexpected_provider_defects_are_not_hidden(tmp_path: Path) -> None:
    fixture = make_archive(tmp_path / "image.tar")
    transport = RecordingTransport([AssertionError("programmer defect")])
    with pytest.raises(AssertionError, match="programmer defect"):
        publish(fixture, transport)


def test_https_adapter_sends_bytes_with_verified_tls_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[bytes] = []
    observed: dict[str, Any] = {}

    class Stream:
        def settimeout(self, timeout: float) -> None:
            observed.setdefault("timeouts", []).append(timeout)

        def connect(self, address: tuple[str, int]) -> None:
            observed["address"] = address

        def close(self) -> None:
            observed["raw_closed"] = True

        def shutdown(self, direction: int) -> None:
            observed["shutdown"] = direction

    def lookup(*args: Any, **kwargs: Any) -> Any:
        observed.setdefault("lookups", []).append((args, kwargs))
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.1", 443))]

    def wrap_socket(stream: Stream, *, server_hostname: str) -> Stream:
        observed["tls_hostname"] = server_hostname
        return stream

    context = ssl.create_default_context()
    monkeypatch.setattr(context, "wrap_socket", wrap_socket)
    monkeypatch.setattr(acr_publish.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(acr_publish, "_getaddrinfo", lookup)
    monkeypatch.setattr(acr_publish, "_socket", lambda *args: Stream())

    class Response:
        status = 201

        def getheaders(self) -> list[tuple[str, str]]:
            return [("Docker-Content-Digest", "sha256:" + "a" * 64)]

    class Connection:
        sock = None

        def __init__(self, host: str, **kwargs: Any) -> None:
            observed.update(host=host, **kwargs)
            observed["connection"] = self

        def connect(self) -> None:
            raise AssertionError("Unbounded HTTPSConnection.connect must not be used")

        def putrequest(self, *args: Any, **kwargs: Any) -> None:
            observed["request"] = args

        def putheader(self, *args: Any) -> None:
            observed.setdefault("headers", []).append(args)

        def endheaders(self) -> None:
            pass

        def send(self, chunk: bytes) -> None:
            sent.append(chunk)

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr(acr_publish.http.client, "HTTPSConnection", Connection)
    result = HttpsRegistryTransport().request(
        REGISTRY,
        "PUT",
        UPLOAD,
        {"Authorization": "Bearer " + ACCESS},
        (b"hello", b"world"),
        content_length=10,
        deadline=time.monotonic() + 10,
    )
    assert result.status == 201
    assert b"".join(sent) == b"helloworld"
    assert observed["host"] == REGISTRY
    assert observed["context"].verify_mode == ssl.CERT_REQUIRED
    assert observed["context"].check_hostname is True
    assert observed["tls_hostname"] == REGISTRY
    assert observed["address"] == ("192.0.2.1", 443)
    assert observed["connection"].auto_open == 0
    assert len(observed["lookups"]) == 1
    assert observed["lookups"][0][0] == (REGISTRY, 443)
    assert all(0 < timeout <= 10 for timeout in observed["timeouts"])
    assert ("Content-Length", "10") in observed["headers"]
    assert observed["closed"]
    assert observed["raw_closed"]


def test_slow_dns_is_bounded_and_late_resolution_cannot_send_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    started = threading.Event()
    workers: list[threading.Thread] = []
    connections: list[bool] = []

    def slow_lookup(*args: Any, **kwargs: Any) -> Any:
        workers.append(threading.current_thread())
        started.set()
        release.wait(timeout=5)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.1", 443))]

    def forbidden_connection(*args: Any, **kwargs: Any) -> Any:
        connections.append(True)
        raise AssertionError("DNS timeout must not create a socket or HTTP connection")

    monkeypatch.setattr(acr_publish, "_getaddrinfo", slow_lookup)
    monkeypatch.setattr(acr_publish, "_socket", forbidden_connection)
    monkeypatch.setattr(acr_publish.http.client, "HTTPSConnection", forbidden_connection)
    monkeypatch.setattr(acr_publish, "_DNS_SLOTS", threading.BoundedSemaphore(1))
    begin = time.monotonic()
    try:
        with pytest.raises(AcrPublishError, match="transport: timeout"):
            HttpsRegistryTransport(io_timeout=0.1).request(
                REGISTRY,
                "POST",
                "/oauth2/token",
                {},
                (REFRESH.encode(),),
                content_length=len(REFRESH),
                deadline=begin + 1,
            )
        assert time.monotonic() - begin < 1
        assert started.is_set()
        assert not release.is_set()
        assert workers[0].daemon
        with pytest.raises(AcrPublishError, match="resolver-busy"):
            HttpsRegistryTransport().request(
                REGISTRY,
                "GET",
                "/v2/",
                {},
                (),
                content_length=0,
                deadline=time.monotonic() + 1,
            )
        assert len(workers) == 1
        assert not connections
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=1)
    assert all(not worker.is_alive() for worker in workers)
    assert not connections


def test_dns_answer_returned_after_deadline_cannot_open_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(acr_publish.time, "monotonic", lambda: clock[0])

    def late_lookup(*args: Any, **kwargs: Any) -> Any:
        clock[0] += 61
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.1", 443))]

    def forbidden_socket(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("An expired DNS result cannot authorize connection I/O")

    monkeypatch.setattr(acr_publish, "_getaddrinfo", late_lookup)
    monkeypatch.setattr(acr_publish, "_socket", forbidden_socket)
    with pytest.raises(AcrPublishError, match="transport: timeout"):
        HttpsRegistryTransport().request(
            REGISTRY,
            "GET",
            "/v2/",
            {},
            (),
            content_length=0,
            deadline=110.0,
        )
