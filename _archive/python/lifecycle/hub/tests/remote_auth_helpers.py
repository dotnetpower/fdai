from __future__ import annotations

import time
from collections.abc import Mapping

from jwt import PyJWK

from fdai_lifecycle_hub.remote_auth import (
    JWKS_CACHE_SECONDS,
    UNKNOWN_KID_REFRESH_SECONDS,
    EntraVerifier,
)


def seed_entra_key_cache(
    verifier: EntraVerifier,
    keys: Mapping[str, PyJWK],
    *,
    refreshed_at: float | None = None,
    refresh_after: float | None = None,
    unknown_kid_refresh_after: float | None = None,
) -> None:
    if not keys:
        raise ValueError("Test signing-key cache requires at least one key.")
    seeded_at = time.monotonic() if refreshed_at is None else refreshed_at
    verifier._keys = dict(keys)
    verifier._last_successful_refresh = seeded_at
    verifier._refresh_after = (
        seeded_at + JWKS_CACHE_SECONDS if refresh_after is None else refresh_after
    )
    verifier._unknown_kid_refresh_after = (
        seeded_at + UNKNOWN_KID_REFRESH_SECONDS
        if unknown_kid_refresh_after is None
        else unknown_kid_refresh_after
    )
