"""Generic Entra JWT verifier - real RS256 signing + JWKS injection.

Exercises :class:`fdai.delivery.read_api.entra_verifier.EntraJwtVerifier`
against genuinely signed tokens (a per-test RSA keypair) so the crypto
path (signature, ``aud``, ``iss``, ``exp``/``nbf``, required claims) is
validated for real, not mocked away. The JWKS client is a small fake that
hands back the public key - no network, deterministic, seedless.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from fdai.delivery.read_api.auth import AuthenticationError
from fdai.delivery.read_api.entra_verifier import (
    EntraJwtVerifier,
    EntraVerifierConfigError,
)

_TENANT = "00000000-0000-0000-0000-000000000abc"
_AUDIENCE = "api://00000000-0000-0000-0000-000000000def"
_ISSUER = f"https://login.microsoftonline.com/{_TENANT}/v2.0"
_KID = "test-signing-key"


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    """One RSA keypair for the whole module (key-gen is the slow part)."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeJwk:
    """Stand-in for :class:`jwt.PyJWK` - only ``.key`` is read."""

    def __init__(self, key: Any) -> None:
        self.key = key


class _FakeJwksClient:
    """Return the injected public key for any token (no network, no kid lookup)."""

    def __init__(self, public_key: Any) -> None:
        self._jwk = _FakeJwk(public_key)

    def get_signing_key_from_jwt(self, token: str) -> _FakeJwk:  # noqa: ARG002
        return self._jwk


def _verifier(rsa_key: rsa.RSAPrivateKey, **overrides: Any) -> EntraJwtVerifier:
    return EntraJwtVerifier(
        jwks_client=_FakeJwksClient(rsa_key.public_key()),  # type: ignore[arg-type]
        audience=overrides.get("audience", _AUDIENCE),
        issuer=overrides.get("issuer", _ISSUER),
    )


def _sign(
    rsa_key: rsa.RSAPrivateKey,
    *,
    aud: str = _AUDIENCE,
    iss: str = _ISSUER,
    exp_delta: timedelta = timedelta(minutes=30),
    nbf_delta: timedelta = timedelta(minutes=-1),
    drop: tuple[str, ...] = (),
    extra: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "oid": "user-oid-1",
        "upn": "user@example.com",
        "roles": ["Reader"],
        "aud": aud,
        "iss": iss,
        "exp": now + exp_delta,
        "nbf": now + nbf_delta,
        "iat": now,
    }
    for key in drop:
        claims.pop(key, None)
    if extra:
        claims.update(extra)
    return jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": _KID})


class TestValidToken:
    def test_valid_token_returns_claims(self, rsa_key: rsa.RSAPrivateKey) -> None:
        claims = _verifier(rsa_key)(_sign(rsa_key))
        assert claims["oid"] == "user-oid-1"
        assert claims["roles"] == ["Reader"]
        assert claims["aud"] == _AUDIENCE
        assert claims["iss"] == _ISSUER

    def test_small_clock_skew_within_leeway_is_accepted(self, rsa_key: rsa.RSAPrivateKey) -> None:
        # nbf 30s in the future - inside the 60s default leeway.
        token = _sign(rsa_key, nbf_delta=timedelta(seconds=30))
        claims = _verifier(rsa_key)(token)
        assert claims["oid"] == "user-oid-1"


