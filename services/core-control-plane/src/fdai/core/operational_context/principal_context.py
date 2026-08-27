"""Authenticated server context for principal-scoped operational reads."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipalContext:
    """Server-authenticated principal and scope binding for one read."""

    principal_ref: str
    principal_scope_digest: str
    purpose: str

    def __post_init__(self) -> None:
        if not self.principal_ref.strip():
            raise ValueError("authenticated principal_ref MUST be non-empty")
        if not self.purpose.strip():
            raise ValueError("authenticated purpose MUST be non-empty")
        if (
            len(self.principal_scope_digest) != 71
            or not self.principal_scope_digest.startswith("sha256:")
            or any(
                character not in "0123456789abcdef" for character in self.principal_scope_digest[7:]
            )
        ):
            raise ValueError("authenticated principal scope MUST be a SHA-256 digest")


__all__ = ["AuthenticatedPrincipalContext"]
