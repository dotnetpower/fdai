"""Compatibility facade for shared human bearer authentication.

New API processes import :mod:`fdai.delivery.auth`. This module preserves the
published Operator API import path without owning authentication behavior,
HTTP response envelopes, route policy, executor identity, or mutable state.
"""

from fdai.delivery.auth.bearer import (
    AuthenticationError,
    Authenticator,
    ClaimsVerifier,
    UnsafeClaimsExtractor,
    build_authenticator,
)

__all__ = [
    "AuthenticationError",
    "Authenticator",
    "ClaimsVerifier",
    "UnsafeClaimsExtractor",
    "build_authenticator",
]
