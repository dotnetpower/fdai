"""Compatibility facade for the shared Entra JWT verifier.

New API processes import :mod:`fdai.delivery.auth`. This module preserves the
published Operator API path while the shared delivery package owns verifier
behavior and process-local JWKS caching.
"""

from fdai.delivery.auth.entra import EntraJwtVerifier, EntraVerifierConfigError

__all__ = ["EntraJwtVerifier", "EntraVerifierConfigError"]
