"""Security-focused tests for private channel attachment handoff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.attachment_handoff import (
    AttachmentDownloadLocation,
    BoundedAttachmentSpool,
    ChannelAttachmentHandoffError,
    ChannelAttachmentIntakeClient,
    SlackPrivateAttachmentFetcher,
    TeamsPrivateAttachmentFetcher,
    WorkloadAccessToken,
)
from fdai_operator_service.families.conversation.channel_edge.attachment_ingestion import (
    ChannelAttachmentIngestor,
    attachment_purpose,
)
from fdai_operator_service.families.conversation.channel_edge.models import (
    AuthenticatedInboundTurn,
    ChannelAttachment,
    InboundChannelTurn,
)
from fdai_service_contracts import (
    ChannelAttachmentAdmissionReceipt,
    ChannelAttachmentAdmissionRequest,
    ChannelAttachmentCommitReceipt,
    ChannelAttachmentOutcome,
    ChannelAttachmentTerminalReceipt,
    DocumentIndexState,
    DocumentPurpose,
    DocumentRetentionState,
    DocumentState,
    channel_attachment_receipt_digest,
)

_NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


class _SlackTokens:
    def __init__(self) -> None:
        self.calls = 0

    async def get_token(self) -> str:
        self.calls += 1
        return "slack-secret"


class _AudienceTokens:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> WorkloadAccessToken:
        self.audiences.append(audience)
        return WorkloadAccessToken("teams-secret", audience)


class _Resolver:
    def __init__(self, location: AttachmentDownloadLocation) -> None:
        self.location = location

    async def resolve(
        self, *, conversation_ref: str, attachment_id: str
    ) -> AttachmentDownloadLocation:
        assert conversation_ref == "conversation-example"
        assert attachment_id == "file-example"
        return self.location


class _Intake:
    def __init__(self, *, replay_ready: bool = False) -> None:
        self.request = None
        self.commits = 0
        self.status_calls = 0
        self.replay_ready = replay_ready

    async def admit(self, request):  # type: ignore[no-untyped-def]
        self.request = request
        return ChannelAttachmentAdmissionReceipt.model_construct(
            handoff_id=request.handoff_id,
            request_digest=request.request_digest,
            policy_digest="sha256:" + "d" * 64,
            max_content_bytes=8,
            accepted_at=_NOW,
            expires_at=_NOW + timedelta(minutes=5),
            execution_authority=False,
            receipt_digest="sha256:" + "e" * 64,
        )

    async def commit(self, request, content):  # type: ignore[no-untyped-def]
        self.commits += 1
        return ChannelAttachmentCommitReceipt.model_construct(
            handoff_id=request.handoff_id,
            request_digest=request.request_digest,
            upload_id=UUID(int=1),
            document_id=UUID(int=2),
            version_id=UUID(int=3),
            observed_size=content.size_bytes,
            observed_sha256=content.sha256,
            state=DocumentState.RECEIVED,
            committed_at=_NOW,
            execution_authority=False,
            receipt_digest="sha256:" + "f" * 64,
        )

    async def status(self, request):  # type: ignore[no-untyped-def]
        self.status_calls += 1
        if self.replay_ready or self.status_calls >= 3:
            return _terminal(request, ChannelAttachmentOutcome.READY)
        if self.status_calls == 1:
            return await self.admit(request)
        return _terminal(request, ChannelAttachmentOutcome.PENDING)


class _Fetcher:
    def __init__(self, spool: BoundedAttachmentSpool) -> None:
        self.spool = spool
        self.calls = 0

    async def fetch(
        self,
        attachment: ChannelAttachment,
        *,
        conversation_ref: str,
        max_content_bytes: int,
    ):
        del conversation_ref
        self.calls += 1

        async def chunks():  # type: ignore[no-untyped-def]
            yield b"evidence"

        return await self.spool.capture(
            chunks(),
            expected_size=attachment.size_bytes,
            max_size=max_content_bytes,
        )


def _attachment(prefix: str) -> ChannelAttachment:
    return ChannelAttachment(
        source_ref=prefix + "file-example",
        name="evidence.txt",
        size_bytes=8,
        media_type_hint="text/plain",
    )


def _turn() -> AuthenticatedInboundTurn:
    return AuthenticatedInboundTurn(
        turn=InboundChannelTurn(
            channel_kind=ChannelKind.SLACK,
            channel_id="channel-example",
            message_id="message-example",
            sender_id="sender-example",
            text="Summarize this evidence.",
            attachments=(_attachment("slack-file:"),),
        ),
        principal_id="principal-example",
        verification_ref="slack-signature:example",
    )


def _terminal(
    request,  # type: ignore[no-untyped-def]
    outcome: ChannelAttachmentOutcome,
    **updates: object,
) -> ChannelAttachmentTerminalReceipt:
    ready = outcome is ChannelAttachmentOutcome.READY
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "receipt_kind": "terminal",
        "handoff_id": request.handoff_id,
        "request_digest": request.request_digest,
        "upload_id": UUID(int=1),
        "document_id": UUID(int=2),
        "version_id": UUID(int=3),
        "commit_receipt_digest": "sha256:" + "f" * 64,
        "observed_size": 8,
        "observed_sha256": "ee8250fb76e094b34b471f13a73dbbe51d1ae142e9df59d7c0d31ec20f0a0a8e",
        "requested_purpose": DocumentPurpose.KNOWLEDGE_BASE,
        "outcome": outcome,
        "document_state": DocumentState.READY if ready else DocumentState.INDEXING,
        "index_state": DocumentIndexState.ACTIVE if ready else DocumentIndexState.QUEUED,
        "retention_state": DocumentRetentionState.LIVE,
        "active": ready,
        "available": ready,
        "handover_draft_ready": False,
        "citation": (
            "doc:00000000-0000-0000-0000-000000000002:00000000-0000-0000-0000-000000000003"
            if ready
            else None
        ),
        "reason_code": None,
        "observed_at": _NOW,
        "execution_authority": False,
    }
    material.update(updates)
    provisional = ChannelAttachmentTerminalReceipt.model_construct(
        **material,
        receipt_digest="sha256:" + "0" * 64,
    )
    return ChannelAttachmentTerminalReceipt.model_validate(
        {**material, "receipt_digest": channel_attachment_receipt_digest(provisional)}
    )


async def test_slack_fetcher_resolves_metadata_then_captures_exact_private_bytes(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer slack-secret"
        if request.url.host == "slack.com":
            assert request.url.params["file"] == "file-example"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "file": {
                        "id": "file-example",
                        "name": "evidence.txt",
                        "mimetype": "text/plain",
                        "size": 8,
                        "url_private_download": "https://files.slack.com/evidence",
                    },
                },
            )
        return httpx.Response(200, content=b"evidence", headers={"Content-Length": "8"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = SlackPrivateAttachmentFetcher(
            http_client=client,
            tokens=_SlackTokens(),
            spool=BoundedAttachmentSpool(scratch_directory=tmp_path),
            files_info_url="https://slack.com/api/files.info",
            metadata_hosts=frozenset({"slack.com"}),
            download_hosts=frozenset({"files.slack.com"}),
        )
        content = await fetcher.fetch(
            _attachment("slack-file:"),
            conversation_ref="conversation-example",
            max_content_bytes=8,
        )
        async with content:
            assert b"".join([chunk async for chunk in content.chunks()]) == b"evidence"
            assert content.sha256 == (
                "ee8250fb76e094b34b471f13a73dbbe51d1ae142e9df59d7c0d31ec20f0a0a8e"
            )
    assert [request.url.host for request in requests] == ["slack.com", "files.slack.com"]


async def test_slack_fetcher_rejects_response_selected_host_before_download(
    tmp_path: Path,
) -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            json={
                "ok": True,
                "file": {
                    "id": "file-example",
                    "name": "evidence.txt",
                    "mimetype": "text/plain",
                    "size": 8,
                    "url_private_download": "https://attacker.invalid/evidence",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = SlackPrivateAttachmentFetcher(
            http_client=client,
            tokens=_SlackTokens(),
            spool=BoundedAttachmentSpool(scratch_directory=tmp_path),
            files_info_url="https://slack.com/api/files.info",
            metadata_hosts=frozenset({"slack.com"}),
            download_hosts=frozenset({"files.slack.com"}),
        )
        with pytest.raises(ValueError, match="fixed HTTPS"):
            await fetcher.fetch(
                _attachment("slack-file:"),
                conversation_ref="conversation-example",
                max_content_bytes=8,
            )
    assert requests == 1


async def test_teams_fetcher_rejects_server_location_audience_before_token_or_io(
    tmp_path: Path,
) -> None:
    tokens = _AudienceTokens()

    def unexpected(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("network I/O occurred for an unauthorized audience")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        fetcher = TeamsPrivateAttachmentFetcher(
            http_client=client,
            tokens=tokens,
            resolver=_Resolver(
                AttachmentDownloadLocation(
                    "https://smba.trafficmanager.net/attachment",
                    "https://graph.microsoft.com/.default",
                )
            ),
            spool=BoundedAttachmentSpool(scratch_directory=tmp_path),
            allowed_hosts=frozenset({"smba.trafficmanager.net"}),
            allowed_audiences=frozenset({"https://api.botframework.com/.default"}),
        )
        with pytest.raises(ChannelAttachmentHandoffError) as error:
            await fetcher.fetch(
                _attachment("teams-file:"),
                conversation_ref="conversation-example",
                max_content_bytes=8,
            )
    assert error.value.code == "invalid_audience"
    assert tokens.audiences == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("summarize handover status", DocumentPurpose.KNOWLEDGE_BASE),
        ("/handover transfer ownership", DocumentPurpose.HANDOVER_BOOTSTRAP),
        ("/attach handover", DocumentPurpose.HANDOVER_BOOTSTRAP),
        ("인수인계 문서: 담당자 변경", DocumentPurpose.HANDOVER_BOOTSTRAP),
    ],
)
def test_attachment_purpose_requires_exact_leading_directive(
    text: str, expected: DocumentPurpose
) -> None:
    assert attachment_purpose(text) is expected


async def test_ingestor_waits_from_pending_until_ready_in_stable_order(tmp_path: Path) -> None:
    intake = _Intake()
    fetcher = _Fetcher(BoundedAttachmentSpool(scratch_directory=tmp_path))
    ingestor = ChannelAttachmentIngestor(
        intake=intake,  # type: ignore[arg-type]
        fetchers={ChannelKind.SLACK: fetcher},
        principal_manifest_digest="sha256:" + "a" * 64,
        terminal_timeout=timedelta(seconds=1),
        poll_interval=0.001,
        clock=lambda: _NOW,
    )

    result = await ingestor.ingest(
        _turn(),
        conversation_ref="conversation-example",
        purpose=DocumentPurpose.KNOWLEDGE_BASE,
    )

    assert fetcher.calls == 1
    assert intake.commits == 1
    assert result.document_context.citations == (result.receipts[0].citation,)
    assert result.document_context.receipt_digests == (result.receipts[0].receipt_digest,)


async def test_ingestor_enforces_edge_ceiling_below_intake_admission(
    tmp_path: Path,
) -> None:
    intake = _Intake()
    fetcher = _Fetcher(BoundedAttachmentSpool(scratch_directory=tmp_path))
    ingestor = ChannelAttachmentIngestor(
        intake=intake,
        fetchers={ChannelKind.SLACK: fetcher},
        principal_manifest_digest="sha256:" + "a" * 64,
        max_content_bytes=7,
        clock=lambda: _NOW,
    )

    with pytest.raises(ChannelAttachmentHandoffError) as error:
        await ingestor.ingest(
            _turn(),
            conversation_ref="conversation-example",
            purpose=DocumentPurpose.KNOWLEDGE_BASE,
        )

    assert error.value.code == "size_limit"
    assert intake.commits == 0


async def test_ingestor_reuses_ready_status_without_vendor_fetch(tmp_path: Path) -> None:
    intake = _Intake(replay_ready=True)
    fetcher = _Fetcher(BoundedAttachmentSpool(scratch_directory=tmp_path))
    ingestor = ChannelAttachmentIngestor(
        intake=intake,  # type: ignore[arg-type]
        fetchers={ChannelKind.SLACK: fetcher},
        principal_manifest_digest="sha256:" + "a" * 64,
        terminal_timeout=timedelta(seconds=1),
        poll_interval=0.001,
        clock=lambda: _NOW,
    )

    result = await ingestor.ingest(
        _turn(),
        conversation_ref="conversation-example",
        purpose=DocumentPurpose.KNOWLEDGE_BASE,
    )

    assert result.receipts[0].outcome is ChannelAttachmentOutcome.READY
    assert fetcher.calls == 0
    assert intake.commits == 0


async def test_ingestor_rejects_terminal_that_does_not_bind_captured_bytes(
    tmp_path: Path,
) -> None:
    class MismatchedTerminalIntake(_Intake):
        async def status(self, request):  # type: ignore[no-untyped-def]
            self.status_calls += 1
            if self.status_calls == 1:
                return await self.admit(request)
            return _terminal(
                request,
                ChannelAttachmentOutcome.READY,
                observed_sha256="f" * 64,
            )

    ingestor = ChannelAttachmentIngestor(
        intake=MismatchedTerminalIntake(),
        fetchers={ChannelKind.SLACK: _Fetcher(BoundedAttachmentSpool(scratch_directory=tmp_path))},
        principal_manifest_digest="sha256:" + "d" * 64,
        terminal_timeout=timedelta(seconds=1),
        poll_interval=0.001,
        clock=lambda: _NOW,
    )

    with pytest.raises(ChannelAttachmentHandoffError) as error:
        await ingestor.ingest(
            _turn(),
            conversation_ref="conversation-example",
            purpose=DocumentPurpose.KNOWLEDGE_BASE,
        )

    assert error.value.code == "terminal_mismatch"


async def test_ingestor_rejects_changed_commit_during_terminal_progression(
    tmp_path: Path,
) -> None:
    class ChangedProgressionIntake(_Intake):
        async def status(self, request):  # type: ignore[no-untyped-def]
            self.status_calls += 1
            if self.status_calls == 1:
                return _terminal(request, ChannelAttachmentOutcome.PENDING)
            return _terminal(
                request,
                ChannelAttachmentOutcome.READY,
                commit_receipt_digest="sha256:" + "9" * 64,
            )

    ingestor = ChannelAttachmentIngestor(
        intake=ChangedProgressionIntake(replay_ready=True),
        fetchers={ChannelKind.SLACK: _Fetcher(BoundedAttachmentSpool(scratch_directory=tmp_path))},
        principal_manifest_digest="sha256:" + "d" * 64,
        terminal_timeout=timedelta(seconds=1),
        poll_interval=0.001,
        clock=lambda: _NOW,
    )

    with pytest.raises(ChannelAttachmentHandoffError) as error:
        await ingestor.ingest(
            _turn(),
            conversation_ref="conversation-example",
            purpose=DocumentPurpose.KNOWLEDGE_BASE,
        )

    assert error.value.code == "terminal_mismatch"


async def test_ingestor_rejects_expired_admission_before_content_commit(
    tmp_path: Path,
) -> None:
    current = [_NOW]

    class SlowFetcher(_Fetcher):
        async def fetch(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            content = await super().fetch(*args, **kwargs)
            current[0] = _NOW + timedelta(minutes=6)
            return content

    intake = _Intake()
    ingestor = ChannelAttachmentIngestor(
        intake=intake,
        fetchers={
            ChannelKind.SLACK: SlowFetcher(BoundedAttachmentSpool(scratch_directory=tmp_path))
        },
        principal_manifest_digest="sha256:" + "d" * 64,
        clock=lambda: current[0],
    )

    with pytest.raises(ChannelAttachmentHandoffError) as error:
        await ingestor.ingest(
            _turn(),
            conversation_ref="conversation-example",
            purpose=DocumentPurpose.KNOWLEDGE_BASE,
        )

    assert error.value.code == "admission_expired"
    assert intake.commits == 0


async def test_ingestor_recovers_ambiguous_intake_unavailable_from_status(
    tmp_path: Path,
) -> None:
    class UnavailableAfterCommitIntake(_Intake):
        def __init__(self) -> None:
            super().__init__()
            self.committed = None

        async def commit(self, request, content):  # type: ignore[no-untyped-def]
            self.committed = await super().commit(request, content)
            raise ChannelAttachmentHandoffError(
                "simulated unavailable response",
                code="intake_unavailable",
            )

        async def status(self, request):  # type: ignore[no-untyped-def]
            self.status_calls += 1
            if self.status_calls == 1:
                return await self.admit(request)
            if self.status_calls == 2:
                return self.committed
            return _terminal(request, ChannelAttachmentOutcome.READY)

    intake = UnavailableAfterCommitIntake()
    ingestor = ChannelAttachmentIngestor(
        intake=intake,
        fetchers={ChannelKind.SLACK: _Fetcher(BoundedAttachmentSpool(scratch_directory=tmp_path))},
        principal_manifest_digest="sha256:" + "d" * 64,
        terminal_timeout=timedelta(seconds=1),
        poll_interval=0.001,
        clock=lambda: _NOW,
    )

    result = await ingestor.ingest(
        _turn(),
        conversation_ref="conversation-example",
        purpose=DocumentPurpose.KNOWLEDGE_BASE,
    )

    assert result.receipts[0].outcome is ChannelAttachmentOutcome.READY
    assert intake.commits == 1


async def test_intake_client_status_uses_digest_header_without_query() -> None:
    request = ChannelAttachmentAdmissionRequest.model_construct(
        handoff_id="channel-attachment-" + "a" * 64,
        request_digest="sha256:" + "b" * 64,
    )
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "receipt_kind": "terminal",
        "handoff_id": request.handoff_id,
        "request_digest": request.request_digest,
        "upload_id": UUID(int=1),
        "document_id": UUID(int=2),
        "version_id": UUID(int=3),
        "commit_receipt_digest": "sha256:" + "f" * 64,
        "observed_size": 8,
        "observed_sha256": "ee8250fb76e094b34b471f13a73dbbe51d1ae142e9df59d7c0d31ec20f0a0a8e",
        "requested_purpose": DocumentPurpose.KNOWLEDGE_BASE,
        "outcome": ChannelAttachmentOutcome.READY,
        "document_state": DocumentState.READY,
        "index_state": DocumentIndexState.ACTIVE,
        "retention_state": DocumentRetentionState.LIVE,
        "active": True,
        "available": True,
        "handover_draft_ready": False,
        "citation": (
            "doc:00000000-0000-0000-0000-000000000002:00000000-0000-0000-0000-000000000003"
        ),
        "reason_code": None,
        "observed_at": _NOW,
        "execution_authority": False,
    }
    provisional = ChannelAttachmentTerminalReceipt.model_construct(
        **material,
        receipt_digest="sha256:" + "0" * 64,
    )
    receipt = ChannelAttachmentTerminalReceipt.model_validate(
        {**material, "receipt_digest": channel_attachment_receipt_digest(provisional)}
    )

    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.query == b""
        assert http_request.headers["x-fdai-request-digest"] == request.request_digest
        return httpx.Response(200, json=receipt.model_dump(mode="json"))

    tokens = _AudienceTokens()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ChannelAttachmentIntakeClient(
            http_client=http_client,
            tokens=tokens,
            origin="http://127.0.0.1:8015",
            audience="api://document-ingestion",
            allow_loopback_http=True,
        )
        observed = await client.status(request)

    assert observed == receipt
    assert tokens.audiences == ["api://document-ingestion"]


async def test_intake_client_commit_streams_with_standard_content_length(
    tmp_path: Path,
) -> None:
    request = ChannelAttachmentAdmissionRequest.model_construct(
        handoff_id="channel-attachment-" + "a" * 64,
        request_digest="sha256:" + "b" * 64,
    )
    material: dict[str, object] = {
        "schema_version": "1.0.0",
        "receipt_kind": "commit",
        "handoff_id": request.handoff_id,
        "request_digest": request.request_digest,
        "upload_id": UUID(int=1),
        "document_id": UUID(int=2),
        "version_id": UUID(int=3),
        "observed_size": 8,
        "observed_sha256": ("ee8250fb76e094b34b471f13a73dbbe51d1ae142e9df59d7c0d31ec20f0a0a8e"),
        "state": DocumentState.RECEIVED,
        "committed_at": _NOW,
        "execution_authority": False,
    }
    provisional = ChannelAttachmentCommitReceipt.model_construct(
        **material,
        receipt_digest="sha256:" + "0" * 64,
    )
    receipt = ChannelAttachmentCommitReceipt.model_validate(
        {**material, "receipt_digest": channel_attachment_receipt_digest(provisional)}
    )

    async def chunks():  # type: ignore[no-untyped-def]
        yield b"evidence"

    content = await BoundedAttachmentSpool(scratch_directory=tmp_path).capture(
        chunks(),
        expected_size=8,
        max_size=8,
    )

    async def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.headers["content-length"] == "8"
        assert http_request.headers["content-type"] == "application/octet-stream"
        assert http_request.headers["x-fdai-content-sha256"] == content.sha256
        assert await http_request.aread() == b"evidence"
        return httpx.Response(200, json=receipt.model_dump(mode="json"))

    async with content:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = ChannelAttachmentIntakeClient(
                http_client=http_client,
                tokens=_AudienceTokens(),
                origin="http://127.0.0.1:8015",
                audience="api://document-ingestion",
                allow_loopback_http=True,
            )
            observed = await client.commit(request, content)

    assert observed == receipt


@pytest.mark.parametrize(("status", "expected"), ((204, True), (403, False)))
async def test_intake_client_readiness_probes_exact_authenticated_route(
    status: int,
    expected: bool,
) -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.path.endswith("/channel-attachments/v1/auth-probe")
        assert http_request.headers["authorization"] == "Bearer teams-secret"
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ChannelAttachmentIntakeClient(
            http_client=http_client,
            tokens=_AudienceTokens(),
            origin="http://127.0.0.1:8015",
            audience="api://document-ingestion",
            allow_loopback_http=True,
        )

        assert await client.probe_readiness() is expected


async def test_intake_client_rejects_oversized_receipt_while_streaming() -> None:
    async def response_chunks():  # type: ignore[no-untyped-def]
        yield b"{" + b"x" * (256 * 1024)

    def handler(_http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=response_chunks())

    request = ChannelAttachmentAdmissionRequest.model_construct(
        handoff_id="channel-attachment-" + "a" * 64,
        request_digest="sha256:" + "b" * 64,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ChannelAttachmentIntakeClient(
            http_client=http_client,
            tokens=_AudienceTokens(),
            origin="http://127.0.0.1:8015",
            audience="api://document-ingestion",
            allow_loopback_http=True,
        )
        with pytest.raises(ChannelAttachmentHandoffError) as error:
            await client.status(request)

    assert error.value.code == "invalid_receipt"


@pytest.mark.parametrize(
    "updates",
    (
        {"handoff_id": "channel-attachment-" + "c" * 64},
        {"request_digest": "sha256:" + "d" * 64},
    ),
    ids=("handoff", "request-digest"),
)
async def test_intake_client_rejects_receipt_for_another_request(
    updates: dict[str, object],
) -> None:
    request = ChannelAttachmentAdmissionRequest.model_construct(
        handoff_id="channel-attachment-" + "a" * 64,
        request_digest="sha256:" + "b" * 64,
    )
    receipt = _terminal(request, ChannelAttachmentOutcome.READY, **updates)

    def handler(_http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=receipt.model_dump(mode="json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ChannelAttachmentIntakeClient(
            http_client=http_client,
            tokens=_AudienceTokens(),
            origin="http://127.0.0.1:8015",
            audience="api://document-ingestion",
            allow_loopback_http=True,
        )
        with pytest.raises(ChannelAttachmentHandoffError) as error:
            await client.status(request)

    assert error.value.code == "invalid_receipt"
