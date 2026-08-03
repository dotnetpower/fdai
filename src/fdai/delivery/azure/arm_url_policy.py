"""Fail-closed ARM resource and long-running-operation URL policy."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class ArmUrlPolicyError(ValueError):
    """Raised before a bearer token can be sent outside the ARM origin."""


@dataclass(frozen=True, slots=True)
class ArmUrlPolicy:
    """Validate resource paths and LRO pointers against one ARM origin."""

    scheme: str
    host: str
    port: int | None

    @classmethod
    def from_client(cls, client: httpx.AsyncClient) -> ArmUrlPolicy:
        base = client.base_url
        if client.follow_redirects:
            raise ArmUrlPolicyError("ARM http_client MUST disable automatic redirects")
        if (
            not base.is_absolute_url
            or base.scheme != "https"
            or not base.host
            or base.username
            or base.password
            or base.path not in {"", "/"}
            or base.query
            or base.fragment
        ):
            raise ArmUrlPolicyError(
                "ARM http_client.base_url MUST be an HTTPS origin without credentials, "
                "path, query, or fragment"
            )
        return cls(scheme=base.scheme, host=base.host.casefold(), port=base.port)

    def validate_lro_url(self, value: str) -> str:
        """Return a normalized same-origin absolute URL or root-relative path."""
        url = _parse(value, name="LRO status URL")
        if url.is_relative_url:
            if not value.startswith("/") or value.startswith("//") or url.fragment:
                raise ArmUrlPolicyError("LRO status URL MUST be root-relative or same-origin HTTPS")
            return str(url)
        if (
            url.scheme != self.scheme
            or not url.host
            or url.host.casefold() != self.host
            or url.port != self.port
            or url.username
            or url.password
            or url.fragment
        ):
            raise ArmUrlPolicyError("LRO status URL MUST use the configured ARM HTTPS origin")
        return str(url)

    @staticmethod
    def validate_resource_ref(value: str) -> str:
        """Return a normalized ARM resource path with no URL authority or query."""
        url = _parse(value, name="provider_ref")
        if (
            not url.is_relative_url
            or not value.startswith("/subscriptions/")
            or value.startswith("//")
            or url.query
            or url.fragment
        ):
            raise ArmUrlPolicyError(
                "provider_ref MUST be a root-relative /subscriptions ARM resource path"
            )
        return str(url)


def _parse(value: str, *, name: str) -> httpx.URL:
    if (
        not value
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ArmUrlPolicyError(f"{name} MUST be non-empty, trimmed, and free of controls")
    try:
        return httpx.URL(value)
    except httpx.InvalidURL as exc:
        raise ArmUrlPolicyError(f"{name} is not a valid URL") from exc


__all__ = ["ArmUrlPolicy", "ArmUrlPolicyError"]
