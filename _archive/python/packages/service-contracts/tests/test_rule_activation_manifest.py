from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from fdai_service_contracts.rule_activation_manifest import (
    RuleActivationManifest,
    RuleActivationManifestExpectation,
    RuleActivationManifestSource,
    RuleActivationManifestTrust,
    RuleActivationTrustedKey,
    RuleRevisionIdentityRef,
    rule_revision_registry_root,
    sign_rule_activation_manifest,
    verify_rule_activation_manifest,
)

NOW = datetime(2026, 10, 17, tzinfo=UTC)
DIGEST = "sha256:" + ("a" * 64)


def _digest(character: str) -> str:
    return "sha256:" + (character * 64)


def _key_material() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    raw = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private, base64.b64encode(raw).decode("ascii")


def _members() -> tuple[RuleRevisionIdentityRef, ...]:
    return (
        RuleRevisionIdentityRef(
            rule_id="rule.alpha",
            rule_version="1.0.0",
            revision_digest=_digest("b"),
        ),
    )


def _manifest() -> RuleActivationManifest:
    members = _members()
    return RuleActivationManifest(
        source=RuleActivationManifestSource.PULL_REQUEST,
        release_id="release-1",
        source_id="pull-request:42:head",
        target_generation_id="rule-activation-" + ("c" * 32),
        target_generation_digest=_digest("c"),
        profile_id="baseline",
        profile_version="1.0.0",
        catalog_manifest_digest=_digest("d"),
        revision_registry_root=rule_revision_registry_root(members),
        members=members,
        deployment_scope_digest=DIGEST,
        nonce="e" * 64,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def _trust(public_key: str) -> RuleActivationManifestTrust:
    return RuleActivationManifestTrust(
        approved_by="owner",
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
        keys=(
            RuleActivationTrustedKey(
                key_id="release-key-1",
                public_key=public_key,
                valid_from=NOW - timedelta(days=1),
                valid_until=NOW + timedelta(days=1),
            ),
        ),
        revocation_checked_at=NOW,
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


def test_signed_manifest_verifies_exact_scope_registry_and_nonce() -> None:
    private, public = _key_material()
    manifest = _manifest()
    envelope = sign_rule_activation_manifest(
        manifest,
        key_id="release-key-1",
        private_key=private,
    )

    verified = verify_rule_activation_manifest(
        envelope,
        trust=_trust(public),
        now=NOW + timedelta(seconds=1),
        expected=_expected(manifest),
    )

    assert verified == manifest
    assert verified.activation_authority is False


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"expected": {"release_id": "another-release"}}, "identity mismatch"),
        ({"expected": {"profile_id": "another-profile"}}, "identity mismatch"),
        ({"consumed_nonces": ("e" * 64,)}, "already consumed"),
    ],
)
def test_manifest_verification_fails_closed(
    override: dict[str, object],
    message: str,
) -> None:
    private, public = _key_material()
    manifest = _manifest()
    envelope = sign_rule_activation_manifest(
        manifest,
        key_id="release-key-1",
        private_key=private,
    )
    arguments: dict[str, object] = {
        "trust": _trust(public),
        "now": NOW + timedelta(seconds=1),
        "expected": _expected(manifest),
    }
    override_values = dict(override)
    expected_override = override_values.pop("expected", None)
    if isinstance(expected_override, dict):
        arguments["expected"] = _expected(manifest).model_copy(update=expected_override)
    arguments.update(override_values)

    with pytest.raises(ValueError, match=message):
        verify_rule_activation_manifest(envelope, **arguments)  # type: ignore[arg-type]


def test_revoked_or_stale_trust_is_rejected() -> None:
    private, public = _key_material()
    manifest = _manifest()
    envelope = sign_rule_activation_manifest(
        manifest,
        key_id="release-key-1",
        private_key=private,
    )
    trust = _trust(public)

    with pytest.raises(ValueError, match="revoked"):
        verify_rule_activation_manifest(
            envelope,
            trust=trust.model_copy(update={"revoked_key_ids": ("release-key-1",)}),
            now=NOW + timedelta(seconds=1),
            expected=_expected(manifest),
        )
    with pytest.raises(ValueError, match="stale"):
        verify_rule_activation_manifest(
            envelope,
            trust=trust,
            now=NOW + timedelta(hours=2),
            expected=_expected(manifest),
        )


def test_trust_times_and_signed_identity_whitespace_fail_at_parse_boundary() -> None:
    _, public = _key_material()
    with pytest.raises(ValueError, match="timezone"):
        RuleActivationTrustedKey(
            key_id="release-key-1",
            public_key=public,
            valid_from=datetime(2026, 10, 17),
            valid_until=datetime(2026, 10, 18),
        )
    with pytest.raises(ValueError, match="MUST be exact"):
        RuleActivationManifest.model_validate(
            {**_manifest().model_dump(mode="json"), "release_id": " release-1 "}
        )


def test_expected_member_set_blocks_signed_manifest_substitution() -> None:
    private, public = _key_material()
    manifest = _manifest()
    envelope = sign_rule_activation_manifest(
        manifest,
        key_id="release-key-1",
        private_key=private,
    )
    expected = _expected(manifest).model_copy(
        update={
            "members": (
                RuleRevisionIdentityRef(
                    rule_id="rule.other",
                    rule_version="9.9.9",
                    revision_digest=_digest("f"),
                ),
            )
        }
    )

    with pytest.raises(ValueError, match="identity mismatch"):
        verify_rule_activation_manifest(
            envelope,
            trust=_trust(public),
            now=NOW + timedelta(seconds=1),
            expected=expected,
        )
