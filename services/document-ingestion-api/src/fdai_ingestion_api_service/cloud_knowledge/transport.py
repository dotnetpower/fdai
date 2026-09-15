"""Public-only DNS-pinned HTTPS transport for exact registered documentation URLs."""

from __future__ import annotations

import ipaddress
import socket

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult
from fdai_service_contracts.cloud_knowledge import CloudKnowledgeSource, public_document_url

from fdai_ingestion_api_service.cloud_knowledge.collector import SourceResponse


class PublicResolver(AbstractResolver):
    """Validate and return the same resolved addresses the connector actually uses."""

    def __init__(self) -> None:
        self._resolver = aiohttp.ThreadedResolver()

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = socket.AF_INET,
    ) -> list[ResolveResult]:
        results = await self._resolver.resolve(host, port, socket.AddressFamily(family))
        if not results or any(not ipaddress.ip_address(item["host"]).is_global for item in results):
            raise OSError("documentation origin resolves outside public address space")
        return results

    async def close(self) -> None:
        await self._resolver.close()


class PublicDocumentationTransport:
    """No ambient proxies, redirects, retries, credentials, or external embedded assets."""

    async def fetch(self, source: CloudKnowledgeSource, *, etag: str | None) -> SourceResponse:
        from urllib.parse import urlsplit

        public_document_url(source.url)
        if not source.enabled or not source.storage_allowed or source.mode != "online":
            raise ValueError("source collection is not authorized")
        host = urlsplit(source.url).hostname or ""
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None:
            raise ValueError("documentation sources MUST use approved DNS names")
        headers = {
            "Accept": "text/html,text/markdown,text/plain",
            "User-Agent": "FDAI-Knowledge/1",
        }
        if etag is not None:
            headers["If-None-Match"] = etag
        resolver = PublicResolver()
        try:
            async with (
                aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False),
                    timeout=aiohttp.ClientTimeout(total=30),
                    trust_env=False,
                ) as client,
                client.get(source.url, headers=headers, allow_redirects=False) as response,
            ):
                content = bytearray()
                if response.status == 200:
                    async for chunk in response.content.iter_chunked(65536):
                        if len(content) + len(chunk) > source.max_bytes:
                            raise ValueError("source response exceeds the byte budget")
                        content.extend(chunk)
                retry = response.headers.get("Retry-After", "0")
                return SourceResponse(
                    status=response.status,
                    content=bytes(content),
                    media_type=response.headers.get("Content-Type", ""),
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    retry_after_seconds=min(int(retry), 7 * 86400) if retry.isdigit() else 86400,
                )
        except aiohttp.ClientError as exc:
            raise OSError("documentation transport unavailable") from exc
        finally:
            await resolver.close()
