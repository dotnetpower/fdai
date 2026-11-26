from __future__ import annotations

import json
import secrets
from base64 import b64encode
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from jwt.algorithms import RSAAlgorithm
from lifecycle.hub.tests.remote_auth_helpers import seed_entra_key_cache

from fdai_lifecycle_hub.configuration_keys import (
    ConfigurationKeyRequest,
    DevelopmentIdentityRecoveryRequest,
    SignedDevelopmentIdentityRecovery,
    SignedKeyRequest,
)
from fdai_lifecycle_hub.remote_auth import DevelopmentRecoveryAuthorization, RemoteAuth
from fdai_lifecycle_hub.signing import installation_key_id, raw_public_key


def request_for(
    identity: Ed25519PrivateKey,
    signing: Ed25519PrivateKey,
    recipient: X25519PrivateKey,
    now: datetime,
    *,
    installation_id: str = "example-installation",
    version: int = 1,
    predecessor: str | None = None,
    **changes,
) -> tuple[ConfigurationKeyRequest, SignedKeyRequest]:
    fields = {
        "format": "fdai.configuration-keys.v1",
        "installation_id": installation_id,
        "installation_identity_key_id": installation_key_id(raw_public_key(identity)),
        "requester": "requester",
        "request_id": secrets.token_hex(16),
        "version": version,
        "predecessor_digest": predecessor,
        "signing_algorithm": "Ed25519",
        "configuration_signing_key": raw_public_key(signing).hex(),
        "encryption_algorithm": "X25519",
        "installation_encryption_key": recipient.public_key().public_bytes_raw().hex(),
        "requested_at": now,
        "approval_expires_at": now + timedelta(minutes=10),
        "binding_expires_at": now + timedelta(days=1),
    }
    fields.update(changes)
    request = ConfigurationKeyRequest.model_validate(fields)
    signed = SignedKeyRequest.model_validate(
        {
            "signed_payload": b64encode(request.payload).decode(),
            "identity_proof": b64encode(identity.sign(request.payload)).decode(),
            "signer_proof": b64encode(signing.sign(request.payload)).decode(),
        }
    )
    return request, signed


def recovery_for(
    replacement: Ed25519PrivateKey,
    now: datetime,
    *,
    installation_id: str,
    previous_identity_key_id: str,
    scope: str = "rg-fdai-dev-wus3",
) -> tuple[DevelopmentIdentityRecoveryRequest, SignedDevelopmentIdentityRecovery]:
    request = DevelopmentIdentityRecoveryRequest(
        format="fdai.development-identity-recovery.v1",
        installation_id=installation_id,
        scope=scope,
        request_id=secrets.token_hex(16),
        previous_identity_key_id=previous_identity_key_id,
        replacement_identity_public_key=raw_public_key(replacement).hex(),
        requested_at=now,
        confirmation=(
            f"recover installation identity {installation_id} "
            f"{previous_identity_key_id} {installation_key_id(raw_public_key(replacement))}"
        ),
    )
    return request, SignedDevelopmentIdentityRecovery(
        signed_payload=b64encode(request.payload).decode(),
        proof=b64encode(replacement.sign(request.payload)).decode(),
    )


def remote_auth(
    recovery: DevelopmentRecoveryAuthorization | None = None,
) -> RemoteAuth:
    return RemoteAuth(
        profile="remote-development",
        tenant_id="00000000-0000-0000-0000-000000000000",
        audience="hub-api",
        origin="https://hub.example.com",
        spa_client_id="operator-browser",
        operator_scope="Hub.Access",
        operator_ids=frozenset({"requester", "approver"}),
        development_recovery=recovery,
    )


def tokens(app, auth):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    public["kid"] = "test-only"
    seed_entra_key_cache(
        app.state.entra_verifier,
        {"test-only": jwt.PyJWK.from_dict(public)},
    )

    def token(actor="requester", *, omit=(), **changes):
        now = datetime.now(UTC)
        claims = {
            "iss": auth.issuer,
            "aud": auth.audience,
            "tid": auth.tenant_id,
            "ver": "2.0",
            "oid": actor,
            "sub": actor,
            "azp": auth.spa_client_id,
            "scp": auth.operator_scope,
            "iat": now,
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(minutes=5),
        }
        claims.update(changes)
        for name in omit:
            claims.pop(name, None)
        return {
            "Authorization": "Bearer "
            + jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-only"})
        }

    return token