class TestRejectedTokens:
    def test_wrong_audience_rejected(self, rsa_key: rsa.RSAPrivateKey) -> None:
        token = _sign(rsa_key, aud="api://not-our-api")
        with pytest.raises(AuthenticationError, match="InvalidAudienceError"):
            _verifier(rsa_key)(token)

    def test_wrong_issuer_rejected(self, rsa_key: rsa.RSAPrivateKey) -> None:
        token = _sign(rsa_key, iss="https://login.microsoftonline.com/other/v2.0")
        with pytest.raises(AuthenticationError, match="InvalidIssuerError"):
            _verifier(rsa_key)(token)

    def test_expired_token_rejected(self, rsa_key: rsa.RSAPrivateKey) -> None:
        token = _sign(rsa_key, exp_delta=timedelta(minutes=-5))
        with pytest.raises(AuthenticationError, match="ExpiredSignatureError"):
            _verifier(rsa_key)(token)

    def test_missing_exp_claim_rejected(self, rsa_key: rsa.RSAPrivateKey) -> None:
        token = _sign(rsa_key, drop=("exp",))
        with pytest.raises(AuthenticationError, match="MissingRequiredClaimError"):
            _verifier(rsa_key)(token)

    def test_missing_aud_claim_rejected(self, rsa_key: rsa.RSAPrivateKey) -> None:
        token = _sign(rsa_key, drop=("aud",))
        with pytest.raises(AuthenticationError):
            _verifier(rsa_key)(token)

    def test_signature_from_other_key_rejected(self, rsa_key: rsa.RSAPrivateKey) -> None:
        attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        # Signed by the attacker, but the verifier only trusts `rsa_key`.
        token = jwt.encode(
            {
                "oid": "x",
                "aud": _AUDIENCE,
                "iss": _ISSUER,
                "exp": datetime.now(UTC) + timedelta(minutes=30),
            },
            attacker_key,
            algorithm="RS256",
            headers={"kid": _KID},
        )
        with pytest.raises(AuthenticationError, match="InvalidSignatureError"):
            _verifier(rsa_key)(token)

    def test_error_message_never_leaks_token(self, rsa_key: rsa.RSAPrivateKey) -> None:
        token = _sign(rsa_key, exp_delta=timedelta(minutes=-5))
        with pytest.raises(AuthenticationError) as exc_info:
            _verifier(rsa_key)(token)
        assert token not in str(exc_info.value)


class TestFromEnv:
    def _base_env(self) -> dict[str, str]:
        return {"FDAI_ENTRA_TENANT_ID": _TENANT, "FDAI_API_AUDIENCE": _AUDIENCE}

    def test_derives_issuer_and_jwks_uri_from_tenant(self) -> None:
        verifier = EntraJwtVerifier.from_env(self._base_env())
        assert verifier.audience == _AUDIENCE
        assert verifier.issuer == _ISSUER
        assert verifier.jwks_client.uri == (
            f"https://login.microsoftonline.com/{_TENANT}/discovery/v2.0/keys"
        )

    def test_issuer_override_wins(self) -> None:
        env = self._base_env()
        env["FDAI_ENTRA_ISSUER"] = f"https://sts.windows.net/{_TENANT}/"
        verifier = EntraJwtVerifier.from_env(env)
        assert verifier.issuer == f"https://sts.windows.net/{_TENANT}/"

    def test_jwks_uri_override_wins(self) -> None:
        env = self._base_env()
        env["FDAI_ENTRA_JWKS_URI"] = "https://sovereign.example/keys"
        verifier = EntraJwtVerifier.from_env(env)
        assert verifier.jwks_client.uri == "https://sovereign.example/keys"

    def test_missing_tenant_fails_fast(self) -> None:
        with pytest.raises(EntraVerifierConfigError, match="FDAI_ENTRA_TENANT_ID"):
            EntraJwtVerifier.from_env({"FDAI_API_AUDIENCE": _AUDIENCE})

    def test_missing_audience_fails_fast(self) -> None:
        with pytest.raises(EntraVerifierConfigError, match="FDAI_API_AUDIENCE"):
            EntraJwtVerifier.from_env({"FDAI_ENTRA_TENANT_ID": _TENANT})

    def test_blank_value_treated_as_missing(self) -> None:
        env = {"FDAI_ENTRA_TENANT_ID": "   ", "FDAI_API_AUDIENCE": _AUDIENCE}
        with pytest.raises(EntraVerifierConfigError, match="FDAI_ENTRA_TENANT_ID"):
            EntraJwtVerifier.from_env(env)
