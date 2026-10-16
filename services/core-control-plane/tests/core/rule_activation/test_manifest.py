from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fdai.core.rule_activation.manifest import (
    RuleActivationManifestReplayError,
    RuleActivationManifestVerifier,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.rule_activation_manifest import (
    RuleActivationManifest,
    RuleActivationManifestExpectation,
    RuleActivationManifestSource,
    RuleActivationManifestTrust,
    RuleActivationTrustedKey,
    RuleRevisionIdentityRef,
    rule_revision_registry_root,
    sign_rule_activation_manifest,
)

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def _envelope() -> tuple[object, RuleActivationManifestTrust, RuleActivationManifest]:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = base64.b64encode(
        private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode("ascii")
    members = (
        RuleRevisionIdentityRef(
            rule_id="rule.alpha",
            rule_version="1.0.0",
            revision_digest="sha256:" + ("a" * 64),
        ),
    )
    manifest = RuleActivationManifest(
        source=RuleActivationManifestSource.OFFLINE_PACKAGE,
        release_id="release-1",
        source_id="offline-package:release-1",
        target_generation_id="rule-activation-" + ("b" * 32),
        target_generation_digest="sha256:" + ("b" * 64),
        profile_id="baseline",
        profile_version="1.0.0",
        catalog_manifest_digest="sha256:" + ("c" * 64),
        revision_registry_root=rule_revision_registry_root(members),
        members=members,
        deployment_scope_digest="sha256:" + ("d" * 64),
        nonce="e" * 64,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    trust = RuleActivationManifestTrust(
        approved_by="owner",
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
        keys=(
            RuleActivationTrustedKey(
                key_id="release-key-1",
                public_key=public,
                valid_from=NOW - timedelta(days=1),
                valid_until=NOW + timedelta(days=1),
            ),
        ),
        revocation_checked_at=NOW,
    )
    return (
        sign_rule_activation_manifest(
            manifest,
            key_id="release-key-1",
            private_key=private,
        ),
        trust,
        manifest,
    )


def _expected(manifest: RuleActivationManifest) -> RuleActivationManifestExpectation:
    return RuleActivationManifestExpectation(
        source=manifest.source,
        release_id=manifest.release_id,
        source_id=manifest.source_id,
        target_generation_id=manifest.target_generation_id,
        target_generation_digest=manifest.target_generation_digest,
        profile_id=manifest.profile_id,
        profile_version=manifest.profile_version,
        catalog_manifest_digest=manifest.catalog_manifest_digest,
        revision_registry_root=manifest.revision_registry_root,
        members=manifest.members,
        deployment_scope_digest=manifest.deployment_scope_digest,
    )


async def test_verified_manifest_nonce_is_reserved_once_without_authority() -> None:
    envelope, trust, manifest = _envelope()
    verifier = RuleActivationManifestVerifier(trust=trust, store=InMemoryStateStore())

    verified = await verifier.verify_and_reserve(
        envelope,  # type: ignore[arg-type]
        now=NOW + timedelta(seconds=1),
        expected=_expected(manifest),
    )

    assert verified == manifest
    with pytest.raises(RuleActivationManifestReplayError, match="already consumed"):
        await verifier.verify_and_reserve(
            envelope,  # type: ignore[arg-type]
            now=NOW + timedelta(seconds=2),
            expected=_expected(manifest),
        )
