"""Fail-closed URL, redirect, and DNS policy for browser evidence."""

from __future__ import annotations

import ipaddress
import posixpath
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from fdai.core.browser_evidence.contracts import (
    BrowserOriginPolicy,
    TrustedBrowserDestination,
    canonical_hostname,
)


class BrowserPolicyViolationError(ValueError):
    """Raised when a URL or network transition is outside policy."""


class BrowserDnsResolver(Protocol):
    async def resolve(self, hostname: str) -> Sequence[str]: ...


@dataclass(frozen=True, slots=True)
class CanonicalBrowserUrl:
    url: str
    scheme: str
    hostname: str
    port: int
    path: str
    addresses: tuple[str, ...]

    @property
    def origin(self) -> tuple[str, str, int]:
        return (self.scheme, self.hostname, self.port)


class BrowserUrlPolicyValidator:
    """Validate every navigation, redirect, and connection against one policy."""

    def __init__(self, *, policy: BrowserOriginPolicy, resolver: BrowserDnsResolver) -> None:
        self._policy = policy
        self._resolver = resolver
        self._resolved: dict[str, frozenset[str]] = {}

    async def validate_navigation(self, url: str) -> CanonicalBrowserUrl:
        candidate = self._canonicalize(url)
        self._require_primary_destination(candidate)
        return await self._resolve_and_pin(candidate)

    async def validate_redirect(
        self,
        url: str,
        *,
        source: CanonicalBrowserUrl,
        redirect_count: int,
    ) -> CanonicalBrowserUrl:
        if redirect_count < 1 or redirect_count > self._policy.redirect_policy.max_redirects:
            raise BrowserPolicyViolationError("redirect count exceeds browser policy")
        candidate = self._canonicalize(url)
        if candidate.origin == source.origin:
            self._require_primary_destination(candidate)
        elif not any(
            self._matches_trusted_destination(candidate, destination)
            for destination in self._policy.redirect_policy.trusted_destinations
        ):
            raise BrowserPolicyViolationError("cross-origin redirect is outside browser policy")
        return await self._resolve_and_pin(candidate)

    async def validate_connection(self, url: str) -> CanonicalBrowserUrl:
        candidate = self._canonicalize(url)
        if candidate.hostname in self._policy.allowed_hosts:
            self._require_primary_destination(candidate)
        elif not any(
            self._matches_trusted_destination(candidate, destination)
            for destination in self._policy.redirect_policy.trusted_destinations
        ):
            raise BrowserPolicyViolationError("connection destination is outside browser policy")
        return await self._resolve_and_pin(candidate)

    def _canonicalize(self, value: str) -> CanonicalBrowserUrl:
        try:
            split = urlsplit(value)
            scheme = split.scheme.lower()
            if scheme not in self._policy.allowed_schemes:
                raise BrowserPolicyViolationError("URL scheme is outside browser policy")
            if split.username is not None or split.password is not None:
                raise BrowserPolicyViolationError("URL credentials are not allowed")
            if split.fragment:
                raise BrowserPolicyViolationError("URL fragments are not allowed")
            if split.hostname is None:
                raise BrowserPolicyViolationError("URL hostname is required")
            hostname = canonical_hostname(split.hostname)
            port = split.port or 443
        except (TypeError, ValueError) as exc:
            if isinstance(exc, BrowserPolicyViolationError):
                raise
            raise BrowserPolicyViolationError("URL is malformed") from exc
        if port != 443:
            raise BrowserPolicyViolationError("URL port is outside browser policy")
        try:
            decoded_path = unquote(split.path or "/", errors="strict")
        except UnicodeDecodeError as exc:
            raise BrowserPolicyViolationError("URL path encoding is invalid") from exc
        if "\\" in decoded_path or any(ord(character) < 32 for character in decoded_path):
            raise BrowserPolicyViolationError("URL path contains unsafe characters")
        normalized_path = posixpath.normpath(decoded_path)
        if decoded_path.endswith("/") and normalized_path != "/":
            normalized_path += "/"
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"
        try:
            query_pairs = parse_qsl(split.query, keep_blank_values=True, strict_parsing=True)
        except ValueError as exc:
            raise BrowserPolicyViolationError("URL query is malformed") from exc
        query_keys = {key for key, _ in query_pairs}
        if not query_keys.issubset(self._policy.allowed_query_keys):
            raise BrowserPolicyViolationError("URL query key is outside browser policy")
        query = urlencode(sorted(query_pairs))
        netloc = f"[{hostname}]" if ":" in hostname else hostname
        canonical = urlunsplit(
            (scheme, netloc, quote(normalized_path, safe="/~!$&'()*+,;=:@-._"), query, "")
        )
        return CanonicalBrowserUrl(
            url=canonical,
            scheme=scheme,
            hostname=hostname,
            port=port,
            path=normalized_path,
            addresses=(),
        )

    def _require_primary_destination(self, candidate: CanonicalBrowserUrl) -> None:
        if candidate.hostname not in self._policy.allowed_hosts:
            raise BrowserPolicyViolationError("URL host is outside browser policy")
        if not _path_allowed(candidate.path, self._policy.allowed_path_prefixes):
            raise BrowserPolicyViolationError("URL path is outside browser policy")

    async def _resolve_and_pin(self, candidate: CanonicalBrowserUrl) -> CanonicalBrowserUrl:
        try:
            raw_addresses = await self._resolver.resolve(candidate.hostname)
        except Exception as exc:
            raise BrowserPolicyViolationError("DNS resolution failed closed") from exc
        if not raw_addresses:
            raise BrowserPolicyViolationError("DNS resolution returned no addresses")
        parsed: set[str] = set()
        for raw_address in raw_addresses:
            try:
                address = ipaddress.ip_address(raw_address)
            except ValueError as exc:
                raise BrowserPolicyViolationError("DNS returned an invalid address") from exc
            if not address.is_global:
                raise BrowserPolicyViolationError("DNS address is not globally routable")
            parsed.add(address.compressed)
        current = frozenset(parsed)
        previous = self._resolved.get(candidate.hostname)
        if previous is not None and previous != current:
            raise BrowserPolicyViolationError("DNS rebinding detected")
        self._resolved[candidate.hostname] = current
        return CanonicalBrowserUrl(
            url=candidate.url,
            scheme=candidate.scheme,
            hostname=candidate.hostname,
            port=candidate.port,
            path=candidate.path,
            addresses=tuple(sorted(current)),
        )

    @staticmethod
    def _matches_trusted_destination(
        candidate: CanonicalBrowserUrl,
        destination: TrustedBrowserDestination,
    ) -> bool:
        return (
            candidate.scheme == destination.scheme
            and candidate.hostname == destination.host
            and candidate.port == destination.port
            and _path_allowed(candidate.path, destination.path_prefixes)
        )


def _path_allowed(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(f"{prefix.rstrip('/')}/") for prefix in prefixes)


__all__ = [
    "BrowserDnsResolver",
    "BrowserPolicyViolationError",
    "BrowserUrlPolicyValidator",
    "CanonicalBrowserUrl",
]
