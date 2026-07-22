from __future__ import annotations

import httpx
import pytest

from fdai.delivery.channels.attachment_fetchers import (
    AttachmentDownloadLocation,
    ChannelAttachmentFetchError,
    SlackAttachmentFetcherConfig,
    SlackPrivateFileFetcher,
    TeamsAttachmentFetcherConfig,
    TeamsServerAttachmentFetcher,
)
from fdai.shared.providers.conversation_channel import ChannelAttachment
from fdai.shared.providers.local.secret import EnvSecretProvider
from fdai.shared.providers.workload_identity import IdentityToken

_ATTACHMENT = ChannelAttachment(
    source_ref="opaque-file-id",
    name="handover.txt",
    size_bytes=4,
    media_type_hint="text/plain",
)


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(token="identity-token", audience=audience, expires_at=None)


class _TeamsResolver:
    async def resolve(self, attachment: ChannelAttachment) -> AttachmentDownloadLocation:
        assert attachment.source_ref == "opaque-file-id"
        return AttachmentDownloadLocation(
            url="https://attachments.example.com/content/opaque-file-id",
            audience="api://attachments.example.com",
        )


async def test_slack_fetcher_resolves_opaque_id_then_downloads_private_bytes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/files.info"):
            assert request.url.params["file"] == "opaque-file-id"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "file": {"url_private_download": "https://files.slack.com/files-pri/content"},
                },
            )
        assert request.url.host == "files.slack.com"
        assert request.headers["Authorization"] == "Bearer bot-token"
        return httpx.Response(200, content=b"data")

    fetcher = SlackPrivateFileFetcher(
        config=SlackAttachmentFetcherConfig(),
        secrets=EnvSecretProvider(env={"slack-bot-token": "bot-token"}, prefix=""),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    assert await fetcher.fetch(_ATTACHMENT, max_bytes=10) == b"data"
    assert len(requests) == 2


async def test_slack_fetcher_rejects_untrusted_download_host_before_get() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "ok": True,
                "file": {"url_private_download": "https://example.com/private"},
            },
        )

    fetcher = SlackPrivateFileFetcher(
        config=SlackAttachmentFetcherConfig(),
        secrets=EnvSecretProvider(env={"slack-bot-token": "bot-token"}, prefix=""),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ChannelAttachmentFetchError, match="allowlist"):
        await fetcher.fetch(_ATTACHMENT, max_bytes=10)
    assert calls == 1


async def test_slack_fetcher_enforces_streamed_byte_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files.info"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "file": {"url_private_download": "https://files.slack.com/private"},
                },
            )
        return httpx.Response(200, content=b"too-large")

    fetcher = SlackPrivateFileFetcher(
        config=SlackAttachmentFetcherConfig(),
        secrets=EnvSecretProvider(env={"slack-bot-token": "bot-token"}, prefix=""),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ChannelAttachmentFetchError, match="byte limit"):
        await fetcher.fetch(_ATTACHMENT, max_bytes=4)


async def test_slack_fetcher_rejects_redirect_without_following_location() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/files.info"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "file": {"url_private_download": "https://files.slack.com/private"},
                },
            )
        return httpx.Response(
            302,
            headers={"Location": "https://untrusted.example.com/private"},
        )

    fetcher = SlackPrivateFileFetcher(
        config=SlackAttachmentFetcherConfig(),
        secrets=EnvSecretProvider(env={"slack-bot-token": "bot-token"}, prefix=""),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ChannelAttachmentFetchError, match="HTTP 302"):
        await fetcher.fetch(_ATTACHMENT, max_bytes=10)
    assert len(requests) == 2


async def test_slack_fetcher_rejects_files_info_redirect_from_redirecting_client() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": "https://example.com/metadata"},
        )

    fetcher = SlackPrivateFileFetcher(
        config=SlackAttachmentFetcherConfig(),
        secrets=EnvSecretProvider(env={"slack-bot-token": "bot-token"}, prefix=""),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        ),
    )

    with pytest.raises(ChannelAttachmentFetchError, match="HTTP 302"):
        await fetcher.fetch(_ATTACHMENT, max_bytes=10)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "api_base",
    (
        "https://user@slack.com/api",
        "https://slack.com/api?redirect=example.com",
        "https://slack.com/api#fragment",
    ),
)
def test_slack_fetcher_config_rejects_non_origin_api_base(api_base: str) -> None:
    with pytest.raises(ValueError, match="without credentials or query"):
        SlackAttachmentFetcherConfig(api_base=api_base)


async def test_slack_fetcher_rejects_allowed_host_on_nonstandard_port() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "file": {"url_private_download": "https://files.slack.com:8443/private"},
            },
        )

    fetcher = SlackPrivateFileFetcher(
        config=SlackAttachmentFetcherConfig(),
        secrets=EnvSecretProvider(env={"slack-bot-token": "bot-token"}, prefix=""),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ChannelAttachmentFetchError, match="allowlist"):
        await fetcher.fetch(_ATTACHMENT, max_bytes=10)


async def test_teams_fetcher_uses_server_resolver_and_audience_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "attachments.example.com"
        assert request.headers["Authorization"] == "Bearer identity-token"
        return httpx.Response(200, content=b"data")

    identity = _Identity()
    fetcher = TeamsServerAttachmentFetcher(
        config=TeamsAttachmentFetcherConfig(allowed_download_hosts=("attachments.example.com",)),
        resolver=_TeamsResolver(),
        identity=identity,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    assert await fetcher.fetch(_ATTACHMENT, max_bytes=10) == b"data"
    assert identity.audiences == ["api://attachments.example.com"]
