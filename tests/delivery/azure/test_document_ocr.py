from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from fdai.delivery.azure.document_ocr import (
    AzureDocumentIntelligenceOcr,
    AzureDocumentOcrConfig,
    AzureDocumentOcrError,
)
from fdai.shared.contracts import (
    AccessDescriptor,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    ProtectionState,
    RetentionPolicy,
)
from fdai.shared.providers.workload_identity import IdentityToken


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(token="identity-token", audience=audience, expires_at=None)


class _FailingIdentity:
    async def get_token(self, audience: str) -> IdentityToken:
        raise RuntimeError("identity unavailable")


class _TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.yielded = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.yielded += 1
            yield chunk


def _version() -> DocumentVersion:
    now = datetime(2026, 7, 22, tzinfo=UTC)
    return DocumentVersion(
        document_id=UUID(int=1),
        version_id=UUID(int=2),
        upload_id=UUID(int=3),
        source_name="handover.png",
        source_sha256="0" * 64,
        size_bytes=4,
        media_type="image/png",
        observed_format="image",
        state=DocumentState.EXTRACTING,
        protection_state=ProtectionState.NONE,
        access=AccessDescriptor(reference="acl", collection_id="collection"),
        retention=RetentionPolicy(policy_version="v1"),
        purposes=(DocumentPurpose.HANDOVER_BOOTSTRAP,),
        uploader_id="operator",
        created_at=now,
        updated_at=now,
    )


async def test_ocr_returns_page_line_citations() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["Authorization"] == "Bearer identity-token"
        if request.method == "POST":
            assert request.headers["Content-Type"] == "image/png"
            return httpx.Response(
                202,
                headers={
                    "operation-location": "https://ocr.example.com/documentintelligence/operations/1"
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "analyzeResult": {
                    "pages": [
                        {
                            "pageNumber": 1,
                            "lines": [
                                {"content": "Thor owner: Example Operator"},
                                {"content": "Heimdall informed: Platform Team"},
                            ],
                        }
                    ]
                },
            },
        )

    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(endpoint="https://ocr.example.com"),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    units = await ocr.extract(version=_version(), content=b"data")

    assert calls == 2
    assert [unit.locator for unit in units] == ["page:1:line:1", "page:1:line:2"]
    assert units[0].text == "Thor owner: Example Operator"


async def test_ocr_rejects_operation_location_outside_configured_origin() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            headers={"operation-location": "https://example.com/operations/1"},
        )

    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(endpoint="https://ocr.example.com"),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AzureDocumentOcrError, match="outside"):
        await ocr.extract(version=_version(), content=b"data")


async def test_ocr_accepts_explicit_default_https_port_for_same_origin() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202,
                headers={"operation-location": "https://ocr.example.com:443/operations/1"},
            )
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "analyzeResult": {"pages": [{"pageNumber": 1, "lines": [{"content": "ready"}]}]},
            },
        )

    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(endpoint="https://ocr.example.com"),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    units = await ocr.extract(version=_version(), content=b"data")

    assert units[0].text == "ready"


async def test_ocr_rejects_output_over_line_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202,
                headers={
                    "operation-location": "https://ocr.example.com/documentintelligence/operations/1"
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "analyzeResult": {
                    "pages": [{"pageNumber": 1, "lines": [{"content": "a"}, {"content": "b"}]}]
                },
            },
        )

    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(
            endpoint="https://ocr.example.com",
            max_lines=1,
        ),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AzureDocumentOcrError, match="bounds"):
        await ocr.extract(version=_version(), content=b"data")


async def test_ocr_rejects_poll_redirect_from_redirecting_client() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                202,
                headers={"operation-location": "https://ocr.example.com/operations/1"},
            )
        return httpx.Response(302, headers={"Location": "https://example.com/result"})

    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(endpoint="https://ocr.example.com"),
        identity=_Identity(),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        ),
    )

    with pytest.raises(AzureDocumentOcrError, match="HTTP 302"):
        await ocr.extract(version=_version(), content=b"data")
    assert len(requests) == 2


async def test_ocr_normalizes_malformed_poll_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202,
                headers={"operation-location": "https://ocr.example.com/operations/1"},
            )
        return httpx.Response(200, content=b"not-json")

    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(endpoint="https://ocr.example.com"),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AzureDocumentOcrError, match="poll failed"):
        await ocr.extract(version=_version(), content=b"data")


async def test_ocr_rejects_poll_payload_before_json_parse() -> None:
    stream = _TrackingStream((b"12345678", b"9", b"never-read"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202,
                headers={"operation-location": "https://ocr.example.com/operations/1"},
            )
        return httpx.Response(200, stream=stream)

    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(
            endpoint="https://ocr.example.com",
            max_response_bytes=8,
        ),
        identity=_Identity(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AzureDocumentOcrError, match="response exceeded"):
        await ocr.extract(version=_version(), content=b"data")
    assert stream.yielded == 2


async def test_ocr_normalizes_identity_failure() -> None:
    ocr = AzureDocumentIntelligenceOcr(
        config=AzureDocumentOcrConfig(endpoint="https://ocr.example.com"),
        identity=_FailingIdentity(),
        http_client=httpx.AsyncClient(),
    )

    with pytest.raises(AzureDocumentOcrError, match="identity token"):
        await ocr.extract(version=_version(), content=b"data")


@pytest.mark.parametrize("timeout", (float("nan"), float("inf")))
def test_ocr_config_rejects_nonfinite_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="limits"):
        AzureDocumentOcrConfig(
            endpoint="https://ocr.example.com",
            timeout_seconds=timeout,
        )
